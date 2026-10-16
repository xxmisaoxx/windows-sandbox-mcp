"""Add only this server to OpenCode; preserve other settings and never print secrets."""
import json
import shutil
from datetime import datetime
from pathlib import Path

project = Path(__file__).resolve().parents[1]
config_path = Path.home() / ".config/opencode/opencode.json"
config = json.loads(config_path.read_text(encoding="utf-8")) if config_path.exists() else {}
desired = {"type": "local", "command": [str(project / ".venv/Scripts/python.exe"), "-m", "winsandbox_mcp",
           "--state-root", str(project / ".runtime/opencode")], "enabled": True, "timeout": 360000}
if config.get("mcp", {}).get("windows_sandbox") != desired:
    if config_path.exists():
        backup = config_path.with_name("opencode.json.backup-windows-sandbox-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
        shutil.copy2(config_path, backup)
    config.setdefault("mcp", {})["windows_sandbox"] = desired
    config_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = config_path.with_suffix(".json.windows-sandbox.tmp")
    temporary.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(config_path)
print("Windows Sandbox MCP configured in OpenCode. Other entries preserved.")
