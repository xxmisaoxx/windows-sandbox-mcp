# Validation record

2026-10-16, Windows 10 Pro 22H2 x64, build 19045.4780. Host Python 3.11.15,
official MCP SDK 1.30.0, guest PowerShell 5.1.19041.4780. Non-elevated host
token. Sandbox 4096 MiB, networking/vGPU/redirection disabled, desktop 1520x774.

| Check | Result | Evidence |
|---|---|---|
| Regression and real stdio protocol suite | 89 passed, 1 skipped | evidence/unit-tests.xml |
| Native reparse/hard-link handling | Junction and hard-link rejection pass; symlink creation privilege unavailable | tests/test_files_config.py |
| Static checks | Pass | ruff check src tests scripts |
| Guest runtime | C# compilation and PowerShell parsing pass on 5.1 | scripts/check-guest.ps1 |
| Live Sandbox integration | All 13 steps pass | evidence/integration.json |
| Real MCP-to-guest command/file/image/resource, UIA3 and DOM actions | Pass, including fill/read-back and click/state verification | evidence/mcp-live.json |
| Expanded GUI integration | Pass, including evidence collection and termination | evidence/accessibility-integration.json |
| Guest debug listener | Verified 127.0.0.1; unregistered CDP port rejected | evidence/mcp-live.json |
| Codex 0.163.0-alpha.10.2 | App-server MCP client discovered 18 tools | evidence/client-connections.json |
| OpenCode 1.15.1 | Persistent user configuration installed and connected without overrides | evidence/opencode-installed.json |
| Final dependency audit | 67 registry packages; 0 known vulnerabilities; local project skipped by registry scanner | evidence/dependency-audit.json |
| Packaging | Wheel and source archive built | dist/ |

## Live integration and timings

The 13-step run passed Sandbox creation/termination, stdout/stderr/exit 7,
200,000-character output capped to 65,536 without deadlock, binary transfer,
screenshot capture, Notepad discovery/inspection/click/Unicode text/shortcut and
text verification, descendant PID termination on timeout, missing unrelated host
file, read-only inbox, ignored host-command-shaped outbox data, malformed response
rejection, agent crash detection and new sessions after both failures.

Final measured startup: 11.73 s; restart: 12.09 s and 12.33 s; guest screenshot: 0.33 s;
Notepad observation/action/verification: 10.86 s; binary roundtrip: 0.42 s.
The Notepad sequence includes separate killable inspection workers; its earlier
in-process implementation was faster but could hang the main guest agent.
Timeout test includes deliberate waiting (14.56 s). Agent crash detection uses
a deliberate 20 s bridge deadline. These are single-run observations, not general
performance or load guarantees. Full per-step durations remain in the JSON.

The host access probes demonstrate the tested bridge configuration and lack of a
host callback dispatcher. They do not prove absence of Windows/Hyper-V/SMB
vulnerabilities, same-user host attacks or outbox disk exhaustion. Guest evidence
can be forged by compromised guest code; hashes preserve captured-byte integrity.

## Expanded accessibility validation

Native observation on the same Windows 10 Notepad window:

| Backend | Nodes | Edit controls | Buttons |
|---|---:|---:|---:|
| Managed UIA2 | 3 | 0 | 0 |
| Native COM UIA3 | 27 | 1 | 7 |
| MSAA with optional IA2-role query | 52 | 1 | 26 |
| Win32 child windows | 2 | 1 | 0 |

Native UIA3 traversal measured approximately 0.46 s inside the worker; this
excludes worker compilation/startup and mapped-folder transport. A raw-view
two-node budget reported truncation. A synthetic provider blocked for 60 s;
the 2 s inspection deadline killed its worker, and a subsequent guest ping
succeeded. Launch argv preserved spaces, quotes, an empty string, trailing
backslashes, Vietnamese Unicode and shell-looking literal text.

The synthetic local Edge form exercised DOM observation, fill/read-back,
button click/state verification, password-value redaction and stale-reference
rejection. Its page is offline and requires no account or external service.
The optional Electron installer comparison runs separately within the same
runner. Its Antidetect page requires networking; the offline empty page is not
evidence of an MCP failure or of online accessibility support.

The complete expanded suite passed, including evidence collection and guest
termination. Evidence: `evidence/accessibility-integration.json`; source and reproduction:
`scripts/accessibility-integration.py`, `docs/GUI-AUTOMATION.md`. The runner's
final `passed` field, including evidence collection and shutdown, determines
whole-suite success. Late round trips in the large-installer run took roughly
18–26 s; these are measured transport-inclusive observations, not worker CPU
times or a throughput guarantee. The host transport grace is separate from
the guest worker deadline.

A separate fresh guest, driven entirely through the official MCP stdio client,
passed UIA3 inspection, CDP opt-in enforcement, DOM fill/read-back and click/state
verification, binary transfer and native MCP image/resource retrieval. Its debug
listener was verified as 127.0.0.1. DOM round trips in that fresh run were about
3 s; the heavier installer run's late latency remains a performance follow-up.

## Existing browser workflow

Unmodified Antidetect Cloud Browser 1.9.6 installer:
`93d73d993fc65852fe5b1dea61e43b3f69766356a3ca273bfac3603e9a86a726`.
Selected file was staged read-only, hash-checked in guest, installed with exit 0,
and the visible app window was captured in an offline fresh guest with synthetic
data. It was launched with its installation directory as working directory.
Report: evidence/browser-workflow.json. No host app execution or profile mapping.

Interactive online login, authenticated Vifox profile isolation and the rest of
the browser investigation are **not validated here**. The user clarified these
will continue in OpenCode. No entitlement bypass or vendor-credential use was
performed by this project.

## Reproduction

Use docs/SETUP.md. For the full real-MCP binary smoke test run
`.venv\Scripts\python.exe scripts\check-mcp-live.py` after the normal regression
and integration runners. Each runner stops its guest in finally. Retained
evidence is in .runtime/ and evidence/, both ignored by Git to avoid shipping
private test data. This document is the concise tracked validation summary.
