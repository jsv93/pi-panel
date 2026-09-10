# Security

Audit of the whole system, 2026-09-08, and what was done about it. Findings were
verified against running code, not inferred — where something was tested and
found *not* exploitable, that is recorded too, because "looks dangerous" and
"is dangerous" are different claims.

## Threat model

A home LAN. The realistic attacker is a compromised IoT device, a guest on the
wifi, or malware on a household laptop — something already on the network,
opportunistic rather than targeted.

That is enough to matter here, because the add-on runs with `host_network: true`:
port 8099 answers directly on the LAN, **bypassing Home Assistant's
authentication**. Anything unauthenticated below was reachable by anything on
the network.

Out of scope: physical access to a panel (it is a computer on a wall; someone
with a screwdriver and an SD card reader owns it), and a compromised Home
Assistant (it can already do everything this system can).

## Findings

Severity is for this threat model. Status is at the foot of each.

### Critical

**1. Stored XSS → full admin takeover, from an unauthenticated request.**
*Verified: script executed in the admin session.*

`POST /api/register` and `/api/heartbeat` took `hostname`, `mac`, `ip` and
`metrics` from anyone, and the GUI rendered every one with `innerHTML` — on the
fleet page, which is the page an admin lands on. A panel registered with an
`<img onerror>` in its hostname ran script in the admin's session, and that
session could provision panels over SSH, scan the LAN, and push configuration
to every panel. (It could not change the admin password, which correctly
requires the current one.)

Fix: escape at render; validate at ingest so the stored data is well-formed in
the first place; a Content-Security-Policy so an injection that slips past both
still cannot run script.

**Two more paths turned up while fixing it** that the audit itself missed — which
is the argument for how it was fixed. The bundle log renders the filename from
the request path, including files that do not exist, so `GET /bundle/<markup>`
from anyone landed in Settings. And the network scan renders each host's SSH
banner, which is whatever the machine on port 22 chooses to say. A fourth was
in the import dialog, interpolating fields from the file being imported.

So markup is now built with an `html` tagged template that escapes every
interpolation by default, and `raw()` marks the few fragments that are already
safe. A missed case under that scheme shows a tag as text rather than running
it. `tests/check_html_sinks.py` fails on any plain template that builds markup
from an interpolation — it found 37 in the file before, none after.

Each layer was verified on its own, under an ingress mount: markup sent to
`/api/register` is cleaned on the way in; markup written **directly into the
database**, bypassing that, renders as text on the fleet page, the detail page
and the bundle log; and a live `onerror` injected straight into the page with
escaping bypassed entirely **does not run**, because the policy admits only
the hash of the GUI's own script.

### High

**2. Panel-facing write endpoints had no authentication.** *Verified.*
`POST /api/panel/{id}/display` returned 200 with no credentials of any kind, so
any device could retheme a panel, change its brightness floor, or repoint its
presence pin. `/api/register` let anyone add fleet entries.

**3. The panel websocket was unauthenticated and last-writer-wins.**
`LIVE[panel_id] = ws` with no check: connecting as a real panel's id evicted its
socket and received its config pushes. The panel quietly fell back to five-minute
polling.

**4. Full configuration disclosure.** *Verified.* `GET /api/config/{id}` returned
room labels, entity ids, the DALI gateway address and the presence pin to anyone.
Panel ids are guessable, and `/api/register` confirms which exist.

Fix for 2–4: a per-panel token, required on every panel-facing endpoint. See
*Panel tokens* below — the migration is the subtle part.

**5. The update channel was unauthenticated plaintext, and panels run it as root.**
Panels fetch `panel-agent.py` from `http://unraid.local:8099` and install it for
systemd to run as root. The sha256 manifest came over the same channel, so it
caught corruption but not a hostile server — and `.local` is mDNS, which anyone
on the LAN can answer. ARP- or mDNS-spoofing the server was **root on every
panel**.

Fix: the manifest — and the config — are signed with a per-panel key the
server holds and a spoofed server does not. See *Update signing*.

**6. No login rate limiting.** *Verified: 20 wrong passwords, none refused, ~19
attempts a second, the right password still accepted immediately after.* With
the shipped default that is a one-request compromise. Once a password is set in
the GUI it is PBKDF2 at 200k rounds, so unlimited concurrent attempts were also
a way to pin the add-on's CPU.

Fix: per-address backoff with a lockout, and a cap on concurrent password
verifications.

Five tries free, then locked out for 60 seconds, doubling per further failure
to fifteen minutes. While locked out the password is **not checked at all** —
otherwise the lockout is still a way to test guesses, only slower, and still a
way to make the server hash. Changing the password has the same limit, since
requiring the current one is what stops a hijacked session locking the owner
out, and unlimited guesses there would let it simply find it.

**One claim did not survive measurement.** PBKDF2 was moved off the event loop
into a thread, on the reasoning that it stalled every other request while it
ran. On the build tested here `hashlib.pbkdf2_hmac` holds the GIL — four
threads took 3.2× as long as one, on 24 cores — so the thread frees nothing and
the loop still waits. It is kept, since it helps wherever the GIL *is*
released, but it is not what bounds an attack. The lockout is: twenty wrong
passwords from one address cost five hashes (289 ms), not twenty (1126 ms with
the lockout disabled). `tests/test_login_limits.py` checks that, and was run
against a copy with the lockout switched off to confirm it fails there.

**16. Config reached the kiosk page's markup, and that page holds Home
Assistant's token.** *Found while fixing 5; verified exploitable.* The kiosk
builds `"cannot reach " + <ha_url>` into `innerHTML` when the Home Assistant
connection fails, `ha_url` comes from config, and config was unsigned — so a
machine posing as the server could push one. The page reads Home Assistant's
long-lived token from `secrets.json` on its own origin, so script there is not
a defaced screen, it is every device in the house. Tested both ways: with the
old code an `ha_url` carrying an `onerror` in its path ran, and a script in
that page read the token out of `secrets.json`; with the fix nothing ran. The
markup makes the address unreachable, which is precisely when that line runs.

Fix, three layers: the sink builds a text node; config is signed, so a spoofed
server cannot write it; and the server refuses an `ha_url` that is not a host
or an http(s) address — while still accepting a bare host, which the kiosk has
always allowed and which refusing would have turned into an error on Save.

### Medium

**7. Home Assistant token stored in plaintext.** A token typed into Settings is
kept in the `settings` table, and that database is inside HA's backups. Under
the add-on the Supervisor already injects a token, so the stored one is only
needed standalone.

**8. HA token on a command line.** The SSH install ran
`sudo env PANEL_HA_TOKEN=<token> bash`, which puts the token in the process
table — readable by any local user via `ps` for the length of the install.

**9. SSH host keys are trusted on first use.** `AutoAddPolicy`: a machine
impersonating the panel during provisioning would be trusted. Documented as a
deliberate trade-off — there is no prior key to pin — but the operator has no
way to check.

**10. Plain HTTP everywhere.** Session cookie, admin password and configuration
cross the LAN in the clear. Accepted for now: see *Not fixed*.

**11. Sessions never expire from memory.** Expired tokens stay in the dict for
the life of the process.

**12. The DALI gateway has no authentication** in the documented firmware. Not
this system's code, but this system drives it. See `DALI-INTEGRATION.md`.

### Low

**13. `/fonts/{name}` checked a prefix and suffix, not an allowlist.** *Tested:
not exploitable* — four traversal encodings all 404, because Starlette's path
converter will not match `/`. One route change from live, so fixed anyway.

**14. The bootstrap script's server URL could come from the `Host` header.**

**15. The bootstrap wrote the HA token into JSON with `printf`**, unescaped.
Harmless for HA's token alphabet; wrong in principle.

### Observation, not a finding

The server's SSH public key stays in each panel's `authorized_keys` after
provisioning. The server's policy is to SSH only to panels with an unused
provisioning token, but that is enforced in the server's code — the key itself
works on any panel. So **anyone with `/data` has SSH to every panel.** That is
inherent to key-based provisioning and to keeping Reinstall working, and it is
why hashing panel tokens at rest (see below) would buy nothing.

## What was already sound

Checked, not assumed: the agent binds `127.0.0.1` only; `secrets.json` is mode
600; SSH is key-only with `allow_agent=False`; the private key is written 600
and **only the public key is ever served**; every interpolated shell argument is
`shlex.quote`d; `slug()` confines panel ids to alphanumerics and hyphens — in any
script, not just ASCII, which a test later caught, but no shell or markup
metacharacter is alphanumeric anywhere; `/bundle/{name}` is
an allowlist; there is no CORS middleware and the session cookie is `httponly`
and `samesite=lax`, so cross-site request forgery is well covered; changing the
password requires the current one and ends every other session.

## Panel tokens

Each panel holds a random token at `/opt/panel/panel-token` (mode 600) and sends
it as `X-Panel-Token` on every request to the server, including the websocket.

**Migration is the hard part.** Existing panels have no token and are running an
agent that does not know tokens exist. Locking them out would be easy and would
leave them unable to fetch the agent that fixes it. So:

- A panel **without** a token on the server is in legacy mode: tokenless
  requests are accepted for it, exactly as before. Nothing breaks on upgrade.
- The new agent generates its token on first start and presents it when it
  registers. If the server has none for that panel, it takes it — trust on
  first use — and records when and from which address.
- From then on that panel's token is required everywhere, and legacy mode is
  over for it.

This is safe to roll out because the old agent can always update itself:
`/bundle/*` stays reachable without a token, and `poll_loop` checks it every
five minutes regardless of the websocket. And a new agent whose claim fails
triggers the agent's existing rollback, rather than stranding the panel.

**The trust-on-first-use window is real.** Between the server upgrading and a
panel claiming — normally seconds, since the socket reconnect pulls the new
agent immediately — something else could claim first. The worst outcome is the
real panel being refused by the server: it keeps running its cached config, so
**no light is affected**, but it stops taking config changes. That shows in the
GUI, along with the address each claim came from, and **Reset token** reopens
the claim. It is never worse than the unauthenticated state it replaces.

**Tested as a migration, not just as a feature.** `tests/test_panel_tokens.py`
builds a database with the *old* schema and two existing panels, starts the new
server against it, and then drives it: a tokenless agent keeps working on
every endpoint and can still fetch the bundle; the real new agent code claims;
from then on no-token and wrong-token are refused on register, heartbeat,
config, the panel writes and the websocket; a claimed panel cannot be renamed
by anything else; the token never appears in a panel row or an export; Reset
reopens the claim and the agent takes it back without prompting; two racing
claims produce exactly one winner; and unauthenticated fleet spam stops at 20.

**Found while doing it: presence and DALI waited on the server.** Both were
written to keep working with no server and no Home Assistant, and both sat in
the same `gather` as everything else — behind the loop that waits for register
to succeed. With the server down at boot, neither ever started. They now start
independently. Not a security finding, but the token work made register able
to refuse, which made it matter.

**Stored in plaintext on the server, deliberately.** The token also keys the
update HMAC, and an HMAC needs the secret itself. Hashing would protect against
the database leaking without the rest of `/data` — but `/data` also holds the
SSH key that reaches every panel, so that scenario buys nothing.

## Update signing

**The first design was worthless, and it is worth recording why.** It keyed an
HMAC on the panel's token. But the agent sends that token on every request —
including to a machine only pretending to be the server, which would read it
off the first request and sign anything it liked. A signature keyed on a
secret you hand to whoever claims to be the server authenticates nothing.

So there are two secrets, in opposite directions:

| | Proves | Sent |
|---|---|---|
| `panel-token` | the panel, to the server | on every request |
| `panel-sign-key` | the server, to the panel | **once**, in the claim |

After the claim the signing key never leaves the panel again — a marker file
records that the claim was made — so something posing as the server later sees
the token at most. That lets it pretend to be the panel, but not sign.

The server signs both the bundle manifest and the config with it. The agent
refuses either if the signature is absent or wrong, and still checks each
bundle file's sha256 against the signed manifest. A refused config leaves the
one on disk in place, which is the point of the panel caching it at all.

A claim must bring both secrets, and a signing key equal to the token is
refused. Reset clears both, and the panel's next claim carries the key again.

**Two bugs the tests found, both from one room name.** The signing test uses a
room called Küche, to check the signature holds over non-ASCII byte for byte.
`slug()` keeps accented letters, so that panel's id had one — and the ingest
validation from #1 was ASCII-only, so it refused that panel at register, which
makes a freshly updated agent roll itself back. Then the panel id was going in
an `X-Panel-Id` header, which is bytes: it happened to survive for Latin-1 and
would have failed every request for a room named in Polish, Greek or Chinese.
Ids are now validated as what `slug()` actually produces, and travel in URLs.

**One more found by tracing recovery rather than by a test.** If a panel's token
is reset while the panel is switched off, it comes back believing it has
claimed, registers without the key, and is refused — and the heartbeat that
normally notices a reset sits behind the loop waiting on that register. It
would have asked the same way forever. A refused claim now clears the marker.

`tests/test_signing.py`, 28 checks. The decisive ones: config and manifest
signed with the **token** — what a spoofed server can do — are refused, while
the same forgery signed with the real key verifies, so the check is not
vacuous; across four ordinary requests after the claim the key appears in
none of them and the token in all; and both reset paths recover.

The same trust-on-first-use caveat applies as for tokens: something present
*at the moment of the claim* would learn the key. Old agents ignore `_sig` —
unknown manifest keys have no install target — so the transition update itself
is unsigned, which is unavoidable: the agent doing it does not know how to
check.

## Not fixed

**Plain HTTP (10).** Fixing it properly means TLS with a pinned certificate on
every panel. The findings it enabled are now closed at the layer above — tokens
stop impersonation, the HMAC stops a spoofed server from shipping code, rate
limiting stops password guessing — so what remains is passive observation on
the LAN. Worth doing eventually; not a quick fix.

**Ingress trusting Home Assistant's own login.** Behind ingress the user has
already authenticated to Home Assistant, and the add-on could accept that
instead of a second password. A usability change to the auth model, so out of
scope for a security pass.

## Status

| # | Finding | Status |
|---|---|---|
| 1 | Stored XSS | **fixed** — escape by default, ingest validation, CSP |
| 2–4 | Unauthenticated panel endpoints and socket | **fixed** — per-panel tokens, TOFU migration |
| 6 | Login rate limiting | **fixed** — per-address lockout, password change too |
| 5 | Update signing | **fixed** — separate signing key; config signed too |
| 16 | Config → kiosk markup → HA token | **fixed** — text node, signed config, URL check |
| 7–15 | Medium and low | pending |
