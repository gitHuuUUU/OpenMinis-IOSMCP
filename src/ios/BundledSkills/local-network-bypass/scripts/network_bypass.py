#!/usr/bin/env python3
"""Network auth bypass — hosts redirect or local server"""
import sys, os
TARGET_HOST = sys.argv[1] if len(sys.argv) > 1 else input("Auth server host (e.g. api.target.com): ").strip()
method = input("Method [1=hosts redirect, 2=local mock server]: ").strip()
if method == "1":
    hosts = r"C:\Windows\System32\drivers\etc\hosts"
    print(f"[network-bypass] Add to hosts: 127.0.0.1 {TARGET_HOST}")
    print(f"  File: {hosts}")
    print(f"  Add line: 127.0.0.1 {TARGET_HOST}")
else:
    print(f"""[network-bypass] Local mock server:
  cd C:\Users\Administrator\Desktop
  C:\Users\Administrator\AppData\Roaming\uv\python\cpython-3.11-windows-x86_64-none\python.exe -c "
import http.server, json
class H(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        self.send_response(200)
        self.send_header('Content-Type','application/json')
        self.end_headers()
        self.wfile.write(json.dumps({'status':'valid','expires':'2099-12-31'}).encode())
http.server.HTTPServer(('127.0.0.1',80), H).serve_forever()
"
""")
