# Home Assistant add-on: plan

Package the config server as a Home Assistant add-on, so an HA deployment
installs and updates it from HA rather than running a second thing alongside.
Standalone Docker stays as-is; the installer picks a shape.

Target is Home Assistant OS (running as a VM here), so the Supervisor is
available. Add-ons do not exist under HA Container.

Not started. Written up so tomorrow does not begin by re-deriving it.

## The model

ESPHome is the precedent worth copying: one dashboard shipped both as an HA
add-on and as a standalone Docker image, with a *separate* integration for the
device-facing side.

- **HA deployment** — the server runs as an add-on, GUI in HA's sidebar
- **Standalone** — the current compose file, unchanged
- **The integration** works with either, since it talks to the server's HTTP API

Keep the add-on and the integration separate. Bundling them would mean no
integration in a standalone deployment, which defeats the split.

## What HAOS gives us

- **`/data` is the add-on's persistent volume**, so `PANEL_DB=/data/panels.db`
  and the bundle directory work unchanged. No migration.
- **`SUPERVISOR_TOKEN`** with `homeassistant_api: true` reaches HA at
  `http://supervisor/core/api`. **`HA_URL`/`HA_TOKEN` disappear entirely** in
  this deployment — worth having for its own sake, given how much trouble that
  pair caused (`.local` resolution, quoted values in `.env`, empty dropdowns
  with no error).
- **Ingress** puts the GUI in the sidebar behind HA's auth, on no extra port.

## Manifest sketch

    name: Panel Config Server
    slug: panel_server
    version: "0.1.0"
    arch: [amd64, aarch64]
    startup: services
    boot: auto
    host_network: true        # keeps .local reachable, matches standalone
    homeassistant_api: true   # replaces HA_URL / HA_TOKEN
    ingress: true
    ingress_port: 8099
    panel_icon: mdi:tablet-dashboard
    options: { admin_password: "", panel_url: "" }
    schema:  { admin_password: password?, panel_url: str? }

Plus `repository.yaml`, a `run.sh` mapping options to env vars, and the
existing Dockerfile.

## Three code changes

### 1. Relative URLs in the frontend

Ingress serves the app under `/api/hassio_ingress/<token>/`, so absolute
`fetch("/api/...")` breaks. Derive a base once at load:

    const BASE = location.pathname.replace(/\/[^/]*$/, "/");

About five call sites: the `api()` helper, the streaming install, the firstrun
download, the preview iframe.

### 2. Two URLs, not one — the one that will bite

The server currently derives its address from the incoming request. Under
ingress that request arrives via HA's proxy, so the derived URL is an ingress
URL **panels cannot reach** — it needs HA auth and is internal to HA.

Two separate notions are needed:

- **Admin URL** — ingress, HA-authenticated, for the operator
- **Panel URL** — `http://<ha-host-ip>:8099`, direct on the LAN, baked into
  bootstrap commands and `firstrun.sh`

Get this wrong and provisioning hands out commands pointing somewhere the Pi
cannot fetch. Make it an explicit add-on option rather than deriving it.

### 3. Keep the existing auth

With `host_network: true` the app is also reachable directly on `:8099`,
bypassing ingress and HA's auth. The password has to stay for that path.
Logging in inside an already-authenticated sidebar is mildly redundant; the
alternative leaves the direct port open.

## Distribution

HA expects `repository.yaml` at a repository root. Either a separate
`pi-panel-addon` repo, or add `repository.yaml` here and put the add-on in a
subfolder — which works but makes this repo do double duty. Leaning separate,
so the add-on versions on its own cadence.

## Sequencing

Settle `config_owner` first. In an HA deployment the pull to let HA own
everything is strongest, and that rule wants to exist before the add-on does,
not after.

## Related: config ownership

**Implemented.** Server setting `config_owner`, enforced on the four endpoints
that write panel config — claim, config, rollback, templates — by refusing with
409 whichever side does not own it. Home Assistant identifies itself with an
`X-Panel-Client` header; both sides are already admin-authenticated, so this is
discipline, not security. Provisioning is deliberately not covered: installing
hardware is the server's job under either setting.

Handing ownership over is itself never refused, or a misconfiguration would
lock both sides out of their own config.

Exactly one source of truth, selected by the installer:

- `config_owner: server` — today's behaviour; the integration is read-only and
  cannot write config
- `config_owner: homeassistant` — HA owns it; the server's config screens go
  read-only with a banner, and HA writes through the server's API

The agent pull path is unchanged either way, so HA is never in the delivery
path and can be down without consequence. The enforcement matters as much as
the setting: "one place" only holds if the other place actively refuses edits,
otherwise you get two half-configured panels and no way to tell which is right.

## Effort

A focused day, nearly all plumbing. No new concepts and no change to how
panels work.
