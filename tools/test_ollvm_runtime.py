import hashlib,importlib.util,json,pathlib,tempfile,unittest,os,subprocess
from unittest.mock import patch
ROOT=pathlib.Path(__file__).resolve().parents[1]
def module(name):
    spec=importlib.util.spec_from_file_location(name,ROOT/"src/ios/default_mount/usr/local/lib/minis-ollvm"/(name+".py"))
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
installer=module("install");driver=module("clang")
class Tests(unittest.TestCase):
    def fixture(self,root):
        (root/"runtime").mkdir()
        rows=[]
        for name in ("libHikari.so","libMinisProtection.so","clang.py","ldid"):
            p=root/"runtime"/name;p.write_bytes(b"test-fixture-not-an-executable")
            rows.append({"path":"runtime/"+name,"bytes":p.stat().st_size,"sha256":hashlib.sha256(p.read_bytes()).hexdigest()})
        m={"schema":1,"runtimeVersion":2,"platform":"aarch64-linux-musl","passes":["bcf","indcall","indgv","sobf","fla"],"files":rows}
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
        self.assertEqual(driver.plan(["-mllvm","-indgv","-mllvm","-indcall"]),([],["indgv","indcall"]))
        for args in [["-mllvm"],["-mllvm","-unknown"],["-mllvm","-allobf"]]:
            with self.assertRaises(ValueError):driver.plan(args)
    def test_runtime_identity_requires_v2_and_all_components(self):
        for change in ("old-version","old-passes","missing-plugin","missing-signer"):
            with tempfile.TemporaryDirectory() as d:
                p=pathlib.Path(d);m=self.fixture(p)
                if change=="old-version":m.pop("runtimeVersion")
                elif change=="old-passes":m["passes"]=["bcf","fla","sobf"]
                elif change=="missing-plugin":m["files"]=[r for r in m["files"] if "MinisProtection" not in r["path"]]
                else:m["files"]=[r for r in m["files"] if r["path"]!="runtime/ldid"]
                (p/"manifest.json").write_text(json.dumps(m))
                with self.assertRaises(ValueError):installer.manifest(p)
    def test_ensure_reinstalls_old_or_modified_runtime(self):
        for reason in ("old-version","tampered-plugin","tampered-signer","intact"):
            with tempfile.TemporaryDirectory() as d:
                base=pathlib.Path(d);bundle=base/"bundle";installed=base/"installed"
                bundle.mkdir();installed.mkdir();self.fixture(bundle);self.fixture(installed)
                expected=installer.sha(bundle/"manifest.json")
                (installed/"bundle.sha256").write_text(expected)
                if reason=="old-version":
                    m=json.loads((installed/"manifest.json").read_text());m.pop("runtimeVersion")
                    (installed/"manifest.json").write_text(json.dumps(m))
                if reason=="tampered-plugin":(installed/"runtime/libMinisProtection.so").write_text("bad")
                if reason=="tampered-signer":(installed/"runtime/ldid").write_text("bad")
                with patch.object(installer,"ROOT",installed),patch.object(installer,"status",return_value={"installed":True}) as status,patch.object(installer,"install",return_value={"installed":True,"upgraded":True}) as install:
                    result=installer.ensure(bundle)
                self.assertTrue(result['installed'])
                if reason=="intact":status.assert_called_once();install.assert_not_called()
                else:install.assert_called_once_with(bundle);status.assert_not_called()
    def test_driver_actual_plugin_chain(self):
        with patch.object(driver,"run") as run:
            driver.main(["-mllvm","-bcf","-mllvm","-indcall","-mllvm","-indgv","-mllvm","-sobf","-c","a.c","-o","a.o"])
        calls=[list(map(str,c.args[0])) for c in run.call_args_list]
        self.assertEqual(len(calls),4)
        self.assertIn("-passes=hikari(enable-bcfobf,enable-strcry)",calls[1])
        self.assertIn("-passes=minis-indcall,minis-indgv",calls[2])
        self.assertTrue(any("libMinisProtection.so" in a for a in calls[2]))
        self.assertEqual(calls[2][-3],calls[1][-1])
    def test_driver_objc_dependency_stages(self):
        with patch.object(driver,"run") as run:
            driver.main(["-mllvm","-indcall","-x","objective-c","Tweak.x","-c","-MMD","-MP","-MF","build/Tweak.d","-MT","build/Tweak.o","-arch","arm64","-isysroot","/sdk","-o","build/Tweak.o"])
        calls=[list(map(str,c.args[0])) for c in run.call_args_list]
        self.assertEqual(len(calls),3)
        for value in ("objective-c","-MMD","-MP","-MF","build/Tweak.d","-MT","build/Tweak.o"):
            self.assertIn(value,calls[0])
        for value in ("objective-c","-MMD","-MP","-MF","-MT"):
            self.assertNotIn(value,calls[-1])
        self.assertIn("-arch",calls[-1]);self.assertIn("/sdk",calls[-1])
        self.assertEqual(calls[-1][-2:],["-o","build/Tweak.o"])
    def test_driver_link_only_and_no_artifact_modes_passthrough(self):
        for args in (["a.o","-dynamiclib","-Wl,-install_name,/x","-o","out.dylib"],["-E","a.m"],["-M","a.c"],["-fsyntax-only","a.m"],["--version"]):
            with patch.object(driver.subprocess,"call",return_value=0) as call,patch.object(driver,"run") as run:
                self.assertEqual(driver.main(["-mllvm","-fla",*args]),0)
            self.assertEqual(call.call_args.args[0],[driver.CLANG,*args]);run.assert_not_called()
    def test_driver_link_flags_objects_preserved_only_for_link(self):
        with patch.object(driver,"run") as run:
            driver.main(["-mllvm","-indgv","a.cpp","other.o","-shared","-L/libs","-lthing","-fuse-ld=lld","-Wl,-rpath,/libs","-o","out.so"])
        calls=[list(map(str,c.args[0])) for c in run.call_args_list]
        for value in ("other.o","-shared","-L/libs","-lthing","-fuse-ld=lld","-Wl,-rpath,/libs"):
            self.assertNotIn(value,calls[0]);self.assertIn(value,calls[-1])
        self.assertIn("--driver-mode=g++",calls[-1])
        self.assertNotIn("a.cpp",calls[-1]);self.assertTrue(any(a.endswith(".o") for a in calls[-1]))
    def test_driver_default_dependency_output_not_temporary(self):
        with patch.object(driver,"run") as run:
            driver.main(["-mllvm","-sobf","-MMD","-c","a.c","-obuild/output.o"])
        frontend=list(map(str,run.call_args_list[0].args[0]))
        self.assertEqual(frontend[frontend.index("-MF")+1],"build/output.d")
        self.assertEqual(frontend[frontend.index("-MT")+1],"build/output.o")
    def test_driver_responses_and_source_option_values(self):
        groups=driver.option_groups(["-include","header.c","-isysroot","/sdk","-MF","source.c","actual.m"])
        self.assertEqual([s for _,s,_ in driver.inputs(groups)],["actual.m"])
        with tempfile.TemporaryDirectory() as d:
            p=pathlib.Path(d);first=p/"first.rsp";second=p/"second.rsp"
            second.write_text('-c "source with space.m" -o "out with space.o"')
            first.write_text('-mllvm -indcall @"'+second.as_posix()+'"')
            with patch.object(driver,"run") as run:
                driver.main(["@"+str(first)])
            self.assertIn("source with space.m",run.call_args_list[0].args[0])
            self.assertIn("out with space.o",run.call_args_list[-1].args[0])
            first.write_text('@"'+first.as_posix()+'"')
            with self.assertRaisesRegex(ValueError,"recursively"):
                driver.expand_response_files(["@"+str(first)])
    def test_driver_multi_compile_and_llvm_output(self):
        with patch.object(driver,"run") as run:
            driver.main(["-mllvm","-indgv","-S","-emit-llvm","a.c"])
        final=list(map(str,run.call_args_list[-1].args[0]))
        self.assertIn("-S",final);self.assertIn("-emit-llvm",final);self.assertEqual(final[-1],"a.ll")
        with patch.object(driver,"run") as run:
            driver.main(["-mllvm","-indgv","-c","a.c","b.c"])
        outputs=[list(map(str,c.args[0]))[-1] for c in run.call_args_list if c.args[0][0]==driver.CLANG]
        self.assertIn("a.o",outputs);self.assertIn("b.o",outputs)
        with self.assertRaisesRegex(ValueError,"multiple"):
            driver.main(["-mllvm","-indgv","-c","a.c","b.c","-o","one.o"])
        for args in (["-x","c-header","a.h"],["-Xclang","-emit-pch","a.h"],["-fmodule-header","a.h"]):
            with self.assertRaisesRegex(ValueError,"PCH"):
                driver.main(["-mllvm","-indgv",*args])
    def test_pass_evidence_rejects_flag_only_noop(self):
        raw='@.str = constant [35 x i8] c"MINIS_PROTECTION_PLAINTEXT_d8b1"\n br i1 %a, label %b, label %c\n'
        for name in installer.PASSES:
            with self.assertRaises(RuntimeError):installer.pass_evidence(name,raw,raw)
            with self.assertRaises(RuntimeError):installer.pass_evidence(name,raw,raw+'\n; accepted only\n')
        self.assertTrue(installer.pass_evidence("bcf",raw,raw+' br i1 %x, label %y, label %z')["conditionalBranchesAfter"]>1)
        self.assertTrue(installer.pass_evidence("fla",raw,raw+' switch i32 %switchVar, label %x []')["switchDispatcher"])
        self.assertTrue(installer.pass_evidence("sobf",raw,raw.replace("MINIS_PROTECTION_PLAINTEXT_d8b1","encrypted"))["plaintextMarkerRemoved"])
        indcall='@minis_indcall_targets = private global [1 x ptr] [ptr @target]\n%minis.indcall.target = load volatile ptr, ptr %table\n%a = call i32 %minis.indcall.target(i32 1)'
        indgv='@minis_indgv_targets = private global [1 x ptr] [ptr @value]\n%minis.indgv.target.1 = load volatile ptr, ptr %table\n%a = load volatile i32, ptr %minis.indgv.target.1'
        self.assertTrue(installer.pass_evidence("indcall",raw,indcall)["indirectCall"])
        self.assertTrue(installer.pass_evidence("indgv",raw,indgv)["indirectGlobalAccess"])
    def test_status_requires_actual_probes_and_preserves_failures(self):
        with tempfile.TemporaryDirectory() as d:
            p=pathlib.Path(d);self.fixture(p)
            def partial(results):
                results['bcf']={'verified':True,'evidence':{'conditionalBranchesAfter':10}}
                results['indcall']={'verified':False,'error':'no indirect call'}
                raise RuntimeError('no indirect call')
            with patch.object(installer,"ROOT",p),patch.object(installer,"command",return_value="Alpine clang version 19.1.4"),patch.object(installer,"probe_passes",side_effect=partial):
                result=installer.status()
            self.assertFalse(result['installed']);self.assertFalse(result['pluginProbe'])
            self.assertEqual(result['availablePasses'],['bcf']);self.assertEqual(result['runtimeVersion'],2)
            self.assertEqual(result['error'],'no indirect call');self.assertGreater(result['installedBytes'],0)
            self.assertEqual(result['signerPath'],str(p/'runtime/ldid'));self.assertNotIn('signerProbe',result)
    @unittest.skipUnless(os.environ.get("MINIS_OLLVM_TEST_RUNTIME"),"optional real LLVM19/plugin driver regression")
    def test_native_driver_theos_argument_pipeline(self):
        runtime=pathlib.Path(os.environ["MINIS_OLLVM_TEST_RUNTIME"]).resolve()
        clang=os.environ.get("MINIS_OLLVM_TEST_CLANG",driver.CLANG)
        opt=os.environ.get("MINIS_OLLVM_TEST_OPT",driver.OPT)
        flags=["-mllvm","-bcf","-mllvm","-indcall","-mllvm","-indgv","-mllvm","-sobf","-mllvm","-fla"]
        with tempfile.TemporaryDirectory() as d,patch.object(driver,"ROOT",runtime),patch.object(driver,"CLANG",clang),patch.object(driver,"OPT",opt):
            p=pathlib.Path(d)
            source=p/"source with space.c";header=p/"project.h"
            header.write_text("extern int external_value(int);\n")
            source.write_text('#include "project.h"\nextern int puts(const char *);\nvolatile int data=5;\nint main(int argc,char **argv) { puts("DRIVER_PROBE_6a19"); return external_value(argc)+data!=17; }\n')
            dependency=p/"result.d";obj=p/"result.o";binary=p/"program"
            response=p/"args.rsp"
            import shlex
            response.write_text(shlex.join([*flags,"-c",str(source),"-Werror","-MMD","-MP","-MF",str(dependency),"-MT",str(obj),"-o",str(obj)]))
            self.assertEqual(driver.main(["@"+str(response)]),0)
            deps=dependency.read_text().replace("\\ "," ")
            self.assertIn(str(obj),deps);self.assertIn("project.h",deps);self.assertNotIn("minis-ollvm-",deps)
            extra=p/"extra.c";extra_obj=p/"extra.o"
            extra.write_text("int external_value(int x) { return x+11; }\n")
            subprocess.run([clang,"-c",str(extra),"-o",str(extra_obj)],check=True)
            self.assertEqual(driver.main([*flags,str(obj),str(extra_obj),"-o",str(binary)]),0)
            output=subprocess.check_output([str(binary)],text=True)
            self.assertEqual(output.strip(),"DRIVER_PROBE_6a19")
            objc=p/"Tweak.x";objc_obj=p/"Tweak.o";objc_dep=p/"Tweak.d"
            objc.write_text('__attribute__((objc_root_class)) @interface Demo\n- (int)value:(int)x;\n@end\n@implementation Demo\n- (int)value:(int)x { return x>2?x+1:x-1; }\n@end\n')
            self.assertEqual(driver.main([*flags,"--target=arm64-apple-ios15.4","-fobjc-arc","-Werror","-x","objective-c","-MMD","-MF",str(objc_dep),"-c",str(objc),"-o",str(objc_obj)]),0)
            self.assertEqual(objc_obj.read_bytes()[:4],bytes.fromhex("cffaedfe"))
            self.assertIn(str(objc_obj),objc_dep.read_text())
            cpp=p/"test.cpp";cpp_bin=p/"cpp-program"
            cpp.write_text('template<class T> __attribute__((noinline)) T twice(T x) { return x*2; }\nint main() {return twice(21)!=42;}\n')
            self.assertEqual(driver.main([*flags,str(cpp),"-o",str(cpp_bin)]),0)
            subprocess.run([str(cpp_bin)],check=True)
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
