# Windows 11 compatibility assessment

Reviewed 2026-10-16. Runtime changes were not made in this review.

## Support status

Windows 10 Pro 22H2 x64 is the tested baseline. Windows 11 compatibility is
plausible from the APIs used but is **not validated**. Passing the current host
build check (19041+) does not certify a Windows 11 build or Sandbox app version.
No Windows 11 machine was used in this review.

The current bridge uses explicit mapped folders and a logon script. Microsoft
continues to document those [.wsb configuration capabilities on Windows 11](https://learn.microsoft.com/en-us/windows/security/application-security/application-isolation/windows-sandbox/windows-sandbox-configure-using-wsb-file).
Native Win32/UIA and guest-local CDP are not deliberately restricted to Windows
10. Guest PowerShell/.NET helper availability and behavior still need live tests.

## Concrete compatibility concerns

- `session.py` launches System32/WindowsSandbox.exe and uses that process's
  lifetime for status and taskkill cleanup. A launcher handing off to a separately
  managed app would invalidate those assumptions. This is a risk inferred from
  the implementation, not a reproduced Windows 11 failure.
- Preflight recognizes WindowsSandbox.exe and WindowsSandboxClient.exe. It must
  also account for the newer session model rather than assuming those names
  enumerate all active environments.
- Several integration scripts and the default GUI launch assume Notepad exists.
  Microsoft's [Sandbox FAQ](https://learn.microsoft.com/en-us/windows/security/application-security/application-isolation/windows-sandbox/windows-sandbox-faq)
  documents unsupported inbox apps including Notepad and the Store, and the
  newer Store-serviced Sandbox beginning with Windows 11 24H2. Use a small
  compiled WinForms editor/button fixture for portable GUI validation. Test the
  real Notepad separately when installed.
- Detect the installed Sandbox capabilities/version as well as the OS build.
  The FAQ provides `wsb --version` and Get-AppxPackage-based detection.

## Review of yourtablecloth/WindowsSandboxMcp

The [repository README](https://github.com/yourtablecloth/WindowsSandboxMcp)
targets Windows 11 24H2+ and wraps wsb.exe. Its useful design references are
environment IDs, lifecycle operations and remote-session readiness.

The inspected [WindowsSandbox.cs](https://github.com/yourtablecloth/WindowsSandboxMcp/blob/main/src/WindowsSandboxMcp/WindowsSandbox.cs)
uses CLI environment IDs and checks WindowsSandboxRemoteSession.exe via WMI.
Its login readiness probe executes a guest command and polls until it receives
an exit code. Our implementation should retain explicit readiness deadlines.

The inspected [MCP tools](https://github.com/yourtablecloth/WindowsSandboxMcp/blob/main/src/WindowsSandboxMcp/Tools/WindowsSandboxTools.cs)
cover lifecycle, launch, sharing, network information and remote sessions. The
execution tool sends `cmd.exe /c start ...` without awaiting command completion;
it does not supply our stdout/stderr, worker deadline or desktop observation
contract. No screenshot/control-inspection/mouse/keyboard tool was present in
that inspected file. Dynamic arbitrary host-folder sharing would also exceed
our current narrow generated-folder policy.

Microsoft's [CLI documentation](https://learn.microsoft.com/en-us/windows/security/application-security/application-isolation/windows-sandbox/windows-sandbox-cli)
introduces wsb management from Windows 11 24H2, including start/list/connect/stop,
and notes that exec does not currently return process I/O. The CLI therefore
does not by itself replace the guest response and artifact channel.

## Recommended implementation

Keep the existing Win10 launcher and introduce a separate, feature-detected
Windows 11 wsb lifecycle adapter. Bind ownership to the environment ID returned
by our own start operation. Never implicitly attach to or stop an unrelated
existing environment. Use list/connect/stop by that owned ID, with bounded waits
and strict CLI JSON validation. Share the current guest executor, GUI workers
and artifact interface between adapters. Bootstrap must be tested with the
configuration format accepted by the installed CLI.

Before claiming Windows 11 support, run the lifecycle, stream/exit, timeout,
malformed-response, restart, artifact and host-boundary suites there; run native
GUI and local CDP tests with reproducible fixtures. Record Windows build,
Sandbox app/CLI version, architecture and actual results. The reference repo is
useful for this adapter; it is not evidence that our current build already
passes those tests.
