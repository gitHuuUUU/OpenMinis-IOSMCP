#!/usr/bin/env python3
"""Cross-reference analysis via IDA Pro"""
import subprocess, sys, os
IDA = r"C:\Users\Administrator\Desktop\ai2\新破甲\Tool\IDA Professional 9.2\ida64.exe"
TARGET = sys.argv[1] if len(sys.argv) > 1 else input("Target binary: ").strip()
print(f"[xref-trace] IDA Pro: {TARGET}")
print("  Steps: View -> Open Subviews -> Strings -> find target -> Ctrl+X (xrefs)")
if os.path.exists(IDA):
    subprocess.Popen([IDA, TARGET])
