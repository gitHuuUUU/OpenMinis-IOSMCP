#!/bin/sh
# Actual native execution/IR/link regression, not a static UI check.
set -eu
WORKDIR=${WORKDIR:-/work/protection-native}
DRIVER=${DRIVER:-/work/bundle/runtime/clang.py}
LLVM_BIN=${LLVM_BIN:-/usr/lib/llvm19/bin}
PLUGIN=${PLUGIN:-/work/bundle/runtime/libMinisProtection.so}
mkdir -p "$WORKDIR"
cd "$WORKDIR"
export LLVM_BIN PLUGIN

cat > fixture.c <<'EOF'
#include <stdio.h>
volatile int counter = 3;
static int values[] = {2, 5, 11, 17};
static const char message[] = "MINIS_FIVE_PASS_SEMANTICS";
_Thread_local int tls_counter = 7;
__attribute__((section(".minis_fixture"))) volatile int abi_counter = 4;
__attribute__((noinline)) int leaf(int x) {
  counter += x & 1;
  if (x < 0) return values[1] - x + tls_counter;
  return values[(unsigned)x % 4] + counter + abi_counter;
}
__attribute__((noinline)) int dispatch(int x) {
  return leaf(x) + leaf(x - 3);
}
int main(void) {
  int total = 0;
  for (int i = -2; i < 8; ++i) total += dispatch(i);
  printf("FIVE_PASS_PROBE:%s:%d:%d:%d\n", message, total, counter, tls_counter);
  return total == 0;
}
EOF
python3 "$DRIVER" fixture.c -o plain
./plain > plain.txt
COMBINATIONS=$(python3 - <<'PY'
from itertools import combinations
passes=('bcf','indcall','indgv','sobf','fla')
for count in range(1,6):
    for selection in combinations(passes,count): print(','.join(selection))
PY
)
for passes in $COMBINATIONS; do
  flags=""
  for pass in $(printf '%s' "$passes" | tr ',' ' '); do
    flags="$flags -mllvm -$pass"
  done
  # shellcheck disable=SC2086
  python3 "$DRIVER" $flags fixture.c -o "native-$passes"
  "./native-$passes" > "native-$passes.txt"
  cmp plain.txt "native-$passes.txt"
  # shellcheck disable=SC2086
  python3 "$DRIVER" $flags -S -emit-llvm fixture.c -o "$passes.ll"
  "$LLVM_BIN/opt" -passes=verify "$passes.ll" -disable-output
done

# Unlike an ignored command-line flag, these passes must change the real IR.
python3 - <<'PY'
import json,pathlib,re
root=pathlib.Path('.')
from itertools import combinations
all_passes=('bcf','indcall','indgv','sobf','fla')
for name in (','.join(c) for count in range(1,6) for c in combinations(all_passes,count)):
    text=(root/(name+'.ll')).read_text()
    if 'indcall' in name:
        assert re.search(r'@minis_indcall_targets\S*\s*=\s*private global',text),name
        assert 'minis.indcall.target' in text and 'load volatile ptr' in text,name
        assert re.search(r'call[^\n]*%minis\.indcall\.target',text),name
    if 'indgv' in name:
        assert re.search(r'@minis_indgv_targets\S*\s*=\s*private global',text),name
        assert 'minis.indgv.target' in text and 'load volatile ptr' in text,name
    if 'sobf' in name:
        assert 'MINIS_FIVE_PASS_SEMANTICS' not in text,name
    if 'fla' in name:
        assert 'switch ' in text,name
print('Single and combined pass IR evidence passed')
PY

# Invoke/exception edges and C++ calling conventions survive operand mutation.
cat > exception.cpp <<'EOF'
#include <cstdio>
#include <stdexcept>
static int protected_data = 11;
__attribute__((noinline)) int may_throw(int value) {
  if (value < 0) throw std::runtime_error("fixture exception");
  return value + protected_data;
}
int main() {
  int result = may_throw(7);
  try { result += may_throw(-1); }
  catch (const std::exception &) { result += 3; }
  std::printf("EXCEPTION_PROBE:%d\n",result);
  return result != 21;
}
EOF
"$LLVM_BIN/clang++" -O0 -Xclang -disable-O0-optnone -emit-llvm -c exception.cpp -o exception.raw.bc
"$LLVM_BIN/opt" -load-pass-plugin="$PLUGIN" -passes=minis-indcall,minis-indgv,verify exception.raw.bc -S -o exception.ll
"$LLVM_BIN/clang++" -O0 exception.ll -o exception
./exception > exception.txt
grep -q '^EXCEPTION_PROBE:21$' exception.txt
grep -q 'invoke.*%minis.indcall.target' exception.ll

cat > edges.ll <<'EOF'
@ordinary = global i32 3
@tls_data = thread_local global i32 6
@reserved = global i32 4, section ".minis_abi"
@letters = global [4 x i8] c"abc\00"
declare i32 @llvm.abs.i32(i32, i1 immarg)
define i32 @leaf(i32 %x) { ret i32 %x }
define i32 @tail(i32 %x) {
  %r = musttail call i32 @leaf(i32 %x)
  ret i32 %r
}
define i32 @edges(i32 %x) {
  %a = load i32, ptr @tls_data
  %b = load i32, ptr @reserved
  %c = load i32, ptr @ordinary
  %d = call i32 @llvm.abs.i32(i32 %x, i1 false)
  call void asm sideeffect "", ""()
  %e = call i32 @leaf(i32 %d)
  %f = load i8, ptr getelementptr ([4 x i8], ptr @letters, i32 0, i32 1)
  %g = zext i8 %f to i32
  %h = add i32 %a, %b
  %i = add i32 %c, %e
  %j = add i32 %h, %i
  %k = add i32 %j, %g
  ret i32 %k
}
EOF
"$LLVM_BIN/opt" -load-pass-plugin="$PLUGIN" -passes=minis-indcall,minis-indgv,verify -S edges.ll -o edges.protected.ll
# A second invocation must not recursively protect our own tables.
"$LLVM_BIN/opt" -load-pass-plugin="$PLUGIN" -passes=minis-indcall,minis-indgv,verify -S edges.protected.ll -o edges.twice.ll
python3 - <<'PY'
from pathlib import Path
text=Path('edges.protected.ll').read_text()
assert 'load i32, ptr @tls_data' in text
assert 'load i32, ptr @reserved' in text
assert 'call i32 @llvm.abs.i32' in text
assert 'call void asm sideeffect' in text
assert 'musttail call i32 @leaf' in text
for name in ('edges.protected.ll','edges.twice.ll'):
    body=Path(name).read_text()
    for symbol in ('minis_indcall_targets','minis_indgv_targets'):
        assert len([line for line in body.splitlines() if line.startswith('@'+symbol) and '= private global' in line])==1
print('Intrinsic/TLS/section/musttail/inline-asm/constant-GEP/idempotency checks passed')
PY

# All five selected passes must also codegen/link for the real iOS target.
cat > dylib.c <<'EOF'
static volatile int shared = 9;
static int offsets[] = {2, 3, 5, 7};
__attribute__((noinline)) int helper(int x) {
  return offsets[(unsigned)x % 4] + shared;
}
int minis_protected_entry(int x) { return x > 2 ? helper(x) : helper(x + 1); }
EOF
python3 "$DRIVER" -mllvm -bcf -mllvm -indcall -mllvm -indgv -mllvm -sobf -mllvm -fla \
  --target=arm64-apple-ios15.4 -fuse-ld=lld -dynamiclib -nostdlib dylib.c -o all-five.dylib
"$LLVM_BIN/llvm-objdump" --macho --disassemble all-five.dylib > all-five.disassembly.txt
python3 - <<'PY'
import json,pathlib,platform,re,struct
p=pathlib.Path('all-five.dylib');raw=p.read_bytes()
magic,cpu,subtype,filetype=struct.unpack_from('<IIII',raw)
assert magic==0xfeedfacf and cpu==0x0100000c and filetype==6
assert re.search(r'\bblr\s+x\d+',pathlib.Path('all-five.disassembly.txt').read_text())
result={'schema':1,'engine':'MinisProtection LLVM19 IR-only','native_arch':platform.machine(),
        'native_single_and_combined_execution':31,'ir_transformation_checked':True,
        'cpp_exception_invoke':True,'intrinsic_tls_reserved_section_musttail_inlineasm_preserved':True,
        'constant_gep_materialized':True,'idempotency':True,
        'all_five_ios154_arm64_macho_dylib':True,'macho_indirect_blr':True,'phone_test':False,
        'limits':'Pointer-table indirection, not cryptographic secrecy or protection of every call/data form.'}
pathlib.Path('verification.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result))
PY
