"""Port scanner — nmap replacement in pure Python with service detection.
Usage: python port_scanner.py --target TARGET [--top N] [--full] [--udp]
"""
import socket, sys, threading, time, json, os
from concurrent.futures import ThreadPoolExecutor, as_completed

COMMON_PORTS = {
    21: "ftp", 22: "ssh", 23: "telnet", 25: "smtp", 53: "dns",
    80: "http", 110: "pop3", 111: "rpcbind", 135: "msrpc", 139: "netbios",
    143: "imap", 443: "https", 445: "smb", 993: "imaps", 995: "pop3s",
    1723: "pptp", 3306: "mysql", 3389: "rdp", 5432: "postgresql",
    5900: "vnc", 6379: "redis", 8080: "http-proxy", 8443: "https-alt",
    27017: "mongodb", 50000: "db2",
}

SERVICE_PROBES = {
    "http": b"GET / HTTP/1.0\r\n\r\n",
    "ssh": b"",
    "ftp": b"",
    "smtp": b"",
    "mysql": b"",
}

def banner_grab(host, port, service):
    """Try to grab service banner."""
    if service == "http":
        probe = b"GET / HTTP/1.0\r\nHost: %s\r\n\r\n" % host.encode()
    elif service == "ssh":
        probe = b""
    else:
        probe = b"\r\n"
    try:
        s = socket.socket()
        s.settimeout(2)
        s.connect((host, port))
        if probe:
            s.send(probe)
        resp = s.recv(1024)
        s.close()
        return resp.decode(errors="replace").split("\n")[0][:80]
    except:
        return ""

def scan_port(host, port, timeout=2):
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        result = s.connect_ex((host, port))
        s.close()
        if result == 0:
            svc = COMMON_PORTS.get(port, "unknown")
            banner = banner_grab(host, port, svc)
            return (port, "tcp", "open", svc, banner)
    except:
        pass
    return None

def scan_target(target, ports, max_workers=100):
    results = []
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(scan_port, target, p): p for p in ports}
        for f in as_completed(futures):
            r = f.result()
            if r:
                results.append(r)
                print(f"  [OPEN] {r[0]}/tcp — {r[3]}" + (f" ({r[4]})" if r[4] else ""))
    return sorted(results, key=lambda x: x[0])

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", required=True)
    ap.add_argument("--top", type=int, default=1000)
    ap.add_argument("--full", action="store_true")
    ap.add_argument("--udp", action="store_true")
    ap.add_argument("--output", default="")
    args = ap.parse_args()

    target = args.target
    
    # Resolve hostname
    try:
        target = socket.gethostbyname(target)
    except:
        pass

    print(f"\n[PORT SCAN] {target}\n")
    
    ports = list(COMMON_PORTS.keys()) if args.full else sorted(COMMON_PORTS.keys())[:args.top]
    start = time.time()
    results = scan_target(target, ports)
    elapsed = time.time() - start

    print(f"\n  Scanned {len(ports)} ports in {elapsed:.1f}s — {len(results)} open\n")
    
    for port, proto, state, svc, banner in results:
        extra = f" — {banner}" if banner else ""
        print(f"  {port}/{proto}  {state:<6} {svc:<12}{extra}")

    if args.output:
        os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
        with open(args.output, "w") as f:
            for r in results:
                f.write(f"{r[0]}/{r[1]}  {r[2]:<6} {r[3]}\n")
        print(f"\n  [OK] -> {args.output}")
