#!/usr/bin/env python3
"""ESP Law OEP finder via x64dbg"""
import subprocess, sys, os
X64DBG = r"C:\Users\Administrator\Desktop\ai2\新破甲\Tool\x64dbg\release\x64\x64dbg.exe"
TARGET = sys.argv[1] if len(sys.argv) > 1 else input("Target binary: ").strip()
print(f"""[esp-law] ESP Law OEP Location for: {TARGET}
Steps in x64dbg:
1. Open {TARGET}
2. F8 step once -> ESP changes (pushad)
3. Right-click ESP value in register panel -> Follow in Dump
4. Select first 4 bytes -> Hardware Breakpoint (Access) -> DWORD
5. F9 run -> stops at popad
6. F8 trace forward -> look for jmp to far address (the big jump)
7. That jmp lands at OEP (Original Entry Point)
8. Scylla: File -> Dump Memory
Works on: UPX, ASPack, MPRESS, PECompact
""")
if os.path.exists(X64DBG):
    subprocess.Popen([X64DBG, TARGET])
