import unittest,pathlib,importlib.util,tempfile,zipfile,stat,json,hashlib,io
from unittest import mock
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
    def sdk_fixture(self,folder):
        archive=folder/'fixture.zip';sdk='iPhoneOS15.6.sdk/'
        with zipfile.ZipFile(archive,'w') as z:
            z.writestr(sdk+'System/Library/Frameworks/Foundation.framework/Headers/Foundation.h','// test')
            z.writestr(sdk+'usr/lib/libSystem.tbd','--- !tapi-tbd')
        data=archive.read_bytes()
        items=[{'version':v,'file':'iPhoneOS'+v+'.sdk.zip','sdkRoot':'iPhoneOS'+v+'.sdk','url':'https://example.test/'+v+'.zip','bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()} for v in ['15.6','16.5']]
        (folder/'sdk-catalog.json').write_text(json.dumps({'sdks':items}))
        return data,items
    def test_selected_sdk_only_streamed_network_install(self):
        with tempfile.TemporaryDirectory() as d:
            d=pathlib.Path(d);data,_=self.sdk_fixture(d);calls=[]
            def opener(request,timeout):
                calls.append(request.full_url);return io.BytesIO(data)
            with mock.patch.object(module,'HERE',d),mock.patch.object(module,'SDK_HOME',d/'theos'/'sdks'),mock.patch.object(module.urllib.request,'urlopen',side_effect=opener),mock.patch.object(module.shutil,'disk_usage',return_value=mock.Mock(free=3_000_000_000)):
                before=module.sdk_status();self.assertFalse(any(i['installed'] for i in before['sdks']))
                result=module.install_sdk('15.6')
                self.assertEqual(result['version'],'15.6');self.assertEqual(calls,['https://example.test/15.6.zip'])
                self.assertTrue(module.sdk_status()['sdks'][0]['installed'])
                self.assertFalse(module.sdk_status()['sdks'][1]['installed'])
                self.assertFalse((d/'theos'/'sdks'/'iPhoneOS16.5.sdk').exists())
                self.assertIn('already installed',module.install_sdk('15.6')['status'])
                self.assertEqual(len(calls),1)
    def test_bad_hash_preserves_existing_sdk_and_cleans_stage(self):
        with tempfile.TemporaryDirectory() as d:
            d=pathlib.Path(d);data,items=self.sdk_fixture(d);items[0]['sha256']='0'*64
            (d/'sdk-catalog.json').write_text(json.dumps({'sdks':items}))
            home=d/'sdks';existing=home/'iPhoneOS16.5.sdk';existing.mkdir(parents=True)
            marker=existing/'keep.txt';marker.write_text('preserve')
            with mock.patch.object(module,'HERE',d),mock.patch.object(module,'SDK_HOME',home),mock.patch.object(module.urllib.request,'urlopen',return_value=io.BytesIO(data)),mock.patch.object(module.shutil,'disk_usage',return_value=mock.Mock(free=3_000_000_000)):
                with self.assertRaisesRegex(ValueError,'SHA256'):module.install_sdk('15.6')
                self.assertEqual(marker.read_text(),'preserve')
                self.assertFalse((home/'iPhoneOS15.6.sdk').exists())
                self.assertEqual(list(home.glob('.sdk-stage-*')),[])
    def test_offline_download_fails_without_installing(self):
        with tempfile.TemporaryDirectory() as d:
            d=pathlib.Path(d);self.sdk_fixture(d);home=d/'sdks'
            with mock.patch.object(module,'HERE',d),mock.patch.object(module,'SDK_HOME',home),mock.patch.object(module.urllib.request,'urlopen',side_effect=OSError('offline')),mock.patch.object(module.shutil,'disk_usage',return_value=mock.Mock(free=3_000_000_000)):
                with self.assertRaisesRegex(OSError,'offline'):module.install_sdk('15.6')
                self.assertEqual(list(home.iterdir()),[])
    def test_short_download_and_incomplete_existing_are_not_replaced(self):
        with tempfile.TemporaryDirectory() as d:
            d=pathlib.Path(d);data,_=self.sdk_fixture(d);home=d/'sdks'
            with mock.patch.object(module,'HERE',d),mock.patch.object(module,'SDK_HOME',home),mock.patch.object(module.urllib.request,'urlopen',return_value=io.BytesIO(data[:-1])),mock.patch.object(module.shutil,'disk_usage',return_value=mock.Mock(free=3_000_000_000)):
                with self.assertRaisesRegex(ValueError,'byte count'):module.install_sdk('15.6')
                target=home/'iPhoneOS15.6.sdk';target.mkdir();(target/'keep.txt').write_text('old')
                with self.assertRaisesRegex(RuntimeError,'incomplete'):module.install_sdk('15.6')
                self.assertEqual((target/'keep.txt').read_text(),'old')
if __name__=='__main__':unittest.main()
