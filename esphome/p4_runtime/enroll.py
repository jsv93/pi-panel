"""Register an unused P4 identity once with the configured Panel Server."""
import argparse
import json
from pathlib import Path
from urllib.request import Request, build_opener, HTTPRedirectHandler


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("identity", type=Path)
    p.add_argument("--ip", required=True)
    args = p.parse_args()
    identity = json.loads(args.identity.read_text())
    url = identity["server"].rstrip("/")
    device = identity["id"]
    client = build_opener(NoRedirect())
    seen = json.load(client.open(url + "/api/panel_seen/" + device, timeout=6))["seen"]
    headers = {"Content-Type": "application/json", "X-Panel-Token": identity["token"]}
    if not seen:
        headers["X-Panel-Sign-Key"] = identity["sign_key"]
    info = dict(panel_id=device, hostname=device, mac=identity["mac"],
                ip=args.ip, kind="esp", version="p4-candidate")
    request = Request(url + "/api/register", data=json.dumps(info).encode(), headers=headers)
    reply = json.load(client.open(request, timeout=6))
    if reply["panel_id"] != device or reply["token"] not in ("active", "claimed"):
        raise ValueError("Panel Server did not accept the device identity")
    print(f"{device} enrolled; assigned to a room: {bool(reply['claimed'])}")


if __name__ == "__main__":
    main()
