#!/usr/bin/env python3
"""Unknown value scan via Cheat Engine"""
import subprocess, sys, os
CE = r"C:\Users\Administrator\Desktop\ai2\新破甲\Tool\Cheat Engine\Cheat Engine.exe"
DTYPE = input("Data type [4=4Byte, f=Float]: ").strip() or "f"
print(f"[unknown-scan] Cheat Engine | Unknown initial | Type={DTYPE}")
print("  Steps: Open Process -> Unknown initial value -> First Scan")
print("  -> change value in game -> filter (Increased/Decreased/Changed)")
if os.path.exists(CE):
    subprocess.Popen([CE])
