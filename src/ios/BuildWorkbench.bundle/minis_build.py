#!/usr/bin/env python3
"""Real build/inspection adapter. Exit status and output hashes are never simulated."""
import re
import argparse, hashlib, json, os, pathlib, plistlib, shutil, subprocess, sys, tarfile, tempfile, zipfile, stat
HERE=pathlib.Path(__file__).resolve().parent
SDK_HOME=pathlib.Path(os.environ.get('THEOS','/opt/theos'))/'sdks'
def run(args,cwd=None):
    print('+ '+' '.join(map(str,args)),flush=True)
    subprocess.run(list(map(str,args)),cwd=cwd,check=True)
def inside(root,path):
    return path.resolve()==root.resolve() or root.resolve() in path.resolve().parents
def sha(p):
    h=hashlib.sha256()
    with open(p,'rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()
def extract_sdk(archive,destination):
    root=pathlib.Path(destination)
    if archive.name.endswith('.zip'):
        with zipfile.ZipFile(archive) as z:
            for i in z.infolist():
                if i.filename.startswith('__MACOSX/'):continue
                p=root/i.filename
                if not inside(root,p):raise ValueError('archive path escapes staging')
                p.parent.mkdir(parents=True,exist_ok=True)
                mode=i.external_attr>>16
                if i.is_dir():p.mkdir(exist_ok=True)
                elif stat.S_ISLNK(mode):
                    target=z.read(i).decode()
                    if not inside(root,p.parent/target):raise ValueError('symlink escapes staging')
                    p.symlink_to(target)
                else:
                    with z.open(i) as src,open(p,'wb') as dst:shutil.copyfileobj(src,dst)
    else:
        with tarfile.open(archive) as t:
            t.extractall(root,filter='data')
def install_sdks():
    catalog=json.loads((HERE/'sdk-catalog.json').read_text())
    SDK_HOME.mkdir(parents=True,exist_ok=True)
    if shutil.disk_usage(SDK_HOME).free<2_000_000_000:raise RuntimeError('Installing four SDKs requires at least 2 GB free space')
    for item in catalog['sdks']:
        archive=HERE/item['file']
        print('VERIFY SDK '+item['version'],flush=True)
        if sha(archive)!=item['sha256']:raise ValueError('SDK SHA256 mismatch')
        with tempfile.TemporaryDirectory(prefix='.sdk-stage-',dir=SDK_HOME) as d:
            extract_sdk(archive,pathlib.Path(d))
            sdk=pathlib.Path(d)/item['sdkRoot']
            assert (sdk/'System/Library/Frameworks/Foundation.framework/Headers/Foundation.h').is_file(),'Foundation headers missing'
            assert (sdk/'usr/lib/libSystem.tbd').is_file(),'libSystem link stubs missing'
            target=SDK_HOME/item['sdkRoot'];backup=SDK_HOME/(item['sdkRoot']+'.minis-backup')
            if backup.exists():raise RuntimeError('Previous SDK backup exists; preserve and inspect before replacing: '+str(backup))
            if target.exists():target.rename(backup)
            try:sdk.rename(target)
            except BaseException:
                if backup.exists():backup.rename(target)
                raise
            if backup.exists():shutil.rmtree(backup)
        print('INSTALLED '+str(target),flush=True)
    return {'sdkVersions':[x['version'] for x in catalog['sdks']],'status':'installed; build probes still required'}
def doctor():
    probes={
      'clang':['clang','--version'],'MachO linker':['ld64.lld','--version'],
      'DEB packager':['dpkg-deb','--version'],'Windows cross compiler':['x86_64-w64-mingw32-gcc','--version'],
      'IDA command-line (licensed installation)':['idat64','-h'],'Hopper command-line (licensed installation)':['hopper','--version'],
      'Java':['java','-version'],'Gradle':['gradle','--version'],'APK packager':['aapt2','version'],
      'Frida CLI (not device connection)':['frida','--version'],
      'REA CLI (provider check separate)':['rea','--version'],'SSH transport':['ssh','-V'],
      'Signing':['ldid','-h']}
    result={}
    for label,cmd in probes.items():
        if not shutil.which(cmd[0]):result[label]={'ready':False,'detail':'missing executable'};continue
        try:
            p=subprocess.run(cmd,capture_output=True,text=True,timeout=20)
            result[label]={'ready':p.returncode==0,'exitCode':p.returncode,'detail':(p.stdout+p.stderr)[-2000:]}
        except Exception as e:result[label]={'ready':False,'detail':str(e)}
    result['SDKs']=[p.name for p in SDK_HOME.glob('iPhoneOS*.sdk') if (p/'usr/lib/libSystem.tbd').exists()]
    for module in ['PIL','openpyxl','reportlab','docx','pypdf','matplotlib','pefile','lief','dnfile']:
        try:__import__(module);result['Python '+module]={'ready':True}
        except ImportError:result['Python '+module]={'ready':False,'detail':'module missing'}
    return result
def validate_artifact(path,target):
    with open(path,'rb') as f:head=f.read(8)
    if target=='dylib' and head[:4] not in [b'\xcf\xfa\xed\xfe',b'\xce\xfa\xed\xfe',b'\xca\xfe\xba\xbe']:raise RuntimeError('Not a Mach-O artifact')
    if target=='exe' and head[:2]!=b'MZ':raise RuntimeError('Not a PE executable')
    if target=='deb' and head!=b'!<arch>\n':raise RuntimeError('Not a Debian ar package')
    if target in ['ipa','apk']:
        with zipfile.ZipFile(path) as z:
            assert z.testzip() is None,'ZIP integrity failure'
            names=z.namelist()
            if target=='apk' and 'AndroidManifest.xml' not in names:raise RuntimeError('APK manifest missing')
            if target=='ipa' and not any(n.startswith('Payload/') and n.endswith('.app/Info.plist') for n in names):raise RuntimeError('IPA application metadata missing')

def build(args):
    src=pathlib.Path(args.project).resolve();out=pathlib.Path(args.output).resolve();out.parent.mkdir(parents=True,exist_ok=True)
    if not src.exists():raise FileNotFoundError(src)
    if args.remote:
        if not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.@:-]*',args.remote):raise ValueError('Use a configured SSH host alias, not options/commands')
        project_name='project'+src.suffix
        # Uses the user's existing SSH profile/key, never opens an unauthenticated command server.
        remote='/tmp/minis-build-'+os.urandom(8).hex()
        run(['ssh',args.remote,'mkdir','-p',remote])
        run(['scp',str(__file__),args.remote+':'+remote+'/minis_build.py'])
        with tempfile.TemporaryDirectory() as d:
            pack=pathlib.Path(d)/'project.tar.gz'
            with tarfile.open(pack,'w:gz') as t:t.add(src,arcname=project_name,filter=lambda i:None if '/.git/' in i.name else i)
            run(['scp',pack,args.remote+':'+remote+'/project.tar.gz'])
            run(['ssh',args.remote,'tar','-xzf',remote+'/project.tar.gz','-C',remote])
        run(['ssh',args.remote,'python3',remote+'/minis_build.py','build','--target',args.target,'--project',remote+'/'+project_name,'--output',remote+'/result'+out.suffix,'--sdk',args.sdk,'--minimum',args.minimum])
        run(['scp',args.remote+':'+remote+'/result'+out.suffix,str(out)])
    elif args.target=='dylib':
        sdk=SDK_HOME/('iPhoneOS'+args.sdk+'.sdk')
        if not sdk.exists():raise RuntimeError('SDK not installed: '+str(sdk))
        if not shutil.which('ld64.lld'):raise RuntimeError('Missing Mach-O linker ld64.lld; installing headers is not sufficient')
        files=[src] if src.is_file() else [*src.glob('*.c'),*src.glob('*.m'),*src.glob('*.mm'),*src.glob('*.cpp')]
        if not files:raise RuntimeError('No native source files')
        run(['clang','--target=arm64-apple-ios'+args.minimum,'-isysroot',sdk,'-fuse-ld=lld','-dynamiclib',*files,'-framework','Foundation','-o',out])
    elif args.target=='deb':
        if not (src/'DEBIAN/control').is_file():raise RuntimeError('DEBIAN/control required')
        with tempfile.TemporaryDirectory(prefix='minis-deb-') as d:
            package=pathlib.Path(d)/'package';shutil.copytree(src,package)
            os.chmod(package/'DEBIAN',0o755)
            for f in (package/'DEBIAN').iterdir():
                if f.is_file():os.chmod(f,0o755 if f.name in ['preinst','postinst','prerm','postrm','config'] else 0o644)
            run(['dpkg-deb','--root-owner-group','--build',package,out])
    elif args.target=='ipa':
        if src.suffix!='.app' or not (src/'Info.plist').is_file():raise RuntimeError('IPA packaging requires a built .app. Swift/Xcode project compilation needs a configured macOS build host.')
        info=plistlib.loads((src/'Info.plist').read_bytes());exe=src/info['CFBundleExecutable']
        if not exe.is_file():raise RuntimeError('App executable missing')
        import struct
        with open(exe,'rb') as f:header=f.read(32)
        if header[:4]!=b'\xcf\xfa\xed\xfe' or struct.unpack_from('<I',header,12)[0]!=2:raise RuntimeError('App requires a Mach-O executable, not a dylib or placeholder')
        with zipfile.ZipFile(out,'w',compression=zipfile.ZIP_DEFLATED) as z:
            for f in src.rglob('*'):
                if f.is_file():z.write(f,'Payload/'+src.name+'/'+f.relative_to(src).as_posix())
        # This packages existing signatures; it does not invent provisioning or entitlements.
    elif args.target=='apk':
        launcher=src/('gradlew.bat' if os.name=='nt' else 'gradlew')
        if launcher.is_file():
            run([launcher,'assembleDebug','--no-daemon'],cwd=src)
            files=list(src.glob('**/build/outputs/apk/**/debug/*.apk'))
            if len(files)!=1:raise RuntimeError('Expected one debug APK; choose variant explicitly in your project')
            shutil.copy2(files[0],out)
        else:
            # Minimal Java Android project; full Gradle projects use their own wrapper.
            sdk=pathlib.Path(os.environ.get('ANDROID_HOME',str(pathlib.Path.home()/'AppData/Local/Android/Sdk') if os.name=='nt' else str(pathlib.Path.home()/'Android/Sdk')))
            suffix='.exe' if os.name=='nt' else ''
            bt=sdk/'build-tools/35.0.0';android=sdk/'platforms/android-35/android.jar'
            if not android.exists() or not (bt/('aapt2'+suffix)).exists():raise RuntimeError('Install Android platform35 and build-tools35.0.0 or use a prepared remote host')
            if not (src/'AndroidManifest.xml').exists():raise RuntimeError('AndroidManifest.xml and src/**/*.java required')
            java=shutil.which('javac')
            if not java:raise RuntimeError('JDK missing')
            os.environ.setdefault('JAVA_HOME',str(pathlib.Path(java).parent.parent))
            with tempfile.TemporaryDirectory(prefix='minis-apk-') as d:
                d=pathlib.Path(d);classes=d/'classes';classes.mkdir();dex=d/'dex';dex.mkdir();gen=d/'gen';gen.mkdir()
                unsigned=d/'unsigned.apk';aligned=d/'aligned.apk'
                run([bt/('aapt2'+suffix),'link','--manifest',src/'AndroidManifest.xml','-I',android,'--min-sdk-version','23','--target-sdk-version','35','--java',gen,'-o',unsigned])
                sources=list((src/'src').rglob('*.java'))+list(gen.rglob('*.java'))
                if not sources:raise RuntimeError('Java source missing')
                run([java,'-source','8','-target','8','-bootclasspath',android,'-d',classes,*sources])
                run([bt/('d8.bat' if os.name=='nt' else 'd8'),'--lib',android,'--output',dex,*classes.rglob('*.class')])
                with zipfile.ZipFile(unsigned,'a',compression=zipfile.ZIP_DEFLATED) as z:
                    for f in dex.glob('*.dex'):z.write(f,f.name)
                run([bt/('zipalign'+suffix),'-f','4',unsigned,aligned])
                ks=d/'debug.keystore'
                run(['keytool','-genkeypair','-keystore',ks,'-storepass','android','-keypass','android','-alias','androiddebugkey','-dname','CN=Minis Debug','-keyalg','RSA','-validity','3650'])
                signer=bt/('apksigner.bat' if os.name=='nt' else 'apksigner')
                run([signer,'sign','--ks',ks,'--ks-pass','pass:android','--key-pass','pass:android','--out',out,aligned])
                run([signer,'verify','--verbose',out])
    elif args.target=='exe':
        cs=[src] if src.is_file() and src.suffix=='.cs' else (list(src.glob('*.cs')) if src.is_dir() else [])
        if cs and os.name=='nt':
            csc=pathlib.Path(os.environ['WINDIR'])/'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
            if not csc.is_file():raise RuntimeError('C# compiler missing')
            run([csc,'/nologo','/target:exe','/out:'+str(out),*cs])
        else:
            compiler=shutil.which('x86_64-w64-mingw32-gcc') or (shutil.which('gcc') if os.name=='nt' else None)
            if not compiler:raise RuntimeError('Windows-target compiler missing; configure SSH host with MinGW/C# compiler')
            files=[src] if src.is_file() else list(src.glob('*.c'))
            if not files:raise RuntimeError('No C source files')
            run([compiler,*files,'-o',out])
    if not out.is_file() or out.stat().st_size==0:raise RuntimeError('Build produced no artifact')
    validate_artifact(out,args.target)
    return {'artifact':str(out),'bytes':out.stat().st_size,'sha256':sha(out),'status':'built; execution/device verification separate'}
def main():
    p=argparse.ArgumentParser();sub=p.add_subparsers(dest='action',required=True)
    sub.add_parser('doctor');sub.add_parser('install-sdks')
    b=sub.add_parser('build');b.add_argument('--target',choices=['dylib','deb','ipa','apk','exe'],required=True);b.add_argument('--project',required=True);b.add_argument('--output',required=True);b.add_argument('--sdk',choices=['15.6','16.5','17.5','18.6'],default='16.5');b.add_argument('--minimum',default='15.4');b.add_argument('--remote',default='')
    args=p.parse_args()
    try:
        result=doctor() if args.action=='doctor' else install_sdks() if args.action=='install-sdks' else build(args)
        print(json.dumps(result,ensure_ascii=False,indent=2))
    except Exception as e:print(json.dumps({'error':str(e),'status':'failed'},ensure_ascii=False),file=sys.stderr);sys.exit(1)
if __name__=='__main__':main()
