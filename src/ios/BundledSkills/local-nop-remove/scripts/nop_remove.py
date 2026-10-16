#!/usr/bin/env python3
"""NOP instruction removal via software_cracker.py"""
import subprocess, sys
TOOL = r"C:\Users\Administrator\Desktop\ai2\新破甲\scripts\software_cracker.py"
TARGET = sys.argv[1] if len(sys.argv) > 1 else input("Target binary: ").strip()
OFFSET = sys.argv[2] if len(sys.argv) > 2 else input("Offset (hex): ").strip()
N = sys.argv[3] if len(sys.argv) > 3 else input("Byte count to NOP: ").strip() or "5"
original = "00" * int(N)
patched = "90" * int(N)
print(f"[nop-remove] {N} NOPs @ {OFFSET} in {TARGET}")
subprocess.run([r"C:\Users\Administrator\AppData\Roaming\uv\python\cpython-3.11-windows-x86_64-none\python.exe", TOOL, "patch", "--target", TARGET, "--offset", OFFSET, "--original", original, "--patched", patched])
