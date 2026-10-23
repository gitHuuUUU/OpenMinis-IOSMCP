#!/usr/bin/env python3
"""Offline, hash-verified Alpine packages and a locally built Hikari runtime."""
import argparse, hashlib, json, os, pathlib, platform, shutil, subprocess, sys, re, tarfile, tempfile
ROOT=pathlib.Path("/opt/minis-protection")
RUNTIME_VERSION=2
PASSES=["bcf","indcall","indgv","sobf","fla"]
RUNTIME_FILES={"runtime/clang.py","runtime/libHikari.so","runtime/libMinisProtection.so","runtime/ldid"}
def sha(path):
    with path.open("rb") as stream:return hashlib.file_digest(stream,"sha256").hexdigest()
def identity(m):
    if m.get("schema")!=1 or m.get("platform")!="aarch64-linux-musl" or m.get("runtimeVersion")!=RUNTIME_VERSION or m.get("passes")!=PASSES:
        raise ValueError("Unsupported OLLVM manifest")
    if not RUNTIME_FILES.issubset(r["path"] for r in m.get("files",[])):
        raise ValueError("OLLVM runtime/plugin components missing")
    return m

def manifest(bundle):
    m=identity(json.loads((bundle/"manifest.json").read_text()))
    seen=set()
    for row in m["files"]:
        name=pathlib.PurePosixPath(row["path"])
        if name.is_absolute() or ".." in name.parts or "\\" in row["path"] or not name.parts or name.parts[0] not in ("apks","runtime","licenses") or row["path"] in seen:
            raise ValueError("Unsafe OLLVM member path")
        seen.add(row["path"]);p=bundle/name
        if not p.resolve().is_relative_to(bundle.resolve()) or p.is_symlink() or not p.is_file() or p.stat().st_size!=row["bytes"] or sha(p)!=row["sha256"]:
            raise ValueError("OLLVM integrity failed: "+row["path"])
    actual={p.relative_to(bundle).as_posix() for p in bundle.rglob("*") if p.is_file() and p.relative_to(bundle).as_posix()!="manifest.json"}
    if actual!=seen:raise ValueError("Unexpected or missing runtime files")
    return m
def command(argv,timeout=900):
    p=subprocess.run(list(map(str,argv)),capture_output=True,text=True,timeout=timeout)
    if p.returncode:raise RuntimeError("rc="+str(p.returncode)+"\n"+(p.stdout+p.stderr)[-4000:])
    return p.stdout.strip()
PROBE_SOURCE='''
extern int minis_external_call(int);
extern int puts(const char *);
volatile int minis_shared_value=17;
__attribute__((noinline)) int minis_probe(int x) {
  int r=x;
  if(x>7) r+=minis_external_call(x); else r-=3;
  if(x<0) r+=4; else r*=2;
  if(x==42) r+=5; else r-=6;
  if(x>100) r+=7; else r-=8;
  puts("MINIS_PROTECTION_PLAINTEXT_d8b1");
  return r+minis_shared_value;
}
'''

def pass_evidence(name, raw, protected):
    """Require transformed IR, not only acceptance of a command-line flag."""
    if raw==protected:raise RuntimeError(name+" pass left IR unchanged")
    if name=="bcf":
        before=len(re.findall(r"\bbr i1\b",raw));after=len(re.findall(r"\bbr i1\b",protected))
        if after<=before:raise RuntimeError("bcf did not add conditional control-flow branches")
        return {"conditionalBranchesBefore":before,"conditionalBranchesAfter":after}
    if name=="fla":
        if not re.search(r"\bswitch i32\b",protected) or "switchVar" not in protected:
            raise RuntimeError("fla dispatcher was not generated")
        return {"switchDispatcher":True}
    if name=="sobf":
        marker="MINIS_PROTECTION_PLAINTEXT_d8b1"
        if marker not in raw or marker in protected:raise RuntimeError("sobf plaintext string remained in IR")
        return {"plaintextMarkerRemoved":True}
    if name=="indcall":
        if "@minis_indcall_targets" not in protected or not re.search(r"%minis\.indcall\.target[^\n]*= load volatile ptr",protected) or not re.search(r"\bcall\b[^\n]*%minis\.indcall\.target",protected):
            raise RuntimeError("indcall table/volatile load/indirect call was not generated")
        return {"mutableCallTable":True,"volatileTargetLoad":True,"indirectCall":True}
    if name=="indgv":
        if "@minis_indgv_targets" not in protected or not re.search(r"%minis\.indgv\.target[^\n]*= load volatile ptr",protected) or not re.search(r"\bload volatile i32, ptr %minis\.indgv\.target",protected):
            raise RuntimeError("indgv table/volatile load/indirect global access was not generated")
        return {"mutableGlobalTable":True,"volatileTargetLoad":True,"indirectGlobalAccess":True}
    raise ValueError("Unknown protection pass: "+name)

def probe_passes(results):
    opt="/usr/lib/llvm19/bin/opt"
    names={"bcf":"hikari(enable-bcfobf)","fla":"hikari(enable-cffobf)","sobf":"hikari(enable-strcry)",
           "indcall":"minis-indcall","indgv":"minis-indgv"}
    with tempfile.TemporaryDirectory(prefix="minis-protection-probe-") as directory:
        path=pathlib.Path(directory);source=path/"probe.c";raw=path/"raw.ll"
        source.write_text(PROBE_SOURCE)
        command(["/usr/lib/llvm19/bin/clang","-O0","-Xclang","-disable-O0-optnone","-S","-emit-llvm",source,"-o",raw],120)
        before=raw.read_text()
        for name in PASSES:
            plugin="libMinisProtection.so" if name in ("indcall","indgv") else "libHikari.so"
            target=path/(name+".ll")
            # bcf selects blocks probabilistically. Retry an unchanged fixture,
            # never report success without added conditional branches.
            for attempt in range(3 if name=="bcf" else 1):
                try:
                    command([opt,"-load-pass-plugin="+str(ROOT/"runtime"/plugin),"-passes="+names[name],"-S",raw,"-o",target],120)
                    after=target.read_text();evidence=pass_evidence(name,before,after)
                    results[name]={"verified":True,"evidence":evidence,"inputSHA256":sha(raw),"outputSHA256":sha(target)}
                    break
                except Exception as e:
                    results[name]={"verified":False,"error":str(e)}
                    if attempt==2 or name!="bcf":break
    errors=[name+": "+result["error"] for name,result in results.items() if not result.get("verified")]
    if errors:raise RuntimeError("; ".join(errors))
    return results

def status():
    result={"installed":False,"runtimeVersion":RUNTIME_VERSION,"passes":PASSES,"availablePasses":[],
            "passProbe":{},"pluginProbe":False,"compiler":str(ROOT/"bin/clang"),
            "scope":"local Linux ARM64 guest; not a native iOS compiler process"}
    try:
        m=identity(json.loads((ROOT/"manifest.json").read_text()))
        for row in m["files"]:
            if row["path"].startswith("runtime/"):
                relative=pathlib.PurePosixPath(row["path"]);path=ROOT/relative
                if relative.is_absolute() or ".." in relative.parts or "\\" in row["path"] or not path.resolve().is_relative_to(ROOT.resolve()) or path.is_symlink() or not path.is_file() or path.stat().st_size!=row["bytes"] or sha(path)!=row["sha256"]:
                    raise ValueError("Installed OLLVM integrity failed: "+row["path"])
        # Presence here means its manifest hash was verified, not that a signing
        # operation ran. The actual Theos build must sign and inspect its output.
        result["signerPath"]=str(ROOT/"runtime/ldid")
        version=command([ROOT/"bin/clang","--version"],60).splitlines()[0]
        result["clang"]=version
        if "19." not in version:raise RuntimeError("Runtime compiler version missing")
        result["installedBytes"]=sum(p.stat().st_size for p in ROOT.rglob("*") if p.is_file() and not p.is_symlink())
        probe_passes(result["passProbe"])
        result.update(installed=True,pluginProbe=True,availablePasses=PASSES[:])
    except Exception as e:
        result["error"]=str(e)
        result["availablePasses"]=[name for name,probe in result["passProbe"].items() if probe.get("verified")]
    return result
def ensure(bundle):
    expected=sha(bundle/"manifest.json")
    # Identity is checked even on the fast path, forcing a v1 -> v2 upgrade.
    identity(json.loads((bundle/"manifest.json").read_text()))
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
        cxx=stage/"bin/clang++"
        cxx.write_text("#!/bin/sh\nexec python3 /opt/minis-protection/runtime/clang.py --driver-mode=g++ \"$@\"\n")
        cxx.chmod(0o755)
        (stage/"runtime/ldid").chmod(0o755)
        signer=stage/"bin/ldid"
        signer.write_text("#!/bin/sh\nexec /opt/minis-protection/runtime/ldid \"$@\"\n")
        signer.chmod(0o755)
        shutil.copy2(bundle/"manifest.json",stage/"manifest.json")
        (stage/"bundle.sha256").write_text(sha(bundle/"manifest.json")+"\n")
        backup=ROOT.with_name(".minis-protection-backup")
        if backup.exists():raise RuntimeError("Previous backup requires inspection before reinstall")
        if ROOT.exists():ROOT.rename(backup)
        activated=False
        try:
            stage.rename(ROOT);activated=True
            s=status()
            if not s["installed"]:raise RuntimeError(s["error"])
        except Exception:
            if activated:
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
