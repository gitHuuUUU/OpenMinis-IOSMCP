# Protected Theos signing helper

## Fixed source

- Official upstream: <https://github.com/ProcursusTeam/ldid>
- Commit: `af86971ae72ec3ed3d0a699107c4e882324c941b`
- Source archive: `ldid-source.tar`, a `git archive --prefix=ldid/` of that commit.
- SHA256: `e72498269d04dea5618d889dfefc95652f3cc39cbcf92cdc9b3eb9ecd0fb2d72`
- Upstream license is included as `ldid/COPYING` (AGPL-3.0).

## Build

Run `tools/build_protection_signer.sh` inside a native Alpine 3.21 aarch64 build
environment. Place the source archive, script, CodeDirectory CLI and product
`macho_signing.py` at `/work/`; first produce the five-pass test dylib at
`/work/protection-native/all-five.dylib`, or set `PROBE_DYLIB` to an isolated
test copy. No `make install` or remote installer runs.

Build dependencies come from the official Alpine `v3.21/main` and `community`
repositories: `build-base`, `pkgconf`, `openssl-dev`, `openssl-libs-static`,
`libplist-dev`, `libplist-static`, `python3`, `file`, and `binutils`.
The official aarch64 APK indexes were checked: both required static packages
exist. The build records the actually installed dependency versions.

The output `/work/protection-signer/ldid` is required to be statically linked
and to have no ELF `INTERP` program header. The script also keeps the ldid
object file (for relinking), upstream license, build dependency list, and
verification evidence. It does not install or modify a pre-existing ldid.
The source archive, dependency versions and this build recipe belong with any
distributed binary; the complete Alpine package sources remain available from
the official aports source history for the recorded package versions.

## What is actually verified

The script strips a temporary copy of the fixture signature, signs it using the
newly built binary with a harmless fixture entitlement, extracts that entitlement
again, and independently recomputes every CodeDirectory code-page hash and
the XML/DER entitlement blob hashes. A no-op shell or `/bin/true` cannot pass.
`tools/verify_macho_code_directory.py` uses the same pure-stdlib product helper
`src/ios/BuildWorkbench.bundle/macho_signing.py` as the app's build backend.

This is ad-hoc signing and read-only embedded hash verification. It is **not**
Apple certificate/provisioning validation, TrollStore installation validation,
or proof that a particular iPhone will accept/load the produced tweak.

## Pre-execution source review

Before compilation the Makefile and ldid main/file-write paths were read.
The default build compiles one C++ source and links libcrypto/libplist; it
does not fetch or execute another payload. SMARTCARD/PKCS11 support is not
enabled. The file replacement/temporary-file cleanup operations act on the
explicit CLI target and its `.ldid.*` temporary file. No socket/network upload,
shell-execution or credential-store collection path was found in the reviewed
default build. This targeted review is not a comprehensive security audit.

Local validation: the official source compiled on WSL x86_64, and the resulting
native ELF genuinely signed a 64-bit arm64 Mach-O fixture; all 13 signed code
pages independently matched their SHA256 values. Ubuntu's missing static
libplist archive prevented a local static build, so native Alpine ARM64 static
compilation is a separate required build step, not a completed local claim.
