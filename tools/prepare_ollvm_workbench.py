"""Fetch reviewed native ARM64 runtime; only verified bytes enter the IPA."""
import hashlib,json,os,pathlib,subprocess,tarfile,tempfile,shutil
ROOT=pathlib.Path(__file__).resolve().parents[1]
def main():
    catalog=json.loads((ROOT/"tools/ollvm-runtime-catalog.json").read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory() as tmp:
        tmp=pathlib.Path(tmp)
        subprocess.run(["gh","release","download",catalog["release"],"-R",os.environ.get("GITHUB_REPOSITORY","gitHuuUUU/OpenMinis-IOSMCP"),"-p",catalog["asset"],"-D",str(tmp)],check=True)
        archive=tmp/catalog["asset"]
        with archive.open("rb") as f:digest=hashlib.file_digest(f,"sha256").hexdigest()
        if archive.stat().st_size!=catalog["bytes"] or digest!=catalog["sha256"]:raise ValueError("OLLVM archive integrity failed")
        with tarfile.open(archive) as tar:
            total=0;seen=set()
            for m in tar.getmembers():
                p=pathlib.PurePosixPath(m.name)
                if not p.parts or p.parts[0]!="bundle" or p.is_absolute() or ".." in p.parts or "\\" in m.name or not (m.isdir() or m.isfile()) or m.name in seen:
                    raise ValueError("Invalid OLLVM archive member")
                seen.add(m.name);total+=m.size
                if total>1_500_000_000 or len(seen)>1000:raise ValueError("OLLVM archive limits")
            tar.extractall(tmp/"unpacked")
        bundle=tmp/"unpacked/bundle"
        import importlib.util
        spec=importlib.util.spec_from_file_location("ollvm_installer",ROOT/"src/ios/default_mount/usr/local/lib/minis-ollvm/install.py")
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        manifest=module.manifest(bundle)
        if manifest!=catalog["manifest"]:raise ValueError("OLLVM manifest differs from reviewed catalog")
        target=ROOT/"src/ios/BuildWorkbench.bundle/ollvm"
        target.mkdir(parents=True,exist_ok=True)
        shutil.copytree(bundle,target,dirs_exist_ok=True)
        print("Verified offline OLLVM:",manifest["clang"],manifest["passes"])
if __name__=="__main__":main()
