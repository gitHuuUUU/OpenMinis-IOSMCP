#!/bin/sh
set -eu
cd /work
exec > /work/ollvm-compat.log 2>&1
apk add --no-cache python3
python3 - <<'PY'
import zipfile,sqlite3,pathlib,struct,stat,os
root=pathlib.Path('/work/guest');root.mkdir()
with zipfile.ZipFile('/work/rootfs.zip') as archive:
 db=pathlib.Path('/work/meta.db');db.write_bytes(archive.read('alpine-rootfs/meta.db'))
 conn=sqlite3.connect(db)
 modes={path.decode():struct.unpack('<IIII',body)[0] for path,body in conn.execute('select path,stat from paths join stats using(inode)')};conn.close()
 for name in archive.namelist():
  prefix='alpine-rootfs/data/'
  if not name.startswith(prefix):continue
  relative=name[len(prefix):].rstrip('/')
  if not relative:continue
  pure=pathlib.PurePosixPath(relative)
  assert not pure.is_absolute() and '..' not in pure.parts
  target=root/relative;mode=modes.get('/'+relative,0o100644)
  if stat.S_ISDIR(mode):target.mkdir(parents=True,exist_ok=True)
  elif stat.S_ISLNK(mode):
   target.parent.mkdir(parents=True,exist_ok=True);target.symlink_to(archive.read(name).decode())
  elif stat.S_ISREG(mode):
   target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(archive.read(name));target.chmod(mode&0o7777)
 (root/'opt').mkdir(exist_ok=True)
 (root/'dev').mkdir(exist_ok=True)
 null=root/'dev/null'
 if not null.exists():null.touch();null.chmod(0o666)
print('Restored actual shipped rootfs with fakefs file modes and symlinks')
PY
tar -xzf /work/ollvm-bundle.tar.gz -C /work/guest/opt
cp /work/install-old.py /work/guest/opt/install-old.py
cp /work/install-new.py /work/guest/opt/install-new.py
chroot /work/guest /usr/bin/curl --version > /work/curl-before.txt
chroot /work/guest /usr/bin/git --version > /work/git-before.txt
# The old installer must reproduce the user's exact-version conflict.
if chroot /work/guest /usr/bin/python3 /opt/install-old.py install --bundle /opt/bundle > /work/old-install.txt 2>&1; then
 echo 'Old installation unexpectedly passed'; exit 1
fi
grep -q 'libcurl' /work/old-install.txt
grep -q 'breaks: curl' /work/old-install.txt
chroot /work/guest /usr/bin/python3 /opt/install-new.py install --bundle /opt/bundle > /work/new-install.txt 2>&1
chroot /work/guest /usr/bin/python3 /opt/install-new.py ensure --bundle /opt/bundle > /work/ensure.txt 2>&1
chroot /work/guest /usr/bin/curl --version > /work/curl-after.txt
chroot /work/guest /usr/bin/git --version > /work/git-after.txt
cmp /work/curl-before.txt /work/curl-after.txt
cmp /work/git-before.txt /work/git-after.txt
cat > /work/guest/opt/compat-probe.c <<'EOF'
#include <stdio.h>
__attribute__((noinline)) int calc(int x) { if (x>5) return x*3+2; return x+11; }
int main(void) { printf("COMPAT_PROBE:%d\n",calc(8));return calc(8)!=26; }
EOF
for passes in bcf fla sobf bcf,sobf bcf,fla,sobf; do
 flags=""
 for pass in $(echo "$passes" | tr ',' ' '); do flags="$flags -mllvm -$pass"; done
 chroot /work/guest /opt/minis-protection/bin/clang $flags /opt/compat-probe.c -o /opt/compat-probe
 chroot /work/guest /opt/compat-probe > "/work/probe-$passes.txt"
 grep -q '^COMPAT_PROBE:26$' "/work/probe-$passes.txt"
done
cat > /work/guest/opt/dylib.c <<'EOF'
int demo(int x) { return x>2?x+3:x-3; }
EOF
chroot /work/guest /opt/minis-protection/bin/clang -mllvm -bcf -mllvm -sobf --target=arm64-apple-ios15.4 -fuse-ld=lld -dynamiclib -nostdlib /opt/dylib.c -o /opt/probe.dylib
cp /work/guest/opt/probe.dylib /work/probe.dylib
python3 - <<'PY'
import json,pathlib,shutil
root=pathlib.Path('/work')
assert (root/'probe.dylib').read_bytes()[:4]==bytes.fromhex('cffaedfe')
for name in ('new-install.txt','ensure.txt'):
 result=json.loads((root/name).read_text().splitlines()[-1]);assert result['installed'] and result['pluginProbe']
(root/'compat-verification.json').write_text(json.dumps({'old_conflict_reproduced':True,'actual_shipped_rootfs':True,'new_offline_install':True,'ensure_plugin_probe':True,'curl_git_unchanged':True,'protected_native_execution':5,'mach_o_dylib':True,'phone_test':False},indent=2))
# Only remove this isolated test copy, never an external/user rootfs.
guest=root/'guest';assert guest.resolve()==pathlib.Path('/work/guest');shutil.rmtree(guest)
for name in ('rootfs.zip','ollvm-bundle.tar.gz','meta.db'):(root/name).unlink(missing_ok=True)
print('Actual-rootfs offline install regression PASSED')
PY
