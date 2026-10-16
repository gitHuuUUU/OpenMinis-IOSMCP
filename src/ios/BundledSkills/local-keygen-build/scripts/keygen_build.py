#!/usr/bin/env python3
"""Build keygen — outputs Python keygen template"""
import sys
TARGET = sys.argv[1] if len(sys.argv) > 1 else input("Target binary: ").strip()
PATTERN = sys.argv[2] if len(sys.argv) > 2 else input("Serial pattern [XXXX-XXXX-XXXX]: ").strip() or "XXXX-XXXX-XXXX"
print(f"[keygen-build] Keygen template for: {TARGET}")
print("""
import hashlib, random

def generate_serial(username="User", pattern=""" + repr(PATTERN) + """):
    result = []
    for char in pattern:
        if char == "X":
            charset = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
            result.append(random.choice(charset))
        elif char == "N":
            result.append(str(random.randint(0, 9)))
        else:
            result.append(char)
    return "".join(result)

# Analyze verification function in IDA Pro to extract algorithm
# Replace generate_serial with reversed algorithm
print(generate_serial())
""")
