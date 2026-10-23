# Embedded OLLVM runtime source record

Hikari-fix source: https://github.com/PPKunOfficial/Hikari-fix
Pinned commit: 5dd3902a0f2c74570e0ab7a637c57a3cccaed9fd
Source archive: hikari-source.tar (git archive; no downloaded executable installer).
License: source repository LICENSE (AGPLv3) and per-file notices; retained in archive and runtime bundle.

Build recipe: tools/build_ollvm_runtime.sh, Alpine 3.21/aarch64 native runner, Clang/LLVM 19.1.4.
Only bcf/fla/sobf are exposed. Anti-debug, anti-hook, class-dump and function-call runtime injection features are not selected by this driver.
The stock Clang frontend emits bitcode; opt loads the reviewed Hikari pass; Clang produces the final object or Mach-O dylib.
This is an ARM64 Linux guest toolchain, not a native iOS dylib injected into the app.

Source review covered CMake, plugin registration/options, pass entrypoints, file reads and process/network/destructive API strings. No explicit host destructive or credential-upload chain was identified in reviewed selected paths. This is not exhaustive malware certification; compiler output and iPhone compatibility still require separate verification.
