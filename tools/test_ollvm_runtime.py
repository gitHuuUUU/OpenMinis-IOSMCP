import hashlib,importlib.util,json,pathlib,tempfile,unittest
ROOT=pathlib.Path(__file__).resolve().parents[1]
def module(name):
    spec=importlib.util.spec_from_file_location(name,ROOT/"src/ios/default_mount/usr/local/lib/minis-ollvm"/(name+".py"))
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
installer=module("install");driver=module("clang")
class Tests(unittest.TestCase):
    def fixture(self,root):
        (root/"runtime").mkdir()
        p=root/"runtime/libHikari.so";p.write_bytes(b"test-fixture-not-an-executable")
        m={"schema":1,"platform":"aarch64-linux-musl","passes":["bcf","fla","sobf"],"files":[{"path":"runtime/libHikari.so","bytes":p.stat().st_size,"sha256":hashlib.sha256(p.read_bytes()).hexdigest()}]}
        (root/"manifest.json").write_text(json.dumps(m))
        return m
    def test_valid_manifest(self):
        with tempfile.TemporaryDirectory() as d:
            p=pathlib.Path(d);m=self.fixture(p);self.assertEqual(installer.manifest(p),m)
    def test_tamper_and_extra(self):
        with tempfile.TemporaryDirectory() as d:
            p=pathlib.Path(d);self.fixture(p)
            (p/"runtime/libHikari.so").write_bytes(b"tampered")
            with self.assertRaises(ValueError):installer.manifest(p)
        with tempfile.TemporaryDirectory() as d:
            p=pathlib.Path(d);self.fixture(p);(p/"extra.txt").write_text("unexpected")
            with self.assertRaises(ValueError):installer.manifest(p)
    def test_unsafe_paths(self):
        for path in ["../bad","/bad","runtime/../bad","runtime\\bad","apks/../../bad"]:
            with tempfile.TemporaryDirectory() as d:
                p=pathlib.Path(d);m=self.fixture(p);m["files"][0]["path"]=path;(p/"manifest.json").write_text(json.dumps(m))
                with self.assertRaises(ValueError):installer.manifest(p)
    def test_driver_passes(self):
        self.assertEqual(driver.plan(["-mllvm","-bcf","-c","a.c","-mllvm","-sobf"]),(["-c","a.c"],["bcf","sobf"]))
        self.assertEqual(driver.plan(["--version"]),(["--version"],[]))
        for args in [["-mllvm"],["-mllvm","-indgv"],["-mllvm","-indcall"],["-mllvm","-allobf"]]:
            with self.assertRaises(ValueError):driver.plan(args)
    def test_bundling_wired(self):
        swift=(ROOT/"src/ios/Workbench.swift").read_text(encoding="utf-8")
        self.assertIn('action == "install-ollvm"',swift)
        workflow=(ROOT/".github/workflows/build-ipa.yml").read_text(encoding="utf-8")
        self.assertIn("prepare_ollvm_workbench.py",workflow)
        self.assertNotIn("--allow-untrusted",(ROOT/"src/ios/default_mount/usr/local/lib/minis-ollvm/install.py").read_text(encoding="utf-8").replace("# Retains Alpine's package signature verification. Never allow-untrusted.",""))
if __name__=="__main__":unittest.main()
