"""Compare real native/Electron backends in an offline Windows Sandbox."""
import argparse
import base64
import hashlib
import json
import shutil
import time
from pathlib import Path

from winsandbox_mcp.errors import SandboxError
from winsandbox_mcp.session import SessionManager

parser = argparse.ArgumentParser()
parser.add_argument("--installer", type=Path, help="Optional Electron installer for comparison")
args = parser.parse_args()
manager = SessionManager(Path(".runtime/accessibility"))
report = {"passed": False, "cases": [], "phase": "notepad"}


def inspect(hwnd, backend="auto", view="control", max_nodes=500):
    result = manager.inspect(hwnd, max_nodes, backend, view, timeout=12)
    counts = {name: sum(n["type"] == name for n in result["nodes"])
              for name in ("ControlType.Edit", "ControlType.Button", "ControlType.Document")}
    report["cases"].append({"phase": report["phase"], "requested_backend": backend, "view": view, "backend": result["backend"],
                            "nodes": len(result["nodes"]), "counts": counts,
                            "duration_ms": result["duration_ms"], "truncated": result["truncated"]})
    print(json.dumps(report["cases"][-1]), flush=True)
    return result


def wait_window(title):
    end = time.monotonic() + 30
    while time.monotonic() < end:
        window = next((w for w in manager.request("windows")["windows"] if title in w["title"].lower()), None)
        if window:
            return window["hwnd"]
        time.sleep(.2)
    raise AssertionError("No guest window: " + title)


def allow_fixture_firewall():
    """User-authorized test-app dialog only, inside the disposable guest."""
    for window in manager.request("windows")["windows"]:
        if window["title"] != "Windows Security Alert":
            continue
        tree = manager.inspect(window["hwnd"], backend="uia3", timeout=8)
        names = " ".join(n.get("name", "") for n in tree["nodes"]).lower()
        if "antidetect cloud browser" not in names or "windows defender firewall" not in names:
            continue
        button = next((n for n in tree["nodes"] if n.get("name", "").lower() == "allow access"
                       and n["type"] == "ControlType.Button"), None)
        if button is None:
            raise AssertionError("Fixture firewall Allow access button not found")
        r = button["bounds"]
        manager.request("click", {"hwnd": window["hwnd"], "x": int(r["x"] + r["width"] / 2),
                                  "y": int(r["y"] + r["height"] / 2), "button": "left"})
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if all(w["hwnd"] != window["hwnd"] for w in manager.request("windows")["windows"]):
                break
            time.sleep(.25)
        else:
            # Some classic dialogs focus their default button on the first click.
            manager.request("keys", {"hwnd": window["hwnd"], "chord": "ENTER"})
            time.sleep(3)
            assert all(w["hwnd"] != window["hwnd"] for w in manager.request("windows")["windows"]), "Guest firewall dialog did not close"
        report["guest_fixture_firewall_allowed"] = True


try:
    manager.start()
    manager.launch("notepad.exe")
    notepad = wait_window("notepad")
    for backend in ("uia3", "uia2", "ia2", "win32"):
        observed = inspect(notepad, backend)
        assert any(n["type"] == "ControlType.Edit" for n in observed["nodes"]) or backend == "uia2"
    bounded = inspect(notepad, "uia3", "raw", 2)
    assert len(bounded["nodes"]) <= 2 and bounded["truncated"]
    fixture = Path("tests/fixtures/HungProvider.cs").read_bytes()
    manager.upload(r"C:\work\HungProvider.cs", base64.b64encode(fixture).decode())
    compiled = manager.execute("$ErrorActionPreference='Stop'; Add-Type -Path C:\\work\\HungProvider.cs -OutputAssembly C:\\work\\hang.exe -OutputType WindowsApplication -ReferencedAssemblies System.dll,System.Core.dll,System.Windows.Forms.dll,System.Drawing.dll,Accessibility.dll; if(-not (Test-Path C:\\work\\hang.exe)){throw 'Fixture executable missing'}")
    assert compiled["exit_code"] == 0, compiled
    arguments = ["space value", 'quote"value', "", "trailing\\", "Tiếng Việt", "$(not-a-shell)"]
    manager.launch(r"C:\work\hang.exe", arguments=arguments)
    for _ in range(50):
        echoed = manager.execute("if(Test-Path C:\\work\\argv.txt){Get-Content C:\\work\\argv.txt}")["stdout"]
        if echoed:
            break
        time.sleep(.1)
    assert [base64.b64decode(line).decode("utf-8") for line in echoed.splitlines()] == arguments
    report["launch_argv_verified"] = True
    manager.launch(r"C:\work\hang.exe")
    hung = wait_window("hung accessibility")
    began = time.monotonic()
    try:
        manager.inspect(hung, backend="uia3", timeout=2)
    except SandboxError as error:
        assert error.code == "GUEST_ERROR" and "INSPECTION_TIMEOUT" in str(error)
    else:
        raise AssertionError("Hung accessibility provider did not trigger worker termination")
    assert time.monotonic() - began < 7 and manager.request("ping")["ready"]
    report["worker_timeout_recovered"] = True
    manager.execute("Get-Process hang -ErrorAction SilentlyContinue | Stop-Process -Force")

    if args.installer:
        digest = hashlib.sha256(args.installer.read_bytes()).hexdigest()
        shutil.copyfile(args.installer, manager.inbox / "fixture-installer.exe")
        verified = manager.execute("Copy-Item C:\\McpInbox\\fixture-installer.exe C:\\work\\fixture.exe; (Get-FileHash C:\\work\\fixture.exe).Hash", 120)
        assert verified["stdout"].strip().lower() == digest
        installed = manager.execute("$p=Start-Process C:\\work\\fixture.exe -ArgumentList '/S' -PassThru; $p.WaitForExit(); exit $p.ExitCode", 300)
        assert installed["exit_code"] == 0 and not installed["timed_out"]
        executable = manager.execute("Get-ChildItem ($env:LOCALAPPDATA+'\\Programs\\antidetect-cloud-browser') -Filter '*.exe' | Where-Object Name -Match '^Antidetect' | Select-Object -First 1 -ExpandProperty FullName")["stdout"].strip()
        manager.launch(executable)
        hwnd = wait_window("antidetect")
        allow_fixture_firewall()
        report["phase"] = "electron-baseline"
        baseline = inspect(hwnd, "uia2")
        baseline_native = inspect(hwnd, "uia3")
        inspect(hwnd, "ia2")
        manager.execute("Get-Process | Where-Object ProcessName -Match 'Antidetect' | Stop-Process -Force")
        time.sleep(1)
        manager.launch(executable, accessibility=True, cdp_port=9222)
        hwnd = wait_window("antidetect")
        time.sleep(2)
        allow_fixture_firewall()
        report["phase"] = "electron-accessibility-enabled"
        enabled_managed = inspect(hwnd, "uia2")
        enabled = inspect(hwnd, "uia3")
        ia2 = inspect(hwnd, "ia2")
        auto = inspect(hwnd)
        report["baseline_nodes"] = len(baseline["nodes"])
        report["enabled_nodes"] = len(enabled["nodes"])
        report["baseline_uia3_nodes"] = len(baseline_native["nodes"])
        report["enabled_uia2_nodes"] = len(enabled_managed["nodes"])
        assert len(auto["nodes"]) > len(baseline["nodes"]), "Combined accessibility changes did not improve inspection"
        snapshot = manager.browser(9222)
        report["electron_dom_snapshot"] = snapshot
        print("Electron DOM nodes: " + str(len(snapshot["nodes"])), flush=True)
        report["electron_evidence"] = manager.capture()
        edit = next((n for n in auto["nodes"] if n["type"] == "ControlType.Edit" and not n.get("password")), None)
        if edit:
            bounds = edit["bounds"]
            manager.request("click", {"hwnd": hwnd, "x": int(bounds["x"] + bounds["width"] / 2),
                                      "y": int(bounds["y"] + bounds["height"] / 2), "button": "left"})
            manager.request("text", {"hwnd": hwnd, "text": "synthetic@example.invalid"})
            verified = manager.inspect(hwnd, timeout=12)
            assert any(n.get("value") == "synthetic@example.invalid" for n in verified["nodes"])
            report["native_electron_input_verified"] = True
        else:
            report["native_electron_input_verified"] = False
        manager.execute("Get-Process | Where-Object ProcessName -Match 'Antidetect|notepad' | Stop-Process -Force")

    report["phase"] = "chromium-dom"
    html = b'''<!doctype html><title>MCP synthetic controls</title><label>Email <input id="email" aria-label="Email"></label><label>Password <input id="pw" type="password" value="synthetic-secret"></label><button id="apply" onclick="document.getElementById('state').textContent='Applied'">Apply synthetic</button><div role="status" id="state">Waiting</div>'''
    manager.upload(r"C:\work\form.html", base64.b64encode(html).decode())
    edge = manager.execute("@('C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe','C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe') | Where-Object {Test-Path -LiteralPath $_} | Select-Object -First 1")["stdout"].strip()
    assert edge, "Guest Edge fixture browser unavailable"
    manager.launch(edge, arguments=["--user-data-dir=C:\\work\\edge-test", "--no-first-run", "file:///C:/work/form.html"], accessibility=True, cdp_port=9223)
    wait_window("mcp synthetic")
    time.sleep(3)
    snapshot = manager.browser(9223)
    assert snapshot["nodes"], "CDP DOM snapshot is empty"
    target = snapshot["target_id"]
    field = next(n for n in snapshot["nodes"] if n["tag"] == "input" and not n["password"])
    manager.browser(9223, "fill", target, field["ref"], "cdp@example.invalid")
    after = manager.browser(9223, target_id=target)
    assert any(n.get("value") == "cdp@example.invalid" for n in after["nodes"])
    report["cdp_fill_verified"] = True
    password = next(n for n in after["nodes"] if n["password"])
    assert password["value"] is None
    button = next(n for n in after["nodes"] if n["tag"] == "button")
    manager.browser(9223, "click", target, button["ref"])
    clicked = manager.browser(9223, target_id=target)
    assert any(n["name"] == "Applied" for n in clicked["nodes"])
    report["cdp_click_verified"] = True
    report["password_redacted"] = True
    # A new snapshot invalidates previous references.
    try:
        manager.browser(9223, "fill", target, field["ref"], "stale@example.invalid")
    except SandboxError as error:
        assert error.code == "GUEST_ERROR"
    else:
        raise AssertionError("Stale browser reference accepted")
    report["stale_reference_rejected"] = True
    report["evidence"] = manager.collect()
    report["passed"] = True
except Exception as error:
    report["error"] = str(error)
    if manager.state == "ready":
        try:
            report["failure_screenshot"] = manager.capture()
        except SandboxError:
            pass
    raise
finally:
    try:
        manager.stop()
    finally:
        Path("evidence/accessibility-integration.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
