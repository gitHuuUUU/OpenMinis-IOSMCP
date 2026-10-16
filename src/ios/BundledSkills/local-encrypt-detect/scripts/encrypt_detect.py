#!/usr/bin/env python3
"""Encryption detection from captured traffic"""
import sys, math
DATA = sys.argv[1] if len(sys.argv) > 1 else input("Hex data to analyze: ").strip().replace(" ", "")
try:
    raw = bytes.fromhex(DATA)
    # Entropy
    freq = [0]*256
    for b in raw: freq[b] += 1
    entropy = -sum((f/len(raw))*math.log2(f/len(raw)) for f in freq if f>0)
    print(f"[encrypt-detect] Length: {len(raw)} bytes | Entropy: {entropy:.2f}")
    if entropy > 7.5:
        print("  -> HIGH entropy: encrypted or compressed (AES, ChaCha, etc.)")
    elif entropy > 5.0:
        print("  -> MEDIUM entropy: possible XOR or custom encoding")
    else:
        print("  -> LOW entropy: likely plaintext or simple encoding (base64, hex)")
    # Block size detection
    if len(raw) % 16 == 0: print("  -> Block-aligned (16 bytes): possible AES/CBC")
    if len(raw) % 8 == 0: print("  -> Block-aligned (8 bytes): possible DES/3DES")
except Exception as e:
    print(f"[-] Error: {e}")
