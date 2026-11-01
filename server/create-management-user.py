"""Create a NEW management policy and display its one-time operator access key.

Run on the server using an authorized console; keep the displayed key private.
Existing policies are never overwritten. Add further users through an audited
operator-managed policy edit, using separate randomly generated keys.
"""
import argparse
import hashlib
import json
import os
import re
import secrets
from urllib.parse import urlsplit

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--policy", required=True)
parser.add_argument("--origin", required=True, help="Exact HTTPS browser origin, without a path")
parser.add_argument("--user", required=True)
parser.add_argument("--panel", action="append", required=True)
args = parser.parse_args()
u = urlsplit(args.origin)
if (u.scheme != "https" or not u.hostname or u.username or u.password
        or u.path or u.query or u.fragment):
    parser.error("origin must be HTTPS with no path or credentials")
if not re.fullmatch(r"[a-zA-Z0-9_.-]{1,64}", args.user):
    parser.error("invalid user name")
if any(not p or len(p) > 128 or p == "*" for p in args.panel):
    parser.error("use explicit panel IDs, never wildcards")
key = secrets.token_urlsafe(32)
policy = {"origin": args.origin, "users": {args.user: {
    "key_sha256": hashlib.sha256(key.encode()).hexdigest(),
    "roles": ["diagnostics.read"], "panels": args.panel}}}
fd = os.open(args.policy, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, "w", encoding="utf-8") as f:
    json.dump(policy, f, indent=2)
    f.write("\n")
print("Policy created. Store this operator key in your password manager:")
print(key)
