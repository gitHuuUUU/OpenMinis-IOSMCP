#!/usr/bin/env python3
"""
工具启动器 - 自动检测已安装工具，提供路由和启动
用法: python tool_launcher.py list
      python tool_launcher.py route disassemble --target app.exe
      python tool_launcher.py route debug --target app.exe
"""

import os, sys, subprocess

TOOL_ROOT = r"C:\Users\Administrator\Desktop\ai2\新破甲\Tool"

def _p(*parts):
    """os.path.join快捷方式"""
    return os.path.join(*parts)

# ======================== 工具注册表 ========================
TOOL_REGISTRY = {
    "ida_pro": {
        "name": "IDA Pro 9.2",
        "paths": [
            _p(TOOL_ROOT, "IDA Professional 9.2", "ida64.exe"),
            _p(TOOL_ROOT, "IDA Professional 9.2", "ida.exe"),
        ],
        "category": "disassembler",
        "priority": 10,
    },
    "ghidra": {
        "name": "Ghidra 11.2.1",
        "paths": [
            _p(TOOL_ROOT, "ghidra", "ghidra_11.2.1_PUBLIC", "ghidraRun.bat"),
        ],
        "category": "disassembler",
        "priority": 8,
        "headless": _p(TOOL_ROOT, "ghidra", "ghidra_11.2.1_PUBLIC", "support", "analyzeHeadless.bat"),
    },
    "x64dbg": {
        "name": "x64dbg",
        "paths": [
            _p(TOOL_ROOT, "x64dbg", "release", "x64", "x64dbg.exe"),
            _p(TOOL_ROOT, "x64dbg", "release", "x32", "x32dbg.exe"),
        ],
        "category": "debugger",
        "priority": 9,
    },
    "cheat_engine": {
        "name": "Cheat Engine",
        "paths": [
            _p(TOOL_ROOT, "Cheat Engine", "Cheat Engine.exe"),
            _p(TOOL_ROOT, "Cheat Engine", "cheatengine-x86_64-SSE4-AVX2.exe"),
        ],
        "category": "memory",
        "priority": 9,
    },
    "dnspy": {
        "name": "dnSpy",
        "paths": [
            _p(TOOL_ROOT, "dnspy", "dnSpy.exe"),
        ],
        "category": "dotnet",
        "priority": 10,
        "dotnet_only": True,
    },
    "die": {
        "name": "Detect It Easy",
        "paths": [
            _p(TOOL_ROOT, "die", "die.exe"),
        ],
        "category": "analyzer",
        "priority": 9,
    },
    "process_hacker": {
        "name": "Process Hacker",
        "paths": [
            _p(TOOL_ROOT, "processhacker", "amd64", "SystemInformer.exe"),
        ],
        "category": "system",
        "priority": 8,
    },
    "frida": {
        "name": "Frida",
        "paths": [],
        "category": "instrumentation",
        "priority": 7,
        "command": "frida",
    },
}

# ======================== 路由规则 ========================
ROUTE_MAP = {
    "disassemble": {"desc": "反编译/静态分析", "categories": ["disassembler"], "prefer": "ida_pro"},
    "debug":       {"desc": "动态调试",       "categories": ["debugger"],     "prefer": "x64dbg"},
    "memory":      {"desc": "内存修改/扫描",   "categories": ["memory"],       "prefer": "cheat_engine"},
    "dotnet":      {"desc": ".NET反编译/修改", "categories": ["dotnet"],       "prefer": "dnspy"},
    "analyze_pe":  {"desc": "PE快速分析",     "categories": ["analyzer"],     "prefer": "die"},
    "process":     {"desc": "进程管理",       "categories": ["system"],       "prefer": "process_hacker"},
    "hook":        {"desc": "动态插桩/Hook",  "categories": ["instrumentation"], "prefer": "frida"},
    "decompile":   {"desc": "反编译到高级语言", "categories": ["disassembler"], "prefer": "ida_pro"},
    "patch":       {"desc": "二进制补丁",     "categories": ["debugger","memory"], "prefer": "x64dbg"},
    "unpack":      {"desc": "脱壳",          "categories": ["debugger"],     "prefer": "x64dbg"},
    "protocol":    {"desc": "协议分析",       "categories": ["instrumentation"], "prefer": "frida"},
}


class ToolRouter:
    def __init__(self):
        self.available = {}
        self._scan()

    def _scan(self):
        for tool_id, info in TOOL_REGISTRY.items():
            found_path = None
            for p in info["paths"]:
                if os.path.exists(p):
                    found_path = p
                    break

            if not found_path and "command" in info:
                if shutil_which(info["command"]):
                    found_path = info["command"]

            if found_path:
                self.available[tool_id] = dict(info, found_path=found_path)

    def list_tools(self):
        print("\n  Installed Tools:")
        print("  " + "-" * 60)
        sorted_tools = sorted(self.available.keys(),
                            key=lambda x: TOOL_REGISTRY[x]["priority"], reverse=True)
        for tool_id in sorted_tools:
            info = self.available[tool_id]
            print("  [%s] %-22s -> %s" % (info["category"].upper(), info["name"], info["found_path"]))

        missing = [t for t in TOOL_REGISTRY if t not in self.available]
        if missing:
            print("\n  [MISSING]")
            for t in missing:
                print("  - %s" % TOOL_REGISTRY[t]["name"])

    def get_tool(self, route_name):
        route = ROUTE_MAP.get(route_name)
        if not route:
            return None
        preferred = route.get("prefer")
        if preferred and preferred in self.available:
            return self.available[preferred]
        for cat in route.get("categories", []):
            candidates = [(tid, t) for tid, t in self.available.items() if t["category"] == cat]
            if candidates:
                candidates.sort(key=lambda x: x[1]["priority"], reverse=True)
                return candidates[0][1]
        return None

    def route(self, route_name, target=None):
        tool = self.get_tool(route_name)
        if not tool:
            print("[-] No tool for: %s" % route_name)
            print("[*] Routes: %s" % ", ".join(ROUTE_MAP.keys()))
            return None
        print("[+] Route: %s -> %s" % (route_name, tool["name"]))
        print("    Path: %s" % tool["found_path"])
        return tool

    def launch(self, route_name, target=None, **kwargs):
        tool = self.route(route_name, target)
        if not tool:
            return False
        path = tool["found_path"]
        cmd = [path]
        if target:
            cmd.append(target)
        print("    CMD: %s" % " ".join('"%s"' % c for c in cmd))
        try:
            if path.endswith(".bat"):
                subprocess.Popen(cmd, shell=True)
            else:
                subprocess.Popen(cmd)
            print("    [+] Launched: %s" % tool["name"])
            return True
        except Exception as e:
            print("    [-] Failed: %s" % e)
            return False


def shutil_which(cmd):
    """shutil.which polyfill"""
    try:
        import shutil
        return shutil.which(cmd)
    except:
        for p in os.environ.get("PATH", "").split(os.pathsep):
            fp = os.path.join(p, cmd + ".exe" if sys.platform == "win32" else cmd)
            if os.path.exists(fp):
                return fp
    return None


def main():
    import argparse
    parser = argparse.ArgumentParser(description="逆向工具启动器 & 路由器")
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("list", help="列出所有工具")

    route_p = sub.add_parser("route", help="路由到最佳工具")
    route_p.add_argument("route_name", choices=list(ROUTE_MAP.keys()))
    route_p.add_argument("--target", "-t", help="目标文件")

    launch_p = sub.add_parser("launch", help="启动指定工具")
    launch_p.add_argument("tool", choices=list(TOOL_REGISTRY.keys()))
    launch_p.add_argument("--target", "-t", help="目标文件")

    args = parser.parse_args()
    router = ToolRouter()

    if args.cmd == "list":
        router.list_tools()
    elif args.cmd == "route":
        router.launch(args.route_name, args.target)
    elif args.cmd == "launch":
        router.launch(args.tool, args.target)
    else:
        router.list_tools()
        print("\n  Routes: %s" % ", ".join(ROUTE_MAP.keys()))
        print("  Usage: python tool_launcher.py route disassemble --target app.exe")


if __name__ == "__main__":
    main()
