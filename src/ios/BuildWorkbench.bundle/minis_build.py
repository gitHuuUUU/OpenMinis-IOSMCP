#!/usr/bin/env python3
"""Real build/inspection adapter. Exit status and output hashes are never simulated."""
import re
import argparse, hashlib, json, os, pathlib, plistlib, shlex, shutil, subprocess, sys, tarfile, tempfile, zipfile, stat, urllib.request
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
def sdk_catalog():
    items=json.loads((HERE/'sdk-catalog.json').read_text(encoding='utf-8'))['sdks']
    if len({i['version'] for i in items})!=len(items):raise ValueError('Duplicate SDK version in catalog')
    for i in items:
        if not re.fullmatch(r'\d+\.\d+',i['version']) or i['sdkRoot']!='iPhoneOS'+i['version']+'.sdk':raise ValueError('Invalid SDK catalog path')
        if i['file'] not in (i['sdkRoot']+'.zip',i['sdkRoot']+'.tar.xz'):raise ValueError('Invalid SDK archive name')
        if not i['url'].startswith('https://') or not re.fullmatch(r'[0-9a-f]{64}',i['sha256']) or not isinstance(i['bytes'],int) or i['bytes']<=0:raise ValueError('Invalid SDK catalog integrity metadata')
    return items
def sdk_valid(path):
    return (path/'System/Library/Frameworks/Foundation.framework/Headers/Foundation.h').is_file() and (path/'usr/lib/libSystem.tbd').is_file()
def sdk_status():
    return {'sdks':[{'version':i['version'],'bytes':i['bytes'],'installed':sdk_valid(SDK_HOME/i['sdkRoot']),'path':str(SDK_HOME/i['sdkRoot'])} for i in sdk_catalog()],'default':'16.5'}
def archive_path(root,name):
    # Resolve against staging, rejecting absolute and Windows-style paths on every host.
    if not name or name.startswith('/') or '\\' in name or any(x in ('..','') for x in name.rstrip('/').split('/')) or ':' in name:raise ValueError('archive path escapes staging: '+name)
    path=root/name
    if not inside(root,path):raise ValueError('archive path escapes staging: '+name)
    return path
def extract_sdk(archive,destination):
    root=pathlib.Path(destination);root.mkdir(parents=True,exist_ok=True)
    if archive.name.endswith('.zip'):
        with zipfile.ZipFile(archive) as z:
            members=[i for i in z.infolist() if not i.filename.startswith('__MACOSX/')]
            links={i.filename.rstrip('/') for i in members if stat.S_ISLNK(i.external_attr>>16)}
            for i in members:
                archive_path(root,i.filename)
                if any(i.filename.startswith(link+'/') for link in links):raise ValueError('archive entry below symlink')
            for i in members:
                p=archive_path(root,i.filename)
                if stat.S_ISLNK(i.external_attr>>16):continue
                if i.is_dir():p.mkdir(parents=True,exist_ok=True)
                else:
                    p.parent.mkdir(parents=True,exist_ok=True)
                    with z.open(i) as src,open(p,'wb') as dst:shutil.copyfileobj(src,dst)
            for i in members:
                if not stat.S_ISLNK(i.external_attr>>16):continue
                p=archive_path(root,i.filename);target=z.read(i).decode('utf-8')
                if target.startswith('/') or '\\' in target or not inside(root,p.parent/target):raise ValueError('symlink escapes staging')
                p.parent.mkdir(parents=True,exist_ok=True);p.symlink_to(target)
    else:
        with tarfile.open(archive) as t:
            members=t.getmembers();links={i.name.rstrip('/') for i in members if i.issym()}
            for i in members:
                archive_path(root,i.name)
                if any(i.name.startswith(link+'/') for link in links):raise ValueError('archive entry below symlink')
                if not (i.isfile() or i.isdir() or i.issym()):raise ValueError('Unsupported SDK archive member: '+i.name)
            for i in members:
                p=archive_path(root,i.name)
                if i.issym():continue
                if i.isdir():p.mkdir(parents=True,exist_ok=True)
                else:
                    p.parent.mkdir(parents=True,exist_ok=True)
                    with t.extractfile(i) as src,open(p,'wb') as dst:shutil.copyfileobj(src,dst)
            for i in members:
                if not i.issym():continue
                p=archive_path(root,i.name);target=i.linkname
                if target.startswith('/') or '\\' in target or not inside(root,p.parent/target):raise ValueError('symlink escapes staging')
                p.parent.mkdir(parents=True,exist_ok=True);p.symlink_to(target)
def download_sdk(item,destination,opener=None):
    digest=hashlib.sha256();count=0
    request=urllib.request.Request(item['url'],headers={'User-Agent':'Minis-SDK-Installer/1'})
    opener=opener or urllib.request.urlopen
    with opener(request,timeout=120) as response,open(destination,'wb') as output:
        while True:
            chunk=response.read(1024*1024)
            if not chunk:break
            count+=len(chunk)
            if count>item['bytes']:raise ValueError('SDK download exceeds catalog byte count')
            output.write(chunk);digest.update(chunk)
    if count!=item['bytes']:raise ValueError('SDK byte count mismatch: got '+str(count))
    if digest.hexdigest()!=item['sha256']:raise ValueError('SDK SHA256 mismatch')
    return count
def install_sdk(version):
    item=next((i for i in sdk_catalog() if i['version']==version),None)
    if item is None:raise ValueError('Unknown SDK version: '+version)
    SDK_HOME.mkdir(parents=True,exist_ok=True)
    target=SDK_HOME/item['sdkRoot']
    if target.exists():
        if sdk_valid(target):return {'version':version,'path':str(target),'status':'already installed; existing SDK preserved'}
        raise RuntimeError('Existing SDK directory is incomplete; preserve and inspect before replacing: '+str(target))
    if shutil.disk_usage(SDK_HOME).free<2_000_000_000:raise RuntimeError('Installing selected SDK requires at least 2 GB free space')
    with tempfile.TemporaryDirectory(prefix='.sdk-stage-',dir=SDK_HOME) as d:
        stage=pathlib.Path(d);archive=stage/item['file'];extract=stage/'extract'
        print('DOWNLOAD SDK '+version+' '+item['url'],flush=True)
        count=download_sdk(item,archive)
        print('VERIFIED SDK '+version+' bytes='+str(count)+' sha256='+item['sha256'],flush=True)
        extract_sdk(archive,extract)
        sdk=extract/item['sdkRoot']
        if not sdk_valid(sdk):raise RuntimeError('SDK headers or link stubs missing')
        if target.exists():raise RuntimeError('SDK target appeared during install; existing SDK preserved: '+str(target))
        sdk.rename(target)
    print('INSTALLED '+str(target),flush=True)
    return {'version':version,'path':str(target),'bytes':count,'sha256':item['sha256'],'status':'installed; build probes still required'}
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
    result['SDKs']=[p.name for p in SDK_HOME.glob('iPhoneOS*.sdk') if sdk_valid(p)]
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

PROTECTION_PASSES={'bcf','indcall','indgv','sobf','fla'}
def protection_flags(args):
    if getattr(args,'protection','normal')=='normal':return []
    selected=getattr(args,'protection_passes','').split(',')
    if not selected or any(p not in PROTECTION_PASSES for p in selected):
        raise ValueError('Select supported protection passes: '+','.join(sorted(PROTECTION_PASSES)))
    selection=getattr(args,'protection_selection','combined')
    if selection not in ('single','combined'):raise ValueError('Unknown protection selection mode')
    if selection=='single' and len(set(selected))!=1:raise ValueError('Single protection mode requires exactly one selected pass')
    return [v for p in sorted(set(selected)) for v in ('-mllvm','-'+p)]

def protection_status(args):
    flags=protection_flags(args)
    if not flags:return {'mode':'normal','status':'normal compilation; protection disabled'}
    compiler=getattr(args,'protection_compiler','')
    installed={}
    if compiler=='/opt/minis-protection/bin/clang' and (HERE/'ollvm/manifest.json').is_file():
        # First actual use installs the bundled signed Alpine packages locally.
        # Normal chat / normal builds never trigger an LLVM install.
        p=subprocess.run([sys.executable,'/usr/local/lib/minis-ollvm/install.py','ensure','--bundle',str(HERE/'ollvm')],capture_output=True,text=True,timeout=1800)
        if p.returncode:raise RuntimeError('Offline protection runtime unavailable: '+(p.stdout+p.stderr)[-4000:])
        try:installed=json.loads(p.stdout.strip().splitlines()[-1])
        except (ValueError,IndexError):raise RuntimeError('Invalid protection runtime status; no ready state assumed')
        if not installed.get('installed') or not installed.get('pluginProbe'):raise RuntimeError('Protection runtime probe failed: '+json.dumps(installed))
    if not compiler or not shutil.which(compiler):
        raise RuntimeError('Protection compiler unavailable: '+str(compiler)+'; stock clang is not substituted')
    # Check the selected target, flags and compilation together. An accepted
    # flag is evidence of compatibility, not a guarantee of obfuscation strength.
    with tempfile.TemporaryDirectory(prefix='minis-protection-') as d:
        source=pathlib.Path(d)/'probe.c';output=pathlib.Path(d)/'probe.o'
        source.write_text('int protection_data=7; const char *s="minis-protection-probe"; __attribute__((noinline)) int callee(int x){return x>2?x+3:x-3;} int f(int x){protection_data+=x; return callee(x)+protection_data+s[0];}\n')
        p=subprocess.run([compiler,'--target=arm64-apple-ios'+getattr(args,'minimum','15.4'),'-O2',*flags,'-c',str(source),'-o',str(output)],capture_output=True,text=True,timeout=60)
        if p.returncode!=0:raise RuntimeError('Protection capability probe failed: '+(p.stdout+p.stderr)[-4000:])
        if not output.is_file():raise RuntimeError('Protection compiler produced no object')
    result={'mode':'enhanced','compiler':compiler,'selection':getattr(args,'protection_selection','combined'),
            'acceptedPasses':sorted(set(args.protection_passes.split(','))),
            'status':'selected target compile probe passed; production artifact and device verification separate'}
    if installed:
        result.update({key:installed[key] for key in ('installed','installedBytes','runtimeVersion','clang','availablePasses') if key in installed})
        result['passEvidence']=installed.get('passProbe',{})
    return result

def is_theos_project(src):
    makefile=src/'Makefile'
    return src.is_dir() and makefile.is_file() and not (src/'DEBIAN/control').is_file() and 'THEOS' in makefile.read_text(errors='replace')

def build_theos(args,src,out):
    """Use a protection frontend, leaving TARGET_LD/sign/package to Theos."""
    theos=pathlib.Path(os.environ.get('THEOS','/opt/theos'))
    if not (theos/'makefiles/common.mk').is_file():raise RuntimeError('Theos makefiles unavailable: '+str(theos))
    if not shutil.which('make'):raise RuntimeError('GNU make required for Theos project')
    sdk=theos/'sdks'/('iPhoneOS'+args.sdk+'.sdk')
    if not sdk_valid(sdk):raise RuntimeError('SDK not installed: '+str(sdk))
    if getattr(args,'protection','normal')=='enhanced' and any(src.rglob('*.swift')):
        raise RuntimeError('The protection frontend handles C/ObjC/C++ only; Swift sources are not silently reported as protected')
    command=['make','-j2','package','FINALPACKAGE=1','SDKVERSION='+args.sdk,'IPHONEOS_DEPLOYMENT_TARGET='+args.minimum]
    if getattr(args,'protection','normal')=='enhanced':
        frontend=shlex.join([args.protection_compiler,*protection_flags(args)])
        command+=['TARGET_CC='+frontend,'TARGET_CXX='+frontend]
        # Do not set TARGET_LD: Theos keeps its configured linker/signing path.
        if args.protection_compiler=='/opt/minis-protection/bin/clang':
            signer=pathlib.Path('/opt/minis-protection/runtime/ldid')
            if not signer.is_file():raise RuntimeError('Bundled real ldid missing; repair the protection component')
            command+=['TARGET_CODESIGN='+str(signer)]
    before={p.resolve():(p.stat().st_mtime_ns,p.stat().st_size,sha(p)) for p in (src/'packages').glob('*.deb')}
    run([part if part!='package' else 'clean' for part in command],cwd=src)
    run(command,cwd=src)
    artifacts=[p for p in (src/'packages').glob('*.deb') if p.resolve() not in before or (p.stat().st_mtime_ns,p.stat().st_size,sha(p))!=before[p.resolve()]]
    if len(artifacts)!=1:raise RuntimeError('Expected one newly built Theos DEB; select one project/package explicitly')
    signatures=[]
    if getattr(args,'protection','normal')=='enhanced' and args.protection_compiler=='/opt/minis-protection/bin/clang':
        # Verify before exposing a shared output; a failed build preserves any
        # previous good artifact rather than leaving an unverified replacement.
        signatures=verify_theos_signatures(artifacts[0])
    with tempfile.NamedTemporaryFile(prefix='.'+out.name+'.',dir=out.parent,delete=False) as staging:
        staged=pathlib.Path(staging.name)
    try:
        shutil.copy2(artifacts[0],staged)
        os.replace(staged,out)
    finally:staged.unlink(missing_ok=True)
    return signatures

def verify_theos_signatures(package):
    """Verify actual packaged thin arm64 code pages, never just a signer's exit code."""
    import importlib.util
    spec=importlib.util.spec_from_file_location('minis_macho_signing',HERE/'macho_signing.py')
    verifier=importlib.util.module_from_spec(spec);spec.loader.exec_module(verifier)
    reports=[]
    with tempfile.TemporaryFile() as errors:
        process=subprocess.Popen(['dpkg-deb','--fsys-tarfile',str(package)],stdout=subprocess.PIPE,stderr=errors)
        try:
            with tarfile.open(fileobj=process.stdout,mode='r|*') as archive:
                for member in archive:
                    if not member.isfile():continue
                    with archive.extractfile(member) as stream:
                        head=stream.read(4)
                        if head in (b'\xca\xfe\xba\xbe',b'\xbe\xba\xfe\xca'):
                            raise RuntimeError('Protected Theos signature validation currently requires thin arm64 output; select ARCHS=arm64')
                        if head!=b'\xcf\xfa\xed\xfe':continue
                        if member.size>256*1024*1024:raise RuntimeError('Mach-O signing verification size limit exceeded')
                        raw=head+stream.read()
                        import struct
                        if len(raw)<32 or struct.unpack_from('<I',raw,4)[0]!=0x0100000c:raise RuntimeError('Protected Theos output must be arm64; select ARCHS=arm64')
                        report=verifier.verify_macho_code_directory(raw)
                        reports.append({'entry':member.name,'sha256':report['sha256'],'codePageHashesVerified':report['codePageHashesVerified']})
            process.stdout.close()
            code=process.wait(timeout=60)
            if code:raise RuntimeError('Cannot inspect actual Theos package signing')
        finally:
            if process.poll() is None:process.kill();process.wait()
    if not reports:raise RuntimeError('Theos package contains no signed Mach-O code; not reporting a protected build')
    return reports

def build(args):
    src=pathlib.Path(args.project).resolve();out=pathlib.Path(args.output).resolve();out.parent.mkdir(parents=True,exist_ok=True)
    if not src.exists():raise FileNotFoundError(src)
    protected=getattr(args,'protection','normal')=='enhanced'
    theos_project=args.target=='deb' and is_theos_project(src)
    if protected and (args.remote or not (args.target=='dylib' or theos_project)):
        raise RuntimeError('Enhanced mode supports local C/ObjC dylib and source Theos DEB projects only; no silent normal-mode fallback or protection of prebuilt packages')
    protection=protection_status(args) if protected else None
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
        compiler=args.protection_compiler if protected else 'clang'
        run([compiler,'--target=arm64-apple-ios'+args.minimum,'-isysroot',sdk,'-fuse-ld=lld','-dynamiclib',*protection_flags(args),*files,'-framework','Foundation','-o',out])
    elif args.target=='deb':
        if theos_project:
            signatures=build_theos(args,src,out)
            validate_artifact(out,'deb')
            return {'artifact':str(out),'bytes':out.stat().st_size,'sha256':sha(out),'protection':protection,'signatures':signatures,'status':'Theos source build/package completed; device verification separate'}
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
                ks=pathlib.Path.home()/'.android/debug.keystore'
                ks.parent.mkdir(parents=True,exist_ok=True)
                if not ks.exists():run(['keytool','-genkeypair','-keystore',ks,'-storepass','android','-keypass','android','-alias','androiddebugkey','-dname','CN=Minis Debug','-keyalg','RSA','-validity','3650'])
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
    return {'artifact':str(out),'bytes':out.stat().st_size,'sha256':sha(out),'protection':protection,'status':'built; execution/device verification separate'}
def main():
    p=argparse.ArgumentParser();sub=p.add_subparsers(dest='action',required=True)
    sub.add_parser('doctor');sub.add_parser('sdk-status')
    install=sub.add_parser('install-sdk');install.add_argument('--sdk',choices=[i['version'] for i in sdk_catalog()],required=True)
    b=sub.add_parser('build');b.add_argument('--target',choices=['dylib','deb','ipa','apk','exe'],required=True);b.add_argument('--project',required=True);b.add_argument('--output',required=True);b.add_argument('--sdk',choices=['15.6','16.5','17.5','18.6'],default='16.5');b.add_argument('--minimum',default='15.4');b.add_argument('--remote',default='')
    ps=sub.add_parser('protection-status')
    for parser in (b,ps):
        parser.add_argument('--protection',choices=['normal','enhanced'],default='normal')
        parser.add_argument('--protection-compiler',default='/opt/minis-protection/bin/clang')
        parser.add_argument('--protection-passes',default='bcf,sobf')
        parser.add_argument('--protection-selection',choices=['single','combined'],default='combined')
    args=p.parse_args()
    try:
        result=doctor() if args.action=='doctor' else sdk_status() if args.action=='sdk-status' else install_sdk(args.sdk) if args.action=='install-sdk' else protection_status(args) if args.action=='protection-status' else build(args)
        print(json.dumps(result,ensure_ascii=False,indent=2))
    except Exception as e:print(json.dumps({'error':str(e),'status':'failed'},ensure_ascii=False),file=sys.stderr);sys.exit(1)
if __name__=='__main__':main()
