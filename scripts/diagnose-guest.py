"""Focused guest process diagnostics for crash recovery validation."""
import json
from pathlib import Path

from winsandbox_mcp.session import SessionManager

manager = SessionManager(Path(".runtime/diagnostics"))
try:
    manager.start()
    command = "$ErrorActionPreference='Stop'; [Console]::WriteLine(('AGENT='+$env:WSMCP_AGENT_PID)); [Console]::WriteLine(('SELF='+$PID)); Get-Process powershell | Select-Object Id,ProcessName | ConvertTo-Json -Compress"
    print(json.dumps(manager.execute(command), indent=2), flush=True)
    command = "$ErrorActionPreference='Stop'; [Console]::WriteLine(('TARGET='+$env:WSMCP_AGENT_PID)); Stop-Process -Id ([int]$env:WSMCP_AGENT_PID) -Force -ErrorAction Stop; [Console]::WriteLine('STOP_RETURNED'); Start-Sleep 20"
    try:
        print(json.dumps(manager.execute(command, timeout=3), indent=2), flush=True)
        print(json.dumps(manager.request('ping', timeout=3)), flush=True)
    except Exception as exc:  # noqa: BLE001 -- diagnostic boundary
        print(type(exc).__name__, str(exc), flush=True)
finally:
    manager.stop()
