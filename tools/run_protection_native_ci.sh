#!/bin/sh
# Entry point for the private native ARM64 build dispatcher.
set -eu
cd /work
apk add --no-cache python3
cleanup() {
    result=$?
    trap - EXIT
    if [ -f /work/bundle/manifest.json ]; then cp /work/bundle/manifest.json /work/runtime-manifest.json; fi
    # Preserve small diagnostics on both success and failure; never package a
    # second copy of the uploaded rootfs/SDK/offline APKs into CI evidence.
    python3 - <<'PY'
from pathlib import Path
import shutil
root=Path('/work')
guest=root/'protection-guest'
for relative in ('lib/apk/db/installed','etc/apk/world'):
    path=guest/relative
    if path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(guest.resolve()):
        shutil.copyfile(path,root/('guest-'+Path(relative).name+'.txt'))
for name in ('bundle','iPhoneOS15.6.sdk','build','protection-guest'):
    path=root/name
    assert not path.is_symlink() and path.parent.resolve()==root and path.resolve()==root/name
    if path.exists():shutil.rmtree(path)
for path in [*root.glob('protection-input-*.tar.gz'),root/'rootfs.zip']:
    assert path.parent.resolve()==root and not path.is_symlink()
    path.unlink(missing_ok=True)
# Docker runs as root; the public host runner must be able to archive proof.
for path in root.rglob('*'):
    if not path.is_symlink() and path.is_dir():path.chmod(path.stat().st_mode | 0o555)
print('Fixed CI scratch copies cleaned; logs and native proof retained privately')
PY
    exit "$result"
}
trap cleanup EXIT
# Windows staging cannot retain executable bits. Restore only reviewed Theos
# fixture scripts; never chmod a symlink target outside the isolated source.
python3 - <<'PY'
from pathlib import Path
root=Path('/work/theos').resolve()
for path in [*(root/'bin').rglob('*'),root/'vendor/dm.pl/dm.pl']:
    if path.is_file() and path.resolve().is_relative_to(root):
        path.chmod(path.stat().st_mode | 0o111)
PY
sh /work/build_ollvm_runtime.sh
