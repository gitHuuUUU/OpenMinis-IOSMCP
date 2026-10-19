"""Execute the production bounded excerpt reader; not a device benchmark."""
import pathlib, shutil, subprocess, sys, tempfile
root = pathlib.Path(__file__).resolve().parents[1]
source = (root/'src/ios/Agent/Session/SkillStore.swift').read_text(encoding='utf8')
body = source.split('    func readSkillExcerpt(',1)[1].split('    /// Collect relative',1)[0]
body = '    func readSkillExcerpt(' + body
assert 'read(upToCount: count * 4 + 4)' in body
assert 'String(contentsOf:' not in body
swift = shutil.which('swiftc')
if not swift:
    if '--require-swift' in sys.argv: raise SystemExit('swiftc required')
    print('Bounded excerpt source checks passed; Swift runtime NOT RUN')
    raise SystemExit(0)
program = r'''import Foundation
class Reader {
 let skillsDir: URL
 init(_ url: URL) { skillsDir = url }
''' + body + r'''}
let root = URL(fileURLWithPath: CommandLine.arguments[1])
let folder = root.appendingPathComponent("example")
try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
let reader = Reader(root)
var checks = 0
for unit in ["a", "中", "😀", "e\u{301}"] {
 for size in [0, 1, 7999, 8000, 8001, 50000] {
  let text = String(repeating: unit, count: size)
  try text.write(to: folder.appendingPathComponent("SKILL.md"), atomically: true, encoding: .utf8)
  let result = reader.readSkillExcerpt("example", maxCharacters: 8000)!
  precondition(result.text == String(text.prefix(8000)))
  precondition(result.truncated == (size > 8000))
  checks += 1
 }
}
precondition(reader.readSkillExcerpt("missing", maxCharacters: 8000) == nil)
precondition(reader.readSkillExcerpt("example", maxCharacters: 0) == nil)
print("Bounded production excerpt: \(checks + 2) checks passed")
'''
with tempfile.TemporaryDirectory() as temp:
    path = pathlib.Path(temp)
    script = path/'main.swift'; script.write_text(program, encoding='utf8')
    exe = path/'tests'
    subprocess.run([swift, str(script), '-o', str(exe)], check=True)
    subprocess.run([str(exe), temp], check=True)
