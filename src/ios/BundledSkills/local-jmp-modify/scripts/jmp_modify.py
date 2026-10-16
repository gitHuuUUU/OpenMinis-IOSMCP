#!/usr/bin/env python3
"""Modify conditional jumps via software_cracker.py"""
import subprocess, sys
TOOL = r"C:\Users\Administrator\Desktop\ai2\新破甲\scripts\software_cracker.py"
TARGET = sys.argv[1] if len(sys.argv) > 1 else input("Target binary: ").strip()
OFFSET = sys.argv[2] if len(sys.argv) > 2 else input("Offset (hex): ").strip()
JTYPE = input("Type [je->jmp/jne->nop/nop]: ").strip() or "je->jmp"
print(f"[jmp-modify] {JTYPE} @ {OFFSET} in {TARGET}")
subprocess.run([r"C:\Users\Administrator\AppData\Roaming\uv\python\cpython-3.11-windows-x86_64-none\python.exe", TOOL, "patch", "--target", TARGET, "--offset", OFFSET, "--jump-type", JTYPE])
