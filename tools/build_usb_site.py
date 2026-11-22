"""Build only the public USB bridge. Never include firmware or server data."""
import argparse
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
FILES = {
    'p4-usb-window.html': 'index.html',
    'p4-usb-window.js': 'p4-usb-window.js',
    'p4-usb-session.js': 'p4-usb-session.js',
    'p4-usb.js': 'p4-usb.js',
    'p4-vendor/esptool-0.7.1.js': 'p4-vendor/esptool-0.7.1.js',
    'p4-vendor/LICENSE': 'p4-vendor/LICENSE',
    'p4-vendor/NOTICE.json': 'p4-vendor/NOTICE.json',
}


def build(output):
    output = Path(output)
    if output.exists() and any(output.iterdir()):
        raise ValueError('Use an empty output directory to avoid publishing unrelated files')
    for source, target in FILES.items():
        destination = output / 'usb' / target
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / 'server/app/static' / source, destination)
    (output / '.nojekyll').touch()
    print(f'Built {len(FILES)} public USB assets; no firmware or configuration')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('output', type=Path)
    build(parser.parse_args().output)
