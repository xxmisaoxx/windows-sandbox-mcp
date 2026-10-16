# Electron and browser accessibility research

Date: 2026-10-16. Research followed by implementation in the built-in guest
runtime. See GUI-AUTOMATION.md for the tool interface and VALIDATION.md for
measured results. The projects below informed design choices; their packages
were not installed or imported into this MCP.

## Initial implementation gaps

The initial `guest/agent.ps1` used the managed UI Automation `ControlViewWalker`
and added Win32 child windows. Its launch operation accepted no arguments.
Consequently the earlier Electron test did not enable renderer accessibility
explicitly. Sparse controls are not enough evidence that the application cannot
expose a usable tree. Control-view filtering, provider activation and backend
choice should be tested separately.

## Relevant GitHub implementations

| Project | Useful part | Fit and limits |
|---|---|---|
| [CursorTouch/Windows-MCP](https://github.com/CursorTouch/Windows-MCP) | [tree/service.py](https://github.com/CursorTouch/Windows-MCP/blob/main/src/windows_mcp/tree/service.py) and [tree/ia2.py](https://github.com/CursorTouch/Windows-MCP/blob/main/src/windows_mcp/tree/ia2.py): cached UIA trees, element budgets and MSAA/IA2 fallback for Firefox content | Closest MCP reference. Its `use_dom` path includes accessibility traversal, not necessarily direct JavaScript DOM access. Current main's pyproject requires Python >=3.14; do not assume drop-in compatibility with this project's 3.11 runtime. |
| [FlaUI/FlaUI](https://github.com/FlaUI/FlaUI) | Native COM UIA3 backend alongside managed UIA2 | Good C# reference for another inspection backend. Cannot create accessibility semantics that the target app does not expose. Packaging/runtime version must be checked before adoption. |
| [yinkaisheng/Python-UIAutomation-for-Windows](https://github.com/yinkaisheng/Python-UIAutomation-for-Windows) | COM-based control discovery and patterns; README explicitly discusses Electron's `--force-renderer-accessibility` | Useful diagnostic reference. Importing it would require an additional guest Python runtime, unlike the current built-in PowerShell/C# approach. |
| [Chromium inspect tools](https://github.com/chromium/chromium/blob/main/tools/accessibility/inspect/README.md) | `ax_dump_tree`, `ax_dump_events`, Windows `--api=ia2` versus `--api=uia` | Good independent diagnostic comparison to determine whether the provider or our traversal is losing controls. Building/distributing the tools is additional work. |
| [microsoft/playwright](https://github.com/microsoft/playwright) | Chromium CDP connection and experimental Electron automation | Optional semantic browser backend when the target permits debugging. CDP attachment is Chromium-only and lower fidelity than Playwright protocol; Electron automation has version/fuse constraints. |
| [microsoft/UFO](https://github.com/microsoft/UFO/blob/main/documents/docs/ufo2/core_features/control_detection/overview.md) | Combines UIA with OmniParser visual detection | Reference for a visual fallback when semantic backends fail. Full framework/model deployment adds substantial dependencies. |

## Primary documentation

- [Electron accessibility](https://github.com/electron/electron/blob/main/docs/tutorial/accessibility.md): automatic activation by assistive technology and explicit application support.
- [Chromium accessibility overview](https://github.com/chromium/chromium/blob/main/docs/accessibility/overview.md): renderer accessibility launch flag.
- [Chromium native Windows UIA](https://developer.chrome.com/blog/windows-uia-support-update): native UIA enabled by default starting with Chrome 138. Older embedded Chromium versions must be evaluated separately.
- [Playwright CDP limits](https://playwright.dev/python/docs/api/class-browsertype#browser-type-connect-over-cdp).
- [Playwright Electron constraints](https://playwright.dev/docs/api/class-electron).

## Recommended implementation order

1. Add safe guest launch arguments and an opt-in accessibility mode using
   `--force-renderer-accessibility`. Restart the target app so flags actually
   apply. For apps whose source we control, enabling accessibility through
   Electron's app API is another option. Chromium flags do not apply to Firefox.
2. Compare raw/control views and native COM UIA3 with the existing managed
   traversal. Add an MSAA/IA2 fallback, especially for Firefox-based engines.
3. Run each potentially blocking provider traversal in a killable guest worker.
   Enforce deadlines and node/output budgets during traversal, not just after
   collecting the tree. A stopwatch cannot interrupt a stuck COM call.
4. Offer an explicit CDP backend for compatible targets, with the debug endpoint
   bound to guest loopback and accessed only by the guest executor. Keep the
   host/guest bridge data-only; no host-facing debug listener is required.
5. Keep screenshot/visual targeting for custom-rendered controls. Report backend,
   truncation, elapsed time and supported patterns so the agent can choose actions.

## Validation before claiming improvement

Use the same application version and synthetic screen in fresh guest sessions.
Compare normal launch, accessibility-enabled launch, UIA3 and IA2. Record total
and actionable nodes, correct role/name/bounds, discovery latency, stalled
provider recovery, and whether a known button/text field can be located, acted
on and verified. More nodes alone is not a success criterion. Preserve password
redaction and test default offline operation. The implementation adds native COM
UIA3, selectable managed UIA2, MSAA/IA2-role inspection, killable workers,
Chromium accessibility launch flags and an opt-in guest-loopback CDP backend.
It does not add OCR, a vision model or complete IA2 text interfaces.

The Antidetect comparison was offline. Its online content requires networking,
as confirmed by the user; an empty offline DOM does not establish an automation
backend failure. Native behavior on a populated online screen remains untested.
