# Room detection — Panel Server and Pi Panel integration 0.19.0

The Pi remains a browser panel. Its optional Linux Bluetooth scanner implements
the ESPHome native API for Home Assistant; it is not ESPHome firmware flashed
onto the Pi. Bermuda runs in HA and estimates the room from several receivers.

## Operation

Open a panel in Panel Config Server → Room detection.

- **Keep existing setup** observes the installed service without changing it.
  This remains the migration default for older configurations. Newly provisioned
  Pi panels default to Enabled; templates explicitly set to Disabled retain that.
- **Enabled** starts an installed, inactive scanner and enables boot startup.
- **Disabled** stops that scanner and disables its boot startup. The Bluetooth
  radio and other services are untouched.
- **Apply scanner settings** changes only the Bluetooth section of this panel's
  configuration. Other unsaved form fields remain unsaved. The usual Save & push,
  export/import, templates and config rollback also include this section.
- **Refresh status** reads the latest heartbeat without discarding form edits.
  Allow up to 45 seconds for reconciliation (15s) plus reporting (30s).

The status shows the service, active state, boot state, controller and measured
process RSS. Running means the process is active; it does not prove HA is
receiving advertisements. Confirm delivery with Bermuda's Nearest Scanner and
Area sensors. Missing/stale heartbeat reports must not be taken as live status.

Home Assistant remains the authority for the scanner's area, active/passive
scanning and Bermuda calibration. The page links to those integrations. On the
current Study installation use **active** scanning; its BlueZ configuration did
not support passive scanning during the trial. Keep the existing device identity
so its HA registry and calibration remain associated.

Screen brightness, wake/sleep, idle and blank timers, diagnostics overlay,
CPU/disk readings, reload and sync continue through the existing **Pi Panel**
integration. Their entity IDs do not change. No parallel ESPHome screen-control
entities are created. Mobile Follow my room remains in each user's dashboard
settings; scanner administration does not overwrite those preferences.

## Runtime and boundaries

Signed panel config carries `bluetooth: {"mode":"existing"|"on"|"off"}`.
The root panel agent reconciles the cached config independently of server/HA
registration, using asynchronous systemctl calls with bounded timeouts. It only
manages `panel-bt-proxy.service` or the existing `study-bt-proxy.service`; if both
are installed it refuses to choose. Commands/service paths cannot come from
configuration. No pip/apt install, radio power change or service-file replacement
occurs during reconciliation. An uninstalled scanner is reported explicitly.
New hardware receives a scanner during provisioning, as described below.
Failed/masked services require diagnosis instead of an automatic restart loop.

The existing Study trial uses denvera/bt-proxy 1.0.3 at commit
3929ecb5c684069545281d4043a4c39d9cfad0e9, installed in /opt/study-bt-proxy,
ESPHome TCP 6053, scan-only, with an HA/localhost peer allowlist. This update
preserves its API restrictions, resource limits, service name and HA identity.

No presence automation, automatic lighting or panel screen wake is introduced.
Local GPIO presence and DALI operation are independent of scanner availability.

## Automatic provisioning (0.19.0)

All three install paths — SSH from the server, generated first-boot files and the
manual bootstrap command — run the same scanner installer after the panel agent
has started. The installer checks for hci0, installs BlueZ/rfkill and an isolated
Python environment, verifies the bundled source archive's SHA-256, and installs
`panel-bt-proxy.service`. Fresh enabled panels start the service immediately and
at boot. A template explicitly set to Disabled installs without starting it.

The scanner name derives from the immutable panel ID; its ESPHome identity is
the Bluetooth controller MAC. The visible name uses the provisioned hostname.
It advertises via mDNS and allows ESPHome TCP 6053 connections only from loopback
and the host resolved from the panel's **Connection → Home Assistant URL**.
Use HA's reachable LAN address/hostname here, not an external reverse proxy.
Installation requires access to the OS package repositories and PyPI.

Install/update the **Pi Panel integration 0.19.0** in HACS and restart HA once.
The integration then adds new panel controls and diagnostics on fleet refresh,
without another integration reload. It also enrols new provisioned, running
scanners using the normal ESPHome config flow and chooses active scanning.
Allow roughly 1–2 minutes after the panel and scanner start. Network failures
retry every five minutes; no failed setup forms are left behind. Existing or
ignored ESPHome entries and their options remain untouched.

When the panel's room matches an existing HA area name or ID, the new scanner's
device is assigned to that area. An ambiguous/missing match is left unassigned:
choose its actual area under ESPHome before relying on Bermuda room estimates.
Calibration and final room-transition testing still happen after mounting.

The installer never replaces an existing `study-bt-proxy.service` or
`panel-bt-proxy.service`. Reprovisioning preserves those installations, including
their identities. Normal signed agent updates do not run package installation.
An existing panel without a scanner needs provisioning to install one; selecting
Enabled alone is not an installation command.

Missing Bluetooth hardware, failed downloads or package errors do not prevent
screen provisioning. Room detection shows the recorded failure from
`/opt/panel/bluetooth-provision.json`, alongside live service status. Correct the
reported issue and re-run provisioning (use a newly issued install token), or
inspect a partially installed service before retrying. Do not overwrite Study's
working trial installation to make it match a newly provisioned panel.

The scanner is scan-only; its API remains plaintext behind the peer allowlist.
CPU quota is 20% of one core. Memory limits require kernel memory-cgroup support;
the status page reports measured RSS regardless of whether those limits work.

## Recovery

Changing Enabled/Disabled is reversible in the same control. Keep existing setup
stops management but leaves the current service state as-is. Restoring an old
config without Bluetooth settings also means observe-only; it does not undo the
last applied enable/disable. Select Enabled first if restoring the running trial.
The normal versioned config history is retained. The release's old server image
and signed agent rollback mechanism remain available; no scanner files or HA
devices are deleted.

## Verification

`python tests/test_bluetooth.py` tests real API auth, validation, narrow writes,
export/import and heartbeat storage, with mocked systemd services for observe,
enable/disable/startup, idempotence, failures, absent/conflicting units and timeout
cleanup. `node tests/test_bluetooth_admin.cjs` uses the real server mounted under
an ingress prefix and tests saving/status refresh without losing other config.
Existing RAM and display tests also apply. No hardware is actuated by these tests.

`python tests/test_bluetooth_provision.py` additionally exercises the real pinned
archive/installer with OS commands simulated, the generated one-use bootstrap,
new/legacy defaults, late-arriving HA entities, scanner enrolment, matching areas,
ignored entries, duplicate prevention, network backoff and canceled-flow cleanup.
These tests do not substitute for the first fresh Pi installation and a reboot
check on that hardware.
