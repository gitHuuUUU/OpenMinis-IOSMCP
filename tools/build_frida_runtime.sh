#!/bin/sh
set -eu
VERSION=17.24.1
DEVKIT_SHA256=fce34c2fd41ea734c8d02612aeae6476cfd5cb4fbbec578bcc31334f6a6cb6f7
SDIST_SHA256=20fbe24c2569a792efc884240251e2ba81402f5753531c0e1b388b01217789cf
BASE=${1:-/work}
mkdir -p "$BASE/sources" "$BASE/devkit" "$BASE/gir" "$BASE/wheelhouse" "$BASE/logs"
cd "$BASE"
exec > "$BASE/logs/build.log" 2>&1
cat /etc/alpine-release
uname -m
apk add --no-cache python3 python3-dev py3-pip py3-setuptools py3-wheel build-base pkgconf meson samurai glib-dev gobject-introspection-dev libffi-dev curl tar xz
if [ ! -s "sources/frida-core-devkit-$VERSION-linux-arm64-musl.tar.xz" ]; then curl -fL --retry 3 -o "sources/frida-core-devkit-$VERSION-linux-arm64-musl.tar.xz" "https://github.com/frida/frida/releases/download/$VERSION/frida-core-devkit-$VERSION-linux-arm64-musl.tar.xz"; fi
echo "$DEVKIT_SHA256  sources/frida-core-devkit-$VERSION-linux-arm64-musl.tar.xz" | sha256sum -c -
if [ ! -s "sources/frida-$VERSION.tar.gz" ]; then curl -fL --retry 3 -o "sources/frida-$VERSION.tar.gz" "https://files.pythonhosted.org/packages/source/f/frida/frida-$VERSION.tar.gz"; fi
echo "$SDIST_SHA256  sources/frida-$VERSION.tar.gz" | sha256sum -c -
tar -xJf sources/frida-core-devkit-$VERSION-linux-arm64-musl.tar.xz -C devkit
# The devkit substitutes g_str_equal with a function-like macro, but generated binding C passes its function pointer.
sed -i "/^#undef g_str_equal$/d; /^#define g_str_equal(v1, v2)/d" devkit/frida-core.h
tar -xzf sources/frida-$VERSION.tar.gz -C sources
cp devkit/frida-core.gir gir/Frida-1.0.gir
for n in GLib GObject Gio; do cp "/usr/share/gir-1.0/$n-2.0.gir" gir/; done
mkdir -p devkit/pkgconfig
cat > devkit/pkgconfig/frida-core-1.0.pc <<EOF
prefix=$BASE/devkit
libdir=\${prefix}
includedir=\${prefix}
frida_girdir=$BASE/gir

Name: frida-core
Description: Frida Core static devkit
Version: $VERSION
Requires: gio-2.0 gobject-2.0 glib-2.0
Libs: -L\${libdir} -lfrida-core -ldl -lm -latomic -pthread -Wl,--export-dynamic
Cflags: -I\${includedir}
EOF
export PKG_CONFIG_PATH="$BASE/devkit/pkgconfig"
pkgconf --modversion frida-core-1.0
pkgconf --cflags --libs frida-core-1.0
cd "$BASE/sources/frida-$VERSION"
python3 -m mesonbuild.mesonmain setup "$BASE/meson-build" . --buildtype=release
python3 -m mesonbuild.mesonmain compile -C "$BASE/meson-build" -v
EXTENSION=$(find "$BASE/meson-build/frida" -maxdepth 1 -name '_frida*.so' -print -quit)
test -n "$EXTENSION"
export FRIDA_EXTENSION="$EXTENSION"
python3 setup.py bdist_wheel --py-limited-api=cp37 --dist-dir "$BASE/wheelhouse"
python3 - <<PY
import glob,sys,zipfile
p=glob.glob("$BASE/wheelhouse/frida-*.whl")
assert len(p)==1,p
print("wheel:",p[0])
with zipfile.ZipFile(p[0]) as z:
 print("extension:",[x for x in z.namelist() if x.endswith(".so")])
PY
sha256sum "$BASE"/wheelhouse/*.whl > "$BASE/wheelhouse/SHA256SUMS"




python3 -m pip wheel --no-build-isolation --find-links "$BASE/wheelhouse" --wheel-dir "$BASE/wheelhouse" "frida==17.24.1" "frida-tools==14.11.0"
python3 -m pip install --break-system-packages --no-index --find-links "$BASE/wheelhouse" "frida==17.24.1" "frida-tools==14.11.0"
python3 - <<'PY'
import frida
assert frida.__version__ == "17.24.1", frida.__version__
print("frida import/version:", frida.__version__)
try:
    devices = frida.get_device_manager().enumerate_devices()
    print("enumerate_devices:", [(d.id, d.type) for d in devices])
except Exception as e:
    print("enumerate_devices failed in container:", repr(e))
PY
frida --version
frida-ps --version
mkdir -p "$BASE/bundle/wheels"
cp "$BASE"/wheelhouse/*.whl "$BASE/bundle/wheels/"
python3 - "$BASE/bundle" <<'PY'
import hashlib, json, pathlib, sys
base = pathlib.Path(sys.argv[1])
wheels = []
for p in sorted((base / "wheels").glob("*.whl")):
    wheels.append({"filename": p.name, "bytes": p.stat().st_size, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()})
assert any(x["filename"].startswith("frida-17.24.1-") for x in wheels)
assert any(x["filename"].startswith("frida_tools-14.11.0-") for x in wheels)
(base / "manifest.json").write_text(json.dumps({
    "frida_version": "17.24.1",
    "frida_tools_version": "14.11.0",
    "python_major_minor": "3.12",
    "wheels": wheels,
}, indent=2) + "\n")
print("bundle wheels:", len(wheels))
PY
sha256sum "$BASE"/bundle/wheels/*.whl > "$BASE/bundle/SHA256SUMS"

