#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
SDK="${IOS_SDK:-/root/theos/sdks/iPhoneOS16.5.sdk}"
OUT="$ROOT/build"
LDID="${LDID:-$ROOT/work/toolchain/ldid/ldid}"
if [[ ! -x "$LDID" ]]; then
  echo "Missing real ldid: $LDID (see README.md)" >&2
  exit 1
fi
mkdir -p "$OUT"
for file in FrostMenu PvZFeatures Availability; do
  /usr/bin/clang -target arm64-apple-ios12.0 -isysroot "$SDK" \
    -fobjc-arc -fmodules -O2 -Wall -Wextra -Werror=unguarded-availability-new \
    -Wno-unused-parameter -c "$ROOT/src/$file.m" -o "$OUT/$file.o"
done
/usr/bin/ld64.lld -arch arm64 -platform_version ios 12.0 16.5 \
  -dylib -syslibroot "$SDK" -install_name @rpath/FrostMenu.dylib -dead_strip \
  -o "$OUT/FrostMenu.dylib" "$OUT/FrostMenu.o" "$OUT/PvZFeatures.o" "$OUT/Availability.o" \
  -framework UIKit -framework Foundation -framework QuartzCore -framework WebKit -lobjc -lSystem
"$LDID" -S -Cadhoc "$OUT/FrostMenu.dylib"
file "$OUT/FrostMenu.dylib"
sha256sum "$OUT/FrostMenu.dylib"
