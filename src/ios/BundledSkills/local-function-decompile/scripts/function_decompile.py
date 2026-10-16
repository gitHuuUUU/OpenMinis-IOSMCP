#!/usr/bin/env python3
"""Decompile binary via IDA Pro or Ghidra"""
import subprocess, sys, os
IDA = r"C:\Users\Administrator\Desktop\ai2\新破甲\Tool\IDA Professional 9.2\ida64.exe"
GHIDRA = r"C:\Users\Administrator\Desktop\ai2\新破甲\Tool\ghidra\ghidra_11.2.1_PUBLIC\ghidraRun.bat"
TARGET = sys.argv[1] if len(sys.argv) > 1 else input("Target binary: ").strip()
if os.path.exists(IDA):
    print(f"[function-decompile] Launching IDA Pro for: {TARGET}")
    subprocess.Popen([IDA, TARGET])
elif os.path.exists(GHIDRA):
    print(f"[function-decompile] Launching Ghidra for: {TARGET}")
    subprocess.Popen([GHIDRA], shell=True)
else:
    print("[-] No disassembler found")
