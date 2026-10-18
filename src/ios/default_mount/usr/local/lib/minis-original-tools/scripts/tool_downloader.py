"""NERV-BREAK tool downloader — all tools, one script.
Usage: python tool_downloader.py --all        (everything)
       python tool_downloader.py --pentest    (pentest only)
       python tool_downloader.py --status     (check what's installed)
"""
import os, sys, urllib.request, zipfile, shutil, subprocess, json

TOOL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "Tool")
os.makedirs(TOOL_DIR, exist_ok=True)

TOOLS = {
    # ═══ Reverse Engineering ═══
    "die": {
        "url": "https://github.com/horsicq/DIE-engine/releases/download/3.10/die_win64_portable_3.10.zip",
        "exe": "die/die.exe", "desc": "Detect It Easy — file type detector"
    },
    "x64dbg": {
        "url": "https://github.com/x64dbg/x64dbg/releases/download/snapshot/snapshot_2025-01-01_12-00.zip",
        "exe": "x64dbg/release/x64/x64dbg.exe", "desc": "x64dbg — Windows debugger"
    },
    "cheat-engine": {
        "url": "https://github.com/cheat-engine/cheat-engine/releases/download/7.5/CheatEngine75.exe",
        "exe": "Cheat Engine/Cheat Engine.exe",
        "desc": "Cheat Engine — memory scanner",
        "installer": True
    },
    "dnspy": {
        "url": "https://github.com/dnSpy/dnSpy/releases/download/v6.1.8/dnSpy-net-win64.zip",
        "exe": "dnspy/dnSpy.exe", "desc": "dnSpy — .NET decompiler"
    },
    "ghidra": {
        "url": "https://github.com/NationalSecurityAgency/ghidra/releases/download/Ghidra_11.2.1_build/ghidra_11.2.1_PUBLIC_20250101.zip",
        "exe": "ghidra/ghidra_11.2.1_PUBLIC/ghidraRun.bat",
        "desc": "Ghidra 11.2.1 — NSA reverse engineering suite",
        "large": True
    },
    "process-hacker": {
        "url": "https://github.com/winsiderss/systeminformer/releases/download/v3.2.25011/systeminformer-3.2.25011-release-bin.zip",
        "exe": "processhacker/amd64/SystemInformer.exe",
        "desc": "SystemInformer — process manager"
    },

    # ═══ Penetration Testing ═══
    "nmap": {
        "url": "https://nmap.org/dist/nmap-7.95-win32.zip",
        "exe": "nmap-7.95/nmap.exe", "desc": "nmap 7.95 — network scanner"
    },
    "nuclei": {
        "url": "https://github.com/projectdiscovery/nuclei/releases/download/v3.3.9/nuclei_3.3.9_windows_amd64.zip",
        "exe": "nuclei.exe", "desc": "nuclei 3.3.9 — vulnerability scanner"
    },
    "subfinder": {
        "url": "https://github.com/projectdiscovery/subfinder/releases/download/v2.6.8/subfinder_2.6.8_windows_amd64.zip",
        "exe": "subfinder.exe", "desc": "subfinder 2.6.8 — subdomain discovery"
    },
    "ffuf": {
        "url": "https://github.com/ffuf/ffuf/releases/download/v2.1.0/ffuf_2.1.0_windows_amd64.zip",
        "exe": "ffuf.exe", "desc": "ffuf 2.1.0 — web fuzzer"
    },
    "hydra": {
        "url": "https://github.com/vanhauser-thc/thc-hydra/releases/download/v9.5/thc-hydra-windows-master.zip",
        "exe": "thc-hydra-windows-master/hydra.exe",
        "desc": "hydra 9.5 — login brute-force"
    },
    "john": {
        "url": "https://github.com/openwall/john-packages/releases/download/jumbo-1.9.0-1/John-1.9.0-jumbo-1-win64.7z",
        "exe": "john-1.9.0-jumbo-1-win64/run/john.exe",
        "desc": "John the Ripper — password cracker"
    },
    "sqlmap": {
        "pip": "sqlmap",
        "exe": None, "desc": "sqlmap 1.8 — SQL injection (pip install sqlmap)"
    },
    "frida": {
        "pip": "frida-tools",
        "exe": None, "desc": "Frida 17.x — dynamic instrumentation (pip install frida-tools)"
    },

    # ═══ Python-only tools ═══
    "pwntools": {
        "pip": "pwntools",
        "exe": None, "desc": "pwntools — CTF & exploit development"
    },
    "impacket": {
        "pip": "impacket",
        "exe": None, "desc": "Impacket — network protocol toolkit"
    },
    "requests": {
        "pip": "requests",
        "exe": None, "desc": "requests — HTTP library (dependency)"
    },
}

def download(url, dest, name):
    print(f"  Downloading {name}...")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})
        resp = urllib.request.urlopen(req, timeout=300)
        total = int(resp.headers.get("Content-Length", 0))
        downloaded = 0
        with open(dest, "wb") as f:
            while True:
                chunk = resp.read(65536)
                if not chunk: break
                f.write(chunk)
                downloaded += len(chunk)
                if total:
                    pct = min(downloaded * 100 // total, 100)
                    mb_dl = downloaded / 1048576
                    mb_tot = total / 1048576
                    print(f"\r    {pct}%  {mb_dl:.1f}/{mb_tot:.1f} MB", end="")
        print(f"\r    100% — OK")
        return True
    except Exception as e:
        print(f"\n    FAILED: {e}")
        if os.path.exists(dest): os.remove(dest)
        return False

def extract_zip(path, dest_dir):
    with zipfile.ZipFile(path) as z:
        z.extractall(dest_dir)
    os.remove(path)

def main():
    import argparse
    ap = argparse.ArgumentParser(description="Download all tools to Tool/")
    ap.add_argument("--all", action="store_true", help="Download everything")
    ap.add_argument("--reverse", action="store_true", help="Reverse engineering tools only")
    ap.add_argument("--pentest", action="store_true", help="Pentest tools only")
    ap.add_argument("--python", action="store_true", help="Python pip tools only")
    ap.add_argument("--status", action="store_true", help="Check installed tools")
    ap.add_argument("--force", action="store_true", help="Re-download if exists")
    for name in TOOLS:
        ap.add_argument(f"--{name}", action="store_true", help=f"Download {name}")
    args = ap.parse_args()

    # Status mode
    if args.status or not any(vars(args).values()):
        print(f"\n  Tools in {TOOL_DIR}\n")
        print(f"  {'Tool':<20} {'Status':<12} {'Size':>8}  Description")
        print(f"  {'─'*20} {'─'*12} {'─'*8}  {'─'*40}")
        installed = 0
        for name, info in TOOLS.items():
            exe = info.get("exe", "")
            pip = info.get("pip", "")
            if pip:
                r = subprocess.run([sys.executable, "-m", "pip", "show", pip], capture_output=True, text=True)
                ok = r.returncode == 0
            elif exe:
                path = os.path.join(TOOL_DIR, exe)
                ok = os.path.exists(path)
            else:
                ok = False
            installed += ok
            status = "✓ INSTALLED" if ok else "✗ missing"
            size = ""
            if ok and exe:
                p = os.path.join(TOOL_DIR, exe)
                if os.path.exists(p):
                    dsize = os.path.getsize(os.path.dirname(p)) if os.path.isfile(p) else 0
                    size = f"{dsize//1048576}MB" if dsize > 1048576 else ""
            print(f"  {name:<20} {status:<12} {size:>8}  {info['desc']}")
        print(f"\n  {installed}/{len(TOOLS)} tools installed")
        print(f"\n  Usage:")
        print(f"    python tool_downloader.py --pentest     (nmap nuclei ffuf hydra subfinder ...)")
        print(f"    python tool_downloader.py --reverse     (die x64dbg dnSpy ghidra ...)")
        print(f"    python tool_downloader.py --python      (sqlmap frida pwntools impacket)")
        print(f"    python tool_downloader.py --all         (everything)")
        return

    # Download mode
    downloaded = 0
    for name, info in TOOLS.items():
        reverse_set = {"die","x64dbg","cheat-engine","dnspy","ghidra","process-hacker"}
        pentest_set = {"nmap","nuclei","subfinder","ffuf","hydra","john"}
        python_set = {"sqlmap","frida","pwntools","impacket","requests"}

        should_dl = (
            args.all or getattr(args, name, False) or
            (args.reverse and name in reverse_set) or
            (args.pentest and name in pentest_set) or
            (args.python and name in python_set)
        )
        if not should_dl: continue

        print(f"\n[{name}] {info['desc']}")

        # pip install
        if info.get("pip"):
            pkg = info["pip"]
            if not args.force:
                r = subprocess.run([sys.executable, "-m", "pip", "show", pkg], capture_output=True)
                if r.returncode == 0:
                    print(f"  ✓ Already installed (use --force to reinstall)")
                    downloaded += 1
                    continue
            r = subprocess.run([sys.executable, "-m", "pip", "install", pkg], capture_output=True, text=True)
            if r.returncode == 0:
                print(f"  [+] pip install {pkg} — OK")
                downloaded += 1
            else:
                print(f"  [!] pip install failed: {r.stderr[:120]}")
            continue

        # URL download
        url = info.get("url")
        if not url:
            print(f"  [!] No download URL")
            continue

        exe = info.get("exe", "")
        if exe and os.path.exists(os.path.join(TOOL_DIR, exe)) and not args.force:
            print(f"  ✓ Already installed (use --force to re-download)")
            downloaded += 1
            continue

        zip_path = os.path.join(TOOL_DIR, f"{name}_dl.zip")
        if download(url, zip_path, name):
            print(f"  Extracting...")
            try:
                extract_zip(zip_path, TOOL_DIR)
                if exe and os.path.exists(os.path.join(TOOL_DIR, exe)):
                    print(f"  [+] Installed: {exe}")
                    downloaded += 1
                elif not exe:
                    print(f"  [+] Extracted")
                    downloaded += 1
            except Exception as e:
                print(f"  [!] Extract: {e}")
        print()

    print(f"\n  {'='*50}")
    print(f"  Done. {downloaded} tools downloaded.")
    print(f"  Run with --status to verify.")

if __name__ == "__main__":
    main()
