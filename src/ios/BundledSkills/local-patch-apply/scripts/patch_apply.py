#!/usr/bin/env python3
"""Apply byte patches"""
import subprocess, sys
TOOL = r"C:\Users\Administrator\Desktop\ai2\新破甲\scripts\software_cracker.py"
TARGET = sys.argv[1] if len(sys.argv) > 1 else input("Target binary: ").strip()
print(f"[patch-apply] Interactive patch mode for {TARGET}")
subprocess.run([r"C:\Users\Administrator\AppData\Roaming\uv\python\cpython-3.11-windows-x86_64-none\python.exe", TOOL, "patch", "--target", TARGET, "--offset", "0x0", "--jump-type", "nop"])
