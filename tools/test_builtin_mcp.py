import importlib.util
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import zipfile

SOURCE=Path(__file__).resolve().parents[1]/'src/ios/default_mount/usr/local/lib/minis-builtin-mcp/server.py'
spec=importlib.util.spec_from_file_location('builtin_mcp',SOURCE)
m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)

class Builtins(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.root=Path(self.tmp.name)
        (self.root/'hello.txt').write_text('hello 中文\nneedle',encoding='utf-8')
    def tearDown(self): self.tmp.cleanup()
    def call(self,profile,name,**args): return m.Server(self.root,profile).call(name,args)
    def test_file_read_hash_list(self):
        self.assertIn('中文',self.call('files','read_text',path='hello.txt')['text'])
        self.assertEqual(len(self.call('files','sha256',path='hello.txt')['sha256']),64)
        self.assertEqual(len(self.call('files','list_files')['entries']),1)
    def test_atomic_write_and_explicit_overwrite(self):
        self.call('files','write_text',path='new.txt',text='one')
        with self.assertRaises(ValueError): self.call('files','write_text',path='new.txt',text='two')
        self.call('files','write_text',path='new.txt',text='two',overwrite=True)
        self.assertEqual((self.root/'new.txt').read_text(),'two')
    def test_path_escape(self):
        with self.assertRaises(ValueError): self.call('files','read_text',path='../outside')
    def test_symlink_escape(self):
        if os.name=='nt': self.skipTest('Windows symlink privilege varies; run in WSL/CI')
        (self.root/'escape').symlink_to('/etc')
        with self.assertRaises(ValueError): self.call('files','read_text',path='escape/passwd')
    def test_search(self):
        result=self.call('project','search_text',query='needle')
        self.assertEqual(result['matches'][0]['line'],2)
    def test_git(self):
        subprocess.run(['git','init',str(self.root)],check=True,capture_output=True)
        self.assertEqual(self.call('project','git_inspect')['exit_code'],0)
        with self.assertRaises(ValueError): self.call('project','git_inspect',action='show',revision='--help')
    def test_sqlite_read_only(self):
        p=self.root/'data.db'
        with closing(sqlite3.connect(p)) as c:
            c.execute('CREATE TABLE example (x)'); c.execute('INSERT INTO example VALUES (42)'); c.commit()
        self.assertEqual(self.call('database','sqlite_query',path='data.db',sql='SELECT x FROM example')['rows'],[[42]])
        self.assertEqual(self.call('database','sqlite_tables',path='data.db')['rows'][0][0],'example')
        with self.assertRaises(sqlite3.Error): self.call('database','sqlite_query',path='data.db',sql='DELETE FROM example')
        with self.assertRaises(sqlite3.Error): self.call('database','sqlite_query',path='data.db',sql="ATTACH DATABASE ':memory:' AS other")
    def test_data_archive_system(self):
        self.assertIn('你好',self.call('data','json_format',text='{"x":"你好"}'))
        (self.root/'a.csv').write_text('a,b\n1,2',encoding='utf-8')
        self.assertEqual(len(self.call('data','csv_preview',path='a.csv')['rows']),2)
        with zipfile.ZipFile(self.root/'a.zip','w') as z: z.writestr('item.txt','content')
        self.assertEqual(self.call('archive','zip_list',path='a.zip')['total'],1)
        self.assertGreater(self.call('system','runtime_info')['disk_free'],0)
    def test_http_local_server(self):
        import http.server, threading
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200); self.end_headers(); self.wfile.write(b'http-ok')
            def log_message(self,*_): pass
        server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler)
        threading.Thread(target=server.serve_forever,daemon=True).start()
        try: self.assertEqual(self.call('web','http_fetch',url='http://127.0.0.1:%d/'%server.server_port)['text'],'http-ok')
        finally: server.shutdown(); server.server_close()
        with self.assertRaises(ValueError): self.call('web','http_fetch',url='file:///etc/passwd')
    def test_bounded_read(self):
        (self.root/'large.txt').write_bytes(b'x'*(m.MAX_BYTES+100))
        self.assertTrue(self.call('files','read_text',path='large.txt')['truncated'])
    def test_stdio_all_profiles(self):
        for profile,tools in m.TOOLS.items():
            requests=[dict(jsonrpc='2.0',id=1,method='initialize',params={'protocolVersion':'2025-06-18'}),
                      dict(jsonrpc='2.0',method='notifications/initialized'),
                      dict(jsonrpc='2.0',id=2,method='tools/list'),
                      dict(jsonrpc='2.0',id=3,method='ping'),
                      dict(jsonrpc='2.0',id=4,method='tools/call',params={'name':'missing','arguments':{}})]
            result=subprocess.run([sys.executable,str(SOURCE),'--profile',profile,'--root',str(self.root)],input='\n'.join(json.dumps(r) for r in requests)+'\n',text=True,capture_output=True,timeout=10,encoding='utf-8',env={**os.environ,'PYTHONIOENCODING':'utf-8'})
            self.assertEqual(result.returncode,0,result.stderr)
            replies=[json.loads(line) for line in result.stdout.splitlines()]
            self.assertEqual([r['id'] for r in replies],[1,2,3,4])
            self.assertEqual(len(replies[1]['result']['tools']),len(tools))
            self.assertTrue(replies[-1]['result']['isError'])

if __name__=='__main__': unittest.main()
