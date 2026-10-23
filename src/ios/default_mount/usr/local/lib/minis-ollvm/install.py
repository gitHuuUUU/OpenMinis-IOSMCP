#!/usr/bin/env python3
"""Offline, hash-verified Alpine packages and a locally built Hikari runtime."""
import argparse, hashlib, json, os, pathlib, platform, shutil, subprocess, sys, re, tarfile
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
def package_records(apks):
    """Read signed-APK control metadata; apk still verifies signatures at install."""
    records=[]
    for path in apks:
        with tarfile.open(path,"r:gz") as archive:
            member=archive.getmember(".PKGINFO")
            if not member.isfile() or member.size>1_048_576:raise ValueError("Invalid APK control metadata")
            fields={}
            for line in archive.extractfile(member).read().decode("utf-8").splitlines():
                if " = " in line:
                    key,value=line.split(" = ",1);fields.setdefault(key,[]).append(value)
            if len(fields.get("pkgname",[]))!=1 or len(fields.get("pkgver",[]))!=1:raise ValueError("Missing APK package identity")
            records.append({"name":fields["pkgname"][0],"version":fields["pkgver"][0],
                            "provides":fields.get("provides",[]),"depends":fields.get("depend",[]),"path":path})
    return records

def installed_records(database):
    records=[]
    for block in database.split("\n\n"):
        fields=dict(line.split(":",1) for line in block.splitlines() if line.startswith(("P:","V:","p:")))
        if "P" in fields and "V" in fields:
            records.append({"name":fields["P"],"version":fields["V"],"provides":fields.get("p","").split()})
    return records

def package_plan(available, installed, compare=None):
    """Preserve installed ABI-compatible dependencies instead of pinning all APKs.

    Passing the entire offline closure to apk pins every shared library by local
    checksum, breaking existing curl -> libcurl exact-version pairs. Only roots
    and genuinely missing/unsatisfied dependencies are explicit install targets.
    A no-network apk simulation remains the final solver before any mutation.
    """
    if compare is None:compare=lambda a,b:command(["apk","version","-t",a,b],30)
    def identity(value):
        match=re.fullmatch(r"([^<>=~]+)([<>=~]*)(.*)",value)
        if not match:raise ValueError("Invalid APK dependency: "+value)
        return match.groups()
    def matches(record, requirement):
        name,op,wanted=identity(requirement)
        offers=[record["name"]+"="+record["version"],*record.get("provides",[])]
        for offer in offers:
            key,_,version=identity(offer)
            if key!=name:continue
            if not op:return True
            if not version:continue
            result=compare(version,wanted)
            if op=="=" and result=="=":return True
            if op==">=" and result in (">","="):return True
            if op=="<=" and result in ("<","="):return True
            if op==">" and result==">":return True
            if op=="<" and result=="<":return True
        return False
    chosen={};pending=[]
    # These exact compiler builds match the bundled LLVM pass ABI. Python is
    # already running this installer; do not upgrade its optional cache packages.
    for name in ("clang19","llvm19","lld"):
        candidates=[r for r in available if r["name"]==name]
        if len(candidates)!=1:raise ValueError("Missing/duplicate compiler APK: "+name)
        record=candidates[0];chosen[name]=record;pending.append(record)
    while pending:
        record=pending.pop()
        for dep in record.get("depends",[]):
            if dep.startswith("!"):continue  # apk enforces conflicts itself.
            key,_,_=identity(dep)
            if key in chosen:
                if not matches(chosen[key],dep):raise ValueError("Conflicting offline APK requirements: "+dep)
                continue
            if any(matches(r,dep) for r in chosen.values()) or any(matches(r,dep) for r in installed):continue
            candidates=[r for r in available if matches(r,dep)]
            if not candidates:raise RuntimeError("Offline OLLVM dependency unavailable: "+dep)
            candidate=next((r for r in candidates if r["name"]==key),candidates[0])
            if candidate["name"] in chosen:raise ValueError("Conflicting offline APK provider: "+dep)
            chosen[candidate["name"]]=candidate;pending.append(candidate)
    return [chosen[name]["path"] for name in sorted(chosen)]

def install(bundle):
    if platform.system()!="Linux" or platform.machine() not in ("aarch64","arm64") or not pathlib.Path("/lib/ld-musl-aarch64.so.1").exists():
        raise RuntimeError("OLLVM payload requires Linux ARM64/musl guest")
    m=manifest(bundle)
    if shutil.disk_usage("/opt").free<1_500_000_000:raise RuntimeError("OLLVM first installation requires 1.5GB free space")
    print("MINIS_STAGE:验证离线编译器与 APK",flush=True)
    apks=sorted((bundle/"apks").glob("*.apk"))
    if not apks:raise ValueError("No offline compiler packages")
    # Retains Alpine's package signature verification. Never allow-untrusted.
    installed=installed_records(pathlib.Path("/lib/apk/db/installed").read_text())
    selected=package_plan(package_records(apks),installed)
    print("MINIS_STAGE:离线依赖预检（保留兼容的现有组件）",flush=True)
    print(command(["apk","add","--simulate","--no-network",*selected]),flush=True)
    print(command(["apk","add","--no-network",*selected]),flush=True)
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
