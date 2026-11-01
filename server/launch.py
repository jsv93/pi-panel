"""Run the existing LAN service and optional native TLS in one process.

Both listeners share enrollment, LIVE sockets and short-lived operator sessions.
Forwarded headers are disabled: the management TLS check reflects the real socket.
"""
import asyncio
import json
import os
from pathlib import Path
import ssl
from urllib.parse import urlsplit

import uvicorn


def private_write(path, content):
    temporary = path.with_suffix('.tmp')
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.chmod(temporary, 0o600)
    with os.fdopen(fd, 'w') as f:
        f.write(content)
    os.replace(temporary, path)


def configure(options, directory):
    if not options.get('secure_diagnostics', False):
        return None
    origin = options.get('management_origin', '')
    url = urlsplit(origin)
    if (url.scheme != 'https' or not url.hostname or url.port != 8449
            or url.path or url.query or url.fragment or url.username or url.password):
        raise ValueError('Management origin must be https://HOST:8449')
    import re
    user = options.get('management_user', '')
    key_hash = options.get('management_key_sha256', '')
    panels = options.get('management_panels', [])
    if (not re.fullmatch(r'[a-zA-Z0-9_.-]{1,64}', user)
            or not re.fullmatch(r'[a-f0-9]{64}', key_hash)
            or not isinstance(panels, list) or not panels
            or any(not isinstance(p, str) or not re.fullmatch(r'[\w-]{1,128}', p) for p in panels)):
        raise ValueError('A named operator, random key digest and explicit panels are required')
    directory.mkdir(parents=True, exist_ok=True)
    certificate = directory / 'management-cert.pem'
    private_key = directory / 'management-key.pem'
    private_write(certificate, options.get('management_certificate', ''))
    private_write(private_key, options.get('management_private_key', ''))
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certificate, private_key)
    import hashlib
    # The first PEM block is the server leaf. Agents pin that exact certificate.
    leaf = certificate.read_text().split('-----END CERTIFICATE-----')[0] + '-----END CERTIFICATE-----'
    fingerprint = hashlib.sha256(ssl.PEM_cert_to_DER_cert(leaf)).hexdigest()
    policy = directory / 'management-policy.json'
    private_write(policy, json.dumps({'origin': origin, 'users': {user: {
        'key_sha256': key_hash, 'roles': ['diagnostics.read'], 'panels': panels}}}))
    os.environ.update(PANEL_MANAGEMENT_POLICY=str(policy),
                      PANEL_MANAGEMENT_FINGERPRINT=fingerprint,
                      PANEL_MANAGEMENT_AUDIT=str(directory / 'management-audit.db'))
    return str(certificate), str(private_key)


async def run():
    data_dir = Path(os.environ.get('PANEL_DATA_DIR', '/data'))
    options_file = data_dir / 'options.json'
    options = json.loads(options_file.read_text()) if options_file.exists() else {}
    try:
        tls = configure(options, data_dir)
    except Exception:
        # A typo in optional management settings must not take the dashboard down.
        os.environ.pop('PANEL_MANAGEMENT_POLICY', None)
        os.environ.pop('PANEL_MANAGEMENT_FINGERPRINT', None)
        print('Secure diagnostics disabled: check TLS certificate and operator settings', flush=True)
        tls = None
    from app.main import app
    configs = [uvicorn.Config(app, host='0.0.0.0', port=8099, proxy_headers=False)]
    if tls:
        configs.append(uvicorn.Config(app, host='0.0.0.0', port=8449,
            ssl_certfile=tls[0], ssl_keyfile=tls[1], proxy_headers=False,
            lifespan='off', ws_max_size=65536))
    servers = [uvicorn.Server(c) for c in configs]
    tasks = [asyncio.create_task(s.serve()) for s in servers]
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for server in servers:
            server.should_exit = True
        await asyncio.gather(*tasks)


if __name__ == '__main__':
    asyncio.run(run())
