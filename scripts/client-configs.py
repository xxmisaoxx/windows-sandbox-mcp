"""Generate reviewable absolute-path client configs; does not edit user configuration."""
import json
from pathlib import Path

project = Path(__file__).resolve().parents[1]
python = project / ".venv/Scripts/python.exe"
examples = project / ".runtime/client-configs"
examples.mkdir(parents=True, exist_ok=True)
config = {"$schema": "https://opencode.ai/config.json", "mcp": {"windows_sandbox": {
    "type": "local", "command": [str(python), "-m", "winsandbox_mcp", "--state-root", str(project / ".runtime/opencode")],
    "enabled": True, "timeout": 360000}}}
(examples / "opencode.json").write_text(json.dumps(config, indent=2), encoding="utf-8")
(examples / "codex-config.toml").write_text(
    "[mcp_servers.windows_sandbox]\ncommand = '" + str(python) + "'\nargs = ['-m', 'winsandbox_mcp', "
    "'--state-root', '" + str(project / ".runtime/codex") + "']\nstartup_timeout_sec = 20\ntool_timeout_sec = 360\n",
    encoding="utf-8")
print("Generated client examples in " + str(examples))
