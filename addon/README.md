# Home Assistant add-on

Runs the config server inside Home Assistant, so an HA deployment has no second
thing to install and update. Standalone Docker (`server/docker-compose.yml`)
remains the alternative; the installer picks one.

Requires **Home Assistant OS or Supervised** — add-ons do not exist under HA
Container.

## This directory is the add-on repository

The contents here are laid out as the *root* of a separate repository, because
Home Assistant expects `repository.yaml` at a repo root with each add-on in a
top-level folder. To publish:

Create an empty `pi-panel-addon` repository on github.com — no README,
.gitignore or licence, since those collide with the first push — then:

    cp -r addon/* ../pi-panel-addon/
    cd ../pi-panel-addon
    git init -b main
    git add -A && git commit -m "Panel Config Server add-on"
    git remote add origin https://github.com/jsv93/pi-panel-addon.git
    git push -u origin main

Then in Home Assistant: **Settings → Add-ons → Add-on Store → ⋮ → Repositories**
and add `https://github.com/jsv93/pi-panel-addon`.

Nothing is built on the Home Assistant host. `config.yaml` points at an image
published by `.github/workflows/addon-image.yml` in the main repo, which
matters because building here would compile `cryptography` on the HAOS VM on
every update.

## Releasing a new version

1. Bump `version:` in `panel-server/config.yaml`
2. Tag the main repo: `git tag v0.2.3 && git push --tags`

That is the whole release. CI builds the images and then pushes this directory
to the add-on repository itself, so the version Home Assistant sees cannot
appear before the image it names. Doing those two steps by hand went wrong in
all three possible ways: the manifest behind the image, a tag pushed against a
stale manifest, and the manifest ahead of an image that was never built. The
last one gives "manifest unknown" on every install attempt.

Automatic publishing needs a **`ADDON_REPO_TOKEN`** secret on the `pi-panel`
repository — a fine-grained personal access token with *Contents: read and
write* on `pi-panel-addon`. `GITHUB_TOKEN` cannot be used, as it only grants
access to the repository the workflow runs in.

Without that secret the workflow says so and does nothing else; run
`addon/sync.sh` and push this repository by hand as before.

## Paste two keys, not one

Raspberry Pi Imager's authorized_keys box takes one key per line. Put the
server's key in it, and your own underneath.

With only the server's key, a panel accepts public-key auth and nothing else,
and the private half lives on the server — so there is no way to get a shell on
that panel from your own machine, which during bring-up you will want.

## Two addresses, not one

The part worth understanding before installing.

Ingress serves the GUI through Home Assistant, at a URL requiring HA's
authentication. **A panel cannot use that URL.** Provisioning commands and
`firstrun.sh` must carry an address the panel itself can fetch.

`host_network: true` means the server also answers directly on `:8099` on the
LAN, which is that address. Usually it is detected correctly and there is
nothing to do. If the GUI's **How panels reach this server** card shows the
wrong one, set `panel_url` in the add-on options.

Get this wrong and provisioning hands out a command the Pi cannot fetch, which
fails confusingly because everything else looks fine.

## Auth is still required

`host_network: true` also means `:8099` is reachable on the LAN *without* going
through ingress, and so without Home Assistant's authentication. The add-on
keeps its own `admin_password` for that path. Logging in inside an
already-authenticated sidebar is mildly redundant; the alternative leaves the
port open.

## Home Assistant access needs no configuring

With `homeassistant_api: true` the Supervisor injects a token and proxies the
core API, so `HA_URL` and `HA_TOKEN` are unset here and the server falls back
to that automatically. Setting either explicitly still overrides it.
