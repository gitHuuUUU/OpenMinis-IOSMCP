"""DNS enumerator — subdomain discovery + record lookup.
Usage: python dns_enum.py --target DOMAIN [--records] [--subdomains]
"""
import socket, sys, os, re, threading, time

SUBS = ["www","mail","ftp","admin","api","dev","test","staging","blog","shop",
        "cdn","docs","portal","vpn","remote","m","mobile","app","webmail",
        "ns1","ns2","dns","mx","smtp","imap","pop","mysql","db","db1"]

def resolve(domain):
    try: return socket.gethostbyname(domain)
    except: return None

def scan_subdomains(target, wordlist, threads=30):
    results = []
    def check(sub):
        domain = f"{sub}.{target}"
        ip = resolve(domain)
        if ip: results.append((domain, ip))
    with threading.ThreadPoolExecutor(max_workers=threads) as ex:
        ex.map(check, wordlist)
    return results

def dns_records(target):
    records = {}
    for rtype, prefix in [("A",""), ("MX","mail"), ("NS","dns"), ("TXT","")]:
        try:
            answers = socket.getaddrinfo(target, None)
            if rtype == "A":
                records[rtype] = list(set(a[4][0] for a in answers))
        except: pass
    return records

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", required=True)
    ap.add_argument("--records", action="store_true")
    ap.add_argument("--subdomains", action="store_true")
    ap.add_argument("--output", default="")
    args = ap.parse_args()

    target = args.target.strip().replace("http://","").replace("https://","").split("/")[0]

    print(f"\n[DNS ENUM] {target}\n")
    
    if args.records:
        recs = dns_records(target)
        for t, vals in recs.items():
            print(f"  {t}: {', '.join(vals[:5])}")
    
    if args.subdomains:
        print(f"\n  Scanning {len(SUBS)} subdomains...")
        start = time.time()
        subs = scan_subdomains(target, SUBS)
        for domain, ip in subs:
            print(f"  [FOUND] {domain} → {ip}")
        print(f"\n  {len(subs)} subdomains in {time.time()-start:.1f}s")
    
    if args.output:
        os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
        with open(args.output, "w") as f:
            f.write(f"DNS Enum: {target}\n")
            for d, ip in subs if args.subdomains else []:
                f.write(f"{d} → {ip}\n")
