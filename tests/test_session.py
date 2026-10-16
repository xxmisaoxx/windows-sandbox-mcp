import base64
import json
import threading
import time

import pytest

from winsandbox_mcp.errors import SandboxError
from winsandbox_mcp.files import atomic_write


def emulate_guest(manager, result, mutate=None):
    def reply():
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            requests = [p for p in manager.inbox.glob("*.request.json")
                        if (manager.inbox / p.name.replace(".request.json", ".ready")).exists()]
            if requests:
                request = json.loads(requests[0].read_bytes())
                response = {"v": 1, "session": request["session"], "id": request["id"],
                            "ok": True, "result": result, "error": None}
                if mutate:
                    mutate(response)
                atomic_write(manager.outbox / (request["id"] + ".response.json"), json.dumps(response).encode())
                return
            time.sleep(.01)
        raise AssertionError("No host request")
    worker = threading.Thread(target=reply)
    worker.start()
    return worker


def test_request_uses_identity_and_cleans_inbox(session):
    thread = emulate_guest(session, {"ready": True})
    assert session.request("ping", timeout=1) == {"ready": True}
    thread.join()
    assert not list(session.inbox.glob("*.request.json"))


def test_wrong_session_fails_closed(session):
    thread = emulate_guest(session, {}, lambda r: r.update(session="b" * 32))
    with pytest.raises(SandboxError) as error:
        session.request("ping", timeout=1)
    thread.join()
    assert error.value.code == "PROTOCOL_ERROR"
    assert session.state == "failed"
    with pytest.raises(SandboxError):
        session.request("ping")


def test_timeout_requires_restart(session):
    with pytest.raises(SandboxError) as error:
        session.request("ping", timeout=.1)
    assert error.value.code == "BRIDGE_TIMEOUT"
    assert session.state == "failed"


def test_cancel_interrupts_wait_before_deadline(session):
    timer = threading.Timer(.1, session.cancelled.set)
    timer.start()
    began = time.monotonic()
    with pytest.raises(SandboxError) as error:
        session.request("ping", timeout=30)
    timer.join()
    assert error.value.code == "CANCELLED"
    assert time.monotonic() - began < 2
    assert session.state == "failed"


def test_mapped_folder_sharing_does_not_mask_result(session, monkeypatch):
    from pathlib import Path
    original = Path.unlink

    def locked(path, *args, **kwargs):
        if path.name.endswith(".request.json"):
            raise PermissionError("mapped-folder sharing violation")
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, "unlink", locked)
    thread = emulate_guest(session, {"ready": True})
    assert session.request("ping", timeout=1) == {"ready": True}
    thread.join()
    assert session.state == "ready"


def test_unknown_callback_never_executes(session):
    marker = session.directory / "host-should-not-exist"
    (session.outbox / "host-command.request.json").write_text(json.dumps({"op": "exec", "command": str(marker)}))
    with pytest.raises(SandboxError):
        session.request("host_exec")
    assert not marker.exists()


def test_artifacts_are_host_selected_and_integrity_checked(session):
    data = b"\x89PNG\r\n\x1a\nsynthetic protocol fixture, not a real screenshot"
    thread = emulate_guest(session, {"data": base64.b64encode(data).decode(), "path": "C:\\secret"})
    artifact = session.capture()
    thread.join()
    assert artifact["path"].startswith(str(session.evidence))
    assert session.artifact_bytes(artifact["id"])[1] == data
    from pathlib import Path
    Path(artifact["path"]).write_bytes(b"tampered")
    with pytest.raises(SandboxError) as error:
        session.artifact_bytes(artifact["id"])
    assert error.value.code == "ARTIFACT_CHANGED"


def test_crashed_launcher(session):
    class Dead:
        returncode = 17

        def poll(self):
            return 17
    session.process = Dead()
    with pytest.raises(SandboxError) as error:
        session.request("ping")
    assert error.value.code == "GUEST_CRASHED"


def test_command_timeout_is_not_bridge_timeout(session):
    thread = emulate_guest(session, {"stdout": "partial", "stderr": "", "exit_code": None, "timed_out": True})
    assert session.execute("Start-Sleep 10", .1)["timed_out"]
    thread.join()
    assert session.state == "ready"
