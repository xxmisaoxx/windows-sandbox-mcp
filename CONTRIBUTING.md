# Contributing

Help make a disposable Windows desktop useful to more coding agents. Small,
focused contributions are welcome: setup fixes, reproducible bug reports, test
coverage, accessibility provider fixes and compatibility results.

## Start here

1. Read the [quick start](README.md#quick-start) and [architecture](docs/ARCHITECTURE.md).
2. Check [open issues](https://github.com/xxmisaoxx/windows-sandbox-mcp/issues).
3. For substantial changes, open a feature request describing the use case first.

Useful areas to work on:

- Windows 11 lifecycle support and validation with recorded OS/Sandbox versions.
- A portable native GUI fixture that does not require a preinstalled Notepad.
- Diagnosing late mapped-folder latency in longer sessions.
- More native accessibility and browser edge cases, with synthetic reproductions.

## Local checks

```powershell
uv sync --frozen --extra dev
uv run --frozen --extra dev ruff check src tests scripts
uv run --frozen --extra dev pytest -m "not integration" -q
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts\check-guest.ps1
uv run --frozen --extra dev python -m build --no-isolation
```

CI runs these checks on Windows. A green CI result does **not** mean real Windows
Sandbox was started. Live desktop testing needs an interactive Windows machine
with the feature enabled. Follow [validation](docs/VALIDATION.md) to reproduce the
integration suites, and record the exact Windows build and client versions.

## Pull requests

Describe the problem, resulting behavior and checks you ran. Keep runtime
changes focused. Include a meaningful regression test when it catches a real
failure, and update setup or security documentation when behavior changes.

Keep the bridge data-only, guest execution inside the guest and host paths under
host control. Preserve the explicit mapped-folder policy, bounded reads and
owned-session cleanup. Report security issues through the repository's private
security reporting channel rather than a public issue; see [SECURITY.md](SECURITY.md).

Use synthetic data. Keep runtime directories, account credentials, private
screenshots and generated workstation configs out of commits. Contributions are
distributed under this project's [MIT license](LICENSE).
