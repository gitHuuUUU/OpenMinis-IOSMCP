#!/usr/bin/env python3
"""Install verified bundled ARM64 musl wheels; no fake module or remote proxy."""
import argparse, hashlib, json, os, platform, re, site, subprocess, sys, sysconfig, venv, shutil
from pathlib import Path

def run(argv, timeout=120):
    p=subprocess.run([str(x) for x in argv],text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=timeout)
    if p.returncode:
        raise RuntimeError(f"rc={p.returncode}: {' '.join(map(str,argv))}\n{p.stdout[-2000:]}\n{p.stderr[-2000:]}")
    return p.stdout.strip()

def digest(path):
    with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def read_manifest(bundle):
    m=json.loads((bundle/'manifest.json').read_text())
    if not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+',m['frida_version']):raise ValueError('Invalid Frida version')
    files=m['wheels']
    if not files:raise ValueError('Empty wheelhouse')
    seen=set()
    for row in files:
        name=row['filename']
        if not re.fullmatch(r'[A-Za-z0-9_.+\-]+\.whl',name) or name in seen:raise ValueError('Invalid or duplicate wheel filename')
        seen.add(name)
        p=bundle/'wheels'/name
        if p.is_symlink() or not p.is_file() or p.stat().st_size!=row['bytes'] or digest(p)!=row['sha256']:
            raise ValueError('Wheel integrity failed: '+name)
    return m

def probe(python):
    code="import frida,json; print(json.dumps({'version':frida.__version__,'module':frida.__file__,'devices':[{'id':d.id,'type':d.type} for d in frida.get_device_manager().enumerate_devices()]}))"
    return json.loads(run([python,'-c',code],timeout=60))

def status(root):
    r={'platform':sysconfig.get_platform(),'machine':platform.machine(),'python':sys.version.split()[0],
       'scope':'Linux guest client, not native iOS process access','installed':False}
    try:
        active=root/'active'
        r['runtime']=probe(active/'bin/python')
        r['cli']=run([active/'bin/frida','--version'],timeout=60)
        r['ps_cli']=run([active/'bin/frida-ps','--version'],timeout=60)
        r['system_python']=probe(sys.executable)
        r['installed']=r['runtime']['version']==r['system_python']['version']==r['cli']
        if not r['installed']:r['error']='Runtime/CLI/system Python version mismatch'
    except Exception as e:r['error']=str(e)
    return r

def install(bundle,root,bin_dir):
    m=read_manifest(bundle)
    if platform.system()!='Linux' or platform.machine() not in ('aarch64','arm64') or not Path('/lib/ld-musl-aarch64.so.1').exists():
        raise RuntimeError('This payload requires Linux aarch64 musl inside MinisRe, not Windows/macOS/glibc')
    actual=f'{sys.version_info.major}.{sys.version_info.minor}'
    if actual!=m['python_major_minor']:raise RuntimeError(f'Python {actual} ABI differs from bundled {m["python_major_minor"]}; not installed')
    fingerprint=hashlib.sha256(json.dumps(m,sort_keys=True).encode()).hexdigest()[:12]
    root.mkdir(parents=True,exist_ok=True)
    env=root/('env-'+m['frida_version']+'-'+fingerprint)
    # Fixed versioned prefix: moving a venv after installation breaks shebangs.
    if not (env/'bin/python').is_file():venv.EnvBuilder(with_pip=False,symlinks=True).create(env)
    print('MINIS_STAGE:安装已校验的离线 wheels',flush=True)
    wheels=[bundle/'wheels'/x['filename'] for x in m['wheels']]
    run([sys.executable,'-m','pip','--python',env/'bin/python','install','--no-index','--no-deps','--no-compile',*wheels],timeout=600)
    print('MINIS_STAGE:验证真实模块、CLI 和设备管理器',flush=True)
    local=probe(env/'bin/python')
    if local['version']!=m['frida_version']:raise RuntimeError('Wrong imported Frida version')
    if run([env/'bin/frida','--version'],60)!=m['frida_version']:raise RuntimeError('Frida CLI version mismatch')
    run([env/'bin/frida-ps','--version'],60)
    package_site=run([env/'bin/python','-c','import site;print(site.getsitepackages()[0])'])
    host_site=Path(site.getsitepackages()[0]);host_site.mkdir(parents=True,exist_ok=True)
    pth=host_site/'minis-frida-runtime.pth'
    original=pth.read_bytes() if pth.exists() else None
    try:
        pth.write_text(package_site+'\n')
        system_probe=probe(sys.executable)
        if system_probe['version']!=m['frida_version']:raise RuntimeError('System Python shadows the verified Frida module')
    except Exception:
        if original is None:pth.unlink(missing_ok=True)
        else:pth.write_bytes(original)
        raise
    active=root/'active'
    if active.exists() and not active.is_symlink():raise RuntimeError('Refusing to overwrite unmanaged active directory')
    temp=root/('.active-'+str(os.getpid()));temp.unlink(missing_ok=True);temp.symlink_to(env.name)
    os.replace(temp,active)
    bin_dir.mkdir(parents=True,exist_ok=True)
    commands=['frida','frida-ps','frida-ls-devices','frida-trace','frida-discover','frida-kill','frida-ls','frida-pull','frida-push','frida-apk','frida-compile','frida-create','frida-python']
    for name in commands:
        target='python' if name=='frida-python' else name
        if not (env/'bin'/target).is_file():continue
        path=bin_dir/name
        if path.exists() and b'MinisRe managed Frida' not in path.open('rb').read(120) and not path.with_suffix('.minis-backup').exists():
            shutil.copy2(path,path.with_suffix('.minis-backup'))
        # Fixed local prefix, no URL, credentials, shell eval or Windows proxy.
        executable=str(active/'bin'/target)
        if "'" in executable:raise RuntimeError('Unsupported runtime path')
        path.write_text("#!/bin/sh\n# MinisRe managed Frida\nexec '"+executable+"' \"$@\"\n")
        path.chmod(0o755)
    wrapped_cli=run([bin_dir/'frida','--version'],60)
    if wrapped_cli!=m['frida_version']:raise RuntimeError('Published CLI wrapper verification failed')
    result={'installed':True,'runtime':local,'system_python':system_probe,'cli':wrapped_cli,
            'scope':'Linux guest client, not native iOS process access',
            'platform':sysconfig.get_platform(),'machine':platform.machine(),'python':sys.version.split()[0]}
    (root/'installed.json').write_text(json.dumps({'manifest':m,'verification':result},indent=2))
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['install','status']);p.add_argument('--bundle',type=Path,default=Path('/opt/minis-workbench/frida'));p.add_argument('--root',type=Path,default=Path('/opt/minis-frida'));p.add_argument('--bin-dir',type=Path,default=Path('/usr/local/bin'));a=p.parse_args()
    try:
        r=install(a.bundle,a.root,a.bin_dir) if a.action=='install' else status(a.root)
        print(json.dumps(r,ensure_ascii=False,indent=2));sys.exit(0 if r['installed'] else 1)
    except Exception as e:print(json.dumps({'installed':False,'error':str(e)},ensure_ascii=False),file=sys.stderr);sys.exit(1)
