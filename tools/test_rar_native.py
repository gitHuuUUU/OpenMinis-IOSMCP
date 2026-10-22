"""Exercise the production Objective-C reader with real stored RAR4 bytes on macOS."""
import binascii, pathlib, shutil, struct, subprocess, tempfile, zlib
ROOT = pathlib.Path(__file__).resolve().parents[1]

def header(kind, flags, payload=b"", extra=b""):
    raw = struct.pack("<BHH", kind, flags, 7 + len(payload)) + payload
    return struct.pack("<H", zlib.crc32(raw) & 65535) + raw + extra

def rar(files):
    data = b"Rar!\x1a\x07\x00" + header(0x73, 0, b"\0" * 6)
    for name, body in files:
        raw = name.encode("utf8")
        payload = struct.pack("<IIBIIBBHI", len(body), len(body), 3, zlib.crc32(body), 0, 20, 0x30, len(raw), 0o100644) + raw
        data += header(0x74, 0x8000, payload, body)
    return data + header(0x7b, 0)

def main():
    if not shutil.which("xcrun"):
        raise SystemExit("macOS compiler and Homebrew libarchive required; native test NOT RUN")
    prefix = subprocess.check_output(["brew", "--prefix", "libarchive"], text=True).strip()
    with tempfile.TemporaryDirectory() as folder:
        d = pathlib.Path(folder)
        (d/"valid.rar").write_bytes(rar([("instructions.md", b"Use concise summaries.")]))
        (d/"traversal.rar").write_bytes(rar([("../escape.md", b"no")]))
        (d/"duplicate.rar").write_bytes(rar([("x.md", b"one"), ("X.md", b"two")]))
        (d/"broken.rar").write_bytes(b"not an archive")
        fixtures = ROOT/"deps/ish/deps/libarchive/libarchive/test"
        for mode in ["stored", "compressed"]:
            lines = (fixtures/("test_read_format_rar5_" + mode + ".rar.uu")).read_bytes().splitlines()
            start = next(i for i,line in enumerate(lines) if line.startswith(b"begin ")) + 1
            data = bytearray()
            for line in lines[start:]:
                if line == b"end": break
                data.extend(binascii.a2b_uu(line))
            (d/("rar5-"+mode+".rar")).write_bytes(data)
        (d/"main.m").write_text(r'''#import <Foundation/Foundation.h>
#import "WorkbenchBridge.h"
int main(int argc, char **argv) { @autoreleasepool {
    NSString *root = [NSString stringWithUTF8String:argv[1]];
    for (NSString *name in @[@"valid", @"traversal", @"duplicate", @"broken", @"rar5-stored", @"rar5-compressed"]) {
        NSError *error = nil;
        NSData *data = [NSData dataWithContentsOfFile:[root stringByAppendingPathComponent:[name stringByAppendingString:@".rar"]]];
        NSDictionary *files = [MinisDeviceBridge readRAR:data error:&error];
        if ([name isEqualToString:@"valid"]) {
            if (error || ![files[@"instructions.md"] isEqualToData:[@"Use concise summaries." dataUsingEncoding:NSUTF8StringEncoding]]) return 1;
        } else if ([name hasPrefix:@"rar5-"]) {
            if (error || !files.count) return 3;
            if ([name isEqualToString:@"rar5-stored"] && ![files[@"helloworld.txt"] isEqualToData:[@"hello libarchive test suite!\n" dataUsingEncoding:NSUTF8StringEncoding]]) return 4;
            if ([name isEqualToString:@"rar5-compressed"] && [files[@"test.bin"] length] != 1200) return 5;
        } else if (files || !error) return 2;
    }
    puts("Native RAR4/5 reader: success, compressed, traversal, duplicate, corrupt fixtures PASSED (not iPhone)");
} return 0; }
''', encoding="utf8")
        subprocess.run(["xcrun", "clang", "-fobjc-arc", "-I"+prefix+"/include", "-I"+str(ROOT/"src/ios"), str(ROOT/"src/ios/WorkbenchBridge.m"), str(d/"main.m"), "-L"+prefix+"/lib", "-larchive", "-framework", "Foundation", "-o", str(d/"rar-tests")], check=True)
        subprocess.run([str(d/"rar-tests"), str(d)], check=True)

if __name__ == "__main__": main()
