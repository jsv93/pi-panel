"""Provisioning over SSH.

Deliberately narrow. CLAUDE.md's rule is that the config server pushes config
and never commands, and this is the one documented exception: the server may
run the bootstrap on a panel it is *currently provisioning*, and nothing else.
The caller enforces that by requiring an unused provisioning token, so the
server cannot reach a panel that is already in service.

Key-based only. Raspberry Pi Imager takes an authorised key at flash time, so
there is nowhere a password would need to be typed, stored, or transmitted.
"""
import os
import shlex
import socket
import time

import paramiko
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

SSH_DIR = os.environ.get("PANEL_SSH_DIR", "/data/ssh")
KEY_PATH = os.path.join(SSH_DIR, "id_ed25519")
PUB_PATH = KEY_PATH + ".pub"


def ensure_key():
    """Generate the fleet key on first use. ed25519: short enough to paste into
    Imager without wrapping, and paramiko has no generator for it, hence
    cryptography (which paramiko already depends on)."""
    if os.path.exists(KEY_PATH) and os.path.exists(PUB_PATH):
        return open(PUB_PATH).read().strip()
    os.makedirs(SSH_DIR, exist_ok=True)
    k = ed25519.Ed25519PrivateKey.generate()
    priv = k.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.OpenSSH,
        serialization.NoEncryption(),
    )
    pub = k.public_key().public_bytes(
        serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH
    ).decode() + " panel-config-server"
    fd = os.open(KEY_PATH, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(priv)
    with open(PUB_PATH, "w") as f:
        f.write(pub + "\n")
    return pub


def public_key():
    try:
        return ensure_key()
    except Exception as e:
        return f"(could not create a key: {e})"


def _client():
    ensure_key()
    key = paramiko.Ed25519Key.from_private_key_file(KEY_PATH)
    c = paramiko.SSHClient()
    # Accept-on-first-use. A panel being provisioned has no prior key to pin,
    # so this is a first-contact trust decision on the local network; there is
    # nothing better available without a manual fingerprint step.
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    return c, key


DONE = "=== finished, exit "


def bootstrap_lines(host, user, url, hostname="", ha_token="", port=22, timeout=20):
    """Yield the install's output as it happens.

    Streamed rather than returned in one lump: this takes several minutes --
    apt, chromium, cage -- and a blank dialog for that long is indistinguishable
    from a hang.
    """
    c, key = _client()
    try:
        c.connect(hostname=host, port=port, username=user, pkey=key, timeout=timeout,
                  allow_agent=False, look_for_keys=False, auth_timeout=timeout)
    except paramiko.AuthenticationException:
        yield (f"{user}@{host} rejected the key.\n\n"
               "Add the server's public key to the panel — Raspberry Pi Imager's "
               "advanced options accept it at flash time — and check the username.\n")
        yield DONE + "1 ===\n"
        return
    except Exception as e:
        hint = ""
        if isinstance(e, socket.gaierror) or "gaierror" in e.__class__.__name__:
            hint = ("\n\nThe server runs in a container, where .local names do not "
                    "resolve — mDNS does not cross that boundary. Use the panel's "
                    "IP address instead.")
        yield f"Could not reach {user}@{host}: {e.__class__.__name__}: {e}{hint}\n"
        yield DONE + "1 ===\n"
        return

    try:
        # The bootstrap needs root and there is no terminal here, so sudo must
        # be passwordless. Check first: the failure is otherwise a silent hang
        # or an unhelpful "sudo: a password is required" buried in the output.
        _in, _out, _err = c.exec_command("sudo -n true", timeout=timeout)
        if _out.channel.recv_exit_status() != 0:
            yield (f"{user}@{host} cannot use sudo without a password, which this "
                   "needs since there is no terminal to prompt on.\n\n"
                   "Raspberry Pi Imager's default user has passwordless sudo; a "
                   "hand-created user may not.\n")
            yield DONE + "1 ===\n"
            return

        cmd = "curl -fsSL {} | sudo -n env PANEL_HA_TOKEN={} bash -s -- {}".format(
            shlex.quote(url), shlex.quote(ha_token or ""), shlex.quote(hostname or "")
        )
        _in, out, err = c.exec_command(cmd, timeout=None, get_pty=False)
        chan = out.channel
        chan.set_combine_stderr(True)
        while True:
            if chan.recv_ready():
                data = chan.recv(4096)
                if data:
                    yield data.decode(errors="replace")
                    continue
            if chan.exit_status_ready() and not chan.recv_ready():
                break
            time.sleep(0.05)
        rest = chan.recv(65536) if chan.recv_ready() else b""
        if rest:
            yield rest.decode(errors="replace")
        yield DONE + f"{chan.recv_exit_status()} ===\n"
    finally:
        c.close()


def run_bootstrap(host, user, url, hostname="", ha_token="", port=22, timeout=20):
    """Whole-output form, for callers that do not want a stream."""
    body = "".join(bootstrap_lines(host, user, url, hostname, ha_token, port, timeout))
    status = 1
    if DONE in body:
        head, _, tail = body.rpartition(DONE)
        body = head
        try:
            status = int(tail.split()[0])
        except Exception:
            pass
    return {"ok": status == 0, "exit_status": status, "output": body.strip()}
