import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock


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
            lock = json.loads((root / "package-lock.json").read_text())
            lock["lockfileVersion"] = 3
            (root / "package-lock.json").write_text(json.dumps(lock))
            self.assertTrue(rea._package_lock_is_compatible(root))
            lock = json.loads((root / "package-lock.json").read_text())
            lock["packages"]["node_modules/rea-agents"]["version"] = "6.4.1"
            (root / "package-lock.json").write_text(json.dumps(lock))
            self.assertFalse(rea._package_lock_is_compatible(root))

    def test_package_lock_rejects_unsupported_lock_format(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "package.json").write_text(json.dumps({"dependencies": {"rea-agents": "6.4.0"}}))
            (root / "package-lock.json").write_text(json.dumps({
                "lockfileVersion": 1,
                "": {"dependencies": {"rea-agents": "6.4.0"}},
                "packages": {"": {"dependencies": {"rea-agents": "6.4.0"}},
                             "node_modules/rea-agents": {"version": "6.4.0"}},
            }))
            self.assertFalse(rea._package_lock_is_compatible(root))

    def test_adaptive_cli_timeout_gives_aarch64_and_large_bundle_grace(self):
        with tempfile.TemporaryDirectory() as temp:
            package = Path(temp) / "rea-agents"
            dist = package / "dist"
            dist.mkdir(parents=True)
            entry = package / "scripts" / "rea.mjs"
            entry.parent.mkdir()
            entry.touch()
            (dist / "main.js").write_bytes(b"0" * (10 * 1024 * 1024))
            with mock.patch.object(rea.platform, "machine", return_value="aarch64"):
                self.assertEqual(rea._adaptive_cli_timeout(entry), 210)

    def test_doctor_cache_is_atomic_readable_and_version_bound(self):
        with tempfile.TemporaryDirectory() as temp:
            prefix = Path(temp)
            entry = prefix / "node_modules/rea-agents/scripts/rea.mjs"
            entry.parent.mkdir(parents=True)
            entry.touch()
            cache_path = rea._doctor_cache_path(entry)
            status = {"completed": True, "healthy": False,
                      "backendStatus": "incomplete_or_unavailable"}
            fingerprint = {
                "nodeVersion": "22.23.2",
                "entrySha256": "entry-hash",
                "packageLockSha256": "lock-hash",
            }
            rea._atomic_json(cache_path, {
                "reaVersion": rea.REA_VERSION,
                **fingerprint,
                "deep": False,
                "checkedAt": __import__("time").time(),
                "doctor": status,
            })
            self.assertEqual(rea._read_doctor_cache(cache_path, fingerprint, False), status)
            self.assertIsNone(rea._read_doctor_cache(cache_path, {**fingerprint, "nodeVersion": "22.23.3"}, False))
            self.assertIsNone(rea._read_doctor_cache(cache_path, fingerprint, True))

    def test_complete_validation_cache_is_fingerprint_bound_and_non_live(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            package = root / "node_modules/rea-agents"
            entry = package / "scripts/rea.mjs"
            entry.parent.mkdir(parents=True)
            (root / "package.json").write_text(json.dumps({
                "dependencies": {"rea-agents": "6.4.0"},
            }))
            (root / "package-lock.json").write_text(json.dumps({
                "lockfileVersion": 3,
                "packages": {
                    "": {"dependencies": {"rea-agents": "6.4.0"}},
                    "node_modules/rea-agents": {"version": "6.4.0"},
                },
            }))
            (package / "package.json").write_text(json.dumps({"version": "6.4.0"}))
            entry.write_text("// tested entry\n")
            fingerprint = rea._package_fingerprint(root, entry, "22.23.2")
            mcp = {"initialize": True, "toolsList": True, "toolCount": 170,
                   "protocolVersion": rea.MCP_PROTOCOL_VERSION}
            doctor = {"completed": True, "healthy": False,
                      "backendStatus": "incomplete_or_unavailable"}
            rea._write_validation_cache(root, fingerprint, mcp, doctor)
            cached = rea._read_validation_cache(root, entry, fingerprint)
            self.assertIsNotNone(cached)
            self.assertEqual(cached["mcp"]["toolCount"], 170)
            self.assertEqual(cached["packageLockSha256"], fingerprint["packageLockSha256"])
            self.assertFalse(cached.get("live", False))
            entry.write_text("// changed after validation\n")
            changed = rea._package_fingerprint(root, entry, "22.23.2")
            self.assertIsNone(rea._read_validation_cache(root, entry, changed))

    def test_diagnose_cache_is_explicitly_last_verified_not_live_ready(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            package = root / "node_modules/rea-agents"
            entry = package / "scripts/rea.mjs"
            entry.parent.mkdir(parents=True)
            (root / "package.json").write_text(json.dumps({
                "dependencies": {"rea-agents": "6.4.0"},
            }))
            (root / "package-lock.json").write_text(json.dumps({
                "lockfileVersion": 3,
                "packages": {
                    "": {"dependencies": {"rea-agents": "6.4.0"}},
                    "node_modules/rea-agents": {"version": "6.4.0"},
                },
            }))
            (package / "package.json").write_text(json.dumps({"version": "6.4.0"}))
            entry.write_text("// verified entry\n")
            fp = rea._package_fingerprint(root, entry, "22.23.2")
            rea._write_validation_cache(root, fp,
                {"initialize": True, "toolsList": True, "toolCount": 170},
                {"completed": True, "healthy": False,
                 "backendStatus": "incomplete_or_unavailable"})
            with mock.patch.object(rea, "PREFIX", root), \
                 mock.patch.object(rea, "_node_and_npm", return_value=("node", "npm", "22.23.2")), \
                 mock.patch.object(rea, "_version", side_effect=AssertionError("must not launch live check")), \
                 mock.patch.object(rea, "_mcp_probe", side_effect=AssertionError("must not launch live check")):
                status = rea.diagnose()
            self.assertEqual(status["status"], "last_verified")
            self.assertFalse(status["verification"]["live"])
            self.assertTrue(status["verification"]["cached"])
            self.assertFalse(status["registrationReady"])

    def test_prepared_stage_is_reusable_after_cli_timeout(self):
        with tempfile.TemporaryDirectory() as temp:
            stage = Path(temp) / ".minis-rea.stage"
            package = stage / "node_modules/rea-agents"
            entry = package / "scripts/rea.mjs"
            entry.parent.mkdir(parents=True)
            (stage / "package.json").write_text(json.dumps({
                "dependencies": {"rea-agents": "6.4.0"},
            }))
            (stage / "package-lock.json").write_text(json.dumps({
                "lockfileVersion": 3,
                "packages": {
                    "": {"dependencies": {"rea-agents": "6.4.0"}},
                    "node_modules/rea-agents": {"version": "6.4.0"},
                },
            }))
            (package / "package.json").write_text(json.dumps({"version": "6.4.0"}))
            entry.write_text("// installed CLI entrypoint\n")
            rea._write_stage_marker(stage, "prepared")
            self.assertTrue(rea._staged_package_is_ready(stage))
            rea._write_stage_marker(stage, "preparing")
            self.assertFalse(rea._staged_package_is_ready(stage))

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
