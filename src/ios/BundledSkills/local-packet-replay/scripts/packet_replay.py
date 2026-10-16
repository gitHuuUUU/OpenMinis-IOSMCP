#!/usr/bin/env python3
"""Packet replay tool"""
import socket, sys, time
HOST = sys.argv[1] if len(sys.argv) > 1 else input("Target host:port (e.g. 127.0.0.1:8888): ").strip()
DATA = sys.argv[2] if len(sys.argv) > 2 else input("Hex payload to replay: ").strip().replace(" ", "")
host, port = HOST.split(":")
port = int(port)
payload = bytes.fromhex(DATA)
print(f"[packet-replay] Sending {len(payload)} bytes to {host}:{port}")
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.settimeout(5)
try:
    sock.connect((host, port))
    sock.send(payload)
    resp = sock.recv(4096)
    print(f"[+] Response: {len(resp)} bytes")
    print(f"    Hex: {resp[:128].hex()}")
except Exception as e:
    print(f"[-] {e}")
finally:
    sock.close()
