#!/usr/bin/env python3
"""Memory scan via Cheat Engine"""
import subprocess, sys, os
CE = rr"C:\Users\Administrator\Desktop\ai2\新破甲\Tool\Cheat Engine\Cheat Engine.exe"
VALUE = sys.argv[1] if len(sys.argv) > 1 else input("Value to scan: ").strip()
DTYPE = input("Data type [4=4Byte, f=Float, 8=8Byte, d=Double, b=Byte]: ").strip() or "4"
print(f"[exact-scan] Cheat Engine | Value={VALUE} | Type={DTYPE}")
print("  Steps: Open Process -> First Scan({VALUE}) -> change in game -> Next Scan")
if os.path.exists(CE):
    subprocess.Popen([CE])
else:
    print(f"  Fallback: C:\Users\Administrator\AppData\Roaming\uv\python\cpython-3.11-windows-x86_64-none\python.exe C:\Users\Administrator\Desktop\ai2\新破甲\scripts\\game_hacker.py --process game.exe --scan --value {VALUE}")
