"""Run production Foundation WDA methods against a local HTTP fixture, not a phone."""
import base64
import http.server
import json
from pathlib import Path
import subprocess
import tempfile
import threading

ROOT=Path(__file__).resolve().parents[1]
source=(ROOT/'src/ios/Workbench.swift').read_text(encoding='utf-8')
# Keep the production WDA status gate in the fixture as well as the HTTP
# transport helpers.  Previously extraction started at wdaBase(), which
# silently omitted wdaStatus() and made the CI fixture fail to compile even
# though the app source was valid.
methods='    func wdaStatus() async -> (reachable: Bool, detail: String) {'+source.split('    func wdaStatus() async -> (reachable: Bool, detail: String) {',1)[1].split('    func run(',1)[0]
calls=[]
class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self,*_): pass
    def reply(self,value,status=200):
        raw=json.dumps({'value':value}).encode(); self.send_response(status); self.send_header('Content-Type','application/json'); self.end_headers(); self.wfile.write(raw)
    def do_GET(self):
        calls.append(('GET',self.path))
        if self.path=='/status': self.reply({'ready':True,'message':'fixture ready'})
        elif self.path=='/sessions': self.reply({'error':'unknown command'},404)
        elif self.path=='/session/mock-session': self.reply({'sessionId':'mock-session'})
        elif self.path.endswith('/source'): self.reply('<App name="fixture"/>')
        elif self.path.endswith('/screenshot'): self.reply(base64.b64encode(b'fixture-image').decode())
        else: self.reply({'error':'invalid session id','message':'missing'},404)
    def do_POST(self):
        data=json.loads(self.rfile.read(int(self.headers.get('Content-Length',0))))
        calls.append(('POST',self.path,data))
        if self.path=='/session':
            assert 'capabilities' in data
            self.reply({'sessionId':'mock-session'})
        elif self.path.endswith('/wda/tap'): self.reply({'error':'unknown command'},404)
        elif self.path.endswith('/wda/tap/0'):
            assert data=={'x':10,'y':20}; self.reply(None)
        elif self.path.endswith('/wda/dragfromtoforduration'):
            assert data['fromX']==10 and data['toX']==30; self.reply(None)
        elif self.path.endswith('/wda/keys'):
            assert ''.join(data['value'])=='hello'; self.reply(None)
        elif self.path.endswith('/wda/apps/activate'):
            assert data['bundleId']=='dev.fixture'; self.reply(None)
        else: self.reply({'error':'unknown command'},404)

server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler)
threading.Thread(target=server.serve_forever,daemon=True).start()
pre='''import Foundation
enum WorkbenchError:Error { case unavailable(String) }
final class FakeJailbreakFullAccessManager { static let shared=FakeJailbreakFullAccessManager(); var isJailbroken=false }
enum JailbreakFullAccessManager { static let shared=FakeJailbreakFullAccessManager() }
enum MinisDeviceBridge { static func openApplication(_ bundleID:String)->Bool { false } }
@MainActor final class DeviceWorkbench {
 let fm=FileManager.default
 var root:URL { fm.temporaryDirectory.appendingPathComponent("minis-wda-fixture") }
'''
post='''
}
@main struct Regression {
 @MainActor static func main() async throws {
  UserDefaults.standard.set("http://127.0.0.1:PORT",forKey:"workbench.wdaURL")
  UserDefaults.standard.removeObject(forKey:"workbench.wdaSession")
  let model=DeviceWorkbench(); let base=try model.wdaBase()
  let session=try await model.ensureWDASession(base:base,bundleID:"dev.fixture")
  precondition(session=="mock-session")
  let verified=try await model.ensureWDASession(base:base,bundleID:"",verifyCached:true)
  precondition(verified==session)
  _ = try await model.wda("tap",args:["bundle_id":"dev.fixture","x":10,"y":20])
  _ = try await model.wda("type",args:["text":"hello"])
  _ = try await model.wda("swipe",args:["x":10,"y":20,"end_x":30,"end_y":40])
  let ui=try await model.wda("get_ui",args:[:]); precondition(ui.contains("fixture"))
  let shot=try await model.wda("screenshot",args:[:]); precondition(shot.contains("截图已保存"))
  UserDefaults.standard.set("stale",forKey:"workbench.wdaSession")
  let refreshed=try await model.ensureWDASession(base:base,bundleID:"",verifyCached:true)
  precondition(refreshed=="mock-session")
  do { _=try await model.wdaJSON(base,"bad"); preconditionFailure("bad WDA response accepted") } catch {}
  precondition(UserDefaults.standard.string(forKey:"workbench.wdaSession")==nil)
  UserDefaults.standard.removeObject(forKey:"workbench.wdaURL")
  print("Production WDA HTTP regression passed: session discovery/create/verify, activation, legacy tap fallback, type, swipe, source, screenshot and stale-session handling; no device UI tested.")
 }
}
'''.replace('PORT',str(server.server_port))
try:
    with tempfile.TemporaryDirectory(prefix='minis-wda-tests-') as folder:
        p=Path(folder); (p/'test.swift').write_text(pre+methods+post,encoding='utf-8')
        subprocess.run(['swiftc','-parse-as-library',str(p/'test.swift'),'-o',str(p/'test')],check=True)
        subprocess.run([str(p/'test')],check=True,timeout=60)
    assert any(c[1].endswith('/wda/tap/0') for c in calls)
    print('Real HTTP calls to fixture:',len(calls))
finally: server.shutdown(); server.server_close()
