# Embedded OLLVM / MinisProtection runtime

## Sources and ABI
- Hikari-fix: https://github.com/PPKunOfficial/Hikari-fix, pinned commit `5dd3902a0f2c74570e0ab7a637c57a3cccaed9fd`; `hikari-source.tar` is a source-only git archive. AGPLv3/per-file notices retained.
- New local LLVM passes: `minis-protection.cpp`; complete source included in the offline runtime and matching source delivery.
- ldid: official Procursus source pinned `af86971ae72ec3ed3d0a699107c4e882324c941b`; see `ldid-README.md` for source hash and AGPLv3 licensing. The static ARM64 signer and complete source/license are bundled.
- Native build: Alpine 3.21/aarch64, Clang/LLVM 19.1.4; do not mix LLVM22 plugins with the LLVM19 process. This is an ARM64 Linux guest toolchain, not a native iOS process/compiler injection.

## Five real transformations (runtime version 2)
- `bcf`: Hikari bogus branches (branch protection).
- `indcall`: MinisProtection direct eligible calls/invokes -> private mutable function-pointer table + volatile load + indirect call.
- `indgv`: MinisProtection eligible global-data address uses -> private mutable pointer table + volatile load + indirect access.
- `sobf`: Hikari string encryption for supported string globals.
- `fla`: Hikari control-flow flattening.

The frontend emits bitcode, runs Hikari then the reviewed local passes, and code-generates the final object/Mach-O. Normal mode does not install or activate protection. Single mode requires exactly one selected pass; combined mode permits any nonempty subset. Unsupported/missing components fail explicitly rather than silently compiling normally. Anti-debug/anti-hook/class-dump/runtime-injection features are not selected.

These are source obfuscation transformations, NOT cryptographic confidentiality or a promise every call/data form is transformed. Intrinsics, inline asm, musttail/callbr, TLS, ABI-special sections and unsupported constant/metadata forms are deliberately preserved. Swift, APK, EXE and already-built IPA/DEB files are not protected by this frontend.

## Theos and signing
Local C/ObjC/C++ dylib builds and Theos **source** DEB projects use the selected frontend. Theos keeps its normal linker; command-line linking without source is passed through. Standard `-c`, response-file, dependency-file and ObjC/ARC arguments are handled. Unsupported protected stdin/PCH/module/offloading modes fail visibly.

The built-in enhanced Theos path uses its own bundled real static `ldid`, without replacing a global signer. After actual packaging, each thin arm64 Mach-O's CodeDirectory page hashes are verified before publishing the output; failed checks leave previous good output untouched. Fat packages currently require `ARCHS=arm64`. CodeDirectory integrity/ad-hoc signing does not establish Apple trust, a provisioning profile or device installation compatibility.

## Offline installation and upgrades
All APK/source/plugin/signer bytes are catalog-pinned by length/SHA256. Runtime v2 checks manifest identity and actual runtime hashes, upgrades an older three-pass runtime, and rolls back failed activation. Status records per-pass **real IR evidence** and actual installed bytes, not a hard-coded ready label. It does not launch repeated probes merely on opening the page.

Do not pass every APK to `apk add`: local APK paths impose checksum/version constraints that conflict with an installed curl -> libcurl exact-version pair. The installer reads signed-APK metadata and installed packages, preserves satisfying dependencies, adds only pinned compiler roots and missing/unsatisfied providers, and first runs a no-network solver simulation. Package signatures remain enforced; no `allow-untrusted` or broken-world workaround.

## Reproducible validation
- `tools/build_ollvm_runtime.sh` / `tools/run_protection_native_ci.sh`: native ARM64 build and all gates below, aborting on any failure.
- `tools/test_ollvm_protection_native.sh`: all **31 nonempty pass combinations** execute against the normal baseline, actual IR changes + LLVM verification, C++ invoke/exception and ABI edge cases, all-five arm64 iOS15.4 Mach-O cross-link and indirect `blr` evidence.
- `tools/build_protection_signer.sh`: static ARM64 ldid, no ELF interpreter; actual signing, code-page hashes and entitlement round-trip.
- `tools/test_theos_protection_native.sh`: actual isolated Theos normal/enhanced compile/link/package, final strings comparison and real signed CodeDirectory page verification.
- `tools/test_protection_guest_install.sh`: actual shipped fakefs rootfs restored in an isolated ARM64 chroot; offline v2 install/ensure, all-five native run, curl/git unchanged, guest-installed signer and final Mach-O hash verification.
- `tools/test_ollvm_runtime.py`, `tools/test_protection_adapter.py`, `tools/test_protection_ui.py`, `tools/test_macho_signing.py`: errors/upgrade/rollback, frontend wiring, single/combined policy, signature corruption/bounds regression.

These Linux/native-host and Xcode build checks are not iPhone execution, thermal/FPS measurements or arbitrary-project certification. Final delivery records actual CI run identifiers and which gates completed.

## Read-only source review boundary
Reviewed selected pass registration/entrypoints, build files, file/process/network/destructive call strings, and official ldid build source. No explicit host destructive or credential-upload chain was identified in these selected paths; this is not exhaustive malware certification. No downloaded executable installer is executed.
