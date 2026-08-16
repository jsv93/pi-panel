# Home Assistant add-on

Runs the config server inside Home Assistant, so an HA deployment does not have
a second thing to install and update alongside. Standalone Docker
(`server/docker-compose.yml`) remains the alternative; the installer picks one.

Requires **Home Assistant OS or Supervised** — add-ons do not exist under HA
Container.

## What differs from standalone

| | Standalone | Add-on |
|---|---|---|
| GUI | `http://<host>:8099` | HA sidebar, behind HA's auth |
| Home Assistant access | `HA_URL` + `HA_TOKEN` | Supervisor, nothing to configure |
| Data | `./data` bind mount | `/data`, included in HA backups |
| Updates | `docker compose up --build` | HA's add-on updates |

The app is the same. Everything above is packaging.

## Two addresses, not one

This is the part worth understanding before installing.

Ingress serves the GUI through Home Assistant, at a URL that requires HA's
authentication. **A panel cannot use that URL.** Provisioning commands and
`firstrun.sh` have to carry an address the panel itself can fetch.

`host_network: true` means the server also answers directly on `:8099` on the
LAN, which is that address. In most installs it is detected correctly and there
is nothing to do. If the GUI's **How panels reach this server** card shows the
wrong address, set `panel_url` in the add-on's options.

Get this wrong and provisioning hands out a command the Pi cannot fetch — which
fails in a thoroughly confusing way, because everything else looks fine.

## Auth is still required

`host_network: true` also means `:8099` is reachable on the LAN *without* going
through ingress, and therefore without HA's authentication. So the add-on still
has its own `admin_password`. Logging in inside an already-authenticated sidebar
is mildly redundant; the alternative leaves that port open.

## Installing

Home Assistant expects `repository.yaml` at the root of an add-on repository,
with each add-on in a top-level folder. This directory is laid out for that but
lives inside the main repo, so it is **not installable as-is**. Either:

- copy `panel-server/` and a `repository.yaml` into their own repo — preferred,
  so the add-on versions on its own cadence; or
- add `repository.yaml` at the root of this repo and move `panel-server/` up
  beside it, accepting that the repo then does double duty.

The build also needs `requirements.txt` and `app/` from `server/`, which the
Dockerfile expects beside it. Whichever layout is chosen has to bring those
along — a copy step, a submodule, or building the image in CI and pointing
`config.yaml` at it with `image:` instead.

That packaging decision is deliberately still open.
