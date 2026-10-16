#!/usr/bin/env python3
"""Frida network hook generator"""
import sys
PROCESS = sys.argv[1] if len(sys.argv) > 1 else input("Target process name: ").strip()
hook_js = """// [frida-intercept] Network hook for: """ + PROCESS + """
const sends = ['send', 'WSASend'];
const recvs = ['recv', 'WSARecv'];

sends.forEach(fn => {
    const func = Module.findExportByName(null, fn);
    if (func) {
        Interceptor.attach(func, {
            onEnter(args) {
                console.log('""" + "[" + PROCESS + "]" + """ ' + fn + ' len=' + args[2]);
                if (args[2]) console.log(hexdump(args[1], {length: Math.min(args[2].toInt32(), 128)}));
            }
        });
    }
});

recvs.forEach(fn => {
    const func = Module.findExportByName(null, fn);
    if (func) {
        Interceptor.attach(func, {
            onLeave(retval) {
                console.log('""" + "[" + PROCESS + "]" + """ ' + fn + ' ret=' + retval);
            }
        });
    }
});
"""
js_path = "hook_" + PROCESS.replace(".exe","") + ".js"
with open(js_path, "w") as f:
    f.write(hook_js)
print(f"[+] Hook script: {js_path}")
print(f"    Run: frida -n {PROCESS} -l {js_path}")
