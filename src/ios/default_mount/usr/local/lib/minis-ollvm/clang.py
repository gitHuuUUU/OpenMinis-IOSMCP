#!/usr/bin/env python3
"""Local LLVM19/Hikari source -> protected IR -> object/link driver."""
import os, pathlib, subprocess, sys, tempfile
PASSES = {"bcf": "enable-bcfobf", "fla": "enable-cffobf", "sobf": "enable-strcry"}
ROOT = pathlib.Path(__file__).resolve().parent
CLANG = "/usr/lib/llvm19/bin/clang"
OPT = "/usr/lib/llvm19/bin/opt"

def plan(args):
    cleaned, selected = [], []
    i = 0
    while i < len(args):
        if args[i] == "-mllvm":
            if i + 1 >= len(args): raise ValueError("-mllvm requires a pass")
            name = args[i+1].lstrip("-")
            if name not in PASSES: raise ValueError("Built-in OLLVM does not support: "+name)
            if name not in selected: selected.append(name)
            i += 2
        else: cleaned.append(args[i]); i += 1
    return cleaned, selected

def run(argv, env):
    subprocess.run(list(map(str, argv)), check=True, env=env)

def main(args):
    args, selected = plan(args)
    env = {k:v for k,v in os.environ.items() if k not in (
        "ALLOBF","BCFOBF","CFFOBF","STRCRY","FCO","INDIBRAN","ADB","ANTIHOOK",
        "FUNCWRA","ACDOBF","CONSTENC","SPLITOBF","SUBOBF")}
    if not selected:
        return subprocess.call([CLANG,*args],env=env)
    sources = [a for a in args if pathlib.Path(a).suffix in (".c",".m",".mm",".cpp",".cc",".cxx") and pathlib.Path(a).is_file()]
    if not sources: raise ValueError("Enhanced driver requires C/ObjC/C++ source")
    if "-E" in args: raise ValueError("Preprocessing alone cannot apply obfuscation")
    output = None
    common=[];i=0
    while i<len(args):
        a=args[i]
        if a=="-o":
            output=args[i+1];i+=2;continue
        if a=="-x": raise ValueError("Use recognized source suffixes instead of -x")
        if a not in sources and a not in ("-c","-S","-emit-llvm","-dynamiclib","-shared"):
            common.append(a)
        i+=1
    if ("-c" in args or "-S" in args) and len(sources)!=1:
        raise ValueError("Compile-only enhanced builds require one source per command")
    pipeline="hikari("+",".join(PASSES[p] for p in selected)+")"
    with tempfile.TemporaryDirectory(prefix="minis-ollvm-") as temp:
        bitcodes=[]
        for index,source in enumerate(sources):
            raw=pathlib.Path(temp)/(str(index)+".raw.bc")
            protected=pathlib.Path(temp)/(str(index)+".protected.bc")
            run([CLANG,*common,"-O0","-Xclang","-disable-O0-optnone","-emit-llvm","-c",source,"-o",raw],env)
            run([OPT,"-load-pass-plugin="+str(ROOT/"libHikari.so"),"-passes="+pipeline,raw,"-o",protected],env)
            bitcodes.append(protected)
        final=[CLANG,*common,"-O0"]
        final += [a for a in args if a in ("-c","-S","-emit-llvm","-dynamiclib","-shared")]
        final += list(map(str,bitcodes))
        if output: final += ["-o",output]
        run(final,env)
    return 0

if __name__=="__main__":
    try: sys.exit(main(sys.argv[1:]))
    except (ValueError,OSError,subprocess.SubprocessError) as e:
        print("MinisRe OLLVM error: "+str(e),file=sys.stderr);sys.exit(1)
