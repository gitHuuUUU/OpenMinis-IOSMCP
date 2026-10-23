#!/bin/sh
set -eu
cd /work
exec > /work/ollvm-build.log 2>&1
apk add --no-cache clang19 llvm19-dev llvm19 lld cmake ninja g++ python3 file
test "$(uname -m)" = aarch64
cat /etc/alpine-release
mkdir -p build bundle/apks bundle/runtime bundle/licenses
cat > hikari/CMakeLists.txt <<'EOF'
cmake_minimum_required(VERSION 3.20)
project(MinisReHikari LANGUAGES C CXX)
execute_process(COMMAND /usr/lib/llvm19/bin/llvm-config --includedir OUTPUT_VARIABLE LLVM_HEADERS OUTPUT_STRIP_TRAILING_WHITESPACE COMMAND_ERROR_IS_FATAL ANY)
execute_process(COMMAND /usr/lib/llvm19/bin/llvm-config --link-shared --libfiles OUTPUT_VARIABLE LLVM_SHARED OUTPUT_STRIP_TRAILING_WHITESPACE COMMAND_ERROR_IS_FATAL ANY)
include_directories(${LLVM_HEADERS} ${CMAKE_SOURCE_DIR}/obfuscation)
file(GLOB SOURCES "obfuscation/*.cpp")
add_library(Hikari SHARED ${SOURCES})
set_target_properties(Hikari PROPERTIES CXX_STANDARD 17)
target_compile_definitions(Hikari PRIVATE GIT_COMMIT_HASH="5dd3902a0f2c74570e0ab7a637c57a3cccaed9fd")
target_compile_options(Hikari PRIVATE -fno-rtti)
target_link_libraries(Hikari PRIVATE ${LLVM_SHARED})
EOF
cmake -S hikari -B build -G Ninja -DLLVM_DIR=/usr/lib/llvm19/lib/cmake/llvm -DCMAKE_BUILD_TYPE=Release -DCMAKE_C_COMPILER=clang-19 -DCMAKE_CXX_COMPILER=clang++-19
cmake --build build -j 3
cp build/libHikari.so bundle/runtime/
cp clang.py bundle/runtime/clang.py
cp hikari/LICENSE bundle/licenses/Hikari-LICENSE
apk update
apk fetch --recursive --output bundle/apks clang19 llvm19 llvm19-libs lld python3
tar -xf iPhoneOS15.6.sdk.tar.xz
cat > probe.c <<'EOF'
#include <stdio.h>
__attribute__((noinline)) int calc(int x) {
  if(x>5) return x*3+2;
  if(x<0) return x-7;
  return x+11;
}
int main(void) { printf("OLLVM_SECRET_8c02:%d\n", calc(8)); return calc(8)!=26; }
EOF
python3 bundle/runtime/clang.py probe.c -o plain
./plain > plain.txt
for passes in bcf fla sobf bcf,sobf bcf,fla,sobf; do
  flags=""
  for pass in $(echo "$passes" | tr ',' ' '); do flags="$flags -mllvm -$pass"; done
  python3 bundle/runtime/clang.py $flags probe.c -o protected
  ./protected > protected.txt
  cmp plain.txt protected.txt
  python3 bundle/runtime/clang.py $flags --target=arm64-apple-ios15.4 -isysroot /work/iPhoneOS15.6.sdk -fuse-ld=lld -dynamiclib probe.c -framework Foundation -o probe.dylib
  file probe.dylib | grep 'Mach-O'
  python3 bundle/runtime/clang.py $flags -S -emit-llvm probe.c -o "probe-$passes.ll"
done
! grep -q 'OLLVM_SECRET_8c02' probe-sobf.ll
grep -q 'switch' probe-fla.ll
python3 - <<'PY'
import hashlib,json,pathlib,subprocess
root=pathlib.Path('bundle');files=[]
for p in sorted(root.rglob('*')):
 if p.is_file():
  files.append({'path':p.relative_to(root).as_posix(),'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()})
manifest={'schema':1,'engine':'Hikari-LLVM19','source':'https://github.com/PPKunOfficial/Hikari-fix','commit':'5dd3902a0f2c74570e0ab7a637c57a3cccaed9fd','platform':'aarch64-linux-musl','alpine':'3.21','passes':['bcf','fla','sobf'],'files':files,'verification':{'native_execution':True,'mach_o_dylib_link':True,'string_ir_checked':True,'flattening_ir_checked':True,'phone_test':False},'clang':subprocess.check_output(['/usr/lib/llvm19/bin/clang','--version'],text=True).splitlines()[0]}
(root/'manifest.json').write_text(json.dumps(manifest,indent=2))
PY
python3 install.py install --bundle /work/bundle
python3 install.py ensure --bundle /work/bundle
/opt/minis-protection/bin/clang -mllvm -bcf -mllvm -sobf probe.c -o installed-probe
./installed-probe > installed.txt
cmp plain.txt installed.txt
tar -czf /work/ollvm-alpine321-aarch64.tar.gz bundle
sha256sum /work/ollvm-alpine321-aarch64.tar.gz
