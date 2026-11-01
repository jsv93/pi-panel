# Secure Pi Panel management

## Release 0.21.0

This release adds opt-in, read-only diagnostics through the existing panel agent
connection. Installing the release does not enable management access: verified
TLS and a named, device-scoped operator policy are required first.

A panel's logical ID, network address and reported agent hash are operational
information, not hardware attestation. An active enrolled agent can answer the
existing signed diagnostic request without the operator's Windows SSH key.

## Existing architecture and trust

- `server/app/main.py`: FastAPI; SQLite fleet/config; a shared admin password and
  a 12-hour `psid` cookie; outbound pushes over `LIVE[panel_id]`.
- `agent/panel-agent.py`: aiohttp agent, persistent **outbound** connection to
  `/api/ws/{panel_id}`, plus registration, 30-second heartbeat and five-minute
  polling. Its UI server binds localhost. Cached config preserves room operation
  when the server is absent.
- `/opt/panel/panel-token` authenticates the agent. A distinct `panel-sign-key`
  verifies server-signed config, updates and screen diagnostic requests. Both
  were initially enrolled by trust on first use. Legacy tokenless devices remain
  supported by existing routes; the new health diagnostic explicitly rejects them.
- `agent/panel-agent.service` runs as **root**. Adding a PTY directly here would
  create root remote execution. Existing action messages include restart, sync,
  reload, wake and sleep; this is already a limited management channel, not a PTY.
- `server/app/ssh.py`: a separate server-owned Ed25519 provisioning key in
  `/data/ssh`. The HTTP API restricts its use to pending provisioning. Its key may
  remain authorized on a provisioned device, independently of the Windows key.
  Do not evade that restriction by resetting provisioning or rewriting the panel.
- The legacy LAN endpoint and shared admin login remain supported for migration.
  Replace default passwords before enabling management and account for existing
  Home Assistant integration consumers. HTTP is not suitable for a shell. The
  legacy fleet API does not report whether the agent socket uses TLS.

## Implemented: limited safe diagnostics

The new page is `/management/`, linked from each device's Diagnostics tab.
It provides two fixed operations: **Connection** (server-side enrollment and
transport metadata) and **Health** (a fresh, allowlisted metrics report).
There is no shell, PTY, free-text command box, SSH target, filename input,
subprocess executor, screenshot or journal download.

`server/app/management.py` is isolated from the old login and does not change
the agent, kiosk HTML, service files, database schema, bundle or lighting path.
The only server dispatcher hook correlates responses for this feature.
Existing dashboard and HA clients keep their current behavior. This does not
retrofit new RBAC or TLS onto the legacy APIs; those remain fleet-admin APIs.

Controls:

- Disabled unless `PANEL_MANAGEMENT_POLICY` names a valid operator-managed file.
- Separate named operator credentials: generated 256-bit random keys, only their
  SHA-256 digests stored. These are random API keys, not hashed human passwords.
- RBAC: explicit `diagnostics.read` role plus explicit panel IDs. No wildcard
  grants. Each session is bound to one selected panel; the old admin cookie and
  a panel's agent token do not grant this role.
- HTTPS and an exact configured browser Origin for every API request. No CORS.
  The app does not trust raw forwarded headers. Deployment must restrict which
  proxy may set the ASGI scheme (see below).
- Health requires the current authenticated **WSS** agent socket, both enrolled
  secrets, and the device's `remote_diagnostics` setting enabled. Connection can
  explain an insecure/offline channel without sending anything to it.
- Signed, existing `screen_diagnostics` message with `capture=false`; random
  request nonce; response bound to panel, exact socket and credential generation.
  A stale/replaced socket cannot satisfy a new request. Request timeout 10 seconds,
  send timeout 2 seconds; one pending request per device.
- A short-lived opaque bearer session lives only in browser memory and is stored
  hashed on the server. Never in URLs, cookies or localStorage. Reload loses it.
  Maximum ten minutes and two minutes idle; policy changes, logout and server
  restart revoke it. Permissions and channel identity are rechecked while waiting.
- Five login attempts per source per minute, 128 sessions maximum, three-second
  operation interval, 2 KiB input limit, 64 KiB diagnostic response limit and an
  allowlist of small scalar metrics. Rendering uses `textContent`, with no ANSI,
  HTML or terminal escape interpretation. Existing global WS frame limits still
  apply before JSON parsing; the 64 KiB limit is an application response limit.
- Durable SQLite audit records for session/access and operation outcomes, bound
  to named operator and device. No credentials, session IDs or output are logged.
  Missing/unwritable audit storage refuses operations. Audit is local durable
  evidence, not tamper-proof against a compromised server. Back up and rotate it.
  Idle expiration is recorded on the next authenticated request/login sweep;
  no long-lived remote process exists to keep running after expiry.

## Deployment and bootstrap

Do this through an authorized server administration path. Do not copy the
server's private SSH key into a browser or use provisioning to bypass access.

1. Back up the current add-on/server data and note the running image version.
   Build this checkout using the existing Dockerfile, but keep the current
   deployment until the TLS path and operator policy are ready. No new Python
   package is needed.
2. Provide HTTPS to the browser and HTTPS/WSS to the agent with a certificate
   that each verifies. Prefer a trusted TLS proxy on the same host/private
   container network. Permit backend 8099 only from that proxy and any legacy
   clients intentionally retained during migration; never forward it publicly.
   Do not configure `--forwarded-allow-ips '*'`. With a remote proxy, encrypt its
   upstream connection too. The existing `run.sh` accepts Uvicorn's
   `FORWARDED_ALLOW_IPS` environment setting; set it to the actual trusted proxy
   IP(s), not the whole LAN. Home Assistant ingress alone is not proof of TLS
   or device enrollment and may need explicit trusted-proxy configuration.
3. On the panel, set `PANEL_SERVER` to the verified HTTPS base URL using an
   authorized administration path; retain the same logical panel ID and secrets.
   The current aiohttp agent already derives WSS from HTTPS and verifies
   certificates by default. Install a private CA in its system trust store if
   needed; never use `ssl=False`. Changing the agent service environment and
   restarting **only panel-agent** requires existing authorized access or a
   separately reviewed signed update. This patch does not perform that migration.
4. Create a new policy on the server (the helper refuses to overwrite any file):

   ```sh
   python3 server/create-management-user.py \
     --policy /data/management-policy.json \
     --origin https://panels.example.com \
     --user joel --panel example-panel
   ```

   Use the real browser origin; the example hostname is not configured. The
   helper prints the new operator key once: store it in a password manager.
   Keep the policy writable only by the server administrator (0600 on Linux).
   To add users, issue separate random keys and edit the policy through that same
   authorized path. To revoke access, remove a user/role/device or rotate its hash;
   any policy edit invalidates existing sessions on their next request.
5. Set `PANEL_MANAGEMENT_POLICY=/data/management-policy.json` and optionally
   `PANEL_MANAGEMENT_AUDIT=/data/management-audit.db` in the server container.
   The directory must already exist and be writable by the server process.
   These are environment settings, not existing HA add-on options: the current
   add-on package needs an operator-managed deployment/configuration path before
   this can be enabled there. Keep one Uvicorn worker, as for existing LIVE state.
6. Open the console over HTTPS, sign in for `example-panel`, check Connection, then
   Health. Verify the agent hash, dashboard controls, heartbeat and audit records.
   The session uses no third-party assets and works under an ingress URL prefix.
   If HA frames the page from a different origin, open the console directly at
   its HTTPS origin rather than relaxing its `frame-ancestors 'self'` policy.

For a device that already has an enrolled agent, no first-time agent bootstrap
is needed for the implemented fixed read. TLS migration and named operator
setup are still required; installing this release does not configure them.

If neither an agent nor a working authorized SSH credential exists on a device,
the panel server cannot install one remotely just because port 22 answers.
One initial authorized path is required: an existing administrator/key holder,
a trusted remote management console, or access to its boot storage/console to
install the approved agent/key and trust material. Last resort is a backed-up,
planned reimage with the correct user and public key. Enabling SSH or knowing
the IP does not authorize a key. Do not reset credentials, disable host-key
verification or enable an unauthenticated listener as a recovery shortcut.

## Design for a future interactive terminal (not implemented)

Browser HTTPS -> named panel-server session -> one-time device-bound terminal
grant -> **existing outbound agent WSS** -> separate unprivileged PTY worker on
that device. No inbound shell port on the CM5. Server compromise remains a
serious fleet risk because the current server also controls signed root updates.

Before adding this, establish TLS and rotate/re-enroll credentials that have
crossed plaintext links. Use a per-device certificate or separately enrolled
management identity; never treat legacy TOFU, IP, MAC, or knowledge of the panel
ID as terminal authorization. Split the root agent's management worker into a
dedicated OS user with no sudo rights, no Home Assistant/panel signing secrets,
and a restricted home directory. Do not inherit the root agent environment.

Give `terminal.open` its own explicit per-device role, fresh step-up
authentication and a one-use grant with an expiry of at most 30 seconds. Bind
the grant to user, device identity, connection generation and session ID. The
agent verifies the signed envelope, expiry, nonce and capability before creating
one PTY. Never turn config fields, update URLs or generic action messages into
shell strings. Browser WS must enforce exact Origin and authenticate before
accepting input; no credentials in query strings or a permanent shell URL.

Define typed `open/input/resize/output/close` frames with sequence numbers,
per-frame and total output limits, backpressure, bounded terminal dimensions,
one terminal per device and a fleet concurrency cap. Rate-limit input and
resize. Reject out-of-order, cross-device and stale-connection frames. Use a
vetted terminal renderer with clipboard/link escape features disabled by
default. Do not let terminal output generate HTML or execute browser actions.

Both server and agent independently enforce two-minute idle and ten-minute
absolute deadlines. Browser close, logout, RBAC revocation, agent disconnection,
lost server lease and server restart must close the PTY and kill/reap its entire
process group. Reconnection must not silently resume an orphan shell. Audit
open/denial/close, named user, device, timestamps, reason and byte counts; do not
log keystrokes or secrets by default. Any command transcript needs a separate
redaction/retention policy. Validate all of this on Linux, including child process
cleanup and kiosk performance, before advertising terminal support.

## Validation and limitations

New tests cover roles, device grants, HTTPS/Origin, legacy-credential rejection,
policy revocation, idle/absolute expiry, logout, operation and response bounds,
audit failures, stale sockets, wrong nonce/device responses and timeout cleanup.
The integration test exercises real main.py routes, signed requests, WSS-shaped
ASGI transport, ingress mounting, response dispatch, heartbeat and dashboard
login. It does not perform a real TLS certificate handshake or run on a CM5.
Existing enrollment, signing, login-lockout and screen-health regressions pass.
The browser test covers keyboard sign-in/check/logout, ingress-relative requests,
CSP, escaped output, no browser credential storage, HTTP refusal, and layouts at
375, 820 and 1280 pixels. Its preview image uses explicitly simulated data.
The existing kiosk HTML and agent are unchanged. No live deployment, real TLS
migration, production policy provisioning or interactive shell was tested.

Design references: [OWASP WebSocket Security](https://cheatsheetseries.owasp.org/cheatsheets/WebSocket_Security_Cheat_Sheet.html)
and [Uvicorn proxy/TLS settings](https://uvicorn.dev/settings/).
