# Windows Sandbox MCP

An offline-first local MCP server for Windows 10 Pro 22H2.
**Early implementation: consult docs/VALIDATION.md for actual test status.**

The host uses the official Python MCP SDK; the guest uses Windows PowerShell 5.1,
Win32 and UI Automation. No RPyC, host interpreter mappings, network listener,
guest package downloads or host desktop automation.

Read [audit](docs/AUDIT.md), [architecture](docs/ARCHITECTURE.md),
[setup](docs/SETUP.md), [security](SECURITY.md), and [Windows 11 assessment](docs/WINDOWS11-COMPATIBILITY.md).

## Quick start

Run from an interactive Windows desktop with Sandbox enabled and Python 3.11+:

```powershell
git clone https://github.com/xxmisaoxx/windows-sandbox-mcp.git
cd windows-sandbox-mcp
$env:UV_CACHE_DIR = Join-Path $PWD '.uv-cache'
uv sync --frozen --extra dev
.venv\Scripts\python.exe -m winsandbox_mcp --doctor
.venv\Scripts\python.exe -m pytest -m 'not integration'
.venv\Scripts\python.exe -m winsandbox_mcp --state-root .runtime
```

The server speaks MCP stdio; do not type plain commands into it. Connect through
Codex or OpenCode using the setup examples. Start with `sandbox_start`, then
`sandbox_exec` or `sandbox_launch`, observe with `sandbox_windows`,
`sandbox_inspect`, `sandbox_screenshot`, act with `sandbox_click`, `sandbox_text`,
`sandbox_keys`, and observe again. `sandbox_collect_evidence` retains an observation
and screenshot. `sandbox_artifact` retrieves native MCP images or base64 bytes.
`sandbox_upload`/`sandbox_download` transfer up to 4 MiB under guest `C:\work`.
`sandbox_stop` terminates the owned guest; `sandbox_restart` creates a fresh guest.

One Sandbox per interactive Windows session. Default networking, GPU, clipboard,
printer and audio/video input redirection are disabled. Networking is an explicit
opt-in for browser work. Only two generated directories are mapped. Response
storage is writable and requires a quota-limited volume for hostile workloads.
Artifacts and outbox remain after shutdown; no automatic recursive deletion of
guest-controlled files is performed.

## Electron and browser controls

`sandbox_launch` accepts an argument list. For Chromium/Electron, set
`accessibility=true` to add `--force-renderer-accessibility` on a fresh launch.
`sandbox_inspect` now supports `backend=auto|uia3|uia2|ia2|win32`,
`view=control|raw|content`, and a 2–20 second worker deadline. Auto compares native
UIA3 and MSAA/IA2 where useful. Returned metadata identifies the selected backend,
attempts, elapsed time and truncation. A stuck provider is terminated in its
worker without stopping the guest agent.

For compatible browser pages, launch with an explicit `cdp_port` such as 9223,
then use `sandbox_browser` to snapshot, fill or click a returned reference.
Take a new snapshot after each action; references expire on the next snapshot or
navigation. This optional debugger operates inside the guest. It adds no host
listener or guest Python installation. See [usage and limits](docs/GUI-AUTOMATION.md).
