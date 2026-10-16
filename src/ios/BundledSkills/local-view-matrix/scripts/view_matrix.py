#!/usr/bin/env python3
"""View matrix finder"""
import sys
print("""[view-matrix] Locate view projection matrix
Steps in Cheat Engine:
1. Attach to game process
2. In game: face exactly north / look straight at horizon
3. CE: First Scan (Float) for angle values around 0.0
4. In game: rotate 90 degrees right
5. CE: Next Scan for values around 90.0
6. Narrow down -> Browse memory region -> find 16 consecutive floats
7. Verify: values should be in range [-1, 1]
8. Record address -> use in w2s function

Output signature: 16x float, address = 0x...
""")
