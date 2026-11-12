"""Build a public release ZIP from its audited Windows executable."""
import hashlib
import json
from pathlib import Path
import sys
import zipfile

from PyInstaller.archive.readers import CArchiveReader

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
import patch_firmware

FIRMWARE = 'firmware/DDF-2.0.5.bin'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def package(executable):
    archive = CArchiveReader(str(executable))
    firmware_entries = [name for name in archive.toc if name.replace('\\', '/') == FIRMWARE]
    if len(firmware_entries) != 1:
        raise ValueError('Public releases require exactly one official firmware resource')
    firmware = archive.extract(firmware_entries[0])
    patch_firmware._require_original(firmware)
    if any(name.replace('\\','/').lower().startswith('startup/presets/') for name in archive.toc):
        raise ValueError('Unexpected bundled startup preset')
    # Use release guides when invoked from the development checkout.
    guides = PROJECT / 'packaging' / 'public'
    player_guide = guides / 'player-build.md' if guides.is_dir() else PROJECT / 'docs/startup-animation.md'
    if not guides.is_dir():
        guides = PROJECT
    files = {name: (guides / name).read_bytes() for name in ('README.md', 'README.fr.md', 'CONTRIBUTING.md')}
    files['CONTRIBUTING.md'] = files['CONTRIBUTING.md'].replace(b'docs/player-build.md', b'docs/startup-animation.md')
    for name in ('LICENSE', 'CREDITS.md', 'docs/startup-media.md'):
        files[name] = (PROJECT / name).read_bytes()
    files['compatibility.json'] = archive.extract('compatibility.json')
    files['docs/startup-animation.md'] = player_guide.read_bytes()
    files[executable.name] = executable.read_bytes()
    files[FIRMWARE] = firmware
    checksums = ''.join(f'{digest(data)}  {name}\n' for name, data in sorted(files.items()))
    files['SHA256SUMS.txt'] = checksums.encode('ascii')
    version = patch_firmware.VERSION.split('-')[0]
    result = executable.parent / f'DDF350-Portable-Public-v{version}.zip'
    with zipfile.ZipFile(result, 'x', zipfile.ZIP_DEFLATED) as package_zip:
        for name, data in files.items():
            package_zip.writestr(name, data)
    with zipfile.ZipFile(result) as package_zip:
        if set(package_zip.namelist()) != set(files) or any(package_zip.read(name) != data for name, data in files.items()):
            raise ValueError('ZIP readback failed')
    checksum = digest(result.read_bytes())
    result.with_name(result.name + '.sha256').write_text(f'{checksum}  {result.name}\n', encoding='ascii')
    return {'file': result.name, 'sha256': checksum, 'bytes': result.stat().st_size}


if __name__ == '__main__':
    print(json.dumps(package(Path(sys.argv[1]).resolve())))
