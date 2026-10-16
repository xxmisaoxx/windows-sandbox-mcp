"""Own Sandbox lifecycle; only this module launches fixed host executables."""

import ctypes
import hashlib
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import uuid
from importlib.resources import files
from pathlib import Path

from . import __version__
from .config import generate
from .errors import SandboxError
from .files import atomic_write, reject_reparse, safe_read
from .protocol import (
    ID,
    OPERATIONS,
    VERSION,
    binary,
    bounded_number,
    decode_response,
    encode,
    validate_result,
)


class Ownership:
    """Windows kernel mutex survives crashes correctly; ownership is never stored in guest files."""

    def __init__(self):
        self.handle = None

    def acquire(self):
        if os.name != "nt":
            raise SandboxError("UNSUPPORTED_HOST", "Windows 10 Pro 22H2 or later is required")
        from ctypes import wintypes
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
        self.kernel.CreateMutexW.restype = wintypes.HANDLE
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.kernel.ReleaseMutex.argtypes = [wintypes.HANDLE]
        self.handle = self.kernel.CreateMutexW(None, True, "Local\\WindowsSandboxMCP-owner-v1")
        if not self.handle:
            raise SandboxError("OWNERSHIP_ERROR", "Cannot acquire Windows session mutex")
        if ctypes.get_last_error() == 183:
            self.kernel.CloseHandle(self.handle)
            self.handle = None
            raise SandboxError("SESSION_BUSY", "Another MCP server owns Sandbox")

    def release(self):
        if self.handle:
            self.kernel.ReleaseMutex(self.handle)
            self.kernel.CloseHandle(self.handle)
            self.handle = None


class SessionManager:
    def __init__(self, root: Path):
        self.root = root.absolute()
        self.root.mkdir(parents=True, exist_ok=True)
        for parent in (self.root, *self.root.parents):
            reject_reparse(parent)
        if os.name == "nt":
            self._protect_root()
        self.lock = threading.RLock()
        self.cancelled = threading.Event()
        self.owner = Ownership()
        self.session = None
        self.state = "stopped"
        self.process = None
        self.sequence = 0
        self.artifacts = {}

    def _protect_root(self):
        import ntsecuritycon
        import win32api
        import win32con
        import win32security
        token = win32security.OpenProcessToken(win32api.GetCurrentProcess(), win32con.TOKEN_QUERY)
        try:
            user = win32security.GetTokenInformation(token, win32security.TokenUser)[0]
        finally:
            token.Close()
        acl = win32security.ACL()
        flags = win32con.OBJECT_INHERIT_ACE | win32con.CONTAINER_INHERIT_ACE
        for sid in (user, win32security.CreateWellKnownSid(win32security.WinLocalSystemSid)):
            acl.AddAccessAllowedAceEx(win32security.ACL_REVISION, flags, ntsecuritycon.FILE_ALL_ACCESS, sid)
        win32security.SetNamedSecurityInfo(str(self.root), win32security.SE_FILE_OBJECT,
                                          win32security.DACL_SECURITY_INFORMATION |
                                          win32security.PROTECTED_DACL_SECURITY_INFORMATION,
                                          None, None, acl, None)

    def _journal(self, event, **fields):
        # Host-only log intentionally excludes command text, typed text and file contents.
        if self.session:
            record = {"time": time.time(), "session": self.session, "event": event, **fields}
            with (self.directory / "events.jsonl").open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, allow_nan=False) + "\n")

    def status(self):
        with self.lock:
            if self.state == "ready" and self.process and self.process.poll() is not None:
                self.state = "failed"
                self._journal("launcher_exited", exit_code=self.process.returncode)
            return {"session": self.session, "state": self.state, "version": __version__,
                    "networking": getattr(self, "networking", False), "requests": self.sequence,
                    "artifacts": list(self.artifacts.values())}

    def start(self, networking=False, memory_mb=4096, startup_timeout=120):
        bounded_number(startup_timeout, 5, 300, "startup_timeout")
        with self.lock:
            if self.state != "stopped":
                raise SandboxError("SESSION_BUSY", "Stop current session before starting another")
            self.cancelled.clear()
            self.owner.acquire()
            try:
                executable = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/WindowsSandbox.exe"
                if not executable.is_file() or sys.getwindowsversion().build < 19041:
                    raise SandboxError("UNSUPPORTED_HOST", "Windows Sandbox on build 19041+ is required")
                listing = subprocess.run([str(executable.parent / "tasklist.exe"), "/FO", "CSV", "/NH"],
                                         capture_output=True, timeout=15, creationflags=0x08000000, check=False)
                if listing.returncode != 0:
                    raise SandboxError("PREFLIGHT_FAILED", "Cannot inspect running Sandbox processes")
                if b'"windowssandbox.exe"' in listing.stdout.lower() or b'"windowssandboxclient.exe"' in listing.stdout.lower():
                    raise SandboxError("SESSION_BUSY", "A Sandbox is already open; close it before starting MCP")
                self.session = uuid.uuid4().hex
                self.directory = self.root / self.session
                self.inbox = self.directory / "inbox"
                self.outbox = self.directory / "outbox"
                self.evidence = self.directory / "artifacts"
                for directory in (self.inbox, self.outbox, self.evidence):
                    directory.mkdir(parents=True, exist_ok=False)
                self.sequence = 0
                self.artifacts = {}
                self.networking = networking
                for name in ("agent.ps1", "Desktop.cs", "Accessibility.cs", "inspect.ps1", "Cdp.cs", "browser.ps1"):
                    (self.inbox / name).write_bytes(files("winsandbox_mcp").joinpath("guest", name).read_bytes())
                config = generate(self.inbox, self.outbox, self.session, networking, memory_mb)
                self.config_path = self.directory / "sandbox.wsb"
                self.config_path.write_text(config, encoding="utf-8")
                self.state = "starting"
                self._journal("starting", networking=networking, memory_mb=memory_mb)
                self.process = subprocess.Popen([str(executable), str(self.config_path)],
                                                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                                stderr=subprocess.DEVNULL)
                self._request("ping", {}, startup_timeout, starting=True)
                self.state = "ready"
                self._journal("ready")
                return self.status()
            except BaseException:
                self.state = "failed"
                # Keep ownership if termination fails; never permit a second owner over a live guest.
                self.stop()
                raise

    def request(self, operation, parameters=None, timeout=30):
        with self.lock:
            return self._request(operation, parameters or {}, timeout)

    def _request(self, operation, parameters, timeout, starting=False):
        bounded_number(timeout, 0.1, 310, "timeout")
        if operation not in OPERATIONS:
            raise SandboxError("INVALID_OPERATION", "Unknown guest operation")
        if self.state != "ready" and not (starting and self.state == "starting"):
            raise SandboxError("SESSION_NOT_READY", "Start or restart Sandbox", state=self.state)
        if self.sequence >= 1000:
            raise SandboxError("SESSION_LIMIT", "Restart after 1000 requests")
        request = uuid.uuid4().hex
        payload = encode({"v": VERSION, "session": self.session, "id": request,
                          "op": operation, "params": parameters})
        self.sequence += 1
        # The Windows mapped-folder broker can deny host rename/delete even after
        # closing a file. Publish closed immutable data, then an empty commit marker.
        try:
            with (self.inbox / f"{request}.request.json").open("xb") as f:
                f.write(payload)
                f.flush()
                os.fsync(f.fileno())
            (self.inbox / f"{request}.ready").touch(exist_ok=False)
        except OSError as exc:
            self.state = "failed"
            raise SandboxError("BRIDGE_IO_ERROR", "Cannot publish guest request") from exc
        began = time.monotonic()
        self._journal("request", id=request, operation=operation)
        try:
            while time.monotonic() - began < timeout:
                if self.cancelled.is_set():
                    raise SandboxError("CANCELLED", "Guest operation cancelled; session must be stopped or restarted")
                if self.process and self.process.poll() is not None:
                    raise SandboxError("GUEST_CRASHED", "Sandbox launcher exited", exit_code=self.process.returncode)
                try:
                    data = safe_read(self.outbox, f"{request}.response.json")
                except (FileNotFoundError, PermissionError):
                    time.sleep(0.1)
                    continue
                result = validate_result(operation, decode_response(data, self.session, request))
                self._journal("response", id=request, operation=operation,
                              duration_ms=round((time.monotonic() - began) * 1000, 1))
                return result
            raise SandboxError("BRIDGE_TIMEOUT", "Guest did not respond; restart required", operation=operation)
        except SandboxError as exc:
            if exc.code != "GUEST_ERROR":
                self.state = "failed"
            self._journal("error", id=request, operation=operation, code=exc.code)
            raise
        except OSError as exc:
            self.state = "failed"
            raise SandboxError("BRIDGE_IO_ERROR", "Cannot read guest response", winerror=getattr(exc, "winerror", None)) from exc
        finally:
            # Only remove a known host-created request in the read-only guest mapping.
            try:
                (self.inbox / f"{request}.ready").unlink(missing_ok=True)
                (self.inbox / f"{request}.request.json").unlink(missing_ok=True)
            except PermissionError:
                # Windows mapped-folder broker may retain an open handle after guest reads.
                # Never turn a completed operation into failure or mask its original error.
                self._journal("request_retained", id=request)

    def execute(self, command, timeout=30):
        bounded_number(timeout, 0.1, 300, "timeout")
        if not isinstance(command, str) or not 1 <= len(command) <= 65536 or "\0" in command:
            raise SandboxError("INVALID_ARGUMENT", "command must contain 1..65536 characters without NUL")
        return self.request("exec", {"command": command, "timeout_ms": int(timeout * 1000)}, timeout + 10)

    def launch(self, executable="notepad.exe", arguments=None, accessibility=False, cdp_port=0):
        if not isinstance(executable, str) or not executable or len(executable) > 1024 or "\0" in executable:
            raise SandboxError("INVALID_ARGUMENT", "Invalid executable")
        if arguments is None:
            arguments = []
        if not isinstance(arguments, list) or len(arguments) > 128 or any(
            not isinstance(a, str) or len(a) > 4096 or "\0" in a for a in arguments
        ) or sum(len(a) + 3 for a in arguments) > 28000:
            raise SandboxError("INVALID_ARGUMENT", "arguments must be at most 128 bounded strings without NUL")
        if type(accessibility) is not bool or type(cdp_port) is not int or not (cdp_port == 0 or 1024 <= cdp_port <= 65535):
            raise SandboxError("INVALID_ARGUMENT", "accessibility must be boolean; cdp_port is 0 or 1024..65535")
        return self.request("launch", {"executable": executable, "arguments": arguments,
                                       "accessibility": accessibility, "cdp_port": cdp_port})

    def inspect(self, hwnd=0, max_nodes=300, backend="auto", view="control", timeout=8):
        bounded_number(timeout, 2, 20, "timeout")
        if type(hwnd) is not int or hwnd < 0 or type(max_nodes) is not int or not 1 <= max_nodes <= 1000:
            raise SandboxError("INVALID_ARGUMENT", "hwnd must be nonnegative and max_nodes must be 1..1000")
        if backend not in {"auto", "uia3", "uia2", "ia2", "win32"} or view not in {"control", "raw", "content"}:
            raise SandboxError("INVALID_ARGUMENT", "Invalid accessibility backend or view")
        return self.request("inspect", {"hwnd": hwnd, "max_nodes": max_nodes, "backend": backend,
                                        "view": view, "timeout_ms": int(timeout * 1000)}, timeout + 25)

    def browser(self, port, action="snapshot", target_id="", reference="", text=""):
        import re
        if type(port) is not int or not 1024 <= port <= 65535 or action not in {"snapshot", "click", "fill"}:
            raise SandboxError("INVALID_ARGUMENT", "Invalid CDP port or action")
        if not isinstance(target_id, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{0,128}", target_id):
            raise SandboxError("INVALID_ARGUMENT", "Invalid browser target ID")
        if not isinstance(reference, str) or not re.fullmatch(r"[a-zA-Z0-9:]{0,64}", reference):
            raise SandboxError("INVALID_ARGUMENT", "Invalid browser reference")
        if not isinstance(text, str) or len(text) > 16384 or "\0" in text:
            raise SandboxError("INVALID_ARGUMENT", "Browser text exceeds limit or contains NUL")
        return self.request("browser", {"port": port, "action": action, "target_id": target_id,
                                        "reference": reference, "text": text}, timeout=35)

    def capture(self, operation="screenshot", parameters=None):
        with self.lock:
            result = self.request(operation, parameters)
            raw = binary(result.get("data"))
            if operation == "screenshot" and not raw.startswith(b"\x89PNG\r\n\x1a\n"):
                self.state = "failed"
                raise SandboxError("PROTOCOL_ERROR", "Screenshot is not PNG")
            artifact = uuid.uuid4().hex
            suffix = ".png" if operation == "screenshot" else ".bin"
            target = self.evidence / (artifact + suffix)
            atomic_write(target, raw)
            metadata = {"id": artifact, "session": self.session, "size": len(raw),
                        "sha256": hashlib.sha256(raw).hexdigest(),
                        "mime_type": "image/png" if suffix == ".png" else "application/octet-stream",
                        "path": str(target), "uri": f"sandbox-artifact://{self.session}/{artifact}"}
            self.artifacts[artifact] = metadata
            self._journal("artifact", **{k: metadata[k] for k in ("id", "size", "sha256", "mime_type")})
            atomic_write(self.directory / f"manifest-{artifact}.json", encode(metadata))
            return metadata

    def artifact_bytes(self, artifact):
        with self.lock:
            if not isinstance(artifact, str) or not ID.fullmatch(artifact) or artifact not in self.artifacts:
                raise SandboxError("ARTIFACT_NOT_FOUND", "Unknown artifact in this session")
            metadata = self.artifacts[artifact]
            data = Path(metadata["path"]).read_bytes()
            if hashlib.sha256(data).hexdigest() != metadata["sha256"]:
                raise SandboxError("ARTIFACT_CHANGED", "Artifact integrity check failed")
            return metadata, data

    def upload(self, path, data):
        binary(data)  # Validate before sending.
        return self.request("upload", {"path": path, "data": data})

    def collect(self):
        with self.lock:
            screenshot = self.capture()
            windows = self.request("windows")
            observation = self.inspect()
            snapshot = {"screenshot": screenshot, "windows": windows, "inspection": observation,
                        "session": self.session, "captured_at": time.time()}
            atomic_write(self.directory / f"observation-{uuid.uuid4().hex}.json", encode(snapshot))
            return snapshot

    def stop(self):
        self.cancelled.set()
        with self.lock:
            if self.process and self.process.poll() is None:
                killer = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/taskkill.exe"
                ended = subprocess.run([str(killer), "/PID", str(self.process.pid), "/T", "/F"],
                                       capture_output=True, timeout=15, creationflags=0x08000000, check=False)
                try:
                    self.process.wait(timeout=15)
                except subprocess.TimeoutExpired as exc:
                    self.state = "failed"
                    raise SandboxError("CLEANUP_FAILED", "Owned Sandbox process did not stop",
                                       exit_code=ended.returncode) from exc
            self.process = None
            self.state = "stopped"
            self._journal("stopped")
            self.owner.release()
            return {"session": self.session, "state": self.state,
                    "retained_directory": str(self.directory) if self.session else None}

    def restart(self, **options):
        with self.lock:
            self.stop()
            return self.start(**options)


def doctor():
    return {"platform": sys.platform, "python": sys.version.split()[0], "version": __version__,
            "sandbox_executable": shutil.which("WindowsSandbox.exe"),
            "windows_build": sys.getwindowsversion().build if os.name == "nt" else None,
            "bridge": "offline-json-mailbox", "guest_runtime": "Windows PowerShell 5.1/.NET Framework",
            "warning": "Presence of executable does not prove feature, virtualization or desktop availability"}
