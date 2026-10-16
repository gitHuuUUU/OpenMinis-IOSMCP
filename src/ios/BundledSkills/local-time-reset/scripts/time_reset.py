#!/usr/bin/env python3
"""Time/trial reset via registry and file cleanup"""
import sys, os, winreg
APP = sys.argv[1] if len(sys.argv) > 1 else input("App name: ").strip()
print(f"[time-reset] Resetting trial for: {APP}")
# Registry cleanup
for root in [winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE]:
    for sub in [f"Software\\{APP}", f"Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\{APP}"]:
        try:
            key = winreg.OpenKey(root, sub, 0, winreg.KEY_SET_VALUE | winreg.KEY_QUERY_VALUE)
            for name in ["InstallDate", "RunCount", "DaysUsed", "FirstRun", "TrialStart"]:
                try: winreg.SetValueEx(key, name, 0, winreg.REG_DWORD, 0)
                except: pass
            winreg.CloseKey(key)
            print(f"  Cleared: {sub}")
        except: pass
# File cleanup
for base in [os.environ.get("APPDATA",""), os.environ.get("LOCALAPPDATA",""), os.environ.get("PROGRAMDATA","")]:
    for fname in ["trial.dat", ".trial", "license.lic", "settings.cfg"]:
        fp = os.path.join(base, APP, fname)
        if os.path.exists(fp):
            os.remove(fp)
            print(f"  Deleted: {fp}")
print("[+] Trial reset complete. Restart app.")
