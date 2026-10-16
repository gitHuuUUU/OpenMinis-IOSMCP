#!/usr/bin/env python3
"""Execution hook via game_hacker.py DLL injection"""
import subprocess, sys, os
TOOL = r"C:\Users\Administrator\Desktop\ai2\新破甲\scripts\game_hacker.py"
DLL = sys.argv[1] if len(sys.argv) > 1 else input("DLL path: ").strip()
PID = sys.argv[2] if len(sys.argv) > 2 else input("Target PID: ").strip()
print(f"[exec-hook] Injecting {DLL} into PID={PID}")
subprocess.run([r"C:\Users\Administrator\AppData\Roaming\uv\python\cpython-3.11-windows-x86_64-none\python.exe", TOOL, "--pid", PID, "--inject", DLL])
