#!/usr/bin/env python3
"""Memory breakpoint OEP method via x64dbg"""
import subprocess, sys, os
X64DBG = r"C:\Users\Administrator\Desktop\ai2\新破甲\Tool\x64dbg\release\x64\x64dbg.exe"
TARGET = sys.argv[1] if len(sys.argv) > 1 else input("Target binary: ").strip()
print(f"""[memory-breakpoint] Memory BP OEP for: {TARGET}
Steps in x64dbg:
1. Open {TARGET} -> break at system breakpoint
2. View -> Memory Map (Alt+M)
3. Find .text section (code, executable)
4. Right-click -> Set Memory Breakpoint (Access)
5. F9 run -> stops inside .text section (at OEP or near it)
6. Scylla: File -> Dump Memory
Works when ESP Law fails. Better for: ASProtect, Armadillo
""")
if os.path.exists(X64DBG):
    subprocess.Popen([X64DBG, TARGET])
