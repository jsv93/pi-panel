"""Narrow, signed per-panel public-key management. No shell input or SSH proxy."""
import re
import time
from cryptography.hazmat.primitives import serialization
from . import db


def validate(body):
    if not isinstance(body, dict) or body.get('action', 'list') not in ('list', 'add', 'remove'):
        raise ValueError('Choose list, add or remove')
    result = {'action': body.get('action', 'list')}
    user = body.get('user', '')
    if not isinstance(user, str) or (user and not re.fullmatch(r'[a-z_][a-z0-9_-]{0,31}', user)):
        raise ValueError('Choose a local panel user')
    result['user'] = user
    if result['action'] == 'add':
        key, name = body.get('key', ''), body.get('name', '')
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 60 or any(ord(c)<32 for c in name):
            raise ValueError('Enter a computer name of 1–60 characters')
        if 'panel-config-server' in name or 'pi-panel-server' in name:
            raise ValueError('That name is reserved for the managed server key')
        if not isinstance(key, str) or len(key) > 8192 or '\n' in key.strip() or '\r' in key.strip():
            raise ValueError('Paste one public-key line, never a private key')
        fields = key.strip().split()
        if len(fields) < 2 or fields[0] not in ('ssh-ed25519', 'ssh-rsa', 'ecdsa-sha2-nistp256', 'ecdsa-sha2-nistp384', 'ecdsa-sha2-nistp521'):
            raise ValueError('Use an ED25519, RSA or ECDSA public key without key options')
        try:
            parsed = serialization.load_ssh_public_key((' '.join(fields[:2])).encode())
            if fields[0] == 'ssh-rsa' and parsed.key_size < 2048:
                raise ValueError('RSA keys must have at least 2048 bits')
        except Exception:
            raise ValueError('The public key is invalid or too short')
        result.update(key=' '.join(fields[:2]), name=name.strip())
    if result['action'] == 'remove':
        fp = body.get('fingerprint', '')
        if not isinstance(fp, str) or not re.fullmatch(r'SHA256:[A-Za-z0-9+/]{43}', fp):
            raise ValueError('Choose the key to remove')
        result['fingerprint'] = fp
    return result


def audit(panel_id, actor, action, detail):
    with db.conn() as c:
        c.execute('INSERT INTO access_audit(panel_id,at,actor,action,detail) VALUES(?,?,?,?,?)',
                  (panel_id, time.time(), actor, action, detail[:200]))
        c.execute('DELETE FROM access_audit WHERE id NOT IN (SELECT id FROM access_audit ORDER BY id DESC LIMIT 5000)')


def history(panel_id):
    with db.conn() as c:
        return [dict(r) for r in c.execute('SELECT at,actor,action,detail FROM access_audit WHERE panel_id=? ORDER BY id DESC LIMIT 30', (panel_id,))]
