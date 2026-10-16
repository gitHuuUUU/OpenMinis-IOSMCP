#!/usr/bin/env python3
"""Decompile .NET via dnSpy"""
import subprocess, sys, os
DNSPY = r"C:\Users\Administrator\Desktop\ai2\新破甲\Tool\dnspy\dnSpy.exe"
TARGET = sys.argv[1] if len(sys.argv) > 1 else input("Target .NET assembly: ").strip()
print(f"[dn-decompile] dnSpy: {TARGET}")
print("  Steps: expand assembly tree -> view classes -> copy C# source")
if os.path.exists(DNSPY):
    subprocess.Popen([DNSPY, TARGET])
