"""Execute the real production Swift disclosure body using lightweight storage/logger doubles."""
import pathlib, shutil, subprocess, tempfile, sys
root=pathlib.Path(__file__).resolve().parents[1]
source=(root/'src/ios/Agent/Session/SkillStore.swift').read_text(encoding='utf-8')
start=source.index('    func skillPromptFragment(for sessionId: String) -> String? {')
end=source.index('        return fragment\n    }', start)+len('        return fragment\n    }')
body=source[start:end]
assert '.prefix(Self.maxSkillMetadataCount)' in body
assert 'max(0, min(10,' in body
assert 'max(0, 100 - selected.count)' in body
swift=shutil.which('swiftc')
if not swift:
    if '--require-swift' in sys.argv: raise SystemExit('swiftc required')
    print('Source bounds checks passed; executable Swift tests require cloud macOS runner.')
    raise SystemExit(0)
stub=r'''
import Foundation
enum SkillImportSource:Equatable { case bundled, file }
struct Skill {
 let id:String; let name:String; let description:String
 let importSource:SkillImportSource; let updatedAt:Date; let useCount:Double
}
struct AppLogger { init(category:String) {} ; func info(_ text:String) {} }
extension String { var xmlEscaped:String { self } }
class SkillStore {
 var skills:[Skill]=[]
 static let maxSkillMetadataCount=20
 func isEnabledForSession(_ id:String, sessionId:String)->Bool { !id.hasPrefix("disabled") }
'''
tests=r'''
}
let store=SkillStore()
var cases=0
for n in [0,1,19,20,21,99,100,101,128,256,1000] {
 for bundled in [0,min(n,19),min(n,20),min(n,21),n] {
  store.skills=(0..<n).map { i in
   Skill(id:"id-\(i)",name:"skill-\(i)",description:"test",importSource:i<bundled ? .bundled : .file,updatedAt:Date().addingTimeInterval(Double(-i)),useCount:Double(i))
  }
  let fragment=store.skillPromptFragment(for:"test")
  if n==0 { precondition(fragment==nil) }
  else {
   let actual=fragment!.components(separatedBy:"<skill>").count-1
   precondition(actual==min(20,n),"metadata budget violation n=\(n) bundled=\(bundled) actual=\(actual)")
   precondition(store.skills.count==n,"disclosure must not delete stored skills")
   if n>20 { precondition(fragment!.contains("more skills not shown")) }
  }
  cases+=1
 }
}
store.skills=[Skill(id:"disabled-1",name:"disabled",description:"test",importSource:.bundled,updatedAt:Date(),useCount:0)]
precondition(store.skillPromptFragment(for:"test")==nil)
print("Skill disclosure regression: \(cases+1) cases passed; real production body, including 128 bundled skills.")
'''
with tempfile.TemporaryDirectory(prefix='minis-skill-regression-') as d:
    path=pathlib.Path(d); f=path/'main.swift'; f.write_text(stub+body+tests,encoding='utf-8')
    exe=path/'skill-tests'; subprocess.run([swift,str(f),'-o',str(exe)],check=True)
    subprocess.run([str(exe)],check=True)
