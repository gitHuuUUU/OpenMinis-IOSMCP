#!/usr/bin/env python3
"""Extract strings from binary via pe_analyzer.py"""
import subprocess, sys, os
TOOL = r"C:\Users\Administrator\Desktop\ai2\新破甲\scripts\pe_analyzer.py"
TARGET = sys.argv[1] if len(sys.argv) > 1 else input("Target binary: ").strip()
PATTERNS = "license|serial|register|key|auth|token|trial|expire|http|api|password|secret|debug|error"
print(f"[string-extract] Target: {TARGET}")
subprocess.run([r"C:\Users\Administrator\AppData\Roaming\uv\python\cpython-3.11-windows-x86_64-none\python.exe", TOOL, "--file", TARGET, "--strings"], check=False)
