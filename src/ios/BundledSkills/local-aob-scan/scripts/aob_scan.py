#!/usr/bin/env python3
"""AOB pattern scan via game_hacker.py"""
import subprocess, sys, os
TOOL = r"C:\Users\Administrator\Desktop\ai2\新破甲\scripts\game_hacker.py"
PATTERN = sys.argv[1] if len(sys.argv) > 1 else input("AOB pattern (e.g. '48 8B 05 ?? ?? ?? ??'): ").strip()
MODULE = sys.argv[2] if len(sys.argv) > 2 else input("Module name [default=game.exe]: ").strip() or "game.exe"
print(f"[aob-scan] Pattern: {PATTERN} | Module: {MODULE}")
subprocess.run([r"C:\Users\Administrator\AppData\Roaming\uv\python\cpython-3.11-windows-x86_64-none\python.exe", TOOL, "--process", MODULE, "--pattern", PATTERN], check=False)
