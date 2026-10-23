#!/usr/bin/env python3
"""Verifier parser/unit fixtures; native ldid signing is tested separately."""
import hashlib
import importlib.util
import pathlib
import plistlib
import struct
import tempfile
import unittest

SOURCE = pathlib.Path(__file__).resolve().parents[1] / "src/ios/BuildWorkbench.bundle/macho_signing.py"
SPEC = importlib.util.spec_from_file_location("macho_signing", SOURCE)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def fixture():
    identifier = b"minis.fixture\0"
    xml = plistlib.dumps({"com.minisre.protection.fixture": True})
    xml = struct.pack(">II", 0xFADE7171, len(xml) + 8) + xml
    der = struct.pack(">II", 0xFADE7172, 10) + b"\x30\x00"
    hash_offset = 88 + len(identifier) + 7 * 32
    directory = bytearray(hash_offset + 32)
    struct.pack_into(">IIIIIIIII", directory, 0, 0xFADE0C02, len(directory),
                     0x20400, 2, hash_offset, 88, 7, 1, 4096)
    struct.pack_into("BBBB", directory, 36, 32, 2, 0, 12)
    directory[88:88 + len(identifier)] = identifier
    signature_size = 12 + 3 * 8 + len(directory) + len(xml) + len(der)
    code = bytearray(4096)
    struct.pack_into("<IIIIIIII", code, 0, 0xFEEDFACF, 0x0100000C, 0, 6, 1, 16, 0, 0)
    struct.pack_into("<IIII", code, 32, 0x1D, 16, len(code), signature_size)
    code[128:141] = b"testcode12345"
    directory[hash_offset:hash_offset + 32] = hashlib.sha256(code).digest()
    for slot, blob in ((5, xml), (7, der)):
        directory[hash_offset - slot * 32:hash_offset - (slot - 1) * 32] = hashlib.sha256(blob).digest()
    start = 12 + 3 * 8
    superblob = struct.pack(">III", 0xFADE0CC0, signature_size, 3)
    for slot, blob in ((0, directory), (5, xml), (7, der)):
        superblob += struct.pack(">II", slot, start)
        start += len(blob)
    return bytes(code) + superblob + directory + xml + der


class Tests(unittest.TestCase):
    def test_bytes_code_pages_and_entitlement_hashes(self):
        result = MODULE.verify_macho_code_directory(fixture())
        self.assertTrue(result["codePageHashesVerified"])
        self.assertEqual(result["codeDirectories"][0]["codePages"], 1)
        self.assertEqual(result["codeDirectories"][0]["entitlementSlotsVerified"], [5, 7])
        self.assertTrue(result["entitlements"]["com.minisre.protection.fixture"])
        self.assertFalse(result["appleTrustVerified"])
        self.assertFalse(result["deviceInstallVerified"])

    def test_path_api(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "fixture.dylib"
            path.write_bytes(fixture())
            self.assertTrue(MODULE.verify_macho_code_directory(path)["codePageHashesVerified"])

    def test_changed_code_page_rejected(self):
        data = bytearray(fixture()); data[200] ^= 1
        with self.assertRaisesRegex(ValueError, "code-page hash mismatch"):
            MODULE.verify_macho_code_directory(data)

    def test_changed_entitlement_blob_rejected(self):
        data = bytearray(fixture()); data[-1] ^= 1
        with self.assertRaisesRegex(ValueError, "entitlement hash mismatch"):
            MODULE.verify_macho_code_directory(data)

    def test_unsigned_macho_rejected(self):
        data = bytearray(fixture()); struct.pack_into("<II", data, 16, 0, 0)
        with self.assertRaisesRegex(ValueError, "absent"):
            MODULE.verify_macho_code_directory(data)

    def test_non_macho_rejected(self):
        with self.assertRaisesRegex(ValueError, "Mach-O"):
            MODULE.verify_macho_code_directory(b"#!/bin/sh\nexit 0\n")

    def test_partial_code_coverage_rejected(self):
        data = bytearray(fixture()); struct.pack_into(">I", data, 4096 + 36 + 32, 128)
        with self.assertRaisesRegex(ValueError, "partial signed-code coverage"):
            MODULE.verify_macho_code_directory(data)

    def test_bad_load_command_bounds_rejected(self):
        data = bytearray(fixture()); struct.pack_into("<I", data, 36, 0xFFFFFFFF)
        with self.assertRaisesRegex(ValueError, "load-command size"):
            MODULE.verify_macho_code_directory(data)

    def test_bad_superblob_entry_rejected(self):
        data = bytearray(fixture()); struct.pack_into(">I", data, 4096 + 16, 0xFFFFFFFF)
        with self.assertRaisesRegex(ValueError, "signature slot"):
            MODULE.verify_macho_code_directory(data)


if __name__ == "__main__":
    unittest.main()
