import unittest,tempfile,json,hashlib,importlib.util
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
p=ROOT/'src/ios/default_mount/usr/local/lib/minis-frida/install.py'
spec=importlib.util.spec_from_file_location('installer',p); module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
class FridaInstallerTests(unittest.TestCase):
 def fixture(self,root):
  (root/'wheels').mkdir();data=b'wheel-placeholder-not-executed'; name='frida-17.24.1-cp37-abi3-linux_aarch64.whl';(root/'wheels'/name).write_bytes(data)
  m={'frida_version':'17.24.1','python_major_minor':'3.12','wheels':[{'filename':name,'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()}]};(root/'manifest.json').write_text(json.dumps(m));return m
 def test_hash_valid(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);m=self.fixture(root);self.assertEqual(module.read_manifest(root),m)
 def test_tamper_rejected(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);m=self.fixture(root);(root/'wheels'/m['wheels'][0]['filename']).write_bytes(b'tampered')
   with self.assertRaises(ValueError):module.read_manifest(root)
 def test_traversal_rejected(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);m=self.fixture(root);m['wheels'][0]['filename']='../../bad.whl';(root/'manifest.json').write_text(json.dumps(m))
   with self.assertRaises(ValueError):module.read_manifest(root)
 def test_duplicate_rejected(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);m=self.fixture(root);m['wheels']*=2;(root/'manifest.json').write_text(json.dumps(m))
   with self.assertRaises(ValueError):module.read_manifest(root)
 def test_status_not_fake_green(self):
  with tempfile.TemporaryDirectory() as d:self.assertFalse(module.status(Path(d))['installed'])
 def test_native_scope_disclosed(self):
  self.assertIn('not native iOS process access',p.read_text(encoding='utf-8'))
 def test_no_remote_proxy(self):
  s=p.read_text(encoding='utf-8');self.assertNotIn('ssh ',s);self.assertIn('frida.get_device_manager().enumerate_devices()',s)
 def test_versioned_prefix_not_moved(self):
  s=p.read_text(encoding='utf-8');self.assertIn('venv.EnvBuilder(with_pip=False',s);self.assertIn('temp.symlink_to(env.name)',s)
if __name__=='__main__':unittest.main()
