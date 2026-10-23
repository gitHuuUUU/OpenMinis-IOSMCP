#!/bin/sh
# Real shipped fakefs rootfs -> isolated native ARM64 Linux chroot regression.
# This is not an iPhone or iOS-kernel acceptance test.
set -eu
cd /work
exec > /work/protection-guest-install.log 2>&1
test "$(uname -m)" = aarch64
test -f /work/rootfs.zip
test -f /work/bundle/manifest.json
test -f /work/install.py
test -f /work/protection-native/all-five.dylib
test -f /work/verify_macho_code_directory.py
test -f /work/macho_signing.py
command -v chroot

python3 - <<'PY'
import pathlib,sqlite3,stat,struct,zipfile
root=pathlib.Path('/work/protection-guest')
assert root.parent.resolve()==pathlib.Path('/work')
assert not root.exists() and not root.is_symlink(), 'Refuse to overwrite an existing guest'
root.mkdir()
database=pathlib.Path('/work/protection-guest-meta.db')
assert not database.exists() and not database.is_symlink()
with zipfile.ZipFile('/work/rootfs.zip') as archive:
    database.write_bytes(archive.read('alpine-rootfs/meta.db'))
    connection=sqlite3.connect(database)
    modes={path.decode() if isinstance(path,bytes) else path:struct.unpack('<IIII',body)[0]
           for path,body in connection.execute('select path,stat from paths join stats using(inode)')}
    connection.close()
    seen=set()
    for member in archive.infolist():
        prefix='alpine-rootfs/data/'
        if not member.filename.startswith(prefix):continue
        relative=member.filename[len(prefix):].rstrip('/')
        if not relative:continue
        pure=pathlib.PurePosixPath(relative)
        assert not pure.is_absolute() and '..' not in pure.parts and '\\' not in relative
        assert relative not in seen, 'Duplicate rootfs member: '+relative
        seen.add(relative)
        target=root/relative
        # Absolute symlink contents are correct inside the chroot, but must
        # never redirect extraction writes into the build host.
        assert target.parent.resolve().is_relative_to(root.resolve()), relative
        mode=modes.get('/'+relative,0o100644)
        if stat.S_ISDIR(mode):
            target.mkdir(parents=True,exist_ok=True);target.chmod(mode&0o7777)
        elif stat.S_ISLNK(mode):
            target.parent.mkdir(parents=True,exist_ok=True)
            target.symlink_to(archive.read(member).decode())
        elif stat.S_ISREG(mode):
            target.parent.mkdir(parents=True,exist_ok=True)
            target.write_bytes(archive.read(member));target.chmod(mode&0o7777)
        else:
            raise ValueError('Unsupported fixture inode mode: '+relative)
for relative in ('opt','dev'):
    path=root/relative
    assert path.resolve().is_relative_to(root.resolve()) and not path.is_symlink()
    path.mkdir(exist_ok=True)
null=root/'dev/null'
if not null.exists():null.touch();null.chmod(0o666)
print('Restored shipped rootfs with fakefs file modes and symlinks')
PY

cp -a /work/bundle /work/protection-guest/opt/bundle
cp /work/install.py /work/protection-guest/opt/install.py
chroot /work/protection-guest /usr/bin/curl --version > /work/protection-guest-curl-before.txt
chroot /work/protection-guest /usr/bin/git --version > /work/protection-guest-git-before.txt
chroot /work/protection-guest /usr/bin/python3 /opt/install.py install --bundle /opt/bundle > /work/protection-guest-install.txt 2>&1
chroot /work/protection-guest /usr/bin/python3 /opt/install.py ensure --bundle /opt/bundle > /work/protection-guest-ensure.txt 2>&1
chroot /work/protection-guest /usr/bin/curl --version > /work/protection-guest-curl-after.txt
chroot /work/protection-guest /usr/bin/git --version > /work/protection-guest-git-after.txt
cmp /work/protection-guest-curl-before.txt /work/protection-guest-curl-after.txt
cmp /work/protection-guest-git-before.txt /work/protection-guest-git-after.txt

cat > /work/protection-guest/opt/protection-guest.c <<'EOF'
#include <stdio.h>
volatile int shared=17;
__attribute__((noinline)) int helper(int x) { return x*3+2; }
__attribute__((noinline)) int calc(int x) { if(x>5)return helper(x)+shared;return x-shared; }
int main(void) { int value=calc(8);printf("PROTECTION_GUEST:%d\n",value);return value!=43; }
EOF
chroot /work/protection-guest /opt/minis-protection/bin/clang \
  -mllvm -bcf -mllvm -indcall -mllvm -indgv -mllvm -sobf -mllvm -fla \
  /opt/protection-guest.c -o /opt/protection-guest-probe
chroot /work/protection-guest /opt/protection-guest-probe > /work/protection-guest-execution.txt
grep -q '^PROTECTION_GUEST:43$' /work/protection-guest-execution.txt

# Re-sign the actual all-five-pass iOS dylib using the newly installed signer,
# not a host signer or an unsigned file with a misleading suffix.
cp /work/protection-native/all-five.dylib /work/protection-guest/opt/protection-guest.dylib
chroot /work/protection-guest /opt/minis-protection/runtime/ldid -r /opt/protection-guest.dylib > /work/protection-guest-ldid.log 2>&1
sha256sum /work/protection-guest/opt/protection-guest.dylib > /work/protection-guest-unsigned-sha256.txt
cat > /work/protection-guest/opt/protection-guest-entitlements.plist <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict><key>com.minisre.protection.guest.fixture</key><true/></dict></plist>
EOF
chroot /work/protection-guest /opt/minis-protection/runtime/ldid -Cadhoc -S/opt/protection-guest-entitlements.plist /opt/protection-guest.dylib >> /work/protection-guest-ldid.log 2>&1
chroot /work/protection-guest /opt/minis-protection/bin/ldid -h /opt/protection-guest.dylib > /work/protection-guest-cdhash.txt 2>&1
chroot /work/protection-guest /opt/minis-protection/runtime/ldid -e /opt/protection-guest.dylib > /work/protection-guest-extracted-entitlements.plist
cp /work/protection-guest/opt/protection-guest.dylib /work/protection-guest-signed.dylib
python3 /work/verify_macho_code_directory.py /work/protection-guest-signed.dylib --output /work/protection-guest-code-directory.json

python3 - <<'PY'
import hashlib,json,pathlib,plistlib,shutil
work=pathlib.Path('/work')
passes=['bcf','indcall','indgv','sobf','fla']
for name in ('protection-guest-install.txt','protection-guest-ensure.txt'):
    result=json.loads((work/name).read_text().splitlines()[-1])
    assert result['installed'] and result['pluginProbe'] and result['runtimeVersion']==2
    assert result['passes']==passes and result['availablePasses']==passes
    assert all(result['passProbe'][name]['verified'] for name in passes)
    assert result['signerPath']=='/opt/minis-protection/runtime/ldid'
    assert 'signerProbe' not in result, 'Status is integrity evidence, not signing evidence'
for program in ('curl','git'):
    assert (work/('protection-guest-'+program+'-before.txt')).read_bytes()==(work/('protection-guest-'+program+'-after.txt')).read_bytes()
assert (work/'protection-guest-execution.txt').read_text().strip()=='PROTECTION_GUEST:43'
signed=work/'protection-guest-signed.dylib'
assert signed.read_bytes()[:4]==bytes.fromhex('cffaedfe')
verification=json.loads((work/'protection-guest-code-directory.json').read_text())
assert verification['codePageHashesVerified'] and all(row['codePageHashesVerified'] for row in verification['codeDirectories'])
assert verification['entitlements']['com.minisre.protection.guest.fixture'] is True
assert plistlib.loads((work/'protection-guest-extracted-entitlements.plist').read_bytes())['com.minisre.protection.guest.fixture'] is True
assert verification['sha256']!=(work/'protection-guest-unsigned-sha256.txt').read_text().split()[0]
result={'schema':1,'actual_shipped_rootfs':True,'platform':'aarch64-linux-musl',
        'runtimeVersion':2,'offline_install':True,'ensure':True,'passes':passes,
        'each_pass_ir_probe_verified':True,'all_five_native_execution':True,
        'curl_git_unchanged':True,'installed_signer_used':True,'signer_wrapper_executed':True,
        'ad_hoc_signing':True,'code_page_hashes_verified':True,'entitlements_round_trip':True,
        'signed_dylib_sha256':hashlib.sha256(signed.read_bytes()).hexdigest(),
        'phone_test':False,'apple_certificate_trust_verified':False,'device_install_verified':False}
(work/'protection-guest-verification.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result))
# Delete only the fixed isolated fixture after all evidence has been copied.
guest=work/'protection-guest'
assert not guest.is_symlink() and guest.resolve()==pathlib.Path('/work/protection-guest')
assert guest.parent.resolve()==pathlib.Path('/work')
shutil.rmtree(guest)
for name in ('rootfs.zip','protection-guest-meta.db'):
    path=work/name
    assert path.parent.resolve()==pathlib.Path('/work') and not path.is_symlink()
    path.unlink()
print('Actual shipped-rootfs five-pass install/signing regression PASSED')
PY
