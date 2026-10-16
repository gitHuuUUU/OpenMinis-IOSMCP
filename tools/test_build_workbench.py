import unittest,pathlib,importlib.util,tempfile,zipfile,stat,json
root=pathlib.Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('minis_build',root/'src/ios/BuildWorkbench.bundle/minis_build.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
class AdapterTests(unittest.TestCase):
    def test_zip_extract(self):
        with tempfile.TemporaryDirectory() as d:
            d=pathlib.Path(d);a=d/'sdk.zip'
            with zipfile.ZipFile(a,'w') as z:z.writestr('sdk/Headers/test.h','int x;')
            module.extract_sdk(a,d/'out');self.assertEqual((d/'out/sdk/Headers/test.h').read_text(),'int x;')
    def test_zip_escape_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            d=pathlib.Path(d);a=d/'sdk.zip'
            with zipfile.ZipFile(a,'w') as z:z.writestr('../escape','bad')
            with self.assertRaises(ValueError):module.extract_sdk(a,d/'out')
            self.assertFalse((d/'escape').exists())
    def test_zip_symlink_escape_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            d=pathlib.Path(d);a=d/'sdk.zip';i=zipfile.ZipInfo('sdk/link');i.external_attr=(stat.S_IFLNK|0o777)<<16
            with zipfile.ZipFile(a,'w') as z:z.writestr(i,'../../../outside')
            with self.assertRaises(ValueError):module.extract_sdk(a,d/'out')
    def test_wrong_exe_magic_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p=pathlib.Path(d)/'bad.exe';p.write_text('not executable')
            with self.assertRaises(RuntimeError):module.validate_artifact(p,'exe')
    def test_ipa_requires_app_metadata(self):
        with tempfile.TemporaryDirectory() as d:
            p=pathlib.Path(d)/'bad.ipa'
            with zipfile.ZipFile(p,'w') as z:z.writestr('hello','test')
            with self.assertRaises(RuntimeError):module.validate_artifact(p,'ipa')
    def test_sdk_manifest_hashes(self):
        j=json.loads((root/'src/ios/BuildWorkbench.bundle/sdk-catalog.json').read_text())
        for i in j['sdks']:
            self.assertEqual(len(i['sha256']),64);self.assertTrue(i['url'].startswith('https://github.com/'));self.assertGreater(i['bytes'],1000000)
if __name__=='__main__':unittest.main()
