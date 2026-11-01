"""Generate local TLS material and a named operator; never print private data.

The signing CA private key exists only in memory and is discarded. Its name
constraints permit only the selected host; the server receives only its leaf key.
Trust root.crt on operator devices, and keep access-key.txt in a password manager.
"""
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import secrets
from urllib.parse import urlsplit

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID, ExtendedKeyUsageOID


def certificates(host):
    now = datetime.now(timezone.utc)
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    leaf_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'Pi Panel local trust ' + host)])
    leaf_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, host)])
    try:
        addr = ipaddress.ip_address(host)
        san = x509.IPAddress(addr)
        constraint = x509.IPAddress(ipaddress.ip_network(str(addr) + ('/32' if addr.version == 4 else '/128')))
    except ValueError:
        san = constraint = x509.DNSName(host)
    ca = (x509.CertificateBuilder().subject_name(ca_name).issuer_name(ca_name)
        .public_key(ca_key.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5)).not_valid_after(now + timedelta(days=366))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(x509.KeyUsage(False, False, False, False, False, True, True, False, False), critical=True)
        .add_extension(x509.NameConstraints([constraint], None), critical=True)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), critical=False)
        .sign(ca_key, hashes.SHA256()))
    leaf = (x509.CertificateBuilder().subject_name(leaf_name).issuer_name(ca_name)
        .public_key(leaf_key.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5)).not_valid_after(now + timedelta(days=365))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.SubjectAlternativeName([san]), critical=False)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .add_extension(x509.KeyUsage(True, False, True, False, False, False, False, False, False), critical=True)
        .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
        .sign(ca_key, hashes.SHA256()))
    return (ca.public_bytes(serialization.Encoding.PEM).decode(),
            leaf.public_bytes(serialization.Encoding.PEM).decode(),
            leaf_key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                   serialization.NoEncryption()).decode())


def create(origin, user, panels, directory):
    url = urlsplit(origin)
    if url.scheme != 'https' or url.port != 8449 or not url.hostname or url.path or url.query or url.fragment or url.username:
        raise ValueError('Use https://HOST:8449 with no path')
    directory.mkdir(mode=0o700, parents=True, exist_ok=False)
    root, leaf, private = certificates(url.hostname)
    key = secrets.token_urlsafe(32)
    options = dict(secure_diagnostics=True, management_origin=origin, management_user=user,
        management_key_sha256=hashlib.sha256(key.encode()).hexdigest(), management_panels=panels,
        management_certificate=leaf + root, management_private_key=private)
    for name, text in [('root.crt', root), ('options.json', json.dumps(options)),
                       ('access-key.txt', key + '\n')]:
        fd = os.open(directory / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as f:
            f.write(text)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--origin', required=True)
    p.add_argument('--user', required=True)
    p.add_argument('--panel', action='append', required=True)
    p.add_argument('--directory', type=Path, required=True)
    a = p.parse_args()
    create(a.origin, a.user, a.panel, a.directory)
    print('Created private configuration and access key; no credentials printed.')
