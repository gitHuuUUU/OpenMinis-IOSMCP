#!/usr/bin/env python3
"""Read-only CLI for the product's CodeDirectory verifier; no Apple trust claim."""
import argparse
import importlib.util
import json
import pathlib
import plistlib
import struct


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=pathlib.Path)
    parser.add_argument("--output", type=pathlib.Path)
    args = parser.parse_args()
    local=pathlib.Path(__file__).resolve().with_name("macho_signing.py")
    source=local if local.is_file() else pathlib.Path(__file__).resolve().parents[1]/"src/ios/BuildWorkbench.bundle/macho_signing.py"
    spec=importlib.util.spec_from_file_location("minis_macho_signing",source)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    try:
        result=module.verify_macho_code_directory(args.path)
    except (OSError, ValueError, struct.error, plistlib.InvalidFileException) as error:
        parser.exit(1,"Mach-O CodeDirectory verification failed: "+str(error)+"\n")
    text=json.dumps(result,ensure_ascii=False,indent=2)+"\n"
    if args.output:args.output.write_text(text,encoding="utf-8")
    print(text,end="")


if __name__=="__main__":
    main()
