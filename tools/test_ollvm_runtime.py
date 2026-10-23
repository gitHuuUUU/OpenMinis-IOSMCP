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
    def test_composer_icon_only(self):
        view=(ROOT/"src/ios/Views/Chat/AIChatView.swift").read_text(encoding="utf-8")
        row=view.split("private var composerModelRow: some View {",1)[1].split("private var composerContextRow:",1)[0]
        self.assertNotIn("Text(",row)
        self.assertNotIn("Label(vm.currentThinkingLevel.displayName",row)
        self.assertNotIn('Image(systemName: "cpu")',row)
        self.assertNotIn('Image(systemName: "slider.horizontal.3")',row)
        self.assertNotIn("showModelPicker = true",row)
        self.assertNotIn("vm.setThinkingLevel(level)",row)
        self.assertIn("composerContextRow",row)
        self.assertIn("showModelPicker = true",view.split("private var composerModelRow:",1)[0])
        self.assertIn("vm.setThinkingLevel(newLevel)",view.split("private var composerModelRow:",1)[0])
        ui=(ROOT/"src/ios/Views/MinisReDesignSystem.swift").read_text(encoding="utf-8")
        self.assertIn("static let showsContextText = false",ui)
        for name in ["ChatInputBar.swift","Voice/InlineVoiceInputView.swift"]:
            self.assertIn("guard MinisReComposerVisibility.showsContextText else",(ROOT/"src/ios/Views/Chat"/name).read_text(encoding="utf-8"))
    def records(self, deps=()):
        return [{"name":name,"version":"19.1.4-r0","provides":[],"depends":list(deps) if name=="llvm19" else [],"path":pathlib.Path(name+".apk")} for name in ("clang19","llvm19","lld")]
    def test_offline_plan_preserves_installed_libcurl(self):
        available=self.records(["so:libcurl.so.4"])+[{"name":"libcurl","version":"8.14.1-r3","provides":["so:libcurl.so.4=4.8.0"],"depends":[],"path":pathlib.Path("libcurl-r3.apk")}]
        installed=installer.installed_records("P:curl\nV:8.14.1-r2\nD:libcurl=8.14.1-r2\n\nP:libcurl\nV:8.14.1-r2\np:so:libcurl.so.4=4.8.0\n")
        plan=installer.package_plan(available,installed,lambda a,b:"=" if a==b else "<")
        self.assertNotIn(pathlib.Path("libcurl-r3.apk"),plan)
        self.assertEqual(len(plan),3)
        self.assertIn(pathlib.Path("libcurl-r3.apk"),installer.package_plan(available,[],lambda a,b:"="))
    def test_offline_plan_adds_unsatisfied_dependency(self):
        available=self.records(["libexpat>=2.8.0"])+[{"name":"libexpat","version":"2.9.0","provides":[],"depends":[],"path":pathlib.Path("libexpat.apk")}]
        installed=[{"name":"libexpat","version":"2.7.0","provides":[]}]
        plan=installer.package_plan(available,installed,lambda a,b:">" if a=="2.9.0" else "<")
        self.assertIn(pathlib.Path("libexpat.apk"),plan)
    def test_offline_plan_missing_provider_fails(self):
        with self.assertRaisesRegex(RuntimeError,"dependency unavailable"):
            installer.package_plan(self.records(["so:missing.so.1"]),[],lambda a,b:"=")
    def test_apk_preflight_before_mutation(self):
        source=(ROOT/"src/ios/default_mount/usr/local/lib/minis-ollvm/install.py").read_text(encoding="utf-8")
        self.assertLess(source.index('["apk","add","--simulate","--no-network",*selected]'),source.index('["apk","add","--no-network",*selected]'))
        self.assertNotIn('["apk","add","--no-network",*apks]',source)

    def test_compact_visual_scale(self):
        ui=(ROOT/"src/ios/Views/MinisReDesignSystem.swift").read_text(encoding="utf-8")
        self.assertIn(".frame(width: 24, height: 24)",ui)
        self.assertIn(".frame(minHeight: 44)",ui)
        self.assertIn("Text(title).font(.subheadline)",ui)
        self.assertIn("cornerRadius: 14",ui)
        self.assertNotIn(".largeTitle",ui)
        self.assertNotIn(".frame(width: 40, height: 40)",ui)
if __name__=="__main__":unittest.main()
