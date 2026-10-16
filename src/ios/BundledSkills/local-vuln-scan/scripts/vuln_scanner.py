"""Vulnerability scanner — CVE check + version detection.
Usage: python vuln_scanner.py --target TARGET [--versions] [--verify CVE-ID]
"""

VULN_PATTERNS = {
    "CVE-2021-44228": {"name": "Log4Shell", "port": [80,443,8080,8443], "test": "${jndi:ldap://test/}"},
    "CVE-2017-5638": {"name": "Struts2 RCE", "port": [80,443,8080], "test": "%{(#test='mulest')}"},
    "CVE-2019-19781": {"name": "Citrix ADC", "port": [443,8443], "path": "/vpn/../vpns/"},
    "CVE-2020-5902": {"name": "F5 BIG-IP", "port": [443,8443], "path": "/tmui/login.jsp/..;/tmui/locallb/workspace/fileRead.jsp"},
    "CVE-2021-41773": {"name": "Apache Path Traversal", "port": [80,443], "path": "/cgi-bin/.%2e/%2e%2e/%2e%2e/etc/passwd"},
}

def check_version(target):
    """Simple service version probe on common ports."""
    import urllib.request
    results = []
    try:
        url = target if "://" in target else f"http://{target}"
        req = urllib.request.Request(url, headers={"User-Agent":"Mozilla/5.0"})
        resp = urllib.request.urlopen(req, timeout=5)
        server = resp.headers.get("Server", "")
        results.append(("Server", server))
        
        # Check for vulnerable versions
        for cve, info in VULN_PATTERNS.items():
            if any(x in server.lower() for x in ["apache/2.4.49","apache/2.4.50"]):
                results.append(("VULN", f"{cve}: {info['name']}"))
    except:
        pass
    
    return results

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", required=True)
    ap.add_argument("--versions", action="store_true")
    ap.add_argument("--verify", default="")
    ap.add_argument("--output", default="")
    args = ap.parse_args()

    print(f"\n[VULN SCAN] {args.target}\n")
    
    if args.versions:
        findings = check_version(args.target)
        for level, info in findings:
            print(f"  [{level}] {info}")
    
    if args.verify:
        cve = args.verify.upper()
        if cve in VULN_PATTERNS:
            info = VULN_PATTERNS[cve]
            print(f"  CVE: {cve} — {info['name']}")
            print(f"  Test ports: {info['port']}")
            if "path" in info:
                print(f"  Path: {info['path']}")
        else:
            print(f"  {cve} not in local DB. Load full CVE DB for complete scan.")
    
    if args.output:
        import os
        os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
