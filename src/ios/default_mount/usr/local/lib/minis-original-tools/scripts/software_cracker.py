#!/usr/bin/env python3
"""
软件破解工具 - 补丁/Keygen/脱壳/启动器
用法: python software_cracker.py --target app.exe --analyze
      python software_cracker.py --target app.exe --patch --offset 0x1234 --original 74 --patched EB
      python software_cracker.py --target app.exe --keygen --serial-pattern "XXXX-XXXX-XXXX"
      python software_cracker.py --target app.exe --unpack
"""

import sys, os, struct, hashlib, re, time, json, subprocess
from pathlib import Path
from datetime import datetime, timedelta

# ======================== PE解析 ========================
class PEInfo:
    """PE文件信息提取"""
    def __init__(self, filepath):
        self.path = Path(filepath)
        self.data = bytearray(self.path.read_bytes())
        self.dos_header = None
        self.nt_headers = None
        self.sections = []
        self.imports = []
        self.exports = []
        self._parse()

    def _parse(self):
        # DOS Header
        if self.data[:2] != b"MZ":
            raise ValueError("Not a valid PE file (missing MZ signature)")

        self.dos_header = {
            "e_magic": self.data[:2],
            "e_lfanew": struct.unpack_from("<I", self.data, 0x3C)[0],
        }

        pe_offset = self.dos_header["e_lfanew"]

        # PE Signature
        if self.data[pe_offset:pe_offset+4] != b"PE\x00\x00":
            raise ValueError("Invalid PE signature")

        # File Header
        file_header_offset = pe_offset + 4
        machine = struct.unpack_from("<H", self.data, file_header_offset)[0]
        num_sections = struct.unpack_from("<H", self.data, file_header_offset + 2)[0]
        size_opt_header = struct.unpack_from("<H", self.data, file_header_offset + 16)[0]

        machine_names = {0x014C: "i386", 0x8664: "AMD64", 0x0200: "IA64", 0x01C4: "ARM"}
        self.machine = machine_names.get(machine, "Unknown(0x%X)" % machine)
        self.is_64bit = machine == 0x8664

        # Optional Header
        opt_offset = file_header_offset + 20
        magic = struct.unpack_from("<H", self.data, opt_offset)[0]
        self.is_pe32plus = magic == 0x020B

        if self.is_pe32plus:
            self.entry_point = struct.unpack_from("<I", self.data, opt_offset + 16)[0]
            self.image_base = struct.unpack_from("<Q", self.data, opt_offset + 24)[0]
        else:
            self.entry_point = struct.unpack_from("<I", self.data, opt_offset + 16)[0]
            self.image_base = struct.unpack_from("<I", self.data, opt_offset + 28)[0]

        # Sections
        section_offset = opt_offset + size_opt_header
        for i in range(num_sections):
            sec_start = section_offset + i * 40
            name = self.data[sec_start:sec_start+8].rstrip(b"\x00").decode("ascii", errors="ignore")
            vsize = struct.unpack_from("<I", self.data, sec_start + 8)[0]
            vaddr = struct.unpack_from("<I", self.data, sec_start + 12)[0]
            rsize = struct.unpack_from("<I", self.data, sec_start + 16)[0]
            roffset = struct.unpack_from("<I", self.data, sec_start + 20)[0]
            characteristics = struct.unpack_from("<I", self.data, sec_start + 36)[0]

            flags = []
            if characteristics & 0x20000000: flags.append("X")
            if characteristics & 0x40000000: flags.append("R")
            if characteristics & 0x80000000: flags.append("W")
            if characteristics & 0x02000000: flags.append("DISCARD")

            # 熵值计算 (简易)
            if rsize > 0 and roffset + rsize <= len(self.data):
                sec_data = self.data[roffset:roffset+rsize]
                entropy = self._calc_entropy(sec_data)
            else:
                entropy = 0

            self.sections.append({
                "name": name,
                "virtual_size": vsize,
                "virtual_address": vaddr,
                "raw_size": rsize,
                "raw_offset": roffset,
                "flags": "|".join(flags),
                "entropy": entropy,
            })

        # 导入表
        self._parse_imports(opt_offset, size_opt_header, section_offset)

    def _calc_entropy(self, data):
        """计算字节熵值 (>7.0可能加壳)"""
        if not data:
            return 0
        freq = [0] * 256
        for b in data:
            freq[b] += 1
        entropy = 0
        length = len(data)
        for f in freq:
            if f > 0:
                p = f / length
                entropy -= p * (p.bit_length() - 1)  # log2 approx
        return entropy

    def _parse_imports(self, opt_offset, size_opt_header, section_offset):
        """解析导入表"""
        import_dir_rva = struct.unpack_from("<I", self.data, opt_offset + 104 if self.is_pe32plus else opt_offset + 80)[0]
        if import_dir_rva == 0:
            return

        import_offset = self._rva_to_offset(import_dir_rva)
        if import_offset is None:
            return

        i = 0
        while True:
            entry_offset = import_offset + i * 20
            if entry_offset + 20 > len(self.data):
                break

            name_rva = struct.unpack_from("<I", self.data, entry_offset + 12)[0]
            if name_rva == 0:
                break

            name_offset = self._rva_to_offset(name_rva)
            if name_offset and name_offset < len(self.data):
                dll_name = self.data[name_offset:].split(b"\x00")[0].decode("ascii", errors="ignore")
                self.imports.append(dll_name)

            i += 1

    def _rva_to_offset(self, rva):
        """RVA转文件偏移"""
        for sec in self.sections:
            if sec["virtual_address"] <= rva < sec["virtual_address"] + sec["virtual_size"]:
                return rva - sec["virtual_address"] + sec["raw_offset"]
        return None

    def _offset_to_rva(self, offset):
        """文件偏移转RVA"""
        for sec in self.sections:
            if sec["raw_offset"] <= offset < sec["raw_offset"] + sec["raw_size"]:
                return offset - sec["raw_offset"] + sec["virtual_address"]
        return None

    def print_info(self):
        """打印PE信息"""
        print("\n" + "=" * 60)
        print("  PE Analysis: %s" % self.path.name)
        print("=" * 60)
        print("  Machine:     %s" % self.machine)
        print("  Image Base:  0x%X" % self.image_base)
        print("  Entry Point: 0x%X (RVA)" % self.entry_point)
        print("  Entry VA:    0x%X" % (self.image_base + self.entry_point))

        print("\n  Sections:")
        print("  %-10s %-10s %-10s %-10s %-8s %s" % ("Name", "VSize", "VAddr", "RSize", "Entropy", "Flags"))
        print("  " + "-" * 65)
        for sec in self.sections:
            print("  %-10s 0x%-8X 0x%-8X 0x%-8X %-8.2f %s" % (
                sec["name"], sec["virtual_size"], sec["virtual_address"],
                sec["raw_size"], sec["entropy"], sec["flags"]
            ))

        if self.imports:
            print("\n  Imports (%d):" % len(self.imports))
            # 分组显示关键导入
            key_apis = ["ReadProcessMemory", "WriteProcessMemory", "VirtualAllocEx",
                       "CreateRemoteThread", "LoadLibrary", "GetProcAddress",
                       "MessageBox", "CreateFile", "RegOpenKey", "InternetOpen",
                       "send", "recv", "WSASend", "WSARecv", "CryptEncrypt",
                       "IsDebuggerPresent", "CheckRemoteDebuggerPresent"]
            found_key = [api for api in key_apis if any(api.lower() in imp.lower() for imp in self.imports)]
            if found_key:
                print("  [Key APIs detected]: %s" % ", ".join(found_key))

            for imp in self.imports[:30]:
                print("    - %s" % imp)
            if len(self.imports) > 30:
                print("    ... (%d more)" % (len(self.imports) - 30))


# ======================== 壳检测 ========================
class PackerDetector:
    """壳检测器"""

    # 已知壳签名
    PACKER_SIGNATURES = {
        "UPX": [b"UPX0", b"UPX1", b"UPX!"],
        "ASPack": [b"ASPack", b".aspack"],
        "MPRESS": [b"MPRESS"],
        "PECompact": [b"PEC2", b"PECompact2"],
        "Themida": [b"Themida", b"WinLicense"],
        "VMProtect": [b"VMProtect", b".vmp"],
        "Enigma": [b"Enigma"],
        "Obsidium": [b"Obsidium"],
        "Armadillo": [b"Armadillo", b".adata"],
        "ASProtect": [b"ASProtect"],
        "NsPacK": [b"NsPacK"],
        "MoleBox": [b"MoleBox"],
    }

    @classmethod
    def detect(cls, pe_info):
        """检测壳"""
        results = []
        data = pe_info.data

        # 1. 签名扫描
        for packer, sigs in cls.PACKER_SIGNATURES.items():
            for sig in sigs:
                if sig in data:
                    results.append(("signature", packer))

        # 2. 区段名检测
        packed_sections = [".UPX0", ".UPX1", ".aspack", ".pec", ".vmp",
                          ".themida", ".enigma", ".MPRESS", ".sforce"]
        for sec in pe_info.sections:
            if sec["name"] in packed_sections:
                results.append(("section_name", sec["name"]))

        # 3. 熵值检测
        high_entropy_sections = 0
        for sec in pe_info.sections:
            if sec["entropy"] > 7.0 and sec["raw_size"] > 0:
                high_entropy_sections += 1

        if high_entropy_sections >= 2:
            results.append(("high_entropy", "%d sections > 7.0 entropy" % high_entropy_sections))

        # 4. 入口点异常
        for sec in pe_info.sections:
            ep = pe_info.entry_point
            sec_start = sec["virtual_address"]
            sec_end = sec_start + sec["virtual_size"]
            if sec_start <= ep < sec_end:
                if sec["name"] not in (".text", ".code", "CODE", "text"):
                    results.append(("ep_in_unusual", sec["name"]))
                break

        # 5. 导入表过少
        if len(pe_info.imports) <= 2 and len(pe_info.imports) > 0:
            results.append(("sparse_imports", "only %d DLLs" % len(pe_info.imports)))

        return results

    @classmethod
    def print_detection(cls, pe_info):
        """打印壳检测结果"""
        results = cls.detect(pe_info)
        print("\n  [Pack Detection]")
        if not results:
            print("  [+] No packer detected (possibly unpacked)")
            return

        for method, detail in results:
            print("  [!] [%s] %s" % (method.upper(), detail))

        # 脱壳建议
        print("\n  [Unpacking Tips]:")
        for method, detail in results:
            if "UPX" in str(detail):
                print("    > upx -d %s   (UPX自带脱壳)" % pe_info.path.name)
            if "ASPack" in str(detail):
                print("    > 使用 ASPackDie 或 手动脱壳 (ESP定律)")
            if "VMProtect" in str(detail):
                print("    > VMP难度高，需x64dbg + 虚拟机检测绕过 + 内存dump")
            if "Themida" in str(detail):
                print("    > Themida难度极高，推荐使用Themida-unpacker工具")


# ======================== 补丁工具 ========================
class Patcher:
    """补丁应用器"""

    @staticmethod
    def apply_patch(filepath, patches):
        """
        应用补丁
        patches: [(offset, original_bytes, patched_bytes), ...]
        """
        path = Path(filepath)
        data = bytearray(path.read_bytes())

        # 备份
        backup_path = path.with_suffix(path.suffix + ".bak")
        if not backup_path.exists():
            path.rename(backup_path)
            print("[*] Backup created: %s" % backup_path.name)
        else:
            # 从备份恢复原始文件
            backup_path = path.with_suffix(path.suffix + ".bak")

        applied = 0
        for offset, original, patched in patches:
            # 支持hex字符串
            if isinstance(offset, str):
                offset = int(offset, 16)
            if isinstance(original, str):
                original = bytes.fromhex(original.replace(" ", ""))
            if isinstance(patched, str):
                patched = bytes.fromhex(patched.replace(" ", ""))

            # 验证原始字节
            if data[offset:offset+len(original)] == original:
                data[offset:offset+len(patched)] = patched
                applied += 1
                print("[+] Patched @ 0x%X: %s -> %s" % (
                    offset,
                    " ".join("%02X" % b for b in original),
                    " ".join("%02X" % b for b in patched)
                ))
            else:
                actual = data[offset:offset+len(original)]
                print("[-] Mismatch @ 0x%X: expected %s, got %s" % (
                    offset,
                    " ".join("%02X" % b for b in original),
                    " ".join("%02X" % b for b in actual)
                ))

        path.write_bytes(data)
        print("[+] %d/%d patches applied. Output: %s" % (applied, len(patches), path))
        return applied


    @staticmethod
    def patch_jump(filepath, offset, jump_type="jmp"):
        """
        修改条件跳转
        jump_type:
          - "nop":  NOP填充 (90 90...)
          - "jmp":  JMP (EB)
          - "je->jmp": JE(74) -> JMP(EB)
          - "jne->nop": JNE(75) -> NOP(90 90)
        """
        path = Path(filepath)
        data = bytearray(path.read_bytes())

        if isinstance(offset, str):
            offset = int(offset, 16)

        if jump_type == "nop":
            data[offset] = 0x90
            data[offset + 1] = 0x90
        elif jump_type == "jmp":
            data[offset] = 0xEB
        elif jump_type == "je->jmp":
            if data[offset] == 0x74:
                data[offset] = 0xEB
            else:
                print("[-] Expected JE(0x74) at 0x%X, got 0x%02X" % (offset, data[offset]))
                return False
        elif jump_type == "jne->nop":
            if data[offset] == 0x75:
                data[offset] = 0x90
                data[offset + 1] = 0x90
            else:
                print("[-] Expected JNE(0x75) at 0x%X, got 0x%02X" % (offset, data[offset]))
                return False

        path.write_bytes(data)
        print("[+] Patch applied: %s @ 0x%X" % (jump_type, offset))
        return True


# ======================== Keygen工具 ========================
class KeygenTool:
    """Keygen生成器"""

    @staticmethod
    def generate_serial(pattern="XXXX-XXXX-XXXX-XXXX", seed=None):
        """生成简单序列号"""
        import random
        if seed:
            random.seed(seed)

        result = []
        for char in pattern:
            if char == "X":
                # 大写字母+数字
                charset = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
                result.append(random.choice(charset))
            elif char == "x":
                result.append(random.choice("0123456789"))
            elif char == "A":
                result.append(random.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZ"))
            elif char == "a":
                result.append(random.choice("abcdefghijklmnopqrstuvwxyz"))
            elif char == "N":
                result.append(str(random.randint(0, 9)))
            elif char == "H":
                result.append(random.choice("0123456789ABCDEF"))
            else:
                result.append(char)

        return "".join(result)

    @staticmethod
    def generate_keyfile(filepath, key_data=None, size=1024):
        """生成key文件"""
        path = Path(filepath)
        data = key_data or os.urandom(size)
        if isinstance(data, str):
            data = data.encode()
        path.write_bytes(data)
        print("[+] Keyfile generated: %s (%d bytes)" % (path, len(data)))
        return path

    @staticmethod
    def generate_license_file(filepath, username, product, expiry_days=None):
        """生成license文件"""
        import base64

        expiry = None
        if expiry_days:
            expiry = (datetime.now() + timedelta(days=expiry_days)).strftime("%Y-%m-%d")

        license_data = {
            "username": username,
            "product": product,
            "license_type": "registered",
            "issue_date": datetime.now().strftime("%Y-%m-%d"),
            "expiry_date": expiry,
            "features": ["all"],
            "signature": hashlib.sha256(
                ("%s:%s:%s" % (username, product, expiry or "permanent")).encode()
            ).hexdigest()[:16].upper(),
        }

        path = Path(filepath)
        content = json.dumps(license_data, indent=2, ensure_ascii=False)
        path.write_text(content)
        print("[+] License file: %s" % path)
        print("    User: %s | Product: %s | Expiry: %s" % (
            username, product, expiry or "PERMANENT"
        ))
        return path


# ======================== 字符串搜索 ========================
class StringSearcher:
    """字符串搜索 - 定位验证逻辑"""

    @staticmethod
    def search(filepath, patterns):
        """搜索模式字符串"""
        path = Path(filepath)
        data = path.read_bytes()

        results = {}
        for pattern in patterns:
            if isinstance(pattern, str):
                pattern = pattern.encode("utf-8")
            elif isinstance(pattern, bytes):
                pass

            pos = 0
            found = []
            while True:
                idx = data.find(pattern, pos)
                if idx == -1:
                    break
                found.append(idx)
                pos = idx + 1

            if found:
                pattern_str = pattern.decode("utf-8", errors="ignore") if isinstance(pattern, bytes) else pattern
                results[pattern_str] = found

        return results

    @staticmethod
    def search_license_strings(filepath):
        """搜索与授权/注册相关的字符串"""
        patterns = [
            "license", "License", "LICENSE",
            "serial", "Serial", "SERIAL",
            "register", "Register", "REGISTER",
            "registration",
            "trial", "TRIAL",
            "expir", "EXPIR",
            "activ", "ACTIV",
            "key", "Key", "KEY",
            "demo", "DEMO",
            "evaluation",
            "unlock",
            "subscription",
            "authorization",
            "perpetual",
            # 中文
            "注册", "授权", "激活", "试用", "到期",
            "序列号", "许可证", "过期", "验证",
        ]

        path = Path(filepath)
        data = path.read_bytes()

        print("\n  [License-related Strings]")
        print("  " + "-" * 60)

        for pattern in patterns:
            pattern_bytes = pattern.encode("utf-8")
            # 也尝试ASCII/GBK编码
            for enc in [pattern_bytes, pattern.encode("ascii", errors="ignore"), pattern.encode("gbk", errors="ignore")]:
                if not enc:
                    continue
                idx = data.find(enc)
                if idx >= 0:
                    # 获取上下文
                    start = max(0, idx - 20)
                    end = min(len(data), idx + len(enc) + 60)
                    context = data[start:end]
                    # 显示
                    context_str = context.decode("utf-8", errors="replace").replace("\x00", " ").replace("\n", "\\n")
                    print("  [0x%X] %s => ...%s..." % (idx, pattern, context_str.strip()[:80]))
                    break  # 找到一种编码就够了


# ======================== 简易反编译器 ========================
class Disassembler:
    """基础反汇编/字节码分析"""

    @staticmethod
    def find_functions(data, ep_rva):
        """通过prologue模式找函数"""
        # 常见x64 prologue: 48 89 5C 24 (mov [rsp+8], rbx) / 40 53 (push rbx)
        # 常见x86 prologue: 55 (push ebp) / 8B FF (mov edi, edi)
        prologues = [
            b"\x55\x8B\xEC",       # push ebp; mov ebp, esp
            b"\x48\x89\x5C\x24",   # mov [rsp+8], rbx
            b"\x40\x53",           # push rbx
            b"\x48\x83\xEC",       # sub rsp, XX
        ]

        functions = set()
        for pro in prologues:
            pos = 0
            while True:
                idx = data.find(pro, pos)
                if idx == -1:
                    break
                functions.add(idx)
                pos = idx + 1

        return sorted(functions)


# ======================== CLI ========================
def main():
    import argparse
    parser = argparse.ArgumentParser(description="软件破解工具 - Cracker/Keygen/Patcher")

    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # analyze命令
    analyze_parser = subparsers.add_parser("analyze", help="分析PE文件")
    analyze_parser.add_argument("--target", "-t", required=True, help="目标文件")
    analyze_parser.add_argument("--strings", action="store_true", help="搜索授权相关字符串")
    analyze_parser.add_argument("--pack-detect", action="store_true", help="壳检测")

    # patch命令
    patch_parser = subparsers.add_parser("patch", help="应用补丁")
    patch_parser.add_argument("--target", "-t", required=True, help="目标文件")
    patch_parser.add_argument("--offset", "-o", required=True, help="补丁偏移 (hex)")
    patch_parser.add_argument("--original", help="原始字节 (hex)")
    patch_parser.add_argument("--patched", help="修改字节 (hex)")
    patch_parser.add_argument("--jump-type", choices=["nop","jmp","je->jmp","jne->nop"],
                             help="跳转修改类型")

    # keygen命令
    keygen_parser = subparsers.add_parser("keygen", help="生成序列号/Keygen")
    keygen_parser.add_argument("--pattern", default="XXXX-XXXX-XXXX-XXXX", help="序列号格式 (X=字母数字, N=数字)")
    keygen_parser.add_argument("--count", type=int, default=1, help="生成数量")
    keygen_parser.add_argument("--output", "-o", help="输出文件")
    keygen_parser.add_argument("--seed", help="随机种子")

    # license命令
    license_parser = subparsers.add_parser("license", help="生成License文件")
    license_parser.add_argument("--username", default="User", help="用户名")
    license_parser.add_argument("--product", default="Software", help="产品名")
    license_parser.add_argument("--expiry", type=int, help="过期天数 (默认: 永久)")
    license_parser.add_argument("--output", "-o", default="license.json", help="输出文件")

    # search命令
    search_parser = subparsers.add_parser("search", help="搜索字符串/模式")
    search_parser.add_argument("--target", "-t", required=True, help="目标文件")
    search_parser.add_argument("--pattern", "-p", action="append", help="搜索模式 (可多次指定)")

    args = parser.parse_args()

    if args.command == "analyze":
        try:
            pe = PEInfo(args.target)
            pe.print_info()

            if args.pack_detect:
                PackerDetector.print_detection(pe)

            if args.strings:
                StringSearcher.search_license_strings(args.target)

        except Exception as e:
            print("[-] Error: %s" % e)
            return 1

    elif args.command == "patch":
        if args.jump_type:
            Patcher.patch_jump(args.target, args.offset, args.jump_type)
        elif args.original and args.patched:
            Patcher.apply_patch(args.target, [(args.offset, args.original, args.patched)])
        else:
            print("[-] Need --original/--patched or --jump-type")
            return 1

    elif args.command == "keygen":
        for i in range(args.count):
            serial = KeygenTool.generate_serial(args.pattern, args.seed)
            print("  [%d] %s" % (i + 1, serial))

        if args.output:
            with open(args.output, "w") as f:
                for i in range(args.count):
                    serial = KeygenTool.generate_serial(args.pattern, args.seed)
                    f.write(serial + "\n")
            print("[+] Saved to: %s" % args.output)

    elif args.command == "license":
        KeygenTool.generate_license_file(args.output, args.username, args.product, args.expiry)

    elif args.command == "search":
        if args.pattern:
            results = StringSearcher.search(args.target, args.pattern)
            for pattern, positions in results.items():
                print("\n  [Pattern: %s] (%d matches)" % (pattern, len(positions)))
                for pos in positions[:20]:
                    print("    0x%X" % pos)
                if len(positions) > 20:
                    print("    ... (%d more)" % (len(positions) - 20))

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
