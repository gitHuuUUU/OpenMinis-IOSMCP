#!/bin/sh
# Real Theos compile/link/package test, isolated from the user's Theos tree.
# No iPhone execution is claimed. A missing real signer is reported as unsigned.
set -eu
BASE=${WORKDIR:-/work/theos-protection-native}
THEOS_SOURCE=${THEOS_SOURCE:-${THEOS:-/work/theos}}
SDK=${SDK:-/work/iPhoneOS15.6.sdk}
LLVM_BIN=${LLVM_BIN:-/usr/lib/llvm19/bin}
RUNTIME=${RUNTIME:-/work/bundle/runtime}
DRIVER=${DRIVER:-$RUNTIME/clang.py}
ADAPTER=${ADAPTER:-/work/bundle/minis_build.py}
SIGNER=${SIGNER:-}
CODEDIR_VERIFIER=${CODEDIR_VERIFIER:-/work/verify_macho_code_directory.py}
export THEOS_SOURCE SDK LLVM_BIN RUNTIME DRIVER ADAPTER SIGNER CODEDIR_VERIFIER
for tool in python3 bash make perl rsync dpkg-deb tar gzip xz timeout; do
    command -v "$tool" >/dev/null 2>&1 || { printf 'Missing real dependency: %s\n' "$tool" >&2; exit 1; }
done
test -f "$THEOS_SOURCE/makefiles/library.mk" || { echo 'Theos source library.mk unavailable' >&2; exit 1; }
test -f "$SDK/usr/lib/libSystem.tbd" || { echo 'iOS SDK libSystem.tbd unavailable' >&2; exit 1; }
test -f "$SDK/System/Library/Frameworks/Foundation.framework/Headers/Foundation.h" || { echo 'SDK headers incomplete' >&2; exit 1; }
for tool in clang clang++ ld64.lld llvm-strip llvm-lipo llvm-ar llvm-ranlib llvm-nm opt; do
    if ! test -x "$LLVM_BIN/$tool"; then
        command -v "$tool" >/dev/null 2>&1 || { printf 'LLVM19 tool missing: %s\n' "$tool" >&2; exit 1; }
    fi
done
mkdir -p "$BASE"
RUN=$(mktemp -d "$BASE/run.XXXXXX")
export RUN
printf 'THEOS_NATIVE_WORKDIR=%s\n' "$RUN"
cd "$RUN"

python3 - <<'PY'
import hashlib,json,os,pathlib,re,shutil,subprocess
root=pathlib.Path(os.environ['RUN']);source=pathlib.Path(os.environ['THEOS_SOURCE']).resolve()
sdk=pathlib.Path(os.environ['SDK']).resolve();llvm=pathlib.Path(os.environ['LLVM_BIN']).resolve()
theos=root/'theos';theos.mkdir()
for name in ('makefiles','bin','vendor'):
    shutil.copytree(source/name,theos/name,symlinks=True)
shutil.copy2(source/'Prefix.pch',theos/'Prefix.pch')
for name in ('lib','include','sdks'):(theos/name).mkdir()
(theos/'sdks'/sdk.name).symlink_to(sdk,target_is_directory=True)
tools=theos/'toolchain/linux/iphone/bin';tools.mkdir(parents=True)
for alias,target in {'clang':'clang','clang++':'clang++','ld':'ld64.lld','ld64.lld':'ld64.lld',
                     'lipo':'llvm-lipo','strip':'llvm-strip','ar':'llvm-ar','ranlib':'llvm-ranlib','nm':'llvm-nm'}.items():
    executable=llvm/target
    if not executable.is_file():
        found=shutil.which(target)
        assert found,'Real tool unavailable: '+target
        executable=pathlib.Path(found).resolve()
    assert executable.is_file() and os.access(executable,os.X_OK),'Real executable unavailable: '+str(executable)
    (tools/alias).symlink_to(executable)
runtime=root/'runtime';runtime.mkdir()
for name in ('libHikari.so','libMinisProtection.so'):
    shutil.copy2(pathlib.Path(os.environ['RUNTIME'])/name,runtime/name)
driver=pathlib.Path(os.environ['DRIVER'])
text=driver.read_text()
# Host-only path adaptation, without changing production driver behavior.
for name,target in (('CLANG','clang'),('OPT','opt')):
    text,count=re.subn(r'^'+name+r' = .*$',name+' = '+repr(str(llvm/target)),text,flags=re.M)
    assert count==1,(name,count)
(runtime/'clang.py').write_text(text)
wrapper=root/'protected-clang'
wrapper.write_text('#!/bin/sh\nexec python3 '+str(runtime/'clang.py')+' "$@"\n');wrapper.chmod(0o755)
version=re.fullmatch(r'iPhoneOS([0-9]+\.[0-9]+)\.sdk',sdk.name)
assert version,'SDK basename must retain true version'
signer=os.environ.get('SIGNER') or shutil.which('ldid')
real_signer=False
if signer:
    data=pathlib.Path(signer).read_bytes()
    real_signer=data[:4] in (b'\x7fELF',b'\xcf\xfa\xed\xfe',b'\xce\xfa\xed\xfe',b'\xca\xfe\xba\xbe')
    if not real_signer:print('SIGNING_UNAVAILABLE: ldid is not a native binary; shell/fake signer is rejected',flush=True)
signing='ldid' if real_signer else 'unsigned'
config={'theosSource':str(source),'theosCopy':str(theos),'sdk':str(sdk),'sdkVersion':version[1],
        'llvmBin':str(llvm),'driverSourceSha256':hashlib.sha256(driver.read_bytes()).hexdigest(),
        'adapterSource':os.environ['ADAPTER'],'signing':signing,'signer':signer if real_signer else None,
        'codeDirectoryVerifier':os.environ['CODEDIR_VERIFIER'],
        'scope':'host-native Theos compile/link/package; no device installation or execution'}
try:config['theosCommit']=subprocess.check_output(['git','-C',str(source),'rev-parse','HEAD'],text=True).strip()
except (OSError,subprocess.CalledProcessError):config['theosCommit']=None
(root/'test-config.json').write_text(json.dumps(config,indent=2))
for mode in ('normal','enhanced'):
    project=root/mode;project.mkdir()
    makefile='''ARCHS = arm64
TARGET = iphone:clang:SDK_VERSION:15.4
LIBRARY_NAME = MinisProtectionProbe
MinisProtectionProbe_FILES = fixture.c
MinisProtectionProbe_CFLAGS = -O0 -fno-modules
MinisProtectionProbe_LDFLAGS = -fuse-ld=lld
MinisProtectionProbe_INSTALL_PATH = /usr/lib
THEOS_PLATFORM_DEB_COMPRESSION_TYPE = gzip
GO_EASY_ON_ME = 1
include $(THEOS)/makefiles/common.mk
SIGNING_CONFIG
include $(THEOS_MAKE_PATH)/library.mk
before-all::
\t@echo "NATIVE_THEOS_CC=$(TARGET_CC)"
\t@echo "NATIVE_THEOS_CXX=$(TARGET_CXX)"
\t@echo "NATIVE_THEOS_LD=$(TARGET_LD)"
'''.replace('SDK_VERSION',version[1])
    if real_signer:
        makefile=makefile.replace('SIGNING_CONFIG','override TARGET_CODESIGN = '+str(pathlib.Path(signer).resolve()))
    else:
        # Explicit unsigned target, not a fake command returning success.
        makefile=makefile.replace('SIGNING_CONFIG','override TARGET_CODESIGN =\nMinisProtectionProbe_LDFLAGS += -Wl,-no_adhoc_codesign')
    (project/'Makefile').write_text(makefile)
    (project/'control').write_text('Package: com.minisre.protectionprobe\nName: MinisProtectionProbe\nVersion: 1.0\nArchitecture: iphoneos-arm\nDescription: Host test fixture only\nMaintainer: MinisRe test\nAuthor: MinisRe test\nSection: Development\n')
    (project/'fixture.c').write_text('''
volatile int minis_fixture_global = 7;
static const char message[] = "MINIS_THEOS_PROTECTION_SENTINEL";
__attribute__((noinline)) int minis_leaf(int x) { return x > 1 ? x + minis_fixture_global : x - minis_fixture_global; }
__attribute__((visibility("default"))) int minis_test(int x) { minis_fixture_global += x & 1; return minis_leaf(x) + message[x & 3]; }
''')
print('SIGNING_MODE='+signing,flush=True)
PY

THEOS="$RUN/theos"
export THEOS
PATH="$THEOS/toolchain/linux/iphone/bin:$PATH"
export PATH
SDK_VERSION=$(python3 -c 'import json;print(json.load(open("test-config.json"))["sdkVersion"])')
for mode in normal enhanced; do
    if ! timeout 300 python3 "$ADAPTER" build --target deb --project "$RUN/$mode" --output "$RUN/$mode.deb" \
        --sdk "$SDK_VERSION" --minimum 15.4 --protection "$mode" \
        --protection-selection combined --protection-passes bcf,indcall,indgv,sobf,fla \
        --protection-compiler "$RUN/protected-clang" > "$mode.log" 2>&1; then
        cat "$mode.log" >&2
        printf 'Actual Theos %s build failed (evidence preserved in %s)\n' "$mode" "$RUN" >&2
        exit 1
    fi
    dpkg-deb -I "$mode.deb" > "$mode-control.txt"
done

python3 - <<'PY'
import hashlib,io,json,pathlib,re,struct,subprocess,sys,tarfile
root=pathlib.Path('.');config=json.loads((root/'test-config.json').read_text());rows=[]
for mode in ('normal','enhanced'):
    # GNU tar mkdirat is unavailable on some WSL1 hosts. Parse the actual DEB
    # data tar using Python instead; reject anything except bounded plain files.
    content=subprocess.check_output(['dpkg-deb','--fsys-tarfile',mode+'.deb'])
    dest=root/(mode+'-extracted');dest.mkdir()
    with tarfile.open(fileobj=io.BytesIO(content),mode='r:') as archive:
        members=archive.getmembers();assert len(members)<=100
        for member in members:
            relative=pathlib.PurePosixPath(member.name)
            assert not relative.is_absolute() and '..' not in relative.parts
            target=dest/relative
            if member.isdir():target.mkdir(parents=True,exist_ok=True)
            else:
                assert member.isfile() and member.size<10_000_000,member.name
                target.parent.mkdir(parents=True,exist_ok=True)
                target.write_bytes(archive.extractfile(member).read())
    log=(root/(mode+'.log')).read_text()
    compiler_lines=re.findall(r'^NATIVE_THEOS_CC=(.*)$',log,re.M)
    linker_lines=re.findall(r'^NATIVE_THEOS_LD=(.*)$',log,re.M)
    assert compiler_lines and linker_lines,mode+' lacks actual Theos toolchain output'
    assert all('protected-clang' not in line and '-mllvm' not in line for line in linker_lines),linker_lines
    if mode=='enhanced':
        assert any('protected-clang' in line and all('-'+p in line for p in ('bcf','indcall','indgv','sobf','fla')) for line in compiler_lines),compiler_lines
    else:assert all('protected-clang' not in line for line in compiler_lines),compiler_lines
    files=list((root/(mode+'-extracted')).rglob('*.dylib'));assert len(files)==1,files
    data=files[0].read_bytes();assert data[:4]==b'\xcf\xfa\xed\xfe','Not thin Mach-O64'
    _,cpu,_,kind,ncmds,_,_,_=struct.unpack_from('<8I',data)
    assert cpu==0x0100000c and kind==6,(cpu,kind)
    commands=[];off=32
    for _ in range(ncmds):
        cmd,size=struct.unpack_from('<II',data,off);assert size>=8 and off+size<=len(data)
        commands.append(cmd);off+=size
    signed=0x1d in commands
    signature_report=None
    if config['signing']=='ldid':
        assert signed,'Real ldid did not leave LC_CODE_SIGNATURE'
        verifier=pathlib.Path(config['codeDirectoryVerifier'])
        assert verifier.is_file(),'Actual CodeDirectory verifier unavailable: '+str(verifier)
        verification_file=root/(mode+'-code-directory.json')
        subprocess.run([sys.executable,str(verifier),str(files[0]),'--output',str(verification_file)],
                       check=True,timeout=60,capture_output=True,text=True)
        signature_report=json.loads(verification_file.read_text())
        assert signature_report.get('codePageHashesVerified') is True,'CodeDirectory hash verification did not succeed'
        assert signature_report.get('sha256')==hashlib.sha256(data).hexdigest(),'Verified CodeDirectory belongs to different bytes'
    else:assert not signed,'Unsigned target unexpectedly contains a signature; inspect before claiming validity'
    if mode=='normal':assert b'MINIS_THEOS_PROTECTION_SENTINEL' in data
    else:assert b'MINIS_THEOS_PROTECTION_SENTINEL' not in data,'String protection ineffective in actual DEB dylib'
    rows.append({'mode':mode,'deb':str((root/(mode+'.deb')).resolve()),'bytes':(root/(mode+'.deb')).stat().st_size,
                 'sha256':hashlib.sha256((root/(mode+'.deb')).read_bytes()).hexdigest(),
                 'dylibSha256':hashlib.sha256(data).hexdigest(),'machO':'arm64 MH_DYLIB','codeSignaturePresent':signed,
                 'codePageHashesVerified':signature_report is not None,'codeDirectoryVerification':signature_report,
                 'compiler':compiler_lines[-1],'linker':linker_lines[-1]})
report={**config,'builds':rows,'result':'normal and all-five-pass actual Theos DEB builds verified',
        'limitations':'Apple certificate trust and device installation/execution are not checked; unsigned mode is not signing verification.'}
(root/'verification.json').write_text(json.dumps(report,indent=2))
print(json.dumps(report,indent=2))
PY
