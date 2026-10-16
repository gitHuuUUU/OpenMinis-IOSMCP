#!/usr/bin/env python3
"""Backup file before modification"""
import shutil, hashlib, sys
TARGET = sys.argv[1] if len(sys.argv) > 1 else input("File to backup: ").strip()
bak = TARGET + ".bak"
shutil.copy2(TARGET, bak)
h1 = hashlib.sha256(open(TARGET,"rb").read()).hexdigest()
h2 = hashlib.sha256(open(bak,"rb").read()).hexdigest()
print(f"[file-backup] {TARGET} -> {bak}")
print(f"  SHA256: {h1[:16]}...")
print(f"  Match: {'OK' if h1==h2 else 'FAIL'}")
