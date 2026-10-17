#!/usr/bin/env python3
"""Provision a scan-only ESPHome-compatible receiver; never run from the updater.

Existing scanner installations are deliberately left alone. Failures are recorded
for the panel agent and do not prevent the display from completing provisioning.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import tarfile
import time
from urllib.parse import urlsplit

ARCHIVE_SHA = "dbd8adb622cff8ae089d3a7948ad3aa053f2434a7a994ed308d70d19d62d9c35"
ROOT = Path("/opt/panel-bt-proxy")
PANEL = Path("/opt/panel")
UNIT = Path("/etc/systemd/system/panel-bt-proxy.service")
ADAPTER = Path("/sys/class/bluetooth/hci0")


def run(*args, timeout=300):
    return subprocess.run(args, check=True, timeout=timeout,
                          text=True, capture_output=True).stdout


def record(status, **extra):
    PANEL.mkdir(parents=True, exist_ok=True)
    target = PANEL / "bluetooth-provision.json"
    temp = target.with_suffix(".tmp")
    temp.write_text(json.dumps({"status": status, **extra}) + "\n")
    temp.replace(target)
    print(f"Bluetooth: {status}", flush=True)


def existing_service():
    for name in ("study-bt-proxy.service", "panel-bt-proxy.service"):
        try:
            if run("systemctl", "show", name, "-p", "LoadState", "--value", timeout=15).strip() not in ("", "not-found"):
                return name
        except subprocess.CalledProcessError:
            pass
    return None


def ha_host(url):
    parsed = urlsplit(url)
    host = parsed.hostname or ""
    if parsed.scheme not in ("http", "https") or parsed.username or parsed.password:
        raise ValueError("Configure a LAN Home Assistant URL in the panel connection settings")
    if not re.fullmatch(r"[A-Za-z0-9.:-]+", host) or host in ("supervisor", "localhost", "127.0.0.1"):
        raise ValueError("Home Assistant URL must identify its LAN host")
    # Refuse an unrestricted listener if the HA host cannot be resolved.
    if not socket.getaddrinfo(host, 6053, type=socket.SOCK_STREAM):
        raise ValueError("Home Assistant host did not resolve")
    return host


def patch_source(root, host):
    path = root / "bt_proxy" / "api_server.py"
    source = path.read_text()
    anchor = "        conn = APIConnection(reader, writer, self)"
    if source.count(anchor) != 1:
        raise ValueError("Unexpected scanner source; refusing an unguarded API")
    # Resolution is bounded and off the event loop. Re-resolve on connection so
    # a DHCP change to HA does not require reinstalling the panel.
    guard = f'''        import socket
        peer = writer.get_extra_info("peername")
        allowed = {{"127.0.0.1", "::1"}}
        try:
            addresses = await asyncio.wait_for(
                asyncio.get_running_loop().getaddrinfo({host!r}, 6053, type=socket.SOCK_STREAM), 5)
            allowed.update(item[4][0] for item in addresses)
        except (OSError, asyncio.TimeoutError):
            pass
        if not peer or peer[0] not in allowed:
            writer.close()
            await writer.wait_closed()
            return
'''
    source = source.replace(anchor, guard + anchor)
    for flag in ("FEATURE_ACTIVE_CONNECTIONS", "FEATURE_REMOTE_CACHING"):
        source = source.replace(f"            | proto.{flag}\n", "")
    path.write_text(source)


def install(archive, url, panel_id, mode):
    if existing_service():
        print("Bluetooth: existing scanner preserved (identity, configuration and startup unchanged)")
        return
    if not ADAPTER.exists():
        raise ValueError("No hci0 Bluetooth adapter; check hardware and boot configuration")
    host = ha_host(url)
    # A fixed ASCII name based on the server identity is stable across renames.
    name = "panel-" + hashlib.sha256(panel_id.encode()).hexdigest()[:12] + "-ble"
    data = Path(archive).read_bytes()
    if hashlib.sha256(data).hexdigest() != ARCHIVE_SHA:
        raise ValueError("Scanner archive checksum mismatch")
    with socket.socket() as probe:
        probe.bind(("0.0.0.0", 6053))
    run("apt-get", "update", "-qq", timeout=600)
    run("env", "DEBIAN_FRONTEND=noninteractive", "apt-get", "install", "-y", "-qq",
        "python3-venv", "bluez", "rfkill", timeout=900)
    run("systemctl", "enable", "--now", "bluetooth.service")
    run("rfkill", "unblock", "bluetooth")
    for attempt in range(3):
        try:
            run("bluetoothctl", "power", "on", timeout=20)
            controller = run("bluetoothctl", "show", timeout=10)
            if "Powered: yes" in controller:
                break
        except subprocess.CalledProcessError:
            pass
        if attempt == 2:
            raise ValueError("Bluetooth adapter could not be powered on")
        time.sleep(2)
    mac_match = re.search(r"Controller\s+((?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2})", controller)
    if not mac_match or mac_match[1] == "00:00:00:00:00:00":
        raise ValueError("Bluetooth controller has no valid MAC identity")
    mac = mac_match[1].lower()
    ROOT.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, "r:gz") as tar:
        # No extraction of links, special files or paths outside this directory.
        for member in tar.getmembers():
            target = (ROOT / member.name).resolve()
            if not target.is_relative_to(ROOT.resolve()) or not (member.isdir() or member.isfile()):
                raise ValueError("Unsafe archive member")
        if hasattr(tarfile, "data_filter"):
            tar.extractall(ROOT, filter="data")
        else:  # Older Bookworm Python: members were validated above.
            tar.extractall(ROOT)
    patch_source(ROOT, host)
    run("python3", "-m", "venv", str(ROOT / ".venv"))
    python = str(ROOT / ".venv/bin/python")
    run(python, "-m", "pip", "install", "--disable-pip-version-check",
        "bleak==3.0.2", "dbus-fast==5.2.0", "ifaddr==0.2.0", "zeroconf==0.151.5", timeout=900)
    friendly = re.sub(r"[^A-Za-z0-9 -]", "", socket.gethostname()).strip()[:40] or "Pi"
    UNIT.write_text(f'''[Unit]
Description=Panel Bluetooth scanner (ESPHome API, scan only)
After=network-online.target bluetooth.service dbus.service
Wants=network-online.target bluetooth.service
StartLimitIntervalSec=300
StartLimitBurst=3

[Service]
Type=simple
WorkingDirectory={ROOT}
ExecStart={python} -m bt_proxy --name {name} --friendly-name "{friendly} Panel BLE" --adapter hci0 --max-connections 0 --log-level INFO
Restart=on-failure
RestartSec=15
TimeoutStopSec=20
Nice=10
CPUQuota=20%
MemoryHigh=96M
MemoryMax=192M
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
Environment=PYTHONDONTWRITEBYTECODE=1
LogRateLimitIntervalSec=60s
LogRateLimitBurst=30

[Install]
WantedBy=multi-user.target
''')
    run("systemd-analyze", "verify", str(UNIT), timeout=30)
    run("systemctl", "daemon-reload")
    if mode == "on":
        run("systemctl", "enable", "--now", UNIT.name)
        run("systemctl", "is-active", "--quiet", UNIT.name)
    record("Installed", managed=True, name=name, mac=mac, ha_host=host, panel_id=panel_id)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", required=True)
    parser.add_argument("--ha-url", required=True)
    parser.add_argument("--panel-id", required=True)
    parser.add_argument("--mode", choices=("on", "off", "existing"), default="on")
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise SystemExit("Run as root during panel provisioning")
    try:
        install(args.archive, args.ha_url, args.panel_id, args.mode)
    except Exception as error:
        # Exception classes/commands only; never dump captured package output or credentials.
        detail = str(error) if isinstance(error, ValueError) else type(error).__name__
        record("Installation incomplete: " + detail, managed=False)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
