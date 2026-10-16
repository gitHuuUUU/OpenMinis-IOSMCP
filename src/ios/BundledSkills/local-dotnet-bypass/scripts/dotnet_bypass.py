#!/usr/bin/env python3
"""Bypass .NET auth via dnSpy"""
import subprocess, sys, os
DNSPY = r"C:\Users\Administrator\Desktop\ai2\新破甲\Tool\dnspy\dnSpy.exe"
TARGET = sys.argv[1] if len(sys.argv) > 1 else input("Target .NET assembly: ").strip()
print(f"[dotnet-bypass] dnSpy: {TARGET}")
print("  Steps in dnSpy:")
print("  1. Find class: LicenseManager / Registration / Auth / Validate")
print("  2. Right-click method -> Edit Method (IL)")
print("  3. Common patches: ldc.i4.0->ldc.i4.1, brfalse->nop, call->nop")
print("  4. File -> Save Module -> overwrite original")
if os.path.exists(DNSPY):
    subprocess.Popen([DNSPY, TARGET])
