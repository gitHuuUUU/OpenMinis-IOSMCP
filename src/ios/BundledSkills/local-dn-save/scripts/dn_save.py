#!/usr/bin/env python3
"""Save modified .NET assembly"""
import sys
print("""[dn-save] Save via dnSpy
Steps:
1. After editing IL: File -> Save Module
2. Choose output path (overwrite original or save as new)
3. dnSpy auto-fixes: metadata, string heap, method tables
4. No IAT/reloc repair needed (managed code)
5. Verify: File -> Open -> check patched code persists
""")
