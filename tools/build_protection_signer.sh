#!/bin/sh
# Native Alpine static build. Never calls make install or a downloaded installer.
set -eu
cd /work
test "$(uname -m)" = aarch64
SOURCE=/work/ldid-source.tar
OUT=/work/protection-signer
EXPECTED_SOURCE_SHA256=e72498269d04dea5618d889dfefc95652f3cc39cbcf92cdc9b3eb9ecd0fb2d72
printf '%s  %s\n' "$EXPECTED_SOURCE_SHA256" "$SOURCE" | sha256sum -c -
apk add --no-cache build-base pkgconf openssl-dev openssl-libs-static libplist-dev libplist-static python3 file binutils
mkdir -p "$OUT"
BUILD=$(mktemp -d /work/ldid-build.XXXXXX)
tar -xf "$SOURCE" -C "$BUILD"
make -C "$BUILD/ldid" -j 3 VERSION=2.1.5-procursus7-af86971 \
  LDFLAGS='-static -static-libgcc -static-libstdc++' \
  LIBCRYPTO_LIBS="$(pkg-config --static --libs libcrypto)" \
  LIBPLIST_LIBS="$(pkg-config --static --libs libplist-2.0)"
cp "$BUILD/ldid/ldid" "$OUT/ldid"
cp "$BUILD/ldid/ldid.cpp.o" "$OUT/ldid.cpp.o"
cp "$BUILD/ldid/COPYING" "$OUT/ldid-COPYING"
file "$OUT/ldid" | tee "$OUT/file.txt"
grep -q 'statically linked' "$OUT/file.txt"
readelf -l "$OUT/ldid" > "$OUT/program-headers.txt"
! grep -q 'INTERP' "$OUT/program-headers.txt"
"$OUT/ldid" > "$OUT/version.txt" 2>&1
apk info -v build-base openssl-dev openssl-libs-static libplist-dev libplist-static > "$OUT/build-dependencies.txt"
PROBE_DYLIB=${PROBE_DYLIB:-/work/protection-native/all-five.dylib}
test -f "$PROBE_DYLIB"
cp "$PROBE_DYLIB" "$OUT/signing-probe.dylib"
"$OUT/ldid" -r "$OUT/signing-probe.dylib"
sha256sum "$OUT/signing-probe.dylib" > "$OUT/unsigned-sha256.txt"
cat > "$OUT/fixture-entitlements.plist" <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict><key>com.minisre.protection.fixture</key><true/></dict></plist>
EOF
"$OUT/ldid" -Cadhoc -S"$OUT/fixture-entitlements.plist" "$OUT/signing-probe.dylib"
"$OUT/ldid" -h "$OUT/signing-probe.dylib" > "$OUT/cdhash.txt" 2>&1
"$OUT/ldid" -e "$OUT/signing-probe.dylib" > "$OUT/extracted-entitlements.plist"
python3 /work/verify_macho_code_directory.py "$OUT/signing-probe.dylib" --output "$OUT/code-directory-verification.json"
python3 - <<'PY'
import hashlib,json,pathlib,plistlib
p=pathlib.Path('/work/protection-signer')
r=json.loads((p/'code-directory-verification.json').read_text())
assert r['codePageHashesVerified'] and r['entitlements']['com.minisre.protection.fixture'] is True
assert plistlib.loads((p/'extracted-entitlements.plist').read_bytes())['com.minisre.protection.fixture'] is True
assert (p/'unsigned-sha256.txt').read_text().split()[0]!=r['sha256']
result={'source':'https://github.com/ProcursusTeam/ldid','commit':'af86971ae72ec3ed3d0a699107c4e882324c941b',
        'sourceSHA256':hashlib.sha256(pathlib.Path('/work/ldid-source.tar').read_bytes()).hexdigest(),
        'binarySHA256':hashlib.sha256((p/'ldid').read_bytes()).hexdigest(),
        'platform':'aarch64-linux-musl','static':True,'adHocSigning':True,
        'codePageHashesVerified':True,'entitlementsRoundTrip':True,'phone_test':False,
        'appleCertificateTrustVerified':False}
(p/'verification.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result))
PY
