# Setup and client integration

Baseline: Windows 10 Pro 22H2 x64, Python 3.11+, logged-on interactive desktop,
virtualization and Windows Sandbox enabled. Close manually opened Sandboxes
before using this server. Do not run the MCP server as administrator. If the
feature is absent, enable Windows Sandbox using Windows optional features and
reboot; this project never changes host feature or firewall settings.

Install [uv](https://docs.astral.sh/uv/) and from the repository root run:

```powershell
$env:UV_CACHE_DIR = Join-Path $PWD '.uv-cache'
uv sync --frozen
.venv\Scripts\python.exe -m winsandbox_mcp --doctor
```

`uv.lock` pins the full graph with distribution hashes. `requirements.lock` is a
hash-pinned runtime export for pip (`pip install --require-hashes -r requirements.lock`
followed by installation of the built project wheel with `--no-deps`).

## Codex (installed CLI 0.163.0-alpha.10.2)

Generate configs with the absolute paths of your checkout:

```powershell
.venv\Scripts\python.exe scripts\client-configs.py
```

Generated files are in `.runtime/client-configs/` and stay out of Git. The examples
below assume `C:\projects\windows-sandbox-mcp`; replace that path with your own.
Add the generated Codex entry to user config or a trusted project config:

```toml
[mcp_servers.windows_sandbox]
command = 'C:\projects\windows-sandbox-mcp\.venv\Scripts\python.exe'
args = ['-m', 'winsandbox_mcp', '--state-root', 'C:\projects\windows-sandbox-mcp\.runtime\codex']
startup_timeout_sec = 20
tool_timeout_sec = 360
```

Or use `codex mcp add windows_sandbox -- <absolute-python> -m winsandbox_mcp --state-root <absolute-state-root>`.
Starting the MCP process does not launch Sandbox. Use `/mcp` to check tools, call
`sandbox_doctor`, then `sandbox_start`. A tool call may need the client's normal
approval. Keep tool timeout longer than the maximum guest startup/command timeout.

Source: [official OpenAI MCP configuration](https://learn.chatgpt.com/docs/extend/mcp?surface=cli).

## OpenCode (installed 1.15.1)

Add an entry to `opencode.json` or use the generated example. To install this
server entry while preserving other OpenCode settings and making a backup, run
`scripts/install-opencode.py` with the project Python interpreter.

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "windows_sandbox": {
      "type": "local",
      "command": ["C:\\projects\\windows-sandbox-mcp\\.venv\\Scripts\\python.exe", "-m", "winsandbox_mcp", "--state-root", "C:\\projects\\windows-sandbox-mcp\\.runtime\\opencode"],
      "enabled": true,
      "timeout": 360000
    }
  }
}
```

Run `opencode mcp list` and request `sandbox_doctor`. Source:
[official OpenCode local MCP schema](https://opencode.ai/docs/mcp-servers/).
Client transport success and actual model-driven calls are recorded separately
in VALIDATION.md. Examples are not evidence that a client called a tool.

## Testing

```powershell
uv sync --frozen --extra dev
.venv\Scripts\python.exe -m pytest -m 'not integration' -q
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts\check-guest.ps1
.venv\Scripts\python.exe scripts\integration.py
```

The last command launches and destroys only the project-owned Sandbox, writes
`evidence/integration.json`, and retains session directories under `.runtime`.
It tests command streams/exit codes, file bytes, screenshots, Notepad GUI input
and verification, timeout descendants, host exposure, malformed responses and
fresh restart after agent crash. It requires an unlocked interactive desktop.
To use pytest instead, set `WSMCP_INTEGRATION=1` and run `pytest -m integration`.
The report's per-step durations provide a reproducible benchmark; compare runs
on the same hardware/build, memory setting and desktop resolution. They are not
general performance guarantees.

For online synthetic browser tests, explicitly call `sandbox_start(networking=true)`.
Stage only installers and synthetic data via uploads. Account login is performed
interactively by the human inside the guest. Keep passwords and production
profiles out of commands, screenshots and saved observations. The existing
Antidetect Cloud Browser/Vifox account workflow is separate from MCP validation
and can continue in OpenCode. It is not required to use this MCP.

For expanded native and DOM inspection see [GUI automation](GUI-AUTOMATION.md).
`sandbox_launch` now accepts `arguments`, `accessibility` and `cdp_port`;
`sandbox_inspect` accepts `backend`, `view` and `timeout`. `sandbox_browser`
provides opt-in DOM snapshot/click/fill. Restart the MCP client to reload the
18-tool schema after updating this editable installation.

## Failure and retention

`BRIDGE_TIMEOUT`, malformed response or launcher exit makes the session failed.
Stop or restart before another command. Command timeout instead returns
`timed_out=true`, `exit_code=null`, and partial bounded output; the session stays
usable. `sandbox_exec` kills descendants after the command, including successful
commands; use `sandbox_launch` to keep a GUI app alive. Failed foreground focus
is an error, not a successful click/type result.

Cancelling an in-flight guest tool through MCP stops the entire owned Sandbox
to prevent unknown partial actions from continuing. Explicit stop also interrupts
pending mailbox waits. Restart is required afterward.

Shutdown does not recursively delete outbox data. Requests whose mapped-folder
broker handles remain open are retained and never replayed in a new session.
Configure a quota-limited disposable state volume for hostile workloads.

## Troubleshooting

| Symptom | Next step |
|---|---|
| Sandbox is missing or will not start | Enable Windows Sandbox and virtualization, reboot if required, then run `--doctor` again. Confirm the tested Windows edition/build. |
| `SESSION_BUSY` | Close another MCP-owned or manually opened Sandbox. This server never attaches to an unrelated session. |
| Tools do not appear after configuration | Reload the client, check its MCP status, and confirm the configured Python executable exists. Generated configs use absolute paths. |
| The terminal appears to wait when running `-m winsandbox_mcp` | The process speaks MCP stdio and is waiting for a client. Use the client configuration instead of typing shell commands into it. |
| Native controls are sparse | Try UIA3, another UIA view or MSAA/IA2; for compatible Chromium pages, opt into DOM/CDP. See GUI-AUTOMATION.md. |
| An online app is blank or reports a network error | Sandbox networking is off by default. Start a fresh guest with networking enabled when the workflow needs it. |
| `INSPECTION_TIMEOUT` | The worker was terminated; the guest remains usable. Try another backend or a smaller inspection. |
| `BRIDGE_TIMEOUT` | Stop or restart the guest before another command. Preserve the structured error when reporting the issue. |

