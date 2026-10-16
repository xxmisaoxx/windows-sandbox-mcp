"""Validate existing app in a fresh guest. Never runs the installer on the host.

Large installer staging is a trusted host-side operation: copy exactly one named
file into the already read-only inbox, verify SHA-256 inside guest, then execute
there. No source directory or existing browser profile is mapped.
"""
import argparse
import base64
import hashlib
import json
import shutil
import time
import uuid
from pathlib import Path

from winsandbox_mcp.session import SessionManager

parser = argparse.ArgumentParser()
parser.add_argument("--installer", type=Path, required=True)
parser.add_argument("--state-root", type=Path, default=Path(".runtime/browser-workflow"))
parser.add_argument("--report", type=Path, default=Path("evidence/browser-workflow.json"))
parser.add_argument("--interactive-online", action="store_true",
                    help="Enable networking and pause for human test-account login; do not type passwords into MCP")
args = parser.parse_args()
manager = SessionManager(args.state_root)
report = {"passed": False, "networking": args.interactive_online,
          "scope": "unmodified installer, synthetic data, GUI observation; no auth or entitlement bypass"}
try:
    assert args.installer.is_file() and args.installer.suffix.lower() == ".exe"
    assert args.installer.stat().st_size <= 1024 ** 3, "Installer exceeds 1 GiB staging limit"
    assert shutil.disk_usage(args.state_root).free > args.installer.stat().st_size + 256 * 1024 ** 2
    with args.installer.open("rb") as source:
        digest = hashlib.file_digest(source, "sha256").hexdigest()
    report["installer"] = {"name": args.installer.name, "sha256": digest, "size": args.installer.stat().st_size}
    manager.start(networking=args.interactive_online)
    print("Sandbox ready; staging selected installer bytes", flush=True)
    staged = uuid.uuid4().hex + ".exe"
    shutil.copyfile(args.installer, manager.inbox / staged)
    copied = manager.execute(f"Copy-Item -LiteralPath 'C:\\McpInbox\\{staged}' -Destination C:\\work\\installer.exe; (Get-FileHash C:\\work\\installer.exe -Algorithm SHA256).Hash", timeout=120)
    assert copied["exit_code"] == 0 and copied["stdout"].strip().lower() == digest, copied
    report["staged_hash_verified"] = True
    synthetic = {"test": "Windows Sandbox MCP", "identity": "synthetic@example.invalid",
                 "profile": "MCP synthetic profile", "contains_real_credentials": False}
    manager.upload(r"C:\work\synthetic-data.json", base64.b64encode(json.dumps(synthetic).encode()).decode())
    print("Installer hash verified; installing only inside guest", flush=True)
    installed = manager.execute("$ErrorActionPreference='Stop'; $p=Start-Process -FilePath C:\\work\\installer.exe -ArgumentList '/S' -PassThru; $p.WaitForExit(); exit $p.ExitCode", timeout=300)
    report["install"] = installed
    assert not installed["timed_out"] and installed["exit_code"] == 0, installed
    found = manager.execute("$root=Join-Path $env:LOCALAPPDATA 'Programs\\antidetect-cloud-browser'; Get-ChildItem -LiteralPath $root -Filter '*.exe' | Where-Object Name -Match '^Antidetect' | Select-Object -First 1 -ExpandProperty FullName")
    executable = found["stdout"].strip()
    assert executable and found["exit_code"] == 0, found
    manager.request("launch", {"executable": executable})
    print("Guest application launched; waiting for visible app window", flush=True)
    window = None
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        windows = manager.request("windows")["windows"]
        window = next((w for w in windows if "antidetect" in w["title"].lower()), None)
        if window:
            break
        time.sleep(.5)
    assert window, "Application did not expose an Antidetect window"
    report["window"] = window
    report["initial_evidence"] = manager.collect()
    report["inspection"] = manager.request("inspect", {"hwnd": window["hwnd"], "max_nodes": 500})
    if args.interactive_online:
        print("Log in manually inside Sandbox with a test account. Press Enter here when ready for a redacted state check.", flush=True)
        input()
        # Do not record authenticated screenshots or arbitrary UI text without review.
        report["human_login_step_completed"] = True
        report["login_verification"] = "Human confirmation only; server-side entitlement/isolation not tested"
    else:
        report["human_login_step_completed"] = False
        report["login_verification"] = "Pending online human test-account login"
    report["passed"] = True
finally:
    try:
        manager.stop()
    finally:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2, ensure_ascii=True), encoding="utf-8")
