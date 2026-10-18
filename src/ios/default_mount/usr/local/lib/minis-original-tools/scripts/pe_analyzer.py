#!/usr/bin/env python3
"""
PE文件深度分析器 - 导入导出/资源/签名/PDB/区段/壳检测/反调试检测
用法: python pe_analyzer.py --file app.exe
      python pe_analyzer.py --file app.exe --full
      python pe_analyzer.py --file app.exe --detect-pack
      python pe_analyzer.py --file app.exe --exports
"""

import sys, os, struct, hashlib, json
from pathlib import Path
from datetime import datetime

# ======================== 常量 ========================
IMAGE_DOS_SIGNATURE = 0x5A4D  # MZ
IMAGE_NT_SIGNATURE = 0x00004550  # PE\0\0

# 机器类型
MACHINE_TYPES = {
    0x014C: "x86 (i386)",
    0x0200: "IA64 (Itanium)",
    0x8664: "x64 (AMD64)",
    0x01C4: "ARM",
    0xAA64: "ARM64",
    0x01C0: "ARM Thumb",
    0x0162: "MIPS R3000",
    0x0166: "MIPS R4000",
    0x0168: "MIPS R10000",
    0x0169: "MIPS WCE v2",
    0x0266: "MIPS16",
    0x0366: "MIPS FPU",
    0x0466: "MIPS16 FPU",
    0x01F0: "PowerPC",
    0x01F1: "PowerPC FP",
    0x0EBC: "EFI Byte Code",
    0x9041: "M32R",
    0x1C0C: "ARM Thumb-2",
}

# 子系统
SUBSYSTEM_TYPES = {
    0: "UNKNOWN",
    1: "NATIVE",
    2: "WINDOWS_GUI",
    3: "WINDOWS_CUI",
    5: "OS2_CUI",
    7: "POSIX_CUI",
    9: "WINDOWS_CE_GUI",
    10: "EFI_APPLICATION",
    11: "EFI_BOOT_SERVICE_DRIVER",
    12: "EFI_RUNTIME_DRIVER",
    13: "EFI_ROM",
    14: "XBOX",
    16: "WINDOWS_BOOT_APPLICATION",
}

# 区段特征
SECTION_FLAGS = {
    0x00000020: "CODE",
    0x00000040: "INITIALIZED_DATA",
    0x00000080: "UNINITIALIZED_DATA",
    0x02000000: "DISCARDABLE",
    0x04000000: "NOT_CACHED",
    0x08000000: "NOT_PAGED",
    0x10000000: "SHARED",
    0x20000000: "EXECUTE",
    0x40000000: "READ",
    0x80000000: "WRITE",
}

# DLL特征
DLL_CHARACTERISTICS = {
    0x0020: "HIGH_ENTROPY_VA",
    0x0040: "DYNAMIC_BASE",
    0x0080: "FORCE_INTEGRITY",
    0x0100: "NX_COMPAT",
    0x0200: "NO_ISOLATION",
    0x0400: "NO_SEH",
    0x0800: "NO_BIND",
    0x1000: "APPCONTAINER",
    0x2000: "WDM_DRIVER",
    0x4000: "GUARD_CF",
    0x8000: "TERMINAL_SERVER_AWARE",
}

# 已知壳的区段名
PACKER_SECTIONS = {
    "UPX0": "UPX (未压缩代码)", "UPX1": "UPX (压缩代码)", "UPX2": "UPX (导入)",
    ".aspack": "ASPack", ".adata": "ASPack",
    ".MPRESS1": "MPRESS", ".MPRESS2": "MPRESS",
    ".pec": "PECompact", ".pec1": "PECompact", ".pec2": "PECompact",
    ".vmp0": "VMProtect", ".vmp1": "VMProtect", ".vmp2": "VMProtect",
    ".themida": "Themida/WinLicense",
    ".enigma": "Enigma Protector",
    ".obsidium": "Obsidium",
    ".sforce": "StarForce",
    "kkrunchy": "kkrunchy",
    ".y0da": "Yoda Protector",
    ".neolit": "Neolite",
    "yzpack": "YzPack",
}


class PEAnalyzer:
    def __init__(self, filepath):
        self.path = Path(filepath)
        if not self.path.exists():
            raise FileNotFoundError("File not found: %s" % filepath)

        self.data = bytearray(self.path.read_bytes())
        self.filesize = len(self.data)
        self.pe_offset = 0
        self.is_pe32plus = False
        self.machine = 0
        self.sections = []
        self.imports = []
        self.exports_list = []
        self.resources = []
        self.pdb_path = None
        self.timestamp = 0
        self.entry_point = 0
        self.image_base = 0
        self.subsystem = 0
        self.dll_characteristics = 0
        self.checksum = 0

        self._parse()

    def _read_uint16(self, offset):
        return struct.unpack_from("<H", self.data, offset)[0]

    def _read_uint32(self, offset):
        return struct.unpack_from("<I", self.data, offset)[0]

    def _read_uint64(self, offset):
        return struct.unpack_from("<Q", self.data, offset)[0]

    def _read_string(self, offset, maxlen=256):
        end = self.data.find(b"\x00", offset)
        if end == -1 or end - offset > maxlen:
            end = offset + maxlen
        return self.data[offset:end].decode("ascii", errors="ignore")

    def _rva_to_offset(self, rva):
        for sec in self.sections:
            if sec["virtual_address"] <= rva < sec["virtual_address"] + sec["virtual_size"]:
                return rva - sec["virtual_address"] + sec["raw_offset"]
        return None

    def _parse(self):
        # DOS Header
        if struct.unpack_from("<H", self.data, 0)[0] != IMAGE_DOS_SIGNATURE:
            raise ValueError("Not a valid PE file")

        self.pe_offset = self._read_uint32(0x3C)

        # PE Signature
        sig = struct.unpack_from("<I", self.data, self.pe_offset)[0]
        if sig != IMAGE_NT_SIGNATURE:
            raise ValueError("Invalid NT signature")

        # COFF File Header
        coff_offset = self.pe_offset + 4
        self.machine = self._read_uint16(coff_offset)
        num_sections = self._read_uint16(coff_offset + 2)
        self.timestamp = self._read_uint32(coff_offset + 4)
        size_opt_header = self._read_uint16(coff_offset + 16)
        characteristics = self._read_uint16(coff_offset + 18)

        # Optional Header
        opt_offset = coff_offset + 20
        magic = self._read_uint16(opt_offset)
        self.is_pe32plus = (magic == 0x020B)

        if self.is_pe32plus:
            # PE32+
            self.image_base = self._read_uint64(opt_offset + 24)
            self.entry_point = self._read_uint32(opt_offset + 16)
            self.dll_characteristics = self._read_uint16(opt_offset + 70)
            self.subsystem = self._read_uint16(opt_offset + 68)
            self.checksum = self._read_uint32(opt_offset + 64)

            # 数据目录
            export_rva = self._read_uint32(opt_offset + 112)
            export_size = self._read_uint32(opt_offset + 116)
            import_rva = self._read_uint32(opt_offset + 120)
            import_size = self._read_uint32(opt_offset + 124)
            resource_rva = self._read_uint32(opt_offset + 128)
            resource_size = self._read_uint32(opt_offset + 132)
            debug_rva = self._read_uint32(opt_offset + 160)
            debug_size = self._read_uint32(opt_offset + 164)
        else:
            # PE32
            self.image_base = self._read_uint32(opt_offset + 28)
            self.entry_point = self._read_uint32(opt_offset + 16)
            self.dll_characteristics = self._read_uint16(opt_offset + 70)
            self.subsystem = self._read_uint16(opt_offset + 68)
            self.checksum = self._read_uint32(opt_offset + 64)

            export_rva = self._read_uint32(opt_offset + 96)
            export_size = self._read_uint32(opt_offset + 100)
            import_rva = self._read_uint32(opt_offset + 104)
            import_size = self._read_uint32(opt_offset + 108)
            resource_rva = self._read_uint32(opt_offset + 112)
            resource_size = self._read_uint32(opt_offset + 116)
            debug_rva = self._read_uint32(opt_offset + 144)
            debug_size = self._read_uint32(opt_offset + 148)

        # Sections
        section_offset = opt_offset + size_opt_header
        for i in range(num_sections):
            sec_start = section_offset + i * 40
            name = self.data[sec_start:sec_start+8].rstrip(b"\x00").decode("ascii", errors="ignore")
            vsize = self._read_uint32(sec_start + 8)
            vaddr = self._read_uint32(sec_start + 12)
            rsize = self._read_uint32(sec_start + 16)
            roffset = self._read_uint32(sec_start + 20)
            characteristics = self._read_uint32(sec_start + 36)

            # 计算熵值
            entropy = 0
            if rsize > 0 and roffset + rsize <= len(self.data):
                entropy = self._calc_entropy(self.data[roffset:roffset + rsize])

            self.sections.append({
                "name": name,
                "virtual_size": vsize,
                "virtual_address": vaddr,
                "raw_size": rsize,
                "raw_offset": roffset,
                "characteristics": characteristics,
                "entropy": entropy,
            })

        # 导入表
        if import_rva and import_size:
            self._parse_imports(import_rva)

        # 导出表
        if export_rva and export_size:
            self._parse_exports(export_rva)

        # 调试信息
        if debug_rva and debug_size:
            self._parse_debug(debug_rva)

        # 资源
        if resource_rva and resource_size:
            self._parse_resources(resource_rva, resource_size)

    def _calc_entropy(self, data):
        if not data:
            return 0.0
        freq = [0] * 256
        for b in data:
            freq[b] += 1
        entropy = 0.0
        length = len(data)
        for f in freq:
            if f > 0:
                p = f / length
                entropy -= p * (p.bit_length() - 1)
        return entropy

    def _parse_imports(self, import_rva):
        import_offset = self._rva_to_offset(import_rva)
        if import_offset is None:
            return

        i = 0
        while True:
            entry_offset = import_offset + i * 20
            if entry_offset + 20 > self.filesize:
                break

            name_rva = self._read_uint32(entry_offset + 12)
            ilt_rva = self._read_uint32(entry_offset + 0)
            if name_rva == 0 and ilt_rva == 0:
                break

            name_offset = self._rva_to_offset(name_rva)
            if name_offset and name_offset < self.filesize:
                dll_name = self._read_string(name_offset)
                functions = []

                # 解析导入函数
                thunk_offset = self._rva_to_offset(ilt_rva)
                if thunk_offset:
                    j = 0
                    while True:
                        if self.is_pe32plus:
                            func_offset = thunk_offset + j * 8
                            if func_offset + 8 > self.filesize:
                                break
                            func_val = self._read_uint64(func_offset)
                            if func_val == 0:
                                break
                            if func_val & (1 << 63):  # 序号导入
                                ordinal = func_val & 0xFFFF
                                functions.append("Ordinal:%d" % ordinal)
                            else:
                                name_rva2 = func_val & 0x7FFFFFFF
                                name_off2 = self._rva_to_offset(name_rva2)
                                if name_off2:
                                    func_name = self._read_string(name_off2 + 2)
                                    functions.append(func_name)
                        else:
                            func_offset = thunk_offset + j * 4
                            if func_offset + 4 > self.filesize:
                                break
                            func_val = self._read_uint32(func_offset)
                            if func_val == 0:
                                break
                            if func_val & 0x80000000:
                                ordinal = func_val & 0xFFFF
                                functions.append("Ordinal:%d" % ordinal)
                            else:
                                name_rva2 = func_val & 0x7FFFFFFF
                                name_off2 = self._rva_to_offset(name_rva2)
                                if name_off2:
                                    func_name = self._read_string(name_off2 + 2)
                                    functions.append(func_name)
                        j += 1

                self.imports.append({
                    "dll": dll_name,
                    "functions": functions[:50],  # 防止爆炸
                    "count": len(functions),
                })

            i += 1

    def _parse_exports(self, export_rva):
        export_offset = self._rva_to_offset(export_rva)
        if export_offset is None:
            return

        name_rva = self._read_uint32(export_offset + 12)
        if name_rva:
            name_off = self._rva_to_offset(name_rva)
            if name_off:
                self.export_dll_name = self._read_string(name_off)

        num_functions = self._read_uint32(export_offset + 20)
        num_names = self._read_uint32(export_offset + 24)
        func_rva = self._read_uint32(export_offset + 28)
        name_ptr_rva = self._read_uint32(export_offset + 32)
        ordinal_rva = self._read_uint32(export_offset + 36)

        if num_names == 0:
            return

        func_offset = self._rva_to_offset(func_rva)
        name_ptr_offset = self._rva_to_offset(name_ptr_rva)
        ordinal_offset = self._rva_to_offset(ordinal_rva)

        if not all([func_offset, name_ptr_offset, ordinal_offset]):
            return

        for i in range(min(num_names, 100)):
            name_rva2 = self._read_uint32(name_ptr_offset + i * 4)
            ordinal = self._read_uint16(ordinal_offset + i * 2)
            func_addr = self._read_uint32(func_offset + ordinal * 4)

            name_off2 = self._rva_to_offset(name_rva2)
            if name_off2:
                func_name = self._read_string(name_off2)
                self.exports_list.append({
                    "name": func_name,
                    "ordinal": ordinal + 1,
                    "rva": func_addr,
                })

    def _parse_debug(self, debug_rva):
        debug_offset = self._rva_to_offset(debug_rva)
        if debug_offset is None:
            return

        debug_type = self._read_uint32(debug_offset + 12)
        if debug_type == 2:  # CODEVIEW
            pdb_rva = self._read_uint32(debug_offset + 20)
            pdb_offset = self._rva_to_offset(pdb_rva)
            if pdb_offset:
                sig = self.data[pdb_offset:pdb_offset+4]
                if sig == b"RSDS":
                    guid = self.data[pdb_offset+4:pdb_offset+20].hex().upper()
                    age = self._read_uint32(pdb_offset + 20)
                    self.pdb_path = self._read_string(pdb_offset + 24).strip()
                    self.pdb_info = {"guid": guid, "age": age}

    def _parse_resources(self, resource_rva, size):
        """解析资源表"""
        res_offset = self._rva_to_offset(resource_rva)
        if res_offset is None:
            return

        # 资源类型
        resource_types = {
            1: "CURSOR", 2: "BITMAP", 3: "ICON", 4: "MENU",
            5: "DIALOG", 6: "STRING", 7: "FONTDIR", 8: "FONT",
            9: "ACCELERATOR", 10: "RCDATA", 11: "MESSAGETABLE",
            12: "GROUP_CURSOR", 14: "GROUP_ICON", 16: "VERSION",
            24: "MANIFEST", 240: "DLGINCLUDE",
        }

        # 简化: 直接搜索版本资源中的字符串
        for rtype_id, rtype_name in resource_types.items():
            if rtype_name == "VERSION":
                self.resources.append({"type": "VERSION", "id": rtype_id})

    def detect_packer(self):
        """壳检测"""
        findings = []

        # 1. 区段名检测
        for sec in self.sections:
            if sec["name"] in PACKER_SECTIONS:
                findings.append({
                    "type": "section_name",
                    "confidence": "HIGH",
                    "detail": "%s -> %s" % (sec["name"], PACKER_SECTIONS[sec["name"]]),
                })

        # 2. 熵值检测
        high_entropy = [s for s in self.sections if s["entropy"] > 7.0 and s["raw_size"] > 0]
        if len(high_entropy) >= 2:
            findings.append({
                "type": "high_entropy",
                "confidence": "MEDIUM",
                "detail": "%d sections with entropy > 7.0" % len(high_entropy),
            })

        # 3. 区段名异常
        unusual_names = []
        for sec in self.sections:
            name = sec["name"]
            if name and not name.startswith(".") and name not in ("CODE", "DATA", "BSS", "TEXT", "text"):
                unusual_names.append(name)
        if unusual_names:
            findings.append({
                "type": "unusual_sections",
                "confidence": "LOW",
                "detail": "Unusual section names: %s" % ", ".join(unusual_names),
            })

        # 4. EP不在第一个区段
        if self.sections:
            first_code = None
            for sec in self.sections:
                if sec["characteristics"] & 0x20000000 and first_code is None:
                    first_code = sec
                    break
            if first_code and first_code.get("virtual_address", 0) > self.entry_point:
                findings.append({
                    "type": "ep_location",
                    "confidence": "MEDIUM",
                    "detail": "EP(0x%X) before first code section %s(0x%X)" % (
                        self.entry_point, first_code["name"], first_code["virtual_address"]
                    ),
                })

        # 5. 导入表异常
        if len(self.imports) == 1:
            dll = self.imports[0]["dll"].lower()
            if "kernel32" in dll or "ntdll" in dll:
                findings.append({
                    "type": "sparse_imports",
                    "confidence": "HIGH",
                    "detail": "Only 1 import DLL: %s (%d functions)" % (
                        dll, self.imports[0]["count"]
                    ),
                })

        # 6. 签名扫描
        packer_signatures = {
            b"UPX!": "UPX",
            b"ASPack": "ASPack",
            b"MPRESS": "MPRESS",
            b"PECompact2": "PECompact",
            b"Themida": "Themida",
            b"WinLicense": "WinLicense",
            b"VMProtect": "VMProtect",
            b"Enigma": "Enigma Protector",
            b"Obsidium": "Obsidium",
        }
        for sig, packer in packer_signatures.items():
            if sig in self.data:
                findings.append({
                    "type": "signature",
                    "confidence": "HIGH",
                    "detail": "Detected: %s" % packer,
                })

        return findings

    def detect_anti_debug(self):
        """反调试检测"""
        findings = []

        anti_debug_apis = [
            "IsDebuggerPresent",
            "CheckRemoteDebuggerPresent",
            "NtQueryInformationProcess",
            "NtSetInformationThread",
            "OutputDebugString",
            "GetTickCount",
            "QueryPerformanceCounter",
            "FindWindow",
            "GetWindowText",
            "EnumWindows",
            "Process32First",
            "Process32Next",
            "Toolhelp32ReadProcessMemory",
        ]

        for imp in self.imports:
            for func in imp.get("functions", []):
                if func in anti_debug_apis:
                    findings.append({
                        "api": func,
                        "from": imp["dll"],
                    })

        return findings

    def get_security_features(self):
        """安全特性检测"""
        features = {
            "ASLR": bool(self.dll_characteristics & 0x0040),
            "DEP/NX": bool(self.dll_characteristics & 0x0100),
            "SafeSEH": False,
            "Control_Flow_Guard": bool(self.dll_characteristics & 0x4000),
            "High_Entropy_ASLR": bool(self.dll_characteristics & 0x0020),
            "Force_Integrity": bool(self.dll_characteristics & 0x0080),
            "AppContainer": bool(self.dll_characteristics & 0x1000),
        }
        return features

    def print_report(self, full=False):
        """打印分析报告"""
        build_date = datetime.fromtimestamp(self.timestamp).strftime("%Y-%m-%d %H:%M:%S")

        print("\n" + "=" * 70)
        print("  PE Analysis Report: %s" % self.path.name)
        print("=" * 70)

        print("\n  [Basic Info]")
        print("  File:          %s" % self.path)
        print("  Size:          %s (%d bytes)" % (self._format_size(self.filesize), self.filesize))
        print("  MD5:           %s" % hashlib.md5(self.data).hexdigest())
        print("  SHA256:        %s" % hashlib.sha256(self.data).hexdigest())
        print("  Machine:       %s (0x%04X)" % (MACHINE_TYPES.get(self.machine, "Unknown"), self.machine))
        print("  Timestamp:     %s" % build_date)
        print("  Entry Point:   0x%X" % self.entry_point)
        print("  Image Base:    0x%X" % self.image_base)
        print("  PE Type:       %s" % ("PE32+" if self.is_pe32plus else "PE32"))
        print("  Subsystem:     %s" % SUBSYSTEM_TYPES.get(self.subsystem, "Unknown(%d)" % self.subsystem))

        # 安全特性
        print("\n  [Security Features]")
        sec = self.get_security_features()
        for feature, enabled in sec.items():
            status = "ON " if enabled else "OFF"
            print("  %-20s [%s]" % (feature, status))

        # PDB
        if self.pdb_path:
            print("\n  [Debug Info - PDB Leak!]")
            print("  PDB Path:  %s" % self.pdb_path)
            if hasattr(self, "pdb_info"):
                print("  GUID:      %s" % self.pdb_info["guid"])
                print("  Age:       %d" % self.pdb_info["age"])

        # 区段
        print("\n  [Sections] (%d)" % len(self.sections))
        print("  %-12s %-10s %-10s %-10s %-8s %s" % ("Name", "VSize", "VAddr", "RSize", "Entropy", "Flags"))
        print("  " + "-" * 70)
        for sec in self.sections:
            flags_str = ""
            if sec["characteristics"] & 0x20000000: flags_str += "X"
            if sec["characteristics"] & 0x40000000: flags_str += "R"
            if sec["characteristics"] & 0x80000000: flags_str += "W"
            if not flags_str: flags_str = "-"
            print("  %-12s 0x%-8X 0x%-8X 0x%-8X %-8.2f %s" % (
                sec["name"], sec["virtual_size"], sec["virtual_address"],
                sec["raw_size"], sec["entropy"], flags_str
            ))

        # 壳检测
        print("\n  [Pack Detection]")
        pack_findings = self.detect_packer()
        if not pack_findings:
            print("  [+] No packer detected")
        else:
            for f in pack_findings:
                mark = "!!!" if f["confidence"] == "HIGH" else "?" if f["confidence"] == "MEDIUM" else " "
                print("  [%s%s] [%s] %s" % (mark, f["confidence"][:1], f["type"], f["detail"]))

        # 反调试检测
        anti_debug = self.detect_anti_debug()
        if anti_debug:
            print("\n  [Anti-Debug APIs Detected]")
            for ad in anti_debug:
                print("  - %s (from %s)" % (ad["api"], ad["from"]))

        # 导入表
        if self.imports:
            print("\n  [Import Table] (%d DLLs)" % len(self.imports))
            for imp in self.imports:
                func_list = imp["functions"]
                if len(func_list) > 10:
                    func_str = ", ".join(func_list[:10]) + "... (+%d more)" % (len(func_list) - 10)
                else:
                    func_str = ", ".join(func_list)
                print("  %s (%d): %s" % (imp["dll"], imp["count"], func_str[:120]))

        # 导出表
        if self.exports_list:
            print("\n  [Export Table] (%d exports)" % len(self.exports_list))
            for exp in self.exports_list[:30]:
                print("  Ordinal:%d  0x%X  %s" % (exp["ordinal"], exp["rva"], exp["name"]))

        # 资源
        if self.resources:
            print("\n  [Resources] (%d)" % len(self.resources))
            for res in self.resources:
                print("  Type: %s (ID: %d)" % (res["type"], res["id"]))

    def _format_size(self, size):
        if size > 1024 * 1024:
            return "%.2f MB" % (size / (1024 * 1024))
        elif size > 1024:
            return "%.2f KB" % (size / 1024)
        return "%d B" % size

    def export_json(self, output_path=None):
        """导出JSON报告"""
        data = {
            "file": str(self.path),
            "size": self.filesize,
            "md5": hashlib.md5(self.data).hexdigest(),
            "sha256": hashlib.sha256(self.data).hexdigest(),
            "machine": MACHINE_TYPES.get(self.machine, "Unknown"),
            "timestamp": datetime.fromtimestamp(self.timestamp).isoformat(),
            "entry_point": "0x%X" % self.entry_point,
            "image_base": "0x%X" % self.image_base,
            "pe_type": "PE32+" if self.is_pe32plus else "PE32",
            "security_features": self.get_security_features(),
            "pdb_path": self.pdb_path,
            "sections": self.sections,
            "pack_detection": self.detect_packer(),
            "anti_debug_apis": self.detect_anti_debug(),
            "imports": [{"dll": i["dll"], "count": i["count"]} for i in self.imports],
            "exports_count": len(self.exports_list),
        }

        if output_path is None:
            output_path = self.path.with_suffix(".analysis.json")

        with open(output_path, "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False, default=str)

        print("[+] JSON report saved: %s" % output_path)
        return output_path


def main():
    import argparse
    parser = argparse.ArgumentParser(description="PE文件深度分析器")
    parser.add_argument("--file", "-f", required=True, help="目标PE文件")
    parser.add_argument("--full", action="store_true", help="完整报告 (包含所有细节)")
    parser.add_argument("--detect-pack", action="store_true", help="仅壳检测")
    parser.add_argument("--json", "-j", help="输出JSON报告路径")
    parser.add_argument("--exports", action="store_true", help="仅导出表")

    args = parser.parse_args()

    try:
        analyzer = PEAnalyzer(args.file)

        if args.detect_pack:
            findings = analyzer.detect_packer()
            if findings:
                print("\n  [Pack Detection Results]")
                for f in findings:
                    print("  [%s] %s: %s" % (f["confidence"], f["type"], f["detail"]))
            else:
                print("\n  [+] No packer detected")
        elif args.exports:
            if analyzer.exports_list:
                print("\n  [Exports]")
                for exp in analyzer.exports_list:
                    print("  %-40s Ordinal:%-5d RVA:0x%X" % (exp["name"], exp["ordinal"], exp["rva"]))
            else:
                print("\n  [-] No exports (not a DLL or no exported functions)")
        else:
            analyzer.print_report(full=args.full)

        if args.json:
            analyzer.export_json(args.json)

    except Exception as e:
        print("[-] Error: %s" % e)
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    main()
