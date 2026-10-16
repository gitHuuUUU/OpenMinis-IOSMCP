#!/usr/bin/env python3
"""IAT rebuild guide"""
import sys
print("""[iat-rebuild] IAT Rebuild via Scylla
Steps:
1. After dumping at OEP, open Scylla (Plugins -> Scylla)
2. Select dumped process in "Attach to active process" dropdown
3. IAT Autosearch -> Get Imports
4. Check for invalid/unresolved pointers
5. "Cut invalid thunks" to remove broken entries
6. Use "Advanced IAT Search" for stubborn pointers
7. Fix Dump -> select dumped binary -> Scylla patches IAT
8. Verify: run rebuilt binary

Fallback: ImpREC (Import REConstructor)
""")
