import os
import xml.etree.ElementTree as ET

import pytest

from winsandbox_mcp.config import generate
from winsandbox_mcp.errors import SandboxError
from winsandbox_mcp.files import atomic_write, safe_read

NAME = "a" * 32 + ".response.json"


def test_minimal_config_and_xml_escaping(tmp_path):
    inbox, outbox = tmp_path / "in & box", tmp_path / "outbox"
    root = ET.fromstring(generate(inbox, outbox, "a" * 32))
    assert root.findtext("Networking") == "Disable"
    assert root.findtext("VGpu") == "Disable"
    assert root.findtext("ClipboardRedirection") == "Disable"
    mappings = root.findall("MappedFolders/MappedFolder")
    assert len(mappings) == 2
    assert [m.findtext("ReadOnly") for m in mappings] == ["true", "false"]
    assert mappings[0].findtext("HostFolder") == str(inbox.resolve())
    assert root.findtext("LogonCommand/Command").endswith("a" * 32)


@pytest.mark.parametrize("memory", [True, -1, "4096", 1024, 20000])
def test_bad_memory(tmp_path, memory):
    with pytest.raises(SandboxError):
        generate(tmp_path, tmp_path, "a" * 32, memory_mb=memory)


def test_bounded_read_and_atomic_publish(tmp_path):
    atomic_write(tmp_path / NAME, b"data")
    assert safe_read(tmp_path, NAME) == b"data"
    with pytest.raises(SandboxError):
        safe_read(tmp_path, NAME, limit=3)


@pytest.mark.parametrize("name", ["../secret", "C:\\secret", "file:stream", "x", NAME + "\\child"])
def test_no_guest_selected_paths(tmp_path, name):
    with pytest.raises(SandboxError):
        safe_read(tmp_path, name)


def test_reject_hardlink(tmp_path):
    target = tmp_path / "secret"
    target.write_bytes(b"do not expose")
    os.link(target, tmp_path / NAME)
    with pytest.raises(SandboxError, match="[Ll]ink"):
        safe_read(tmp_path, NAME)


def test_reject_symlink(tmp_path):
    target = tmp_path / "secret"
    target.write_bytes(b"do not expose")
    try:
        (tmp_path / NAME).symlink_to(target)
    except OSError as exc:
        pytest.skip(f"Symlink privilege unavailable: {exc}")
    with pytest.raises((SandboxError, OSError)):
        safe_read(tmp_path, NAME)


@pytest.mark.skipif(os.name != "nt", reason="Windows reparse semantics")
def test_reject_directory_junction_without_traversal(tmp_path):
    import _winapi
    target = tmp_path / "host-only"
    target.mkdir()
    (target / NAME).write_bytes(b"unrelated host data")
    junction = tmp_path / "mapped-root"
    _winapi.CreateJunction(str(target), str(junction))
    try:
        with pytest.raises(SandboxError, match="Reparse"):
            safe_read(junction, NAME)
    finally:
        junction.rmdir()  # Remove the junction itself, never recurse through it.
