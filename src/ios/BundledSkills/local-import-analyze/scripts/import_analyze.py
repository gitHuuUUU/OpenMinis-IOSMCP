#!/usr/bin/env python3
"""Analyze imports via DIE"""
import subprocess, sys, os
DIE = r"C:\Users\Administrator\Desktop\ai2\新破甲\Tool\die\die.exe"
TARGET = sys.argv[1] if len(sys.argv) > 1 else input("Target binary: ").strip()
print(f"[import-analyze] Opening DIE for: {TARGET}")
if os.path.exists(DIE):
    subprocess.Popen([DIE, TARGET])
    print("  DIE launched — check Import tab for suspicious APIs")
else:
    print(f"  DIE not found at {DIE}")
    # fallback to pe_analyzer
    subprocess.run([r"C:\Users\Administrator\AppData\Roaming\uv\python\cpython-3.11-windows-x86_64-none\python.exe", r"C:\Users\Administrator\Desktop\ai2\新破甲\scripts\pe_analyzer.py", "--file", TARGET], check=False)
