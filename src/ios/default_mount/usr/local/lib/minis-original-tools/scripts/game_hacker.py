#!/usr/bin/env python3
"""
游戏内存修改器 - 进程内存读写/模式扫描/DLL注入/代码注入
用法: python game_hacker.py --pid 1234 --scan --value 100
      python game_hacker.py --process game.exe --read --address 0x00400000 --size 256
      python game_hacker.py --pid 1234 --inject --dll myhack.dll
"""

import sys, os, struct, ctypes, time, re
from ctypes import wintypes
from pathlib import Path

# ======================== Windows API ========================
kernel32 = ctypes.windll.kernel32
psapi = ctypes.windll.psapi
user32 = ctypes.windll.user32

# 常量
PROCESS_ALL_ACCESS = 0x1F0FFF
PROCESS_VM_READ = 0x0010
PROCESS_VM_WRITE = 0x0020
PROCESS_VM_OPERATION = 0x0008
PROCESS_CREATE_THREAD = 0x0002
PROCESS_QUERY_INFORMATION = 0x0400
MEM_COMMIT = 0x1000
MEM_RESERVE = 0x2000
MEM_RELEASE = 0x8000
PAGE_EXECUTE_READWRITE = 0x40
PAGE_READWRITE = 0x04
TH32CS_SNAPPROCESS = 0x00000002
TH32CS_SNAPMODULE = 0x00000008
INVALID_HANDLE_VALUE = -1


class MEMORY_BASIC_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BaseAddress", ctypes.c_void_p),
        ("AllocationBase", ctypes.c_void_p),
        ("AllocationProtect", wintypes.DWORD),
        ("RegionSize", ctypes.c_size_t),
        ("State", wintypes.DWORD),
        ("Protect", wintypes.DWORD),
        ("Type", wintypes.DWORD),
    ]


class PROCESSENTRY32(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", ctypes.c_char * 260),
    ]


class MODULEENTRY32(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("th32ModuleID", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("GlblcntUsage", wintypes.DWORD),
        ("ProccntUsage", wintypes.DWORD),
        ("modBaseAddr", ctypes.POINTER(ctypes.c_byte)),
        ("modBaseSize", wintypes.DWORD),
        ("hModule", wintypes.HMODULE),
        ("szModule", ctypes.c_char * 256),
        ("szExePath", ctypes.c_char * 260),
    ]


# ======================== GameHacker 核心类 ========================
class GameHacker:
    def __init__(self):
        self.handle = None
        self.pid = None
        self.process_name = None
        self.is_64bit = True  # 默认64位

    def find_process(self, name):
        """查找进程PID"""
        name_lower = name.lower()
        snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        if snapshot == INVALID_HANDLE_VALUE:
            return None

        entry = PROCESSENTRY32()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32)

        if kernel32.Process32First(snapshot, ctypes.byref(entry)):
            while True:
                exe_name = entry.szExeFile.decode("gbk", errors="ignore").lower()
                if exe_name == name_lower or name_lower in exe_name:
                    kernel32.CloseHandle(snapshot)
                    return entry.th32ProcessID
                if not kernel32.Process32Next(snapshot, ctypes.byref(entry)):
                    break

        kernel32.CloseHandle(snapshot)
        return None

    def list_processes(self, filter_str=None):
        """列出所有进程"""
        print("\n  PID     Process Name")
        print("  " + "-" * 50)
        snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        if snapshot == INVALID_HANDLE_VALUE:
            print("  [-] Failed to create snapshot")
            return

        entry = PROCESSENTRY32()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32)
        found = 0

        if kernel32.Process32First(snapshot, ctypes.byref(entry)):
            while True:
                try:
                    name = entry.szExeFile.decode("gbk", errors="ignore").lower()
                except Exception:
                    name = ""
                if filter_str is None or filter_str.lower() in name:
                    print("  %-7d %s" % (entry.th32ProcessID, name))
                    found += 1
                if not kernel32.Process32Next(snapshot, ctypes.byref(entry)):
                    break

        kernel32.CloseHandle(snapshot)
        print("  [*] %d processes found" % found)

    def open_process(self, pid=None, name=None):
        """打开进程获取句柄"""
        if name:
            pid = self.find_process(name)
            if not pid:
                print("[-] Process not found: %s" % name)
                return False
            print("[*] Found process: %s (PID: %d)" % (name, pid))

        if not pid:
            print("[-] No PID specified")
            return False

        self.pid = pid
        self.handle = kernel32.OpenProcess(PROCESS_ALL_ACCESS, False, pid)
        if not self.handle:
            # 降级尝试
            self.handle = kernel32.OpenProcess(
                PROCESS_VM_READ | PROCESS_VM_WRITE | PROCESS_VM_OPERATION |
                PROCESS_CREATE_THREAD | PROCESS_QUERY_INFORMATION,
                False, pid
            )

        if not self.handle:
            print("[-] Failed to open process (PID: %d). Error: %d" % (pid, kernel32.GetLastError()))
            print("[!] Try running as Administrator")
            return False

        # 检测架构
        is_wow64 = ctypes.c_bool()
        if hasattr(kernel32, "IsWow64Process"):
            kernel32.IsWow64Process(self.handle, ctypes.byref(is_wow64))
            self.is_64bit = not is_wow64.value

        print("[+] Process opened: PID=%d, Handle=0x%X, %s" % (
            self.pid, self.handle, "x64" if self.is_64bit else "x86"
        ))
        return True

    def close(self):
        """关闭句柄"""
        if self.handle:
            kernel32.CloseHandle(self.handle)
            self.handle = None
            print("[*] Handle closed")

    # ======================== 内存读写 ========================
    def read_memory(self, address, size, data_type="bytes"):
        """读取进程内存"""
        buffer = ctypes.create_string_buffer(size)
        bytes_read = ctypes.c_size_t()

        if not kernel32.ReadProcessMemory(self.handle, ctypes.c_void_p(address),
                                          buffer, size, ctypes.byref(bytes_read)):
            err = kernel32.GetLastError()
            if err != 299:  # 忽略部分读取
                print("[-] ReadProcessMemory failed at 0x%X: error %d" % (address, err))
            return None

        raw = buffer.raw[:bytes_read.value]

        if data_type == "bytes":
            return raw
        elif data_type == "int32":
            return struct.unpack("<i", raw[:4])[0] if len(raw) >= 4 else None
        elif data_type == "int64":
            return struct.unpack("<q", raw[:8])[0] if len(raw) >= 8 else None
        elif data_type == "float":
            return struct.unpack("<f", raw[:4])[0] if len(raw) >= 4 else None
        elif data_type == "double":
            return struct.unpack("<d", raw[:8])[0] if len(raw) >= 8 else None
        elif data_type == "hex":
            return " ".join("%02X" % b for b in raw[:64])
        elif data_type == "string":
            null_pos = raw.find(b"\x00")
            return raw[:null_pos].decode("utf-8", errors="ignore") if null_pos > 0 else raw.decode("utf-8", errors="ignore")
        return raw

    def write_memory(self, address, data):
        """写入进程内存"""
        if isinstance(data, (int, float)):
            data = struct.pack("<i" if isinstance(data, int) and -2147483648 <= data <= 2147483647 else "<f", data)

        size = len(data) if isinstance(data, bytes) else len(data.encode())
        buffer = ctypes.create_string_buffer(data if isinstance(data, bytes) else data.encode(), size)
        bytes_written = ctypes.c_size_t()

        # 先修改页面保护
        old_protect = wintypes.DWORD()
        kernel32.VirtualProtectEx(self.handle, ctypes.c_void_p(address),
                                  size, PAGE_EXECUTE_READWRITE, ctypes.byref(old_protect))

        result = kernel32.WriteProcessMemory(self.handle, ctypes.c_void_p(address),
                                             buffer, size, ctypes.byref(bytes_written))

        # 恢复保护
        kernel32.VirtualProtectEx(self.handle, ctypes.c_void_p(address),
                                  size, old_protect, ctypes.byref(wintypes.DWORD()))

        if not result:
            print("[-] WriteProcessMemory failed at 0x%X: error %d" % (address, kernel32.GetLastError()))
            return False

        print("[+] Wrote %d bytes to 0x%X" % (bytes_written.value, address))
        return True

    # ======================== 内存扫描 ========================
    def scan_memory(self, value, data_type="int32", max_results=100):
        """扫描进程内存 - 精确值搜索"""
        if not self.handle:
            print("[-] No process opened")
            return []

        target_bytes = b""
        if data_type == "int32":
            target_bytes = struct.pack("<i", int(value))
        elif data_type == "int64":
            target_bytes = struct.pack("<q", int(value))
        elif data_type == "float":
            target_bytes = struct.pack("<f", float(value))
        elif data_type == "double":
            target_bytes = struct.pack("<d", float(value))
        elif data_type == "bytes":
            target_bytes = value if isinstance(value, bytes) else bytes.fromhex(value)

        target_len = len(target_bytes)
        results = []
        address = 0
        scanned_regions = 0
        total_bytes = 0

        print("[*] Scanning for %s = %s (%d bytes)..." % (data_type, value, target_len))
        start_time = time.time()

        while True:
            mbi = MEMORY_BASIC_INFORMATION()
            result = kernel32.VirtualQueryEx(self.handle, ctypes.c_void_p(address),
                                             ctypes.byref(mbi), ctypes.sizeof(mbi))
            if not result:
                break

            # 只扫描已提交的可读写内存
            if (mbi.State == MEM_COMMIT and
                mbi.Protect in (PAGE_READWRITE, PAGE_EXECUTE_READWRITE, 0x04, 0x08, 0x40) and
                mbi.RegionSize > 0 and mbi.RegionSize < 256 * 1024 * 1024):  # <256MB per region

                try:
                    data = self.read_memory(mbi.BaseAddress, mbi.RegionSize)
                    if data:
                        offset = 0
                        while offset < len(data) - target_len + 1:
                            pos = data.find(target_bytes, offset)
                            if pos == -1:
                                break
                            abs_addr = mbi.BaseAddress + pos
                            results.append(abs_addr)
                            offset = pos + 1
                            if len(results) >= max_results:
                                break
                except Exception:
                    pass

                scanned_regions += 1
                total_bytes += mbi.RegionSize

            address = mbi.BaseAddress + mbi.RegionSize

            # 64位进程地址空间上限
            if self.is_64bit and address > 0x7FFFFFFFFFFF:
                break
            elif not self.is_64bit and address > 0x7FFFFFFF:
                break

            if len(results) >= max_results:
                break

        elapsed = time.time() - start_time
        print("[*] Scanned %d regions (%.1f MB) in %.1fs" % (
            scanned_regions, total_bytes / (1024 * 1024), elapsed
        ))
        print("[+] Found %d matches" % len(results))
        return results

    def next_scan(self, previous_results, new_value, data_type="int32"):
        """变化值过滤 - 二次扫描"""
        target_bytes = b""
        if data_type == "int32":
            target_bytes = struct.pack("<i", int(new_value))
        elif data_type == "float":
            target_bytes = struct.pack("<f", float(new_value))
        elif data_type == "int64":
            target_bytes = struct.pack("<q", int(new_value))

        results = []
        print("[*] Filtering %d addresses for new value: %s..." % (len(previous_results), new_value))

        for addr in previous_results:
            data = self.read_memory(addr, len(target_bytes))
            if data == target_bytes:
                results.append(addr)

        print("[+] %d addresses remain" % len(results))
        return results

    def pointer_scan(self, address, max_depth=4, max_offset=0x2000):
        """指针扫描 - 查找指向目标地址的指针链"""
        print("[*] Pointer scanning for 0x%X (max depth: %d)..." % (address, max_depth))
        pointer_size = 8 if self.is_64bit else 4

        chains = []
        target = struct.pack("<Q" if self.is_64bit else "<I", address)

        # 第一层：扫描所有内存找指向目标的指针
        found = self.scan_memory(target, "bytes", max_results=500)
        for ptr_addr in found:
            chains.append([ptr_addr])

        # 继续深层扫描
        for depth in range(1, max_depth):
            new_chains = []
            for chain in chains:
                ptr_addr = chain[-1]
                # 扫描偏移范围内的指针
                # (简化实现，实际应用中需要更精细的控制)
                new_chains.append(chain)  # 保留原链

        print("[+] Found %d pointer chains" % len(chains))
        return chains

    # ======================== DLL注入 ========================
    def inject_dll(self, dll_path):
        """DLL注入 (CreateRemoteThread + LoadLibrary)"""
        if not self.handle:
            print("[-] No process opened")
            return False

        dll_path = str(Path(dll_path).resolve())
        if not os.path.exists(dll_path):
            print("[-] DLL not found: %s" % dll_path)
            return False

        print("[*] Injecting: %s" % dll_path)

        # 在目标进程分配内存
        dll_path_bytes = dll_path.encode("utf-8") + b"\x00"
        dll_len = len(dll_path_bytes)

        remote_mem = kernel32.VirtualAllocEx(
            self.handle, None, dll_len,
            MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE
        )
        if not remote_mem:
            print("[-] VirtualAllocEx failed: error %d" % kernel32.GetLastError())
            return False

        # 写入DLL路径
        written = ctypes.c_size_t()
        if not kernel32.WriteProcessMemory(self.handle, remote_mem,
                                           dll_path_bytes, dll_len,
                                           ctypes.byref(written)):
            print("[-] WriteProcessMemory failed: error %d" % kernel32.GetLastError())
            kernel32.VirtualFreeEx(self.handle, remote_mem, 0, MEM_RELEASE)
            return False

        # 获取LoadLibraryA地址
        kernel32_handle = kernel32.GetModuleHandleW("kernel32.dll")
        if not kernel32_handle:
            print("[-] GetModuleHandleW failed")
            return False

        load_lib_addr = kernel32.GetProcAddress(kernel32_handle, b"LoadLibraryA")
        if not load_lib_addr:
            print("[-] GetProcAddress(LoadLibraryA) failed")
            return False

        # 创建远程线程
        thread_handle = kernel32.CreateRemoteThread(
            self.handle, None, 0,
            load_lib_addr, remote_mem, 0, None
        )
        if not thread_handle:
            print("[-] CreateRemoteThread failed: error %d" % kernel32.GetLastError())
            kernel32.VirtualFreeEx(self.handle, remote_mem, 0, MEM_RELEASE)
            return False

        # 等待线程结束
        kernel32.WaitForSingleObject(thread_handle, 10000)

        # 获取LoadLibrary返回值(DLL基址)
        exit_code = wintypes.DWORD()
        kernel32.GetExitCodeThread(thread_handle, ctypes.byref(exit_code))

        kernel32.CloseHandle(thread_handle)
        kernel32.VirtualFreeEx(self.handle, remote_mem, 0, MEM_RELEASE)

        if exit_code.value == 0:
            print("[-] DLL load returned NULL (injection failed or DLLMain returned FALSE)")
            return False

        print("[+] DLL injected successfully! Base: 0x%X" % exit_code.value)
        return True

    # ======================== 模块信息 ========================
    def get_module_info(self, module_name=None):
        """获取进程加载的模块列表"""
        if not self.handle:
            print("[-] No process opened")
            return []

        modules = []
        snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPMODULE | TH32CS_SNAPMODULE, self.pid)
        if snapshot == INVALID_HANDLE_VALUE:
            return modules

        entry = MODULEENTRY32()
        entry.dwSize = ctypes.sizeof(MODULEENTRY32)

        if kernel32.Module32First(snapshot, ctypes.byref(entry)):
            while True:
                mod_name = entry.szModule.decode("gbk", errors="ignore")
                if module_name is None or module_name.lower() in mod_name.lower():
                    modules.append({
                        "name": mod_name,
                        "base": entry.modBaseAddr,
                        "size": entry.modBaseSize,
                        "path": entry.szExePath.decode("gbk", errors="ignore"),
                    })
                if not kernel32.Module32Next(snapshot, ctypes.byref(entry)):
                    break

        kernel32.CloseHandle(snapshot)
        return modules

    def print_modules(self, filter_name=None):
        """打印模块列表"""
        modules = self.get_module_info(filter_name)
        print("\n  Base Address    Size       Module")
        print("  " + "-" * 60)
        for m in modules:
            base_addr = ctypes.cast(m["base"], ctypes.c_void_p).value or 0
            print("  0x%016X  %-10s %s" % (base_addr, self._format_size(m["size"]), m["name"]))
        print("  [*] %d modules" % len(modules))

    # ======================== 模式扫描 (AOB Scan) ========================
    def pattern_scan(self, pattern, module_name=None):
        """AOB模式扫描 (支持 ?? 通配符)"""
        # 解析 pattern: "48 8B ?? ?? 8B 40 ?? C3"
        pat_bytes = []
        mask = []

        for byte_str in pattern.split():
            if byte_str == "??" or byte_str == "?":
                pat_bytes.append(0x00)
                mask.append(0)
            else:
                pat_bytes.append(int(byte_str, 16))
                mask.append(1)

        pat_bytes = bytes(pat_bytes)

        # 确定扫描范围
        if module_name:
            modules = self.get_module_info(module_name)
            if not modules:
                print("[-] Module not found: %s" % module_name)
                return None
            scan_base = modules[0]["base"]
            scan_size = modules[0]["size"]
        else:
            # 扫描主模块
            modules = self.get_module_info()
            if not modules:
                return None
            scan_base = modules[0]["base"]
            scan_size = modules[0]["size"]

        print("[*] Pattern scanning in %s (0x%X bytes)..." % (modules[0]["name"], scan_size))

        data = self.read_memory(scan_base, scan_size)
        if not data:
            return None

        for i in range(len(data) - len(pat_bytes) + 1):
            match = True
            for j in range(len(pat_bytes)):
                if mask[j] == 1 and data[i + j] != pat_bytes[j]:
                    match = False
                    break
            if match:
                addr = scan_base + i
                print("[+] Pattern found at: 0x%X + 0x%X = 0x%X" % (
                    ctypes.cast(scan_base, ctypes.c_void_p).value or 0,
                    i, addr
                ))
                return addr

        print("[-] Pattern not found")
        return None

    # ======================== 辅助方法 ========================
    def _format_size(self, size):
        if size > 1024 * 1024:
            return "%.1fMB" % (size / (1024 * 1024))
        elif size > 1024:
            return "%.1fKB" % (size / 1024)
        return "%dB" % size

    def hex_dump(self, address, size=256):
        """内存hex dump"""
        data = self.read_memory(address, size)
        if not data:
            return

        print("\n  Hex Dump @ 0x%X:" % address)
        print("  " + "-" * 70)
        for i in range(0, min(len(data), size), 16):
            hex_str = " ".join("%02X" % b for b in data[i:i+16])
            ascii_str = "".join(chr(b) if 32 <= b < 127 else "." for b in data[i:i+16])
            print("  0x%08X: %-48s %s" % (address + i, hex_str, ascii_str))


# ======================== CLI ========================
def main():
    import argparse
    parser = argparse.ArgumentParser(description="游戏内存修改器 - Memory Hacker")
    parser.add_argument("--pid", type=int, help="目标进程PID")
    parser.add_argument("--process", help="目标进程名 (e.g. game.exe)")
    parser.add_argument("--list", action="store_true", help="列出进程")
    parser.add_argument("--filter", help="进程名过滤")

    # 内存读写
    parser.add_argument("--read", help="读取地址 (hex)")
    parser.add_argument("--write", help="写入地址 (hex)")
    parser.add_argument("--value", help="写入值")
    parser.add_argument("--size", type=int, default=4, help="读取大小(bytes)")
    parser.add_argument("--type", default="int32",
                       choices=["int32","int64","float","double","bytes","hex","string"],
                       help="数据类型")
    parser.add_argument("--dump", help="hex dump 地址 (hex)")

    # 扫描
    parser.add_argument("--scan", action="store_true", help="首次扫描")
    parser.add_argument("--nextscan", action="store_true", help="变化值过滤")
    parser.add_argument("--scan-value", help="扫描值")
    parser.add_argument("--max-results", type=int, default=50, help="最大结果数")

    # 注入
    parser.add_argument("--inject", help="注入DLL路径")
    parser.add_argument("--dll", help="DLL路径 (同--inject)")

    # 模式扫描
    parser.add_argument("--pattern", help='AOB模式 (e.g. "48 8B ?? ?? 8B 40 ??")')
    parser.add_argument("--module", help="模块名过滤")

    # 模块
    parser.add_argument("--modules", action="store_true", help="列出模块")
    parser.add_argument("--mod-filter", help="模块名过滤")

    args = parser.parse_args()

    hacker = GameHacker()

    # 列进程
    if args.list:
        hacker.list_processes(args.filter)
        return

    # 模式扫描不需要打开进程(但需要已打开)
    if args.pattern and not args.pid and not args.process:
        print("[-] --pattern requires --pid or --process")
        return

    # 打开进程
    if args.pid or args.process:
        if not hacker.open_process(pid=args.pid, name=args.process):
            return

    if not hacker.handle and not args.list:
        hacker.list_processes(None)
        pid_str = input("\n  Enter PID: ").strip()
        if pid_str.isdigit():
            if not hacker.open_process(pid=int(pid_str)):
                return
        else:
            return

    # 模块列表
    if args.modules:
        hacker.print_modules(args.mod_filter)

    # 内存读取
    if args.read:
        addr = int(args.read, 16)
        data = hacker.read_memory(addr, args.size, args.type)
        if data is not None:
            print("[+] Read @ 0x%X: %s" % (addr, data))

    # Hex Dump
    if args.dump:
        addr = int(args.dump, 16)
        hacker.hex_dump(addr, args.size if args.size != 4 else 256)

    # 内存写入
    if args.write and args.value:
        addr = int(args.write, 16)
        if args.type in ("int32", "int64"):
            value = int(args.value)
        elif args.type in ("float", "double"):
            value = float(args.value)
        else:
            value = args.value
        hacker.write_memory(addr, value)

    # 首次扫描
    if args.scan and args.scan_value:
        results = hacker.scan_memory(args.scan_value, args.type, args.max_results)
        if results:
            print("\n  Matched Addresses:")
            for addr in results[:50]:
                current = hacker.read_memory(addr, 8 if args.type in ("int64","double") else 4, args.type)
                print("    0x%016X = %s" % (addr, current))
            print("  ... (%d total)" % len(results))

    # AOB模式扫描
    if args.pattern:
        addr = hacker.pattern_scan(args.pattern, args.module)
        if addr:
            hacker.hex_dump(addr, 64)

    # DLL注入
    dll = args.inject or args.dll
    if dll:
        hacker.inject_dll(dll)

    hacker.close()


if __name__ == "__main__":
    main()
