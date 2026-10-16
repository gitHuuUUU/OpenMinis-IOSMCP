#!/usr/bin/env python3
"""Rollback from backup"""
import shutil, hashlib, sys
TARGET = sys.argv[1] if len(sys.argv) > 1 else input("File to restore: ").strip()
bak = TARGET + ".bak"
if not __import__("os").path.exists(bak):
    print(f"[-] No backup found: {bak}")
    sys.exit(1)
shutil.copy2(bak, TARGET)
h1 = hashlib.sha256(open(TARGET,"rb").read()).hexdigest()
h2 = hashlib.sha256(open(bak,"rb").read()).hexdigest()
print(f"[patch-rollback] Restored: {TARGET}")
print(f"  SHA256: {h1[:16]}... | Match: {'OK' if h1==h2 else 'FAIL'}")
