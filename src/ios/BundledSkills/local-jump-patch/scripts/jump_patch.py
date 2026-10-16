#!/usr/bin/env python3
"""Patch conditional jumps via software_cracker.py"""
import subprocess, sys, os
TOOL = r"C:\Users\Administrator\Desktop\ai2\新破甲\scripts\software_cracker.py"
TARGET = sys.argv[1] if len(sys.argv) > 1 else input("Target binary: ").strip()
OFFSET = sys.argv[2] if len(sys.argv) > 2 else input("Patch offset (hex, e.g. 0x1234): ").strip()
JTYPE = sys.argv[3] if len(sys.argv) > 3 else input("Jump type [je->jmp/jne->nop/nop/jmp]: ").strip() or "je->jmp"
print(f"[jump-patch] Patching {TARGET} at {OFFSET} : {JTYPE}")
subprocess.run([r"C:\Users\Administrator\AppData\Roaming\uv\python\cpython-3.11-windows-x86_64-none\python.exe", TOOL, "patch", "--target", TARGET, "--offset", OFFSET, "--jump-type", JTYPE], check=False)
print("  Verify: run patched binary, confirm behavior changed")
