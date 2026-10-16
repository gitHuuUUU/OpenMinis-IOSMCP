"""Web scanner — directory brute-force + tech fingerprint.
Usage: python web_scanner.py --target URL [--dirs] [--whatweb] [--vuln]
"""
import urllib.request, urllib.error, sys, os, re, threading, time

DIRS = ["admin","login","wp-admin","api","backup","config","db","test","dev","staging",
        ".git","phpmyadmin","wp-content","uploads","static","assets","js","css","images",
        "robots.txt","sitemap.xml","crossdomain.xml",".env",".htaccess","info.php",
        "console","dashboard","portal","manager","jenkins","solr","grafana","cgi-bin"]

def try_url(target, path, timeout=3):
    url = target.rstrip("/") + "/" + path.lstrip("/")
    try:
        req = urllib.request.Request(url, headers={"User-Agent":"Mozilla/5.0"})
        resp = urllib.request.urlopen(req, timeout=timeout)
        code = resp.status
        size = len(resp.read())
        if code != 404:
            return (path, code, size)
    except urllib.error.HTTPError as e:
        if e.code != 404:
            return (path, e.code, 0)
    except:
        pass
    return None

def scan_dirs(target, wordlist, threads=20):
    results = []
    with threading.ThreadPoolExecutor(max_workers=threads) as ex:
        futures = {ex.submit(try_url, target, d): d for d in wordlist}
        for f in futures:
            r = f.result()
            if r:
                results.append(r)
                print(f"  [{r[1]}] /{r[0]} ({r[2]}B)")
    return results

def whatweb(target):
    url = target if "://" in target else "http://" + target
    try:
        req = urllib.request.Request(url, headers={"User-Agent":"Mozilla/5.0"})
        resp = urllib.request.urlopen(req, timeout=10)
        headers = dict(resp.headers)
        body = resp.read(10000).decode(errors="replace")
        
        tech = []
        svr = headers.get("Server",""); xp = headers.get("X-Powered-By","")
        if "nginx" in svr.lower(): tech.append("nginx")
        elif "apache" in svr.lower(): tech.append("apache")
        if "php" in xp.lower(): tech.append("php")
        if "wordpress" in body.lower(): tech.append("WordPress")
        if "wp-content" in body: tech.append("WordPress")
        
        print(f"\n  URL: {url}")
        print(f"  Status: {resp.status}")
        print(f"  Server: {svr}")
        print(f"  Tech: {', '.join(tech) if tech else 'unknown'}")
        return {"url": url, "status": resp.status, "server": svr, "tech": tech}
    except Exception as e:
        print(f"  Error: {e}")
        return None

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", required=True)
    ap.add_argument("--dirs", action="store_true")
    ap.add_argument("--whatweb", action="store_true")
    ap.add_argument("--vuln", action="store_true")
    ap.add_argument("--output", default="")
    args = ap.parse_args()

    target = args.target
    
    if args.whatweb:
        whatweb(target)
    
    if args.dirs:
        print(f"\n[DIR SCAN] {target}\n")
        start = time.time()
        results = scan_dirs(target, DIRS)
        print(f"\n  {len(results)} directories found in {time.time()-start:.1f}s")
    
    if args.output:
        os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
        with open(args.output, "w") as f:
            f.write(f"Web Scan: {target}\n")
