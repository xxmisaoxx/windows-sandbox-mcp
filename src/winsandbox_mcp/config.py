import xml.etree.ElementTree as ET
from pathlib import Path

from .errors import SandboxError


def generate(inbox: Path, outbox: Path, session: str, networking=False, memory_mb=4096) -> str:
    if type(memory_mb) is not int or not 2048 <= memory_mb <= 16384:
        raise SandboxError("INVALID_ARGUMENT", "memory_mb must be an integer in 2048..16384")
    if type(networking) is not bool:
        raise SandboxError("INVALID_ARGUMENT", "networking must be boolean")
    root = ET.Element("Configuration")
    for key, value in {"VGpu": "Disable", "Networking": "Enable" if networking else "Disable",
                       "AudioInput": "Disable", "VideoInput": "Disable", "PrinterRedirection": "Disable",
                       "ClipboardRedirection": "Disable", "MemoryInMB": str(memory_mb)}.items():
        ET.SubElement(root, key).text = value
    mappings = ET.SubElement(root, "MappedFolders")
    for source, target, readonly in ((inbox, r"C:\McpInbox", True), (outbox, r"C:\McpOutbox", False)):
        folder = ET.SubElement(mappings, "MappedFolder")
        ET.SubElement(folder, "HostFolder").text = str(source.resolve())
        ET.SubElement(folder, "SandboxFolder").text = target
        ET.SubElement(folder, "ReadOnly").text = str(readonly).lower()
    command = ET.SubElement(ET.SubElement(root, "LogonCommand"), "Command")
    command.text = (r'powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass '
                    rf'-File C:\McpInbox\agent.ps1 -Session {session}')
    return ET.tostring(root, encoding="unicode")
