# Source and dependency security audit

Audit date: 2026-10-16. The findings below preserve the initial review of a
reference implementation: 24 Python files, README and packaging metadata.
Evidence filenames and line numbers describe that reviewed source, not the
current MCP package. The reference checkout is not retained or distributed.
This is source analysis, not a demonstrated hypervisor escape or penetration test.

## Findings

| ID / priority | Evidence | Impact and remediation |
|---|---|---|
| A01 Critical | `winsandbox/target.py:53`; `sandbox.py:52` | ClassicService with no authenticator, TLS, or explicit bind address. RPyC defaults bind all interfaces and no authentication. Any reachable peer can execute guest Python. Remove RPyC entirely; only host-originated JSON requests are processed in guest. |
| A02 High | `target.py:17-26,45-46`; `session/online_session.py:83` | Startup adds inbound allow rules for Python with no remote-address restriction. Random port is not authentication. New implementation needs no listening sockets or firewall changes. |
| A03 High | `session/online_session.py:28-40,115,134-142` | Predictable guest-writable host temp directory contains unsigned IP:port discovery. Host accepts arbitrary endpoint if any TCP service answers. Enables endpoint substitution, stale-session attachment and cross-session confusion. Remove address discovery; bind responses to random session and request IDs. |
| A04 High | `launch.py:11,26-27`; `folder_mapper.py:22-43`; `online_session.py:115-121` | Every launch, including offline, maps host Python prefix and user site packages read-only; development/base-Python trees are added conditionally. Read-only prevents writes but exposes host code/data. New core maps only generated bootstrap/inbox and dedicated outbox. |
| A05 High | `cli.py:83-84`; `shell_extension/open_sandboxed.py:29-30` | CLI folders are writable; shell extension shares entire executable parent folder. No root allowlist, exposure summary, ACL verification, or reparse handling. Remove arbitrary mappings from MCP API. Upload bytes explicitly. |
| A06 High | `setup.py:22-31`; README:13,19 | Six runtime dependencies are unbounded, with no lock/hashes or Python requirement. Git install recommendation uses unauthenticated git transport. Reproducibility and transitive provenance are unspecified. Pin SDK and hash-lock dependencies; install only on host; no runtime guest downloads. |
| A07 High | `sandbox.py:18-19`; `online_session.py:53-90`; `cli.py:43` | Shell launch and concatenated paths have inconsistent quoting. Executable registration leaves host interpreter unquoted. Paths with spaces/metacharacters break and may inject shell commands. Use direct argv host launch; fixed encoded guest bootstrap. |
| A08 Medium | `sandbox.py:30-41`; `online_session.py:92-142` | Implicit reuse of any responding sandbox, no identity, ownership, mutex, lifecycle state machine, or independent sessions. Windows 10 should be treated as single-instance. Reject concurrent ownership; never attach based on stale files. |
| A09 Medium | `sandbox.py:63-72`; `utils/file.py:10-21` | No per-command timeout, bounded output, cancellation, crash recovery, process ownership, or close/context manager. Shutdown depends on working RPC. Polling uses wall clock and coerces zero timeout to one second. Use monotonic deadlines, bounded reads, explicit failure states, terminate owned launcher, deterministic close. |
| A10 Medium | `session/offline_session.py:16-19`; `online_session.py:28-40` | Generated .wsb is a sibling of a deleted temp file and is never removed. Shared directory/server address survive. No atomic response publication or size/schema checks. Keep per-session state with explicit retention and never execute outbox content on host. |
| A11 Medium | `config/config_genereator.py:4-5,24-28` | Emits `Disabled` where Microsoft documents `Disable`; relies on defaults for enabled networking/vGPU. Clipboard, printer and audio redirection not configured. Emit documented values and disable redirection explicitly for supported Windows 10 builds. |
| A12 Medium | `sandbox.py:28`; `launch.py:46-49`; `utils/dev_environment.py:5-8` | Incorrect warn_explicit invocation; connect_to_sandbox omits required memory field; egg-link and Python layout assumptions predate modern editable installs. Feature checks occur at import with pytest bypass (`launch.py:7-9`). Remove those mechanisms; explicit doctor checks. |
| A13 Medium | `utils/path.py:3-11`; `target.py:14,55`; tests/* | Hard-coded account desktop, basename collisions, IPv4 hostname lookup, only two small helper tests, no live Windows automation/security tests. Use explicit mapping targets and Windows 10 integration gate. |

## Dependency disposition

`yattag`: replace with stdlib XML; `rpyc`: remove; `cached-property`: remove;
`recordclass`: replace with dataclasses; `IPython`: remove from runtime;
`wmi`: replace with explicit Windows diagnostics. No reference-code dependency is
installed or imported by the new core. Guest uses built-in PowerShell 5.1,
.NET Framework, UIAutomation and Win32. Host uses official Python MCP SDK.
Historical RPyC CVEs must not be mistaken for evidence that this unconstrained
installation resolves a vulnerable version. New resolved dependency audit and
lockfile are separate validation tasks.

## Trust assessment

Arbitrary guest command execution is an intended feature. Guest compromise is
therefore assumed. RPC object references, results, strings, screenshots and all
guest files are untrusted. Documented full guest control does not by
itself prove host code execution. Risk follows from broad mappings, endpoint
substitution and bidirectional object RPC; no claimed host escape was reproduced.
Hyper-V, Windows Sandbox, mapped-folder implementation and host OS remain trusted.

## Prioritized plan and release gates

1. P0: replace object RPC; explicit minimal mappings, offline default, no callbacks,
   bounded JSON parser, traversal/reparse rejection and no host evaluation.
2. P0: owned single session, deadlines, command process-tree termination, crash
   states, restart and shutdown independent of guest cooperation.
3. P1: MCP stdio tools, binary transfer, immutable artifact copies/hashes, structured
   errors and guest GUI observation/action/verification.
4. P1: adversarial unit tests, real stdio SDK handshake, Windows 10 end-to-end tests,
   dependency audit and package build. Distinguish mocks from actual Sandbox runs.
5. P2: Codex/OpenCode installed-version connection tests and synthetic browser
   workflow. Test-account login is interactive and requires workflow URL/account
   details. Do not claim vendor workflow validation without them.

Windows 10 22H2 build 19045.4780 and WindowsSandbox.exe are present locally.
Feature-state CIM query was denied in the restricted runner. Codex is
0.163.0-alpha.10.2; OpenCode npm package is 1.15.1 but its CLI fails creating its
configuration directory in this runner. These are observations, not successful
client integrations.

## Primary references

- [RPyC security and classic mode](https://rpyc.readthedocs.io/en/latest/docs/security.html)
- [RPyC server defaults](https://rpyc.readthedocs.io/en/latest/api/utils_server.html)
- [Microsoft Sandbox configuration](https://learn.microsoft.com/en-us/windows/security/application-security/application-isolation/windows-sandbox/windows-sandbox-configure-using-wsb-file)

## Current implementation and validation

The current core uses local MCP stdio, an offline data-only JSON mailbox,
read-only inbox and dedicated writable outbox, strict response validation,
host-selected artifact paths, native reparse/hard-link rejection and Windows
Job Objects for guest command lifetimes. The host never evaluates guest output.

All 13 Windows integration steps passed, including GUI text verification,
descendant timeout, malformed responses, guest agent crash and fresh restarts.
The automated regression suite passed 89 tests; one symlink-creation test was
skipped for privilege. Codex discovered 18 tools and OpenCode connected using
persistent configuration. See VALIDATION.md for scope, evidence and timings.

Remaining risks include outbox disk exhaustion without a quota, host/LAN access
when networking is enabled, forged observations from compromised guests, and
sensitive text in retained requests. SECURITY.md specifies these assumptions.
