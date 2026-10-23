#!/usr/bin/env python3
"""LLVM19 protected C/ObjC/C++ frontend; normal link/query commands pass through.

Supports usual Theos one-source compilation, dependencies and response files.
Modules/PCH creation, stdin and offloading still require the original toolchain.
"""
import os, pathlib, shlex, subprocess, sys, tempfile

PASSES = {"bcf": "enable-bcfobf", "indcall": "minis-indcall", "indgv": "minis-indgv",
          "sobf": "enable-strcry", "fla": "enable-cffobf"}
HIKARI = {"bcf", "fla", "sobf"}
ROOT = pathlib.Path(__file__).resolve().parent
CLANG = "/usr/lib/llvm19/bin/clang"
OPT = "/usr/lib/llvm19/bin/opt"
SOURCE_SUFFIXES = {".c", ".m", ".mm", ".cpp", ".cc", ".cxx", ".C", ".c++"}
SOURCE_LANGUAGES = {"c", "objective-c", "c++", "objective-c++", "c-cpp-output",
                    "c++-cpp-output", "objective-c-cpp-output", "objective-c++-cpp-output"}
PAIR_FLAGS = {"-o", "-x", "-target", "--target", "-arch", "-isysroot", "--sysroot",
              "-I", "-F", "-L", "-l", "-isystem", "-iquote", "-idirafter", "-iframework",
              "-include", "-imacros", "-include-pch", "-D", "-U", "-Xclang", "-Xlinker",
              "-Xassembler", "-mllvm", "-MF", "-MT", "-MQ", "-dependency-file",
              "-framework", "-weak_framework", "-weak_library", "-rpath", "-install_name",
              "-compatibility_version", "-current_version", "-B", "-resource-dir",
              "-gcc-toolchain", "--gcc-toolchain", "-fmodule-map-file"}
DEPENDENCY_FLAGS = {"-MD", "-MMD", "-MP", "-MG", "-MF", "-MT", "-MQ", "-dependency-file"}
LINK_PAIR_FLAGS = {"-L", "-l", "-Xlinker", "-framework", "-weak_framework", "-weak_library",
                   "-rpath", "-install_name", "-compatibility_version", "-current_version"}
LINK_FLAGS = {"-dynamiclib", "-shared", "-static", "-pie", "-no-pie", "-nostdlib",
              "-nodefaultlibs", "-nostartfiles", "-rdynamic", "-s", "-r"}


def expand_response_files(args, depth=0):
    if depth > 16:
        raise ValueError("Response files are recursively nested")
    expanded = []
    for arg in args:
        if arg.startswith("@"):
            path = pathlib.Path(arg[1:])
            expanded.extend(expand_response_files(shlex.split(path.read_text(encoding="utf-8-sig")), depth + 1))
        else:
            expanded.append(arg)
    return expanded


def plan(args):
    cleaned, selected = [], []
    i = 0
    while i < len(args):
        if args[i] == "-mllvm":
            if i + 1 >= len(args):
                raise ValueError("-mllvm requires a pass")
            name = args[i + 1].lstrip("-")
            if name not in PASSES:
                raise ValueError("Built-in OLLVM does not support: " + name)
            if name not in selected:
                selected.append(name)
            i += 2
        else:
            cleaned.append(args[i]); i += 1
    return cleaned, selected


def option_groups(args):
    """Do not mistake an option value such as -include common.c for a source."""
    groups = []
    i = 0
    while i < len(args):
        token = args[i]
        if token in PAIR_FLAGS:
            if i + 1 == len(args):
                raise ValueError(token + " requires a value")
            groups.append(args[i:i + 2]); i += 2
        elif token.startswith("-o") and len(token)>2 and not token.startswith("-objc"):
            groups.append(["-o",token[2:]]); i += 1
        else:
            groups.append([token]); i += 1
    return groups


def inputs(groups):
    language = None
    found = []
    for index, group in enumerate(groups):
        token = group[0]
        if token == "-x":
            language = None if group[1] == "none" else group[1]
        elif token.startswith("-x") and len(token) > 2:
            language = None if token[2:] == "none" else token[2:]
        elif len(group) == 1 and (not token.startswith("-") or token == "-"):
            if language in SOURCE_LANGUAGES or (language is None and pathlib.Path(token).suffix in SOURCE_SUFFIXES):
                found.append((index, token, language))
    return found


def dependency_option(group):
    token = group[0]
    return token in DEPENDENCY_FLAGS or any(token.startswith(p) and len(token) > len(p) for p in ("-MF", "-MT", "-MQ")) or token.startswith(("-Wp,-MD", "-Wp,-MMD"))


def link_option(group):
    token = group[0]
    return token in LINK_FLAGS or token in LINK_PAIR_FLAGS or token.startswith(("-Wl,", "-fuse-ld=", "-rtlib=", "--ld-path=")) or (len(group) == 1 and token.startswith(("-l", "-L")))


def frontend_options(groups, source_indices):
    options = []
    for index, group in enumerate(groups):
        token = group[0]
        if index in source_indices or token in ("-o", "-c", "-S", "-emit-llvm", "-x") or token.startswith("-x") or link_option(group):
            continue
        if len(group) == 1 and not token.startswith("-"):
            continue  # object/archive inputs belong exclusively to final linking
        options.extend(group)
    return options


def run(argv, env):
    subprocess.run(list(map(str, argv)), check=True, env=env)


def transform(raw, protected, selected, env):
    """Hikari first; indirect passes also cover globals introduced by sobf."""
    current = raw
    hikari = [PASSES[p] for p in selected if p in HIKARI]
    custom = [PASSES[p] for p in ("indcall", "indgv") if p in selected]
    if hikari:
        target = protected if not custom else protected.with_suffix(".hikari.bc")
        run([OPT, "-load-pass-plugin=" + str(ROOT / "libHikari.so"),
             "-passes=hikari(" + ",".join(hikari) + ")", current, "-o", target], env)
        current = target
    if custom:
        run([OPT, "-load-pass-plugin=" + str(ROOT / "libMinisProtection.so"),
             "-passes=" + ",".join(custom), current, "-o", protected], env)


def main(args):
    args, selected = plan(expand_response_files(args))
    env = {k: v for k, v in os.environ.items() if k not in (
        "ALLOBF", "BCFOBF", "CFFOBF", "STRCRY", "FCO", "INDIBRAN", "ADB", "ANTIHOOK",
        "FUNCWRA", "ACDOBF", "CONSTENC", "SPLITOBF", "SUBOBF")}
    if not selected:
        return subprocess.call([CLANG, *args], env=env)
    groups = option_groups(args)
    sources = inputs(groups)
    if any(a.startswith(("-fmodule-output", "-fmodule-header")) for a in args) or any(g == ["-Xclang", "-emit-pch"] or (g[0] == "-x" and g[1].endswith("-header")) for g in groups):
        raise ValueError("Protected module/PCH creation is not supported")
    if not sources or any(a in args for a in ("-E", "-M", "-MM", "-fsyntax-only", "--version", "-dumpmachine")):
        return subprocess.call([CLANG, *args], env=env)
    if any(source == "-" for _, source, _ in sources):
        raise ValueError("Protected stdin compilation is not supported; use a source file")
    output = next((g[1] for g in reversed(groups) if g[0] == "-o"), None)
    compile_only = "-c" in args or "-S" in args
    if output and compile_only and len(sources) != 1:
        raise ValueError("A single -o cannot name multiple compile-only outputs")
    common = frontend_options(groups, {i for i, _, _ in sources})
    lowering = []
    for group in option_groups(common):
        if not dependency_option(group):
            lowering.extend(group)
    with tempfile.TemporaryDirectory(prefix="minis-ollvm-") as temp:
        objects = {}
        for index, source, language in sources:
            raw = pathlib.Path(temp) / (str(index) + ".raw.bc")
            protected = pathlib.Path(temp) / (str(index) + ".protected.bc")
            options = [*common]
            if any(g[0] in ("-MD", "-MMD") for g in groups):
                final_name = output if compile_only and output else pathlib.Path(source).with_suffix(".o").name
                if not any(g[0] == "-MF" or g[0].startswith("-MF") for g in groups):
                    options += ["-MF", pathlib.Path(final_name).with_suffix(".d").as_posix()]
                if not any(g[0] in ("-MT", "-MQ") or g[0].startswith(("-MT", "-MQ")) for g in groups):
                    options += ["-MT", str(final_name)]
            if language:
                options += ["-x", language]
            run([CLANG, *options, "-O0", "-Xclang", "-disable-O0-optnone",
                 "-emit-llvm", "-c", source, "-o", raw], env)
            transform(raw, protected, selected, env)
            if compile_only:
                suffix = ".ll" if "-S" in args and "-emit-llvm" in args else ".bc" if "-emit-llvm" in args else ".s" if "-S" in args else ".o"
                final_name = output or pathlib.Path(source).with_suffix(suffix).name
                mode = ["-S"] if "-S" in args else ["-c"]
                if "-emit-llvm" in args:
                    mode += ["-emit-llvm"]
                run([CLANG, *lowering, "-O0", *mode, protected, "-o", final_name], env)
            else:
                obj = pathlib.Path(temp) / (str(index) + ".o")
                run([CLANG, *lowering, "-O0", "-c", protected, "-o", obj], env)
                objects[index] = str(obj)
        if not compile_only:
            final = [CLANG]
            if any(language in ("c++", "objective-c++", "c++-cpp-output", "objective-c++-cpp-output") or (language is None and pathlib.Path(source).suffix in (".cpp", ".cc", ".cxx", ".C", ".c++", ".mm")) for _,source,language in sources) and not any(a.startswith("--driver-mode=") for a in args):
                final.append("--driver-mode=g++")
            for index, group in enumerate(groups):
                if index in objects:
                    final.append(objects[index])
                elif not dependency_option(group) and group[0] != "-x" and not group[0].startswith("-x"):
                    final.extend(group)
            run(final, env)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except (ValueError, OSError, subprocess.SubprocessError) as e:
        print("MinisRe OLLVM error: " + str(e), file=sys.stderr); sys.exit(1)
