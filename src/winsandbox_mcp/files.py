"""Safe direct-leaf reads of hostile outbox files, without following reparse points."""

import ctypes
import os
import re
import stat
from pathlib import Path

from .errors import SandboxError
from .protocol import MAX_WIRE

LEAF = re.compile(r"^[0-9a-f]{32}\.response\.json$")


def reject_reparse(path: Path):
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
        raise SandboxError("UNSAFE_PATH", "Reparse points are forbidden")


def safe_read(directory: Path, name: str, limit=MAX_WIRE) -> bytes:
    if not LEAF.fullmatch(name):
        raise SandboxError("UNSAFE_PATH", "Invalid outbox filename")
    reject_reparse(directory)
    path = directory / name
    if os.name != "nt":
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as f:
            info = os.fstat(f.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise SandboxError("UNSAFE_PATH", "Only regular single-link files are allowed")
            data = f.read(limit + 1)
    else:
        import msvcrt
        from ctypes import wintypes

        class FileInfo(ctypes.Structure):
            _fields_ = [("attrs", wintypes.DWORD), ("created", wintypes.FILETIME),
                        ("accessed", wintypes.FILETIME), ("written", wintypes.FILETIME),
                        ("volume", wintypes.DWORD), ("sizehi", wintypes.DWORD),
                        ("sizelo", wintypes.DWORD), ("links", wintypes.DWORD),
                        ("indexhi", wintypes.DWORD), ("indexlo", wintypes.DWORD)]

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                      ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        kernel.CreateFileW.restype = wintypes.HANDLE
        kernel.GetFileInformationByHandle.argtypes = [wintypes.HANDLE, ctypes.POINTER(FileInfo)]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        # OPEN_REPARSE_POINT inspects the link itself; never follows a leaf link.
        handle = kernel.CreateFileW(str(path), 0x80000000, 7, None, 3, 0x00200000, None)
        if handle == ctypes.c_void_p(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            info = FileInfo()
            if not kernel.GetFileInformationByHandle(handle, ctypes.byref(info)):
                raise ctypes.WinError(ctypes.get_last_error())
            if info.attrs & (0x400 | 0x10) or info.links != 1:
                raise SandboxError("UNSAFE_PATH", "Linked or nonregular guest file rejected")
            if (info.sizehi << 32) + info.sizelo > limit:
                raise SandboxError("PAYLOAD_TOO_LARGE", "Response file exceeds limit")
            fd = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
            handle = None  # fd owns the handle now.
            with os.fdopen(fd, "rb") as f:
                data = f.read(limit + 1)
        finally:
            if handle is not None:
                kernel.CloseHandle(handle)
    if len(data) > limit:
        raise SandboxError("PAYLOAD_TOO_LARGE", "Response file exceeds limit")
    return data


def atomic_write(path: Path, data: bytes):
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("xb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    temporary.replace(path)
