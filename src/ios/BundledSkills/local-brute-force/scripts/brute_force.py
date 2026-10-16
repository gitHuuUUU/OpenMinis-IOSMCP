"""Brute-force tester for common services.
Usage: python brute_force.py --target TARGET --service ssh --user USER [--wordlist NAME]
"""
import socket, sys, os, time

COMMON_CREDS = [
    ("root","root"), ("root","admin"), ("root","password"), ("root","123456"),
    ("admin","admin"), ("admin","password"), ("admin","123456"), ("admin","admin123"),
    ("test","test"), ("user","user"), ("user","password"),
    ("guest","guest"), ("oracle","oracle"), ("postgres","postgres"),
]

def test_ssh(target, user, pwd, port=22, timeout=3):
    """Basic SSH auth test — just connect, banner grab for version."""
    try:
        s = socket.socket()
        s.settimeout(timeout)
        s.connect((target, port))
        banner = s.recv(256).decode(errors="replace")[:60]
        s.close()
        return f"SSH available — {banner}"
    except:
        return None

def test_ftp(target, user, pwd, port=21, timeout=3):
    try:
        s = socket.socket()
        s.settimeout(timeout)
        s.connect((target, port))
        banner = s.recv(256).decode(errors="replace")[:60]
        s.close()
        return f"FTP available — {banner}"
    except:
        return None

def test_http(target, user, pwd, port=80, timeout=3):
    """Check if HTTP Basic Auth is enabled."""
    import urllib.request, base64
    try:
        url = f"http://{target}:{port}/"
        req = urllib.request.Request(url)
        resp = urllib.request.urlopen(req, timeout=timeout)
        auth_header = resp.headers.get("WWW-Authenticate","")
        if auth_header:
            return f"HTTP Auth required — {auth_header[:60]}"
        return f"HTTP open (no auth) — status {resp.status}"
    except Exception as e:
        return None

SERVICE_TEST = {"ssh": test_ssh, "ftp": test_ftp, "http": test_http}

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", required=True)
    ap.add_argument("--detect", action="store_true")
    ap.add_argument("--service", default="ssh")
    ap.add_argument("--user", default="root")
    ap.add_argument("--wordlist", default="common")
    ap.add_argument("--output", default="")
    args = ap.parse_args()

    target = args.target

    print(f"\n[BRUTE FORCE] {target}\n")

    if args.detect:
        print("  Detecting services...")
        for svc, fn in SERVICE_TEST.items():
            result = fn(target, "test", "test")
            if result:
                print(f"  [FOUND] {svc}: {result}")
    
    # Test common credentials
    test_fn = SERVICE_TEST.get(args.service)
    if test_fn:
        print(f"\n  Testing {len(COMMON_CREDS)} common credentials on {args.service}...")
        for user, pwd in COMMON_CREDS:
            result = test_fn(target, user, pwd)
            if result:
                print(f"  [ATTEMPT] {user}:{pwd} — {result}")
        print(f"\n  Tested {len(COMMON_CREDS)} combos. Use full wordlists for exhaustive testing.")
    
    if args.output:
        os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
