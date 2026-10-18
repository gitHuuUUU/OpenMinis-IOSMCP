"""Production URL resolver + manual WebKit/KVO methods; host tests, not iPhone UI."""
from pathlib import Path
import json, subprocess, tempfile, threading, http.server, sys, unittest
ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'src/ios/Agent/BrowserUse/BrowserUseManager.swift'
def read(p): return (ROOT/p).read_text(encoding='utf-8')
class BrowserContracts(unittest.TestCase):
 def test_forward_active_manager_state(self):
  s=read('src/ios/Agent/BrowserUse/BrowserTabPool.swift')
  for x in ['activeStateObservation?.cancel()', 'mgr.objectWillChange', '.throttle(for: .milliseconds(100)', '.removeDuplicates()']: self.assertIn(x,s)
 def test_explicit_submit_and_start_page(self):
  s=read('src/ios/Agent/BrowserUse/BrowserSheetView.swift')
  for x in ['.onSubmit { submitAddress() }','打开网址或搜索','browserStartPage','.navigationViewStyle(.stack)','addressFocused = false']: self.assertIn(x,s)
 def test_manual_downloads_have_real_destination(self):
  s=read('src/ios/Agent/BrowserUse/BrowserTabPool.swift')
  self.assertIn('sessionId ?? "manual-browser"',s)
  self.assertIn('self?.downloadSessionId',s)
  m=SOURCE.read_text(encoding='utf-8')
  self.assertIn('(suggestedFilename as NSString).lastPathComponent',m)
 def test_visible_tab_not_idle_evicted(self):
  s=read('src/ios/Agent/BrowserUse/BrowserTabPool.swift')
  self.assertIn('isPresentedToUser && tab.id == selectedTabId',s)
  self.assertIn('pool.isPresentedToUser && tab.id == pool.selectedTabId',s)
 def test_webview_can_be_replaced(self):
  s=read('src/ios/Agent/BrowserUse/BrowserWebView.swift')
  for x in ['@ObservedObject var manager','webView.superview !== container','removeFromSuperview()','dismantleUIView','restoreViewportFrame()']: self.assertIn(x,s)
 def test_download_panel_exports_after_dismiss(self):
  s=read('src/ios/Agent/BrowserUse/BrowserSheetView.swift')
  for x in ['onDismiss:', 'pendingDownloadURL', 'BrowserShareSheet', 'file.deletingLastPathComponent() == directory']: self.assertIn(x,s)
 def test_failure_has_timeout_and_cancel_rules(self):
  s=SOURCE.read_text(encoding='utf-8')
  self.assertIn('URLError(.timedOut)',s)
  self.assertGreaterEqual(s.count('code == NSURLErrorCancelled'),2)
  self.assertIn('self.webView === observed',s)
 def test_brand_and_feedback(self):
  s=read('src/ios/Views/ContentView.swift')
  self.assertIn('QQ交流群：1082489804',s)
  self.assertNotIn('showFeedback',s)
  self.assertNotIn('Text("Minis")',s)
  self.assertNotIn('Open Minis',read('src/ios/Launch Screen.storyboard'))
 def test_about_no_duplicate_qq_or_feedback(self):
  s=read('src/ios/Views/Settings/AboutView.swift')
  self.assertNotIn('Report an Issue',s); self.assertNotIn('1082489804',s)
 def test_localizations_valid_and_branded(self):
  catalog=json.loads(read('src/ios/Localizable.xcstrings'))
  for key,value in catalog['strings'].items():
   self.assertNotIn('IOS-MCP',key)
   self.assertNotIn('IOS-MCP',json.dumps(value,ensure_ascii=False))

if __name__=='__main__':
 result=unittest.TextTestRunner().run(unittest.defaultTestLoader.loadTestsFromTestCase(BrowserContracts))
 if not result.wasSuccessful(): sys.exit(1)
 if '--require-swift' not in sys.argv: sys.exit(0)
 source=SOURCE.read_text(encoding='utf-8')
 resolver=source.split('// MARK: - Manual browser address resolution (Foundation regression seam)',1)[1].split('// MARK: - End manual browser address resolution',1)[0]
 tests=r"""
let vectors: [(String, String?)] = [
 ("",nil),("  ",nil),("example.com","https://example.com"),(" https://example.com/a?q=x ","https://example.com/a?q=x"),
 ("http://localhost:8080/a","http://localhost:8080/a"),("localhost:8080","http://localhost:8080"),("192.168.0.39:8080","http://192.168.0.39:8080"),
 ("[::1]:8000","http://[::1]:8000"),("about:blank","about:blank"),("minis://workspace/test.html","minis://workspace/test.html"),
 ("ftp://example.com",nil),("javascript:alert(1)",nil),("data:text/html,hello",nil),("file:///etc/passwd",nil),
 ("https://",nil),("https://exa mple.com",nil),("https://example.com:0",nil),("https://example.com:99999",nil),("mailto:test@example.com",nil),
 ("hello world","search"),("搜索测试","search"),("C++ & iOS","search"),("example.org/path#here","https://example.org/path#here")
]
for (input, expected) in vectors {
 let actual=BrowserAddressResolver.resolve(input)
 if expected == "search" {
  let c=actual.flatMap { URLComponents(url:$0,resolvingAgainstBaseURL:false) }
  precondition(c?.host == "www.bing.com" && c?.queryItems?.first?.value == input, "query: \(input)")
 } else { precondition(actual?.absoluteString == expected, "input=\(input), actual=\(String(describing:actual)) expected=\(String(describing:expected))") }
}
print("Browser address production resolver: \(vectors.count) cases passed")
"""
 with tempfile.TemporaryDirectory() as folder:
  p=Path(folder); f=p/'resolver.swift';f.write_text('import Foundation\n'+resolver+tests,encoding='utf-8')
  subprocess.run(['swiftc',str(f),'-o',str(p/'resolver')],check=True)
  subprocess.run([str(p/'resolver')],check=True,timeout=30)
