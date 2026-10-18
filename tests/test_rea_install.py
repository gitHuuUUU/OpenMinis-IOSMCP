import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "src/ios/default_mount/usr/local/lib/minis-reverse-tools/rea_install.py"
)
SPEC = importlib.util.spec_from_file_location("rea_install", SCRIPT)
rea = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(rea)


class REAInstallTests(unittest.TestCase):
    def test_supported_node_versions(self):
        for major, minor in ((22, 19), (22, 23), (24, 11), (26, 0), (30, 1)):
            with self.subTest(major=major, minor=minor):
                self.assertTrue(rea._node_version_supported(major, minor))
        for major, minor in ((20, 99), (22, 18), (23, 99), (24, 10), (25, 99)):
            with self.subTest(major=major, minor=minor):
                self.assertFalse(rea._node_version_supported(major, minor))

    def test_lockfile_requires_exact_declared_and_installed_version(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "package.json").write_text(json.dumps({"dependencies": {"rea-agents": "6.4.0"}}))
            (root / "package-lock.json").write_text(json.dumps({"packages": {
                "": {"dependencies": {"rea-agents": "6.4.0"}},
                "node_modules/rea-agents": {"version": "6.4.0"},
            }}))
            self.assertTrue(rea._package_lock_is_compatible(root))
            lock = json.loads((root / "package-lock.json").read_text())
            lock["packages"]["node_modules/rea-agents"]["version"] = "6.4.1"
            (root / "package-lock.json").write_text(json.dumps(lock))
            self.assertFalse(rea._package_lock_is_compatible(root))

    def test_two_rpc_responses_share_one_stdout_reader_queue(self):
        class FakeProcess:
            stdout = io.StringIO(
                '{"jsonrpc":"2.0","id":1,"result":{"ok":true}}\n'
                '{"jsonrpc":"2.0","id":2,"result":{"tools":[]}}\n'
            )

            @staticmethod
            def poll():
                return None

        process = FakeProcess()
        lines = rea._start_stdout_reader(process)
        first = rea._read_json_id(process, lines, 1, 1)
        second = rea._read_json_id(process, lines, 2, 1)
        self.assertTrue(first["result"]["ok"])
        self.assertEqual(second["result"]["tools"], [])


if __name__ == "__main__":
    unittest.main()
