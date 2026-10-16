"""Real Windows 10 integration runner. Does not automate host desktop."""
import base64
import json
import sys
import time
import uuid
from pathlib import Path

from winsandbox_mcp.errors import SandboxError
from winsandbox_mcp.session import SessionManager, doctor


def run(root: Path, report: Path):
    manager = SessionManager(root)
    results = {"host": doctor(), "steps": [], "passed": False}

    def step(name, action):
        start = time.monotonic()
        try:
            value = action()
            results["steps"].append({"name": name, "passed": True,
                                     "duration_ms": round((time.monotonic() - start) * 1000, 2)})
            print(f"PASS {name}", flush=True)
            return value
        except BaseException as exc:
            results["steps"].append({"name": name, "passed": False,
                                     "duration_ms": round((time.monotonic() - start) * 1000, 2),
                                     "error": str(exc), "code": getattr(exc, "code", type(exc).__name__)})
            raise

    try:
        step("start offline Sandbox", lambda: manager.start(startup_timeout=120))

        def command():
            value = manager.execute("[Console]::Out.Write('hello');[Console]::Error.Write('error');exit 7")
            assert value["stdout"] == "hello" and value["stderr"] == "error" and value["exit_code"] == 7, value
        step("stdout stderr exit code", command)

        def output_limit():
            value = manager.execute("[Console]::Out.Write(('x' * 200000))")
            assert value["exit_code"] == 0 and len(value["stdout"]) == 65536 and value["possibly_truncated"]
        step("bounded output without pipe deadlock", output_limit)

        def transfer():
            data = bytes(range(256)) * 100
            manager.upload(r"C:\work\synthetic.bin", base64.b64encode(data).decode())
            artifact = manager.capture("download", {"path": r"C:\work\synthetic.bin"})
            assert manager.artifact_bytes(artifact["id"])[1] == data
        step("binary file transfer", transfer)
        step("guest screenshot", manager.capture)

        def notepad():
            launched = manager.request("launch", {"executable": "notepad.exe"})
            deadline = time.monotonic() + 15
            window = None
            while time.monotonic() < deadline:
                window = next((w for w in manager.request("windows")["windows"] if w["pid"] == launched["pid"]), None)
                if window:
                    break
                time.sleep(.2)
            assert window, "Notepad window did not appear"
            hwnd = window["hwnd"]
            observed = manager.request("inspect", {"hwnd": hwnd, "max_nodes": 300})
            results["notepad_initial"] = observed
            edit = next((n for n in observed["nodes"] if n["type"] in ("ControlType.Edit", "ControlType.Document")), None)
            assert edit, "Notepad edit control absent; inspect notepad_initial in report"
            rect = edit["bounds"]
            manager.request("click", {"hwnd": hwnd, "x": int(rect["x"] + 20), "y": int(rect["y"] + 20), "button": "left"})
            text = "Synthetic Sandbox MCP " + uuid.uuid4().hex[:8] + " Unicode: café"
            manager.request("text", {"hwnd": hwnd, "text": text})
            manager.request("keys", {"hwnd": hwnd, "chord": "CTRL+A"})
            verified = manager.request("inspect", {"hwnd": hwnd, "max_nodes": 300})
            assert any(text in (node.get("value") or "") for node in verified["nodes"]), verified
            evidence = manager.collect()
            results["notepad_evidence"] = evidence
        step("Notepad discover inspect click type shortcut verify", notepad)

        def timeout():
            value = manager.execute("$info=New-Object Diagnostics.ProcessStartInfo; $info.FileName='C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe'; $info.Arguments='-NoProfile -Command Start-Sleep 8; Set-Content C:\\work\\escaped.txt bad'; $info.UseShellExecute=$false; $child=[Diagnostics.Process]::Start($info); [Console]::WriteLine($child.Id); Start-Sleep 20", timeout=3)
            assert value["timed_out"] and value["exit_code"] is None
            assert value["stdout"].strip().isdigit(), value
            child_pid = int(value["stdout"].strip())
            time.sleep(9)
            checked = manager.execute(f"Test-Path C:\\work\\escaped.txt; [bool](Get-Process -Id {child_pid} -ErrorAction SilentlyContinue)")
            assert checked["stdout"].splitlines() == ["False", "False"], checked
        step("timeout kills descendant process", timeout)

        def boundary():
            sentinel = manager.directory / "host-only.txt"
            sentinel.write_text(uuid.uuid4().hex)
            escaped_path = str(sentinel).replace("'", "''")
            check = manager.execute(f"Test-Path -LiteralPath '{escaped_path}'; try {{ Set-Content C:\\McpInbox\\forbidden.txt bad -ErrorAction Stop; 'WRITABLE' }} catch {{ 'READ_ONLY' }}")
            assert check["stdout"].splitlines() == ["False", "READ_ONLY"], check
            marker = manager.directory / "guest-request-must-not-run.txt"
            (manager.outbox / "host-command.request.json").write_text(json.dumps({"op": "exec", "command": str(marker)}))
            manager.request("ping")
            assert not marker.exists()
            assert not (manager.inbox / "forbidden.txt").exists()
        step("host files absent inbox read-only and no host callback dispatcher", boundary)

        def malformed():
            code = "$id=$env:WSMCP_ACTIVE_REQUEST; [IO.File]::WriteAllText(('C:\\McpOutbox\\'+$id+'.response.json'),'not-json');Start-Sleep 2"
            try:
                manager.execute(code, timeout=5)
            except SandboxError as exc:
                assert exc.code == "PROTOCOL_ERROR", exc.code
            else:
                raise AssertionError("Malformed response was accepted")
            assert manager.state == "failed"
        step("malformed response fails closed", malformed)
        old_session = manager.session
        step("restart after malformed response", lambda: manager.restart(startup_timeout=120))
        assert manager.session != old_session

        def crash():
            try:
                value = manager.execute("Stop-Process -Id ([int]$env:WSMCP_AGENT_PID) -Force -ErrorAction Stop; Start-Sleep 30", timeout=10)
            except SandboxError as exc:
                assert exc.code in ("BRIDGE_TIMEOUT", "GUEST_CRASHED")
            else:
                raise AssertionError("Guest agent crash did not fail request: " + json.dumps(value))
        step("guest agent crash", crash)
        step("restart after crash", lambda: manager.restart(startup_timeout=120))
        step("terminate Sandbox", manager.stop)
        results["passed"] = True
    finally:
        try:
            manager.stop()
        finally:
            report.parent.mkdir(parents=True, exist_ok=True)
            report.write_text(json.dumps(results, indent=2, ensure_ascii=True), encoding="utf-8")
    return results


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--state-root", type=Path, default=Path(".runtime/integration"))
    parser.add_argument("--report", type=Path, default=Path("evidence/integration.json"))
    args = parser.parse_args()
    try:
        run(args.state_root, args.report)
    except Exception as exc:  # noqa: BLE001 -- CLI boundary records errors and exits nonzero
        print(f"FAIL {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(1)
