#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
# Reuse the exact libarchive revision pinned by the iSH submodule.
SOURCE="$PWD/deps/ish/deps/libarchive"
SDK="$(xcrun --sdk iphoneos --show-sdk-path)"
cmake -S "$SOURCE" -B deps/archive-ios -G Ninja \
  -DCMAKE_POLICY_VERSION_MINIMUM=3.5 -DCMAKE_TRY_COMPILE_TARGET_TYPE=STATIC_LIBRARY \
  -DCMAKE_SYSTEM_NAME=iOS -DCMAKE_OSX_SYSROOT="$SDK" \
  -DCMAKE_OSX_ARCHITECTURES=arm64 -DCMAKE_OSX_DEPLOYMENT_TARGET=15.4 \
  -DCMAKE_BUILD_TYPE=Release -DENABLE_TEST=OFF -DENABLE_TAR=OFF \
  -DENABLE_CPIO=OFF -DENABLE_CAT=OFF -DENABLE_OPENSSL=OFF \
  -DENABLE_MBEDTLS=OFF -DENABLE_NETTLE=OFF -DENABLE_LIBB2=OFF \
  -DENABLE_LZ4=OFF -DENABLE_LZO=OFF -DENABLE_LZMA=OFF -DENABLE_ZSTD=OFF \
  -DENABLE_BZip2=OFF -DENABLE_LIBXML2=OFF -DENABLE_EXPAT=OFF \
  -DENABLE_PCREPOSIX=OFF -DENABLE_ICONV=OFF -DENABLE_ACL=OFF \
  -DENABLE_XATTR=OFF -DENABLE_WERROR=OFF
cmake --build deps/archive-ios --target archive_static --parallel 3
mkdir -p deps/libs deps/include
cp deps/archive-ios/libarchive/libarchive.a deps/libs/libminisarchive.a
cp "$SOURCE/libarchive/archive.h" "$SOURCE/libarchive/archive_entry.h" deps/include/
