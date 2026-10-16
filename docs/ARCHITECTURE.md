# Architecture decision: small isolated core

Status: implemented; live validation recorded in VALIDATION.md.

A small core keeps session ownership, command execution, desktop control and
artifact handling in separate modules. A data-only JSON bridge avoids exposing
Python objects across the host/guest boundary. Session identity is explicit;
running Sandbox instances are never attached implicitly.

## Components and data flow

1. Official Python MCP SDK serves stdio on the host. Session manager owns one
   Windows 10 Sandbox and serializes desktop actions and command execution.
2. Host creates a unique session: read-only bootstrap/request directory and a
   dedicated writable response directory, with explicit guest target paths.
   The trusted browser runner may stage one explicitly selected installer in the
   read-only inbox; it never maps the installer's parent directory.
   Parent state and host evidence are never mapped. No host user directories,
   Python installation, project root, clipboard or credentials are shared.
3. Guest PowerShell agent reads atomic JSON requests from the read-only inbox.
   It executes a closed set of operations, including arbitrary guest PowerShell
   commands. Responses are committed JSON in the outbox. The bridge uses no sockets,
   guest dependency installation, object deserialization or host RPC callbacks.
4. Host reads only its expected random response basename, with bounded reads
   and Windows reparse rejection. It validates version/session/request/schema,
   decodes bounded binary payloads, and copies bytes into host-only artifacts.
   Guest filenames, paths and reported MIME types never select host paths.

Session/request randomness prevents stale responses and accidental collisions;
it is not protection from malicious guest code, which can read session material.
Compromised guests can forge observations. Host isolation does not imply evidence
authenticity. Hashes establish captured-byte integrity only.

## Reliability

Single active Sandbox is an explicit Windows 10 constraint. Cross-process lock
prevents independent MCP servers from sharing ownership. No opportunistic attach
to an existing Sandbox. Lifecycle: starting, ready, failed, stopped. Unknown or
late results are never replayed. Bridge timeout marks session failed; command
timeout is a bounded guest result with partial output. Restart creates a fresh
session and cannot recover guest disk contents. Shutdown uses owned launcher
process tracking with deadlines even when the guest is dead.

Requests and responses have hard size limits; stdout/stderr are bounded, uploads
and downloads have explicit byte limits. Sequential operations avoid conflicting
input and allow deterministic evidence order. Each action must be followed by
fresh window/UI/screenshot observation in workflows. GUI runs in guest's
interactive desktop; no host desktop automation fallback is permitted.

## Residual risks and alternatives

Desktop inspection runs in a separate guest PowerShell process assigned to a
kill-on-close job before execution. UIA3 uses native COM; the managed UIA2 backend
remains selectable. MSAA enumeration queries IAccessible2 roles when available;
it is not a complete IA2 text implementation. Node/depth/character/time limits
bound traversal, and the job deadline interrupts hung COM providers.

The optional browser backend runs in another killable guest worker. Launch must
explicitly register a debug port. Discovery uses guest 127.0.0.1 without a proxy
or redirects; websocket identity must match that port and discovered page ID.
Only fixed DOM snapshot/focus scripts and CDP input methods are exposed. There is
no arbitrary evaluate tool. DOM references identify one snapshot of one page;
fresh snapshots invalidate older references. The guest debugger can still expose
broader browser capabilities to other processes inside that guest. Browsers may
ignore or override launch flags; the MCP cannot enforce a third-party listener's
binding merely by passing flags. No debugger port is forwarded to the host.

A writable mapped outbox is a deliberate narrow host exposure. Bounded reading
does not impose a disk quota: a malicious guest can fill the mapped volume.
Run state on a quota-limited disposable volume for hostile-code testing. Reparse
handling and cleanup must be tested on Windows, and cleanup must never recurse
through guest-controlled trees. Default retention preserves outbox for explicit
host-side removal after guest termination. No hard guarantee against local
same-user host attackers or hypervisor/SMB vulnerabilities is claimed.

Networking remains disabled by default. Explicitly enabling it for browser login
also permits guest access to the host/LAN via the normal virtual network; the
bridge does not provide egress isolation. A separately firewalled VM is preferred
when strong network restrictions, hard quotas or multiple concurrent guests are
required. An authenticated guest-to-host HTTP queue is a possible later backend,
but would add a listener and require networking for every operation.

## Compatibility baseline

Windows 10 Pro 22H2, interactive logged-on desktop, Sandbox feature and
virtualization enabled, Python 3.11+ on host. Use only documented .wsb settings
available on this baseline. Guest runtime uses built-in PowerShell/.NET instead
of host Python mappings. SDK 1.x is deliberately bounded below 2; lock an exact
tested maintenance release and record reasons before moving to 2.x.
