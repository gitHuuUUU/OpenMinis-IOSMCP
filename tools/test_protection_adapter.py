"""Protection selection, runtime evidence and real Theos command wiring."""
import importlib.util,json,pathlib,tempfile,unittest
from types import SimpleNamespace
from unittest import mock
ROOT=pathlib.Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('build_adapter',ROOT/'src/ios/BuildWorkbench.bundle/minis_build.py')
adapter=importlib.util.module_from_spec(spec);spec.loader.exec_module(adapter)

class Tests(unittest.TestCase):
    def args(self,**values):
        base=dict(protection='enhanced',protection_passes='bcf,indcall,indgv,sobf,fla',protection_selection='combined',protection_compiler='/opt/minis-protection/bin/clang',sdk='15.6',minimum='15.4')
        base.update(values);return SimpleNamespace(**base)
    def test_five_real_pass_flags_and_single_invariant(self):
        flags=adapter.protection_flags(self.args())
        self.assertEqual(set(flags[1::2]),{'-bcf','-indcall','-indgv','-sobf','-fla'})
        with self.assertRaisesRegex(ValueError,'exactly one'):adapter.protection_flags(self.args(protection_selection='single'))
        self.assertEqual(adapter.protection_flags(self.args(protection_selection='single',protection_passes='indcall')),['-mllvm','-indcall'])
    def test_empty_unknown_and_duplicate_selection(self):
        for raw in ('','bcf,','unknown','bcf,--output=/tmp/not-a-pass'):
            with self.assertRaises(ValueError):adapter.protection_flags(self.args(protection_passes=raw))
        with self.assertRaises(ValueError):adapter.protection_flags(self.args(protection_selection='wrong'))
        self.assertEqual(adapter.protection_flags(self.args(protection_selection='single',protection_passes='indgv,indgv')),['-mllvm','-indgv'])
    def test_normal_never_installs_or_claims_protection(self):
        with mock.patch.object(adapter.subprocess,'run',side_effect=AssertionError('must not execute')):
            self.assertEqual(adapter.protection_status(self.args(protection='normal')),{'mode':'normal','status':'normal compilation; protection disabled'})
    def test_builtin_probe_failure_is_not_ready(self):
        with tempfile.TemporaryDirectory() as d:
            root=pathlib.Path(d);(root/'ollvm').mkdir();(root/'ollvm/manifest.json').write_text('{}')
            for response in ('not JSON',json.dumps({'installed':False,'pluginProbe':False,'error':'missing pass'})):
                with mock.patch.object(adapter,'HERE',root),mock.patch.object(adapter.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout=response,stderr='')):
                    with self.assertRaises(RuntimeError):adapter.protection_status(self.args())
    def test_theos_detection_does_not_reinterpret_prebuilt_deb(self):
        with tempfile.TemporaryDirectory() as d:
            root=pathlib.Path(d);(root/'Makefile').write_text('all:')
            self.assertFalse(adapter.is_theos_project(root))
            (root/'Makefile').write_text('include $(THEOS)/makefiles/common.mk')
            self.assertTrue(adapter.is_theos_project(root))
            (root/'DEBIAN').mkdir();(root/'DEBIAN/control').write_text('Package: fixture')
            self.assertFalse(adapter.is_theos_project(root))
    def fixture(self,root):
        src=root/'source';src.mkdir();(src/'Makefile').write_text('include $(THEOS)/makefiles/common.mk')
        theos=root/'theos';(theos/'makefiles').mkdir(parents=True);(theos/'makefiles/common.mk').touch()
        sdk=theos/'sdks/iPhoneOS15.6.sdk';(sdk/'System/Library/Frameworks/Foundation.framework/Headers').mkdir(parents=True)
        (sdk/'System/Library/Frameworks/Foundation.framework/Headers/Foundation.h').touch();(sdk/'usr/lib').mkdir(parents=True);(sdk/'usr/lib/libSystem.tbd').touch()
        return src,theos
    def test_theos_uses_protected_frontend_keeps_linker_and_packages_new_output(self):
        with tempfile.TemporaryDirectory() as d:
            root=pathlib.Path(d);src,theos=self.fixture(root);out=root/'result.deb';calls=[]
            def run(command,cwd=None):
                calls.append(command)
                if 'package' in command:
                    (src/'packages').mkdir();(src/'packages/result.deb').write_bytes(b'!<arch>\nfixture')
            with mock.patch.dict(adapter.os.environ,{'THEOS':str(theos)}),mock.patch.object(adapter.shutil,'which',return_value='/usr/bin/make'),mock.patch.object(adapter,'run',side_effect=run):
                adapter.build_theos(self.args(protection_compiler='/fixture/protected-clang'),src,out)
            self.assertEqual(len(calls),2);self.assertIn('clean',calls[0]);self.assertNotIn('package',calls[0]);self.assertIn('package',calls[1]);self.assertNotIn('clean',calls[1])
            for command in calls:
                for key in ('TARGET_CC=','TARGET_CXX='):
                    frontend=next(x for x in command if x.startswith(key))
                    for flag in ('-bcf','-indcall','-indgv','-sobf','-fla'):self.assertIn(flag,frontend)
                self.assertFalse(any(x.startswith('TARGET_LD=') for x in command))
            self.assertEqual(out.read_bytes(),b'!<arch>\nfixture')
    def test_stale_package_never_reported_as_new_build(self):
        with tempfile.TemporaryDirectory() as d:
            root=pathlib.Path(d);src,theos=self.fixture(root);(src/'packages').mkdir();(src/'packages/old.deb').write_bytes(b'!<arch>\nold')
            with mock.patch.dict(adapter.os.environ,{'THEOS':str(theos)}),mock.patch.object(adapter.shutil,'which',return_value='/usr/bin/make'),mock.patch.object(adapter,'run'):
                with self.assertRaisesRegex(RuntimeError,'newly built'):adapter.build_theos(self.args(protection_compiler='/fixture/protected-clang'),src,root/'out.deb')
    def test_normal_theos_does_not_override_compiler_or_linker(self):
        with tempfile.TemporaryDirectory() as d:
            root=pathlib.Path(d);src,theos=self.fixture(root);commands=[]
            def run(command,cwd=None):
                commands.append(command)
                if 'package' in command:
                    (src/'packages').mkdir();(src/'packages/a.deb').write_bytes(b'!<arch>\n')
            with mock.patch.dict(adapter.os.environ,{'THEOS':str(theos)}),mock.patch.object(adapter.shutil,'which',return_value='/usr/bin/make'),mock.patch.object(adapter,'run',side_effect=run):adapter.build_theos(self.args(protection='normal'),src,root/'out.deb')
            self.assertFalse(any(x.startswith('TARGET_') for c in commands for x in c))
    def test_failed_signature_preserves_previous_output(self):
        with tempfile.TemporaryDirectory() as d:
            root=pathlib.Path(d);src,theos=self.fixture(root);out=root/'result.deb';out.write_bytes(b'previous valid build')
            def run(command,cwd=None):
                if 'package' in command:
                    (src/'packages').mkdir();(src/'packages/result.deb').write_bytes(b'!<arch>\nnew unverified')
            with mock.patch.dict(adapter.os.environ,{'THEOS':str(theos)}),mock.patch.object(adapter.shutil,'which',return_value='/usr/bin/make'),mock.patch.object(adapter,'run',side_effect=run),mock.patch.object(adapter.pathlib.Path,'is_file',return_value=True),mock.patch.object(adapter,'verify_theos_signatures',side_effect=ValueError('code page mismatch')):
                with self.assertRaisesRegex(ValueError,'code page'):adapter.build_theos(self.args(),src,out)
            self.assertEqual(out.read_bytes(),b'previous valid build')
            self.assertEqual(list(root.glob('.result.deb.*')),[])
    def test_workbench_captures_one_selection_before_await(self):
        text=(ROOT/'src/ios/Workbench.swift').read_text(encoding='utf-8').split('func buildWorkbench(',1)[1].split('func desktopTool(',1)[0]
        for key in ('build.protection','build.protectionCompiler','build.protectionPasses','build.protectionSelection'):
            self.assertEqual(text.count('forKey:"'+key+'"'),1)
            self.assertLess(text.index('forKey:"'+key+'"'),text.index('try await'))
    def test_workbench_passes_persisted_selection_to_backend(self):
        text=(ROOT/'src/ios/Workbench.swift').read_text(encoding='utf-8')
        self.assertIn('--protection-selection ',text);self.assertIn('"build.protectionSelection"',text)

if __name__=='__main__':unittest.main()
