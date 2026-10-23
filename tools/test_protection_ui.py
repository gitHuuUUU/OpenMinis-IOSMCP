"""Compact protection UI contracts and the actual production Swift selection policy.

--require-swift is used by macOS CI. Windows still runs source wiring checks,
but explicitly reports that it has not executed the Swift policy.
"""
import argparse
import pathlib
import shutil
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src/ios/Views/MinisReDesignSystem.swift"
SWIFT = SOURCE.read_text(encoding="utf-8")
POLICY = SWIFT.split("enum CompilationProtectionPolicy {", 1)[1].split("struct CompilationProtectionView:", 1)[0]
POLICY = "import Foundation\nenum CompilationProtectionPolicy {" + POLICY
VIEW = SWIFT.split("struct CompilationProtectionView:", 1)[1].split("struct MinisReAgentStrip:", 1)[0]


class ProtectionUIContracts(unittest.TestCase):
    def test_persistence_and_existing_backend_keys(self):
        for key in ("build.protection", "build.protectionCompiler", "build.protectionPasses", "build.protectionSelection"):
            self.assertIn(f'@AppStorage("{key}")', VIEW)
        self.assertIn('private var selection = "combined"', VIEW)
        self.assertIn('"single"', VIEW)
        self.assertIn('"combined"', VIEW)

    def test_all_five_real_capability_choices(self):
        for capability in ("bcf", "indcall", "indgv", "sobf", "fla"):
            self.assertEqual(VIEW.count(f'Option(id: "{capability}"'), 1)
        self.assertIn("CompilationProtectionPolicy.toggled(item.id", VIEW)
        self.assertIn('.accessibilityValue(selected(item.id)', VIEW)
        self.assertNotIn("本内置引擎未提供此项", VIEW)
        self.assertNotIn('contains(item.0)', VIEW)
        self.assertNotIn("normalizeBuiltinPasses", VIEW)

    def test_component_entry_uses_actual_runtime(self):
        self.assertIn('RuntimeComponentView(name: "OLLVM")', VIEW)
        self.assertIn('model.componentStatus["OLLVM"]', VIEW)
        self.assertIn('report["installed"] as? Bool', VIEW)
        self.assertIn('report["installedBytes"] as? NSNumber', VIEW)
        self.assertIn('ByteCountFormatter.string(fromByteCount: bytes', VIEW)
        self.assertIn('report["availablePasses"] as? [String]', VIEW)
        self.assertIn('report["acceptedPasses"] as? [String]', VIEW)
        self.assertNotIn("92.2", VIEW)
        self.assertNotIn("已就绪", VIEW)

    def test_empty_selection_guards_probe_and_is_visible(self):
        self.assertIn("if let error = validationError", VIEW)
        self.assertIn('guard !isBusy, mode == "enhanced", validationError == nil else { return }', VIEW)
        self.assertIn("validationError != nil", VIEW)
        self.assertIn('"请至少选择一项保护能力；未选择时不能执行强化编译"', POLICY)

    def test_compact_log_sheet_not_giant_inline_card(self):
        body, helpers = VIEW.split("private func smallIcon", 1)
        self.assertIn(".sheet(isPresented: $showReport) { reportSheet }", body)
        self.assertNotIn("Text(result)", body)
        self.assertIn("Text(result)", helpers)
        self.assertIn("UIPasteboard.general.string = result", helpers)
        self.assertIn(".frame(width: 24, height: 24)", helpers)
        self.assertNotIn(".largeTitle", VIEW)
        self.assertNotIn(".title2", VIEW)
        self.assertIn('DisclosureGroup("高级编译器设置")', VIEW)

    def test_no_auto_probe_on_appear_and_stale_success_invalidation(self):
        self.assertIn(".onAppear { normalizeSelection() }", VIEW)
        self.assertNotIn(".task", VIEW)
        self.assertIn('.onChange(of: passes) { _ in invalidateProbe() }', VIEW)
        self.assertIn("let startingCompiler = compiler, startingPasses = passes, startingSelection = selection", VIEW)
        self.assertIn("compiler == startingCompiler, passes == startingPasses", VIEW)
        self.assertIn("acceptedPasses == expected", VIEW)
        self.assertIn("probePassed = false; checked = true", VIEW)


SWIFT_TEST = r'''
import Foundation
@main struct ProtectionPolicyTests {
    static func main() {
        var count = 0
        func check(_ condition: @autoclosure () -> Bool) { precondition(condition()); count += 1 }
        let p = CompilationProtectionPolicy.self
        check(p.order == ["bcf", "indcall", "indgv", "sobf", "fla"])
        check(p.normalized("sobf,bcf,sobf,indcall,indgv,fla", selection: "combined") == "bcf,indcall,indgv,sobf,fla")
        check(p.normalized("sobf,bcf,sobf", selection: "single") == "bcf")
        check(p.normalized(" indgv , sobf ", selection: "combined") == "indgv,sobf")
        check(p.normalized("unknown", selection: "combined") == "")
        check(p.normalized("", selection: "single") == "")
        check(p.toggled("indcall", in: "bcf,sobf", selection: "combined") == "bcf,indcall,sobf")
        check(p.toggled("bcf", in: "bcf,sobf", selection: "combined") == "sobf")
        check(p.toggled("indgv", in: "bcf", selection: "single") == "indgv")
        check(p.toggled("indgv", in: "indgv", selection: "single") == "")
        check(p.toggled("unknown", in: "bcf,sobf", selection: "combined") == "bcf,sobf")
        check(p.validationError(mode: "normal", passes: "", selection: "combined") == nil)
        check(p.validationError(mode: "enhanced", passes: "", selection: "combined") != nil)
        check(p.validationError(mode: "enhanced", passes: "bcf,indgv", selection: "single") != nil)
        check(p.validationError(mode: "enhanced", passes: "indgv", selection: "single") == nil)
        check(p.validationError(mode: "enhanced", passes: "bcf,indcall,indgv,sobf,fla", selection: "combined") == nil)
        check(p.validationError(mode: "enhanced", passes: "unknown", selection: "combined") != nil)
        check(p.validationError(mode: "enhanced", passes: "bcf", selection: "invalid") != nil)
        let raw = #"""
stage: installing
{"installed":true,"passes":["bcf","indcall","indgv","sobf","fla"],"installedBytes":98765432}
{
  "mode":"enhanced",
  "acceptedPasses":["indcall","indgv"],
  "passEvidence":{"indgv":{"changed":true}},
  "status":"a } and { in quoted string with escaped \"quote\""
}
"""#
        let reports = p.reports(in: raw)
        check(reports.count == 2)
        check(reports[0]["installed"] as? Bool == true)
        check((reports[0]["installedBytes"] as? NSNumber)?.int64Value == 98765432)
        check(reports[1]["acceptedPasses"] as? [String] == ["indcall", "indgv"])
        check(reports[1]["passEvidence"] is [String: Any])
        check(p.reports(in: "no report, even if string says ready").isEmpty)
        check(p.reports(in: "{broken}\n{\"installed\":false}").count == 1)
        check(p.reports(in: "{\"installed\":true").isEmpty)
        for capability in p.order {
            check(p.toggled(capability, in: "", selection: "single") == capability)
            check(p.toggled(capability, in: "bcf,indcall,indgv,sobf,fla", selection: "single").split(separator: ",").count <= 1)
        }
        print("Production compilation protection Swift policy: \(count) checks passed")
    }
}
'''


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--require-swift", action="store_true")
    args = parser.parse_args()
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(ProtectionUIContracts)
    if not unittest.TextTestRunner().run(suite).wasSuccessful():
        raise SystemExit(1)
    swift = shutil.which("swiftc")
    if not swift:
        if args.require_swift:
            raise SystemExit("swiftc required for production policy regression")
        print("Production Swift protection policy NOT RUN: swiftc unavailable on this host")
        return
    with tempfile.TemporaryDirectory() as directory:
        folder = pathlib.Path(directory)
        policy = folder / "policy.swift"
        test = folder / "test.swift"
        binary = folder / "protection-ui-test"
        policy.write_text(POLICY, encoding="utf-8")
        test.write_text(SWIFT_TEST, encoding="utf-8")
        subprocess.run([swift, str(policy), str(test), "-o", str(binary)], check=True)
        subprocess.run([str(binary)], check=True)


if __name__ == "__main__":
    main()
