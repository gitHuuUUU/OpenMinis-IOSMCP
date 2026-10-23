#!/usr/bin/env python3
"""Read-only thin Mach-O CodeDirectory page-hash verification.

This checks embedded code-page/entitlement hashes, NOT Apple certificate trust,
provisioning, TrollStore installation, or acceptance by an iPhone kernel.
"""
import hashlib
import json
import pathlib
import plistlib
import struct


def verify_macho_code_directory(data_or_path):
    if isinstance(data_or_path, (bytes, bytearray, memoryview)):
        path = None
        raw = bytes(data_or_path)
    else:
        path = pathlib.Path(data_or_path)
        raw = path.read_bytes()
    if len(raw) < 32 or raw[:4] != bytes.fromhex("cffaedfe"):
        raise ValueError("Expected a thin little-endian Mach-O 64-bit file")
    ncmds, sizeofcmds = struct.unpack_from("<II", raw, 16)
    end = 32 + sizeofcmds
    if end > len(raw) or ncmds > sizeofcmds // 8:
        raise ValueError("Invalid Mach-O load-command bounds")
    offset = 32
    signature = None
    for _ in range(ncmds):
        if offset + 8 > end:
            raise ValueError("Truncated load command")
        command, size = struct.unpack_from("<II", raw, offset)
        if size < 8 or offset + size > end:
            raise ValueError("Invalid load-command size")
        if command == 0x1D:
            if signature is not None or size < 16:
                raise ValueError("Invalid or duplicate LC_CODE_SIGNATURE")
            signature = struct.unpack_from("<II", raw, offset + 8)
        offset += size
    if signature is None:
        raise ValueError("LC_CODE_SIGNATURE is absent")
    signature_offset, signature_size = signature
    if signature_offset < end or signature_offset + signature_size > len(raw):
        raise ValueError("Code-signature data is outside the file")
    superblob = raw[signature_offset:signature_offset + signature_size]
    if len(superblob) < 12:
        raise ValueError("Truncated signature superblob")
    magic, length, count = struct.unpack_from(">III", superblob)
    if magic != 0xFADE0CC0 or not 12 <= length <= len(superblob) or count > (length - 12) // 8:
        raise ValueError("Invalid signature superblob")
    entries = {}
    for index in range(count):
        slot, start = struct.unpack_from(">II", superblob, 12 + index * 8)
        if slot in entries or start < 12 + 8 * count or start + 8 > length:
            raise ValueError("Invalid signature slot")
        blob_magic, blob_length = struct.unpack_from(">II", superblob, start)
        if blob_length < 8 or start + blob_length > length:
            raise ValueError("Invalid embedded signature blob")
        entries[slot] = (blob_magic, superblob[start:start + blob_length])
    if 0 not in entries or entries[0][0] != 0xFADE0C02:
        raise ValueError("Primary CodeDirectory is absent")
    directories = []
    for slot, (blob_magic, directory) in entries.items():
        if slot != 0 and not 0x1000 <= slot <= 0x1005:
            continue
        if blob_magic != 0xFADE0C02 or len(directory) < 44:
            raise ValueError("Invalid CodeDirectory")
        version, flags, hashes, identifier, special_count, code_count, code_limit = struct.unpack_from(
            ">IIIIIII", directory, 8)
        hash_size, hash_type, _platform, page_shift = struct.unpack_from("BBBB", directory, 36)
        algorithms = {1: hashlib.sha1, 2: hashlib.sha256, 3: hashlib.sha256, 4: hashlib.sha384}
        if hash_type not in algorithms or not 1 <= hash_size <= algorithms[hash_type]().digest_size:
            raise ValueError("Unsupported CodeDirectory hash algorithm or size")
        if version >= 0x20100 and (len(directory) < 48 or struct.unpack_from(">I", directory, 44)[0]):
            raise ValueError("Scatter CodeDirectories are not supported by this verifier")
        if version >= 0x20300 and code_limit == 0xFFFFFFFF:
            if len(directory) < 64:
                raise ValueError("Truncated CodeDirectory codeLimit64")
            code_limit = struct.unpack_from(">Q", directory, 56)[0]
        if code_limit != signature_offset or page_shift > 30:
            raise ValueError("Invalid or partial signed-code coverage or page size")
        page_size = (1 << page_shift) if page_shift else code_limit
        expected_count = (code_limit + page_size - 1) // page_size if page_size else 0
        if code_count != expected_count or hashes < special_count * hash_size or hashes + code_count * hash_size > len(directory):
            raise ValueError("Invalid CodeDirectory page-hash bounds")
        digest = algorithms[hash_type]
        for page in range(code_count):
            wanted = directory[hashes + page * hash_size:hashes + (page + 1) * hash_size]
            actual = digest(raw[page * page_size:min((page + 1) * page_size, code_limit)]).digest()[:hash_size]
            if actual != wanted:
                raise ValueError("CodeDirectory code-page hash mismatch at page " + str(page))
        checked_special = []
        for special in (5, 7):
            if special not in entries:
                continue
            if special > special_count:
                raise ValueError("Entitlements blob is not covered by CodeDirectory")
            wanted = directory[hashes - special * hash_size:hashes - (special - 1) * hash_size]
            actual = digest(entries[special][1]).digest()[:hash_size]
            if actual != wanted:
                raise ValueError("CodeDirectory entitlement hash mismatch")
            checked_special.append(special)
        if not 0 <= identifier < len(directory):
            raise ValueError("Invalid CodeDirectory identifier")
        identifier_end = directory.find(b"\0", identifier)
        if identifier_end < 0:
            raise ValueError("Unterminated CodeDirectory identifier")
        directories.append({"slot": slot, "version": hex(version), "flags": flags,
                            "identifier": directory[identifier:identifier_end].decode("utf-8", "replace"),
                            "hashType": hash_type, "hashSize": hash_size, "codePages": code_count,
                            "codeLimit": code_limit, "pageSize": page_size,
                            "codePageHashesVerified": True, "entitlementSlotsVerified": checked_special,
                            "cdhash": digest(directory).digest()[:20].hex()})
    entitlements = None
    if 5 in entries:
        magic, xml = entries[5]
        if magic != 0xFADE7171:
            raise ValueError("Unexpected entitlement blob format")
        entitlements = plistlib.loads(xml[8:])
    return {"path": str(path) if path is not None else "<memory>", "sha256": hashlib.sha256(raw).hexdigest(),
            "codePageHashesVerified": True, "codeDirectories": directories,
            "entitlements": entitlements, "appleTrustVerified": False,
            "deviceInstallVerified": False}

