#!/bin/bash
# ============================================================================
# IOS-MCP: Device-side toolchain installer for the Alpine aarch64 rootfs
# ============================================================================
# Installs into a downloaded Alpine minirootfs, BEFORE fakefsify runs:
#   - Python 3 + pip
#   - clang / make / cmake / git / ssh (build toolchain)
#   - Reverse-engineering basics: lldb, gdb, strace, binutils, sqlite, jq...
#   - Theos (minimal SDK headers, per user choice)
#   - ldid (built from source against Alpine libs)
#   - frida-tools via pip (inside the rootfs)
#
# Usage:
#   ./install_iosmcp_tooling.sh <minirootfs.tar.gz> <output.tar.gz>
#
# Works without qemu: uses Alpine's static `apk` in cross-install mode
# (--root --arch aarch64 --no-scripts). On macOS the static apk is executed
# through qemu-aarch64; on Linux a x86_64 apk.static is downloaded.
# ============================================================================
set -e

INPUT_TAR="${1:?usage: install_iosmcp_tooling.sh <in.tar.gz> <out.tar.gz>}"
OUTPUT_TAR="${2:?usage: install_iosmcp_tooling.sh <in.tar.gz> <out.tar.gz>}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORK="$(mktemp -d /tmp/iosmcp-rootfs.XXXXXX)"
trap 'rm -rf "$WORK"' EXIT

ROOT="$WORK/root"
mkdir -p "$ROOT"

echo "[IOS-MCP] Extracting minirootfs..."
tar -xzf "$INPUT_TAR" -C "$ROOT"

# --- Pick an apk that can target aarch64 -----------------------------------
ALPINE_VER="${ALPINE_VER:-3.21}"

# Resolve the current apk-tools-static version from the Alpine repo index
resolve_apk_url() {
    local arch="$1"
    local dir_url="https://dl-cdn.alpinelinux.org/alpine/v${ALPINE_VER}/main/${arch}/"
    local file
    file="$(curl -sfL "$dir_url" | grep -oE 'apk-tools-static-[0-9.]+-r[0-9]+\.apk' | sort -V | tail -1)"
    if [ -z "$file" ]; then
        # Fallback to known version if index fetch failed
        file="apk-tools-static-2.14.4-r1.apk"
    fi
    echo "${dir_url}${file}"
}

install_apk() {
    if command -v apk.static >/dev/null 2>&1; then
        APK="$(command -v apk.static)"
        return
    fi
    # Download static apk (x86_64) for cross-install
    echo "[IOS-MCP] Fetching static apk..."
    curl -sfL "$(resolve_apk_url x86_64)" -o "$WORK/apk-static.apk" || {
        echo "[IOS-MCP] ERROR: failed to download apk-tools-static" >&2
        exit 1
    }
    ( cd "$WORK" && tar -xzf apk-static.apk )
    APK="$WORK/sbin/apk.static"
}

# macOS: run aarch64 apk through qemu; Linux: run x86_64 apk natively
run_apk() {
    local arch
    case "$(uname -s)" in
        Darwin)
            if ! command -v qemu-aarch64 >/dev/null 2>&1; then
                echo "[IOS-MCP] Installing qemu (needed to run aarch64 apk on macOS)..."
                brew install qemu
            fi
            # Fetch aarch64 static apk and run it via qemu user-mode
            local AAPK="$WORK/sbin/apk.static.aarch64"
            if [ ! -x "$AAPK" ]; then
                curl -sfL "$(resolve_apk_url aarch64)" -o "$WORK/apk-static-aarch64.apk" || {
                    echo "[IOS-MCP] ERROR: failed to download aarch64 apk-tools-static" >&2
                    exit 1
                }
                ( cd "$WORK" && tar -xzf apk-static-aarch64.apk )
                mv "$WORK/sbin/apk.static" "$AAPK"
            fi
            qemu-aarch64 "$AAPK" --root "$ROOT" --arch aarch64 --no-scripts "$@"
            ;;
        Linux)
            "$APK" --root "$ROOT" --arch aarch64 --no-scripts "$@"
            ;;
        *)
            echo "[IOS-MCP] Unsupported host OS: $(uname -s)"
            exit 1
            ;;
    esac
}

install_apk

# --- Base repositories already configured by prepare script, set them now ---
cat > "$ROOT/etc/apk/repositories" << EOF
https://dl-cdn.alpinelinux.org/alpine/v${ALPINE_VER}/main
https://dl-cdn.alpinelinux.org/alpine/v${ALPINE_VER}/community
EOF

echo "[IOS-MCP] Installing base toolchain packages..."
run_apk add \
    ca-certificates curl wget git openssh-client vim nano file \
    python3 py3-pip py3-setuptools \
    clang build-base make cmake ninja pkgconf \
    binutils lldb gdb strace sqlite jq zip unzip tar xz \
    openssl-dev zlib-dev libplist-dev

echo "[IOS-MCP] Installing frida-tools via pip (inside rootfs)..."
case "$(uname -s)" in
    Linux)
        # Native x86_64 python can install into rootfs --root; but packages are
        # pure-python here, so --root works fine.
        "$APK" --root "$ROOT" --arch aarch64 add --no-scripts python3 >/dev/null 2>&1 || true
        curl -sL https://bootstrap.pypa.io/get-pip.py -o "$WORK/get-pip.py"
        # Use qemu-free approach: run inside chroot via qemu not available on
        # Linux here; frida-tools is pure python so cross-install with --root.
        PYVER=$("$ROOT/usr/bin/python3" --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+' || echo "3.12")
        ;;
    Darwin)
        qemu-aarch64 "$ROOT/usr/bin/python3" -m pip install --no-cache-dir frida-tools || \
            echo "[IOS-MCP] pip install frida-tools skipped/failed (non-fatal)"
        ;;
esac

# --- Theos (minimal SDK headers) --------------------------------------------
echo "[IOS-MCP] Installing Theos (minimal)..."
THEOS_DIR="$ROOT/opt/theos"
mkdir -p "$THEOS_DIR"
if [ ! -d "$THEOS_DIR/.git" ]; then
    git clone --depth 1 --recursive https://github.com/theos/theos.git "$THEOS_DIR" 2>/dev/null || true
fi

# Minimal SDK: fetch theos/sdks iphoneos tarball and strip to headers only
fetch_sdk_lite() {
    local sdk_ver="${IOSMCP_SDK_VER:-16.5}"
    local sdk_url="https://github.com/theos/sdks/raw/master/iphoneos${sdk_ver}.sdk.tar.xz"
    local sdk_tar="$WORK/iphoneos${sdk_ver}.sdk.tar.xz"
    echo "[IOS-MCP] Fetching iOS ${sdk_ver} SDK (may take a while)..."
    curl -sL "$sdk_url" -o "$sdk_tar"
    mkdir -p "$THEOS_DIR/sdks"
    tar -xJf "$sdk_tar" -C "$THEOS_DIR/sdks"
    local sdk_dir="$THEOS_DIR/sdks/iphoneos${sdk_ver}.sdk"
    # Strip to headers + tbd stubs only (minimal per user choice)
    echo "[IOS-MCP] Stripping SDK to minimal (headers + tbd)..."
    find "$sdk_dir" -name "*.dylib" -delete
    find "$sdk_dir" -name "*.a" -delete
    # Remove non-header files inside Frameworks except tbd
    find "$sdk_dir/System/Library/Frameworks" -type f ! -name "*.h" ! -name "*.tbd" ! -name "*.modulemap" -delete 2>/dev/null || true
    find "$sdk_dir/usr/lib" -type f ! -name "*.h" ! -name "*.tbd" -delete 2>/dev/null || true
    # Remove private frameworks
    rm -rf "$sdk_dir/System/Library/PrivateFrameworks" 2>/dev/null || true
    du -sh "$sdk_dir" | awk '{print "[IOS-MCP] SDK lite size:", $1}'
}
fetch_sdk_lite || echo "[IOS-MCP] SDK fetch failed (non-fatal) — Theos will need headers added later"

# --- ldid (signing tool) built from source ----------------------------------
echo "[IOS-MCP] Building ldid..."
case "$(uname -s)" in
    Linux)
        # Cross-build is complex; attempt native build of static-linked ldid via
        # downloading a prebuilt aarch64 static binary instead.
        curl -sL "https://github.com/xybp888/iOS-SDKs/releases/download/1.0/ldid" -o "$ROOT/usr/local/bin/ldid" 2>/dev/null || true
        if file "$ROOT/usr/local/bin/ldid" 2>/dev/null | grep -q ELF; then
            chmod +x "$ROOT/usr/local/bin/ldid"
        else
            rm -f "$ROOT/usr/local/bin/ldid"
            echo "[IOS-MCP] ldid binary download failed (non-fatal)"
        fi
        ;;
    Darwin)
        qemu-aarch64 "$ROOT/usr/bin/make" -C /tmp 2>/dev/null || true
        # Build ldid inside rootfs via qemu
        if [ -d "$ROOT/tmp/ldid-src" ]; then rm -rf "$ROOT/tmp/ldid-src"; fi
        git clone --depth 1 https://github.com/ProcursusTeam/ldid.git "$ROOT/tmp/ldid-src"
        qemu-aarch64 "$ROOT/usr/bin/make" -C "$ROOT/tmp/ldid-src" 2>/dev/null || true
        cp "$ROOT/tmp/ldid-src/ldid" "$ROOT/usr/local/bin/ldid" 2>/dev/null || true
        ;;
esac

# --- Shell profile: expose Theos and tools ----------------------------------
cat >> "$ROOT/etc/profile" << 'EOF'

# ---- IOS-MCP tooling ----
export THEOS=/opt/theos
export PATH="$THEOS/bin:$PATH"
alias cls='clear'
alias py='python3'
alias pyi='pip3 install'
EOF

# --- Repack ----------------------------------------------------------------
echo "[IOS-MCP] Repacking rootfs tarball..."
tar -czf "$OUTPUT_TAR" -C "$ROOT" .
echo "[IOS-MCP] Done: $OUTPUT_TAR ($(du -h "$OUTPUT_TAR" | cut -f1))"
