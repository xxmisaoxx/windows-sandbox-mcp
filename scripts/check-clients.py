"""Read-only MCP connection checks; no model conversations or user config mutations."""
import json
import os
import queue
import shutil
import subprocess
import threading
from pathlib import Path

project = Path(__file__).resolve().parents[1]
python = (project / ".venv/Scripts/python.exe").as_posix()
args = ["-m", "winsandbox_mcp", "--state-root", (project / ".runtime/codex-client-check").as_posix()]
override = "mcp_servers.windows_sandbox={command=" + json.dumps(python) + ",args=" + json.dumps(args)
override += ",startup_timeout_sec=20,tool_timeout_sec=360}"
environment = dict(os.environ, CODEX_HOME=os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
process = subprocess.Popen([shutil.which("codex"), "-c", override, "app-server"], stdin=subprocess.PIPE,
                           stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding="utf-8",
                           env=environment)
messages = queue.Queue()


def receive():
    for line in process.stdout:
        try:
            messages.put(json.loads(line))
        except ValueError:
            pass


threading.Thread(target=receive, daemon=True).start()


def rpc(number, method, params):
    process.stdin.write(json.dumps({"id": number, "method": method, "params": params}) + "\n")
    process.stdin.flush()
    while True:
        message = messages.get(timeout=45)
        if message.get("id") == number:
            if "error" in message:
                raise RuntimeError(str(message["error"]))
            return message["result"]


report = {}
try:
    rpc(1, "initialize", {"clientInfo": {"name": "winsandbox-mcp-validation", "version": "0.1.0"},
                          "capabilities": {"experimentalApi": True}})
    process.stdin.write('{"method":"initialized","params":{}}\n')
    process.stdin.flush()
    result = rpc(2, "mcpServerStatus/list", {"serverName": "windows_sandbox", "limit": 1})
    servers = result.get("data", [])
    server = next(item for item in servers if item.get("name") == "windows_sandbox")
    tools = server.get("tools", {})
    names = sorted(tools if isinstance(tools, dict) else [t["name"] for t in tools])
    assert "sandbox_doctor" in names and len(names) == 18
    report["codex"] = {"connected": True, "tool_count": len(names), "tools": names,
                       "method": "installed app-server mcpServerStatus/list; no thread or model call"}
finally:
    process.stdin.close()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)

# Capture the full client output privately and expose only this project's status.
# Other configured clients may print credentials in their command arguments.
client_config = project / ".runtime/client-check.json"
client_config.parent.mkdir(parents=True, exist_ok=True)
client_config.write_text(json.dumps({"mcp": {"windows_sandbox": {"type": "local",
    "command": [python, "-m", "winsandbox_mcp", "--state-root", str(project / ".runtime/opencode-client-check")],
    "enabled": True, "timeout": 360000}}}), encoding="utf-8")
env = dict(os.environ, OPENCODE_CONFIG=str(client_config), NO_COLOR="1")
opencode = shutil.which("opencode.exe") or shutil.which("opencode.cmd")
if not opencode:
    opencode = str(Path(os.environ["APPDATA"]) / "npm/node_modules/opencode-ai/bin/opencode.exe")
completed = subprocess.run([opencode, "--pure", "mcp", "list"], env=env, capture_output=True,
                           timeout=45, text=True, encoding="utf-8", errors="replace", check=False)
lines = [line for line in completed.stdout.splitlines() if "windows_sandbox" in line]
report["opencode"] = {"connected": completed.returncode == 0 and any("connected" in line for line in lines),
                      "exit_code": completed.returncode, "method": "installed opencode mcp list; no model call"}
assert report["opencode"]["connected"], "OpenCode did not report windows_sandbox connected"
(project / "evidence/client-connections.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
print(json.dumps(report, indent=2))
