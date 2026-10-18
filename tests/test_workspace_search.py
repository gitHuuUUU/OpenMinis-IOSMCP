import base64
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "src/ios/default_mount/usr/local/bin/minis-workspace-search"


def run_search(**request):
    arg = base64.b64encode(json.dumps(request).encode()).decode()
    process = subprocess.run([sys.executable, str(SCRIPT), arg], capture_output=True, text=True, timeout=10)
    assert process.returncode == 0, process.stderr
    return json.loads(process.stdout)


class WorkspaceSearchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "workspace"
        self.root.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def test_unicode_content_and_paging(self):
        for i in range(3):
            (self.root / f"文件{i}.swift").write_text("let 文本 = \"你好世界\"\n", encoding="utf-8")
        first = run_search(root=str(self.root), query="你好", mode="content", glob="*.swift", limit=2)
        self.assertEqual(first["status"], "ok")
        self.assertEqual(len(first["results"]), 2)
        self.assertEqual(first["results"][0]["line"], 1)
        self.assertTrue(first["has_more"])
        second = run_search(root=str(self.root), query="你好", mode="content", glob="*.swift", offset=first["next_offset"], limit=2)
        self.assertEqual(len(second["results"]), 1)
        self.assertFalse(second["has_more"])

    def test_symlink_escape_binary_and_dependencies(self):
        outside = Path(self.tmp.name) / "outside.txt"
        outside.write_text("secret marker", encoding="utf-8")
        try:
            (self.root / "escape.txt").symlink_to(outside)
            (self.root / "escape-dir").symlink_to(outside.parent, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks unavailable")
        (self.root / "binary.txt").write_bytes(b"secret\0 marker")
        deps = self.root / "node_modules"
        deps.mkdir()
        (deps / "dep.txt").write_text("secret marker")
        r = run_search(root=str(self.root), query="secret", mode="content")
        self.assertEqual(r["results"], [])
        self.assertEqual(r["stats"]["skipped_binary"], 1)
        r2 = run_search(root=str(self.root), query="secret", mode="content", include_ignored=True)
        self.assertEqual([x["relative_path"] for x in r2["results"]], ["node_modules/dep.txt"])

    def test_name_regex_limits_and_unavailable(self):
        (self.root / "Hello.swift").write_text("line")
        (self.root / "Other.swift").write_text("line")
        names = run_search(root=str(self.root), query="hello", mode="name", glob="*.swift")
        self.assertEqual(len(names["results"]), 1)
        self.assertEqual(names["results"][0]["relative_path"], "Hello.swift")
        invalid = run_search(root=str(self.root), query="[", regex=True)
        self.assertEqual(invalid["status"], "error")
        limited = run_search(root=str(self.root), query="swift", mode="name", max_files=1)
        self.assertEqual(limited["status"], "partial")
        self.assertEqual(limited["stop_reason"], "max_files")
        unavailable = run_search(root=str(self.root / "missing"), query="x")
        self.assertEqual(unavailable["status"], "unavailable")

    def test_content_file_byte_bound_and_explicit_encoding(self):
        (self.root / "large.txt").write_text("needle " * 500)
        (self.root / "utf16.txt").write_bytes("你好\n".encode("utf-16-le"))
        bounded = run_search(root=str(self.root), query="needle", mode="content", max_file_bytes=1024)
        self.assertEqual(bounded["results"], [])
        self.assertEqual(bounded["stats"]["skipped_large"], 1)
        utf16 = run_search(root=str(self.root), query="你好", mode="content", encoding="utf-16-le", glob="utf16.txt")
        self.assertEqual(len(utf16["results"]), 1)
        self.assertEqual(utf16["results"][0]["line"], 1)


if __name__ == "__main__":
    unittest.main()
