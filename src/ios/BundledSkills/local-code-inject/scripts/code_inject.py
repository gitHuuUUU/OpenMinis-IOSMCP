#!/usr/bin/env python3
"""Code injection via Cheat Engine Auto Assembler"""
import subprocess, sys, os
CE = r"C:\Users\Administrator\Desktop\ai2\新破甲\Tool\Cheat Engine\Cheat Engine.exe"
ADDR = sys.argv[1] if len(sys.argv) > 1 else input("Injection address (hex): ").strip()
print(f"""[code-inject] Cheat Engine Auto Assembler @ {ADDR}
Template:
[ENABLE]
alloc(newmem,2048)
label(returnhere)
label(originalcode)
newmem:
  // your custom code here
  originalcode:
  // original instructions
  jmp returnhere
"game.exe"+{ADDR}:
  jmp newmem
  nop
returnhere:
[DISABLE]
"game.exe"+{ADDR}:
  // restore original bytes
dealloc(newmem)
""")
if os.path.exists(CE):
    subprocess.Popen([CE])
