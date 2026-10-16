#!/usr/bin/env python3
"""Pointer chain scan via Cheat Engine"""
import subprocess, sys, os
CE = r"C:\Users\Administrator\Desktop\ai2\新破甲\Tool\Cheat Engine\Cheat Engine.exe"
print("[pointer-chain] Cheat Engine Pointer Scanner")
print("  Steps:")
print("  1. Find value address -> Right-click -> Pointer scan")
print("  2. Max depth=5, Max offset=0x2000 -> Save to file")
print("  3. Restart game, find new address")
print("  4. Pointer Scanner -> Rescan -> input new address")
print("  5. Filter results -> output: [[[module+off1]+off2]+off3]")
if os.path.exists(CE):
    subprocess.Popen([CE])
