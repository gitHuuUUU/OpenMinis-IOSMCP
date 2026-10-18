"""Fetch the reproducible private runtime asset and verify every embedded wheel."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    catalog = json.loads((ROOT / 'tools/frida-runtime-catalog.json').read_text())
    target = ROOT / 'src/ios/BuildWorkbench.bundle/frida'
    with tempfile.TemporaryDirectory() as temp:
        temp = Path(temp)
        subprocess.run(['gh', 'release', 'download', catalog['release'], '--repo',
                        os.environ.get('GITHUB_REPOSITORY', 'gitHuuUUU/OpenMinis-IOSMCP'),
                        '-p', catalog['asset'], '-D', str(temp)], check=True)
        archive = temp / catalog['asset']
        assert archive.stat().st_size == catalog['bytes'], 'Runtime archive size mismatch'
        assert hashlib.sha256(archive.read_bytes()).hexdigest() == catalog['sha256'], 'Runtime archive hash mismatch'
        with tarfile.open(archive) as tar:
            for member in tar.getmembers():
                path = PurePosixPath(member.name)
                assert not path.is_absolute() and '..' not in path.parts and '\\' not in member.name
                assert path.parts and path.parts[0] == 'bundle'
                assert member.isfile() or member.isdir(), 'No links/devices allowed'
            tar.extractall(temp / 'unpacked')
        source = temp / 'unpacked/bundle'
        manifest = json.loads((source / 'manifest.json').read_text())
        assert manifest == catalog['manifest'], 'Wheel manifest mismatch'
        expected = set()
        for wheel in manifest['wheels']:
            name = wheel['filename']
            assert PurePosixPath(name).name == name and name.endswith('.whl')
            assert name not in expected
            expected.add(name)
            path = source / 'wheels' / name
            assert path.stat().st_size == wheel['bytes']
            assert hashlib.sha256(path.read_bytes()).hexdigest() == wheel['sha256'], name
        assert {p.name for p in (source / 'wheels').iterdir()} == expected
        target.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, target, dirs_exist_ok=True)
        print(f'Verified offline Frida bundle: {len(expected)} wheels')


if __name__ == '__main__':
    main()
