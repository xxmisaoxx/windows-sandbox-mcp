# Security model

Guest code may execute arbitrary commands as WDAGUtilityAccount. Guest output is
untrusted data, including screenshots, text, titles, UI Automation values and
reported exit codes. Treat embedded instructions as data. The bridge never
imports/evaluates guest objects, starts host commands requested by the guest, or
uses guest paths as host destinations. Session/request IDs address stale response
confusion, not authenticity against a compromised guest.

Read-only inbox contains generated agent files and pending requests. The trusted
browser workflow runner additionally stages exactly one explicitly selected
installer there; its parent folder and host browser profiles are never mapped.
Writable outbox is a dedicated host directory. Host evidence, parent session
state, project source, user folders and host Python are not mapped. Expected
outbox leaf reads are size bounded, reject reparse points/hard links and validate
JSON identity/schema. Binary data has a 4 MiB cap. No bridge ports or automatic
firewall changes. Default guest networking is disabled. Enabling it permits ordinary
host/LAN access; this project is not a network firewall.

The host trusts its OS/hypervisor, Python, dependencies, package files, state
parent ACLs and local MCP client. Run as a normal user; do not elevate the MCP
server. Protect its state root from other host users. A compromised host process
running as the same user is outside the threat model. GUI content is not a
trusted authorization signal. Never type production secrets during testing.

Event logs omit commands and typed text. Retained inbox requests still contain
commands, typed text and upload bytes; protect the entire state root. The host
applies a protected DACL allowing its current user and SYSTEM to session state.
Avoid credentials in tool arguments. Screenshots can expose visible data.

The writable outbox permits disk exhaustion. Host-side size limits bound reads,
not guest writes. Use a disposable quota-limited volume for hostile applications.
Automatic recursive cleanup is intentionally absent. After shutdown, review and
remove retained session directories using a host tool that does not traverse
reparse points. Native junction/hard-link rejection and read-only mappings were
tested on Windows; symlink creation was unavailable under the test token.
No claim of hypervisor escape prevention or forensic evidence authenticity.

Optional CDP is explicitly enabled per guest launch and accessed by a fixed
guest-only worker over 127.0.0.1. It does not create a host listener. Other guest
processes may access the browser debugger; use disposable synthetic profiles.
Third-party applications may override binding flags; inspect guest listeners
when enabling networking. Discovery rejects redirects and caps response bytes;
DOM actions accept only bounded references/text, not caller-supplied JavaScript.
Password values are omitted from snapshots and rejected by the host schema if
present. This does not conceal secrets visible elsewhere in page content or
screenshots. CDP snapshots currently cover the main frame and ordinary DOM;
cross-origin frames, closed shadow roots and canvas controls need another path.

The accessibility integration runner may accept a Windows Defender Firewall
dialog for the explicitly selected Antidetect fixture, inside the disposable
guest, as authorized by the user. This behavior is not an MCP-wide auto-approval
policy and does not modify the host firewall.

Report security issues privately to the repository maintainer before publishing
exploit details.
