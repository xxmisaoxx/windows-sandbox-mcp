# Guest GUI automation

Use a fresh observation before choosing a target, perform one action, then
observe again to verify application state. Window handles and coordinates are
temporary. A successful input call means input was submitted, not that the
application accepted it.

## Native desktop

1. `sandbox_launch(executable="notepad.exe")` starts a persistent guest app.
2. `sandbox_windows()` discovers its window handle.
3. `sandbox_inspect(hwnd=..., backend="auto", view="control", timeout=8)` returns
   controls, physical desktop bounds and backend metadata.
4. Click a fresh control's center, type with `sandbox_text`, or use
   `sandbox_keys(chord="CTRL+A", hwnd=...)`.
5. Inspect again and verify the expected value; capture a screenshot as evidence.

Select `uia3`, `uia2`, `ia2` or `win32` to compare providers. `ia2` enumerates
MSAA and queries IA2 roles when available. `raw` and `content` views apply to UIA;
MSAA/Win32 report their actual raw view. Auto selects by actionable-node count
and total count; this is a heuristic, not proof that every returned node works.
Provider errors appear in `attempts`. `truncated=true` means a limit was reached.
`INSPECTION_TIMEOUT` kills the worker and permits another observation. A bridge
timeout instead requires restarting the guest.

For Chromium/Electron start a new app process with `accessibility=true`.
Already-running single-instance applications may ignore new flags. Native UIA3
and MSAA can expose more controls than managed UIA2, but no backend can invent
semantics for an empty page or custom renderer.

## Optional browser DOM

The examples below are MCP arguments, not host shell commands:

```json
{"executable":"C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe","arguments":["--user-data-dir=C:\\work\\synthetic-profile","--no-first-run","file:///C:/work/form.html"],"accessibility":true,"cdp_port":9223}
```

Call `sandbox_browser(port=9223)` for a snapshot. Save its `target_id` and a
node's `ref`. Then call `sandbox_browser(port=9223, action="fill", target_id=...,
reference=..., text="synthetic@example.invalid")` or `action="click"`.
Take a new snapshot to verify and obtain new references before another action.
Never pass DOM viewport-CSS bounds to native desktop clicks without converting
coordinates; `sandbox_browser` performs its own CDP click.

The port must have been explicitly enabled by `sandbox_launch` in this session.
Only snapshot/click/fill are available; arbitrary JavaScript and arbitrary
websocket addresses are not tool parameters. A browser must support CDP and
permit debugging. Firefox is not supported by this backend. Snapshots include
up to 500 visible ordinary DOM controls in the main frame. Offscreen elements
may be listed and are scrolled into view before action. Closed shadow roots,
cross-origin frames, canvas and browser chrome are not covered. Use native
inspection or screenshots where needed. Password values are redacted.

Inspection uses built-in Windows components. No guest Python, Playwright,
FlaUI, OCR model or additional runtime dependency is installed.

## Reproduce

Run normal tests and `scripts/integration.py` first. Run
`scripts/accessibility-integration.py` for native inspection, hung-provider
recovery, launch-argument fidelity and local DOM form action/verification.
Optionally add `--installer <explicit installer path>` for the Antidetect
Electron comparison. It stages only that selected installer in the read-only
inbox, uses synthetic data without login, records
`evidence/accessibility-integration.json` and stops its guest in `finally`.
Actual results and limitations are recorded in `VALIDATION.md`.
