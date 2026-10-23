#!/usr/bin/env python3
"""Offline, hash-verified Alpine packages and a locally built Hikari runtime."""
import argparse, hashlib, json, os, pathlib, platform, shutil, subprocess, sys
ROOT=pathlib.Path("/opt/minis-protection")
def sha(path):
    with path.open("rb") as stream:return hashlib.file_digest(stream,"sha256").hexdigest()
def manifest(bundle):
    m=json.loads((bundle/"manifest.json").read_text())
    if m.get("schema")!=1 or m.get("platform")!="aarch64-linux-musl" or m.get("passes")!=["bcf","fla","sobf"]:
        raise ValueError("Unsupported OLLVM manifest")
    seen=set()
    for row in m["files"]:
        name=pathlib.PurePosixPath(row["path"])
        if name.is_absolute() or ".." in name.parts or "\\" in row["path"] or not name.parts or name.parts[0] not in ("apks","runtime","licenses") or row["path"] in seen:
            raise ValueError("Unsafe OLLVM member path")
        seen.add(row["path"]);p=bundle/name
        if not p.resolve().is_relative_to(bundle.resolve()) or p.is_symlink() or not p.is_file() or p.stat().st_size!=row["bytes"] or sha(p)!=row["sha256"]:
            raise ValueError("OLLVM integrity failed: "+row["path"])
    actual={p.relative_to(bundle).as_posix() for p in bundle.rglob("*") if p.is_file() and p.name!="manifest.json"}
    if actual!=seen:raise ValueError("Unexpected or missing runtime files")
    return m
def command(argv,timeout=900):
    p=subprocess.run(list(map(str,argv)),capture_output=True,text=True,timeout=timeout)
    if p.returncode:raise RuntimeError("rc="+str(p.returncode)+"\n"+(p.stdout+p.stderr)[-4000:])
    return p.stdout.strip()
def status():
    p=ROOT/"manifest.json"
    try:
        m=json.loads(p.read_text())
        version=command([ROOT/"bin/clang","--version"],60).splitlines()[0]
        if "19." not in version or not (ROOT/"runtime/libHikari.so").is_file():raise RuntimeError("Runtime version/plugin missing")
        probe=subprocess.run(["/usr/lib/llvm19/bin/opt","-load-pass-plugin="+str(ROOT/"runtime/libHikari.so"),"-passes=hikari(enable-strcry)","-disable-output"],
                             input="define i32 @probe(i32 %x) { ret i32 %x }\n",capture_output=True,text=True,timeout=120)
        if probe.returncode:raise RuntimeError("Plugin load/IR probe failed: "+probe.stderr[-2000:])
        return {"installed":True,"clang":version,"passes":m["passes"],"pluginProbe":True,"compiler":str(ROOT/"bin/clang"),"scope":"local Linux ARM64 guest; not a native iOS compiler process"}
    except Exception as e:return {"installed":False,"error":str(e)}
def ensure(bundle):
    expected=sha(bundle/"manifest.json")
    if (ROOT/"bundle.sha256").is_file() and (ROOT/"bundle.sha256").read_text().strip()==expected and (ROOT/"manifest.json").is_file() and sha(ROOT/"manifest.json")==expected:
        m=json.loads((bundle/"manifest.json").read_text())
        intact=all((ROOT/r["path"]).is_file() and sha(ROOT/r["path"])==r["sha256"]
                   for r in m["files"] if r["path"].startswith("runtime/"))
        if intact:
            s=status()
            if s["installed"]:return s
    return install(bundle)
def install(bundle):
    if platform.system()!="Linux" or platform.machine() not in ("aarch64","arm64") or not pathlib.Path("/lib/ld-musl-aarch64.so.1").exists():
        raise RuntimeError("OLLVM payload requires Linux ARM64/musl guest")
    m=manifest(bundle)
    if shutil.disk_usage("/opt").free<1_500_000_000:raise RuntimeError("OLLVM first installation requires 1.5GB free space")
    print("MINIS_STAGE:验证离线编译器与 APK",flush=True)
    apks=sorted((bundle/"apks").glob("*.apk"))
    if not apks:raise ValueError("No offline compiler packages")
    # Retains Alpine's package signature verification. Never allow-untrusted.
    print(command(["apk","add","--no-network",*apks]),flush=True)
    stage=ROOT.with_name(".minis-protection-stage-"+str(os.getpid()))
    stage.mkdir(parents=True,exist_ok=False)
    try:
        for name in ("runtime","licenses"):shutil.copytree(bundle/name,stage/name)
        (stage/"bin").mkdir()
        driver=stage/"bin/clang"
        driver.write_text("#!/bin/sh\nexec python3 /opt/minis-protection/runtime/clang.py \"$@\"\n")
        driver.chmod(0o755)
        shutil.copy2(bundle/"manifest.json",stage/"manifest.json")
        (stage/"bundle.sha256").write_text(sha(bundle/"manifest.json")+"\n")
        backup=ROOT.with_name(".minis-protection-backup")
        if backup.exists():raise RuntimeError("Previous backup requires inspection before reinstall")
        if ROOT.exists():ROOT.rename(backup)
        stage.rename(ROOT)
        try:
            s=status()
            if not s["installed"]:raise RuntimeError(s["error"])
        except Exception:
            failed=ROOT.with_name(".minis-protection-failed-"+str(os.getpid()))
            ROOT.rename(failed)
            if backup.exists():backup.rename(ROOT)
            raise
        if backup.exists():shutil.rmtree(backup)
        print("MINIS_STAGE:安装与版本探针完成",flush=True)
        return s
    finally:
        if stage.exists():shutil.rmtree(stage)
def main():
    p=argparse.ArgumentParser();p.add_argument("action",choices=["install","ensure","status"]);p.add_argument("--bundle",type=pathlib.Path)
    a=p.parse_args()
    try:
        if a.action=="status":result=status()
        else:
            if a.bundle is None:raise ValueError("bundle path required")
            result=ensure(a.bundle) if a.action=="ensure" else install(a.bundle)
        print(json.dumps(result,ensure_ascii=False))
        return 0 if result["installed"] else 1
    except Exception as e:print(json.dumps({"installed":False,"error":str(e)},ensure_ascii=False));return 1
if __name__=="__main__":sys.exit(main())
