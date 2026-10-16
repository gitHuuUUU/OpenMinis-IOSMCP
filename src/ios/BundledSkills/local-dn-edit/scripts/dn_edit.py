#!/usr/bin/env python3
"""Edit .NET IL via dnSpy"""
import subprocess, sys, os
DNSPY = r"C:\Users\Administrator\Desktop\ai2\新破甲\Tool\dnspy\dnSpy.exe"
TARGET = sys.argv[1] if len(sys.argv) > 1 else input("Target .NET assembly: ").strip()
print(f"""[dn-edit] dnSpy IL Editor: {TARGET}
Common IL patches:
  ldc.i4.0 -> ldc.i4.1   (return true instead of false)
  brfalse -> nop          (skip false check)
  brtrue -> nop           (skip true check)
  call X -> nop x5        (remove method call)
  ret -> ldc.i4.1 + ret   (force return 1/true)
""")
if os.path.exists(DNSPY):
    subprocess.Popen([DNSPY, TARGET])
