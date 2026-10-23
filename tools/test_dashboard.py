"""Dashboard contracts, protection adapter failures, and production cost policy."""
import argparse, importlib.util, pathlib, shutil, subprocess, tempfile, unittest
from types import SimpleNamespace
from unittest import mock
ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("adapter", ROOT/"src/ios/BuildWorkbench.bundle/minis_build.py")
adapter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(adapter)

class DashboardTests(unittest.TestCase):
    def test_new_sources_registered_once(self):
        project = (ROOT/"src/ios/Minis.xcodeproj/project.pbxproj").read_text(encoding="utf-8")
        for name in ("MinisReDesignSystem.swift", "UsageCostPolicy.swift"):
            self.assertEqual(project.count(f"/* {name} in Sources */"), 2)
            self.assertIn(f"path = {'Views' if 'Design' in name else 'Shared'}/{name};", project)

    def test_real_navigation_and_no_placeholder_price(self):
        ui = (ROOT/"src/ios/Views/MinisReDesignSystem.swift").read_text(encoding="utf-8")
        for token in ("ProviderInstanceDetailView(", "AddProviderView()", "ProviderInstancesView()",
                      "fetchUsageStats()", "ModelsDevAPI.priceCatalog()", "refreshPriceCatalog()",
                      '@AppStorage("minisre.currency")', '@AppStorage("build.protection")',
                      '"protection-status"', "activeChildren(parent:", "canAccessOutsideAppContainer"):
            self.assertIn(token, ui)
        self.assertNotIn("GPT-5.6", ui)
        self.assertNotIn('enabled ? "已启用"', ui)
        self.assertIn("record.hasSnapshot", ui)

    def test_normal_never_needs_protection_compiler(self):
        args=SimpleNamespace(protection="normal")
        self.assertEqual(adapter.protection_flags(args), [])
        self.assertEqual(adapter.protection_status(args)["mode"], "normal")

    def test_flags_whitelist_and_combination(self):
        args=SimpleNamespace(protection="enhanced",protection_passes="sobf,bcf,sobf")
        self.assertEqual(adapter.protection_flags(args),["-mllvm","-bcf","-mllvm","-sobf"])
        for bad in ("", "unknown", "bcf,--output=/tmp/a", "fla;whoami"):
            args.protection_passes=bad
            with self.assertRaises(ValueError):adapter.protection_flags(args)

    def test_missing_compiler_fails_without_fallback(self):
        args=SimpleNamespace(protection="enhanced",protection_passes="bcf",protection_compiler="/missing/ollvm")
        with mock.patch.object(adapter.shutil,"which",return_value=None):
            with self.assertRaisesRegex(RuntimeError,"unavailable"):adapter.protection_status(args)

    def test_packaging_does_not_claim_protected(self):
        with tempfile.TemporaryDirectory() as d:
            args=SimpleNamespace(project=d,output=str(pathlib.Path(d)/"out.ipa"),target="ipa",
                                 remote="",protection="enhanced")
            with self.assertRaisesRegex(RuntimeError,"local C/ObjC"):adapter.build(args)

    def test_failed_probe_never_ready(self):
        args=SimpleNamespace(protection="enhanced",protection_passes="bcf",protection_compiler="clang")
        with mock.patch.object(adapter.shutil,"which",return_value="/clang"), mock.patch.object(adapter.subprocess,"run",return_value=SimpleNamespace(returncode=1,stdout="",stderr="unsupported pass")):
            with self.assertRaisesRegex(RuntimeError,"unsupported pass"):adapter.protection_status(args)

SWIFT_TEST = r'''
import Foundation
@main struct Test {
    static func main() {
        func estimate(_ i: Int, _ o: Int, _ r: Int, _ w: Int,
                      _ ir: Double?, _ or: Double?, _ rr: Double?, _ wr: Double?) -> Double? {
            UsageCostPolicy.estimate(input: i, output: o, read: r, write: w,
                inputRate: ir, outputRate: or, readRate: rr, writeRate: wr)
        }
        precondition(estimate(1_000_000, 2_000_000, 0, 0, 2, 10, nil, nil) == 22)
        precondition(estimate(0, 0, 1_000_000, 1_000_000, nil, nil, 0.2, 1.25) == 1.45)
        precondition(estimate(0, 0, 1, 0, 2, 10, nil, nil) == nil)
        precondition(estimate(1, 0, 0, 0, nil, 10, nil, nil) == nil)
        precondition(estimate(-1, 0, 0, 0, 1, 1, nil, nil) == nil)
        precondition(estimate(1, 0, 0, 0, .infinity, 1, nil, nil) == nil)
        precondition(estimate(1, 0, 0, 0, -1, 1, nil, nil) == nil)
        precondition(estimate(0, 0, 0, 0, nil, nil, nil, nil) == 0)
        precondition(UsageCostPolicy.display(nil, currency:"USD", usdToCNY:0) == "暂无价格")
        precondition(UsageCostPolicy.display(1, currency:"CNY", usdToCNY:0) == "请设置参考汇率")
        precondition(UsageCostPolicy.display(1, currency:"CNY", usdToCNY:7) == "¥7.0000")
        precondition(UsageCostPolicy.display(1, currency:"USD", usdToCNY:0) == "$1.0000")
        print("Production usage policy: 12 checks passed")
    }
}
'''
if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("--require-swift",action="store_true");args=parser.parse_args()
    result=unittest.TextTestRunner().run(unittest.defaultTestLoader.loadTestsFromTestCase(DashboardTests))
    if not result.wasSuccessful():raise SystemExit(1)
    swift=shutil.which("swiftc")
    if not swift:
        if args.require_swift:raise SystemExit("swiftc required")
        print("Production Swift policy NOT RUN on this host")
    else:
        with tempfile.TemporaryDirectory() as d:
            test=pathlib.Path(d)/"test.swift";test.write_text(SWIFT_TEST,encoding="utf-8")
            exe=pathlib.Path(d)/"test"
            subprocess.run([swift,str(ROOT/"src/ios/Shared/UsageCostPolicy.swift"),str(test),"-o",str(exe)],check=True)
            subprocess.run([str(exe)],check=True)
