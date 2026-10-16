import SwiftUI
import Foundation
import UIKit
import Security
import UniformTypeIdentifiers

struct DeviceAppRecord: Identifiable, Codable {
    var bundleID: String
    var name: String
    var bundlePath: String
    var dataPath: String
    var id: String { bundleID }
    var roots: [String] { [bundlePath, dataPath].filter { !$0.isEmpty } }
}

enum DesktopSSHProfile {
    static let query:[String:Any]=[kSecClass as String:kSecClassGenericPassword,kSecAttrService as String:"MinisDesktopSSH",kSecAttrAccount as String:"profile"]
    static func save(_ data:Data) throws {
        let value=try JSONSerialization.jsonObject(with:data) as? [String:Any]
        guard let host=value?["host"] as? String, host.range(of:"^[A-Za-z0-9][A-Za-z0-9.:-]*$",options:.regularExpression) != nil,
              let user=value?["user"] as? String, user.range(of:"^[A-Za-z0-9_.-]+$",options:.regularExpression) != nil,
              let key=value?["privateKey"] as? String,key.contains("BEGIN OPENSSH PRIVATE KEY"),
              let hostKey=value?["hostKey"] as? String,hostKey.hasPrefix("ssh-ed25519 ") else { throw WorkbenchError.unavailable("电脑配置格式不正确") }
        var q=query; q[kSecValueData as String]=data; q[kSecAttrAccessible as String]=kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        SecItemDelete(query as CFDictionary)
        guard SecItemAdd(q as CFDictionary,nil)==errSecSuccess else { throw WorkbenchError.unavailable("无法写入连接凭据钥匙串") }
    }
    static func load() throws -> [String:Any] {
        var q=query;q[kSecReturnData as String]=true;q[kSecMatchLimit as String]=kSecMatchLimitOne
        var result:CFTypeRef?
        guard SecItemCopyMatching(q as CFDictionary,&result)==errSecSuccess,
              let data=result as? Data, let profile=try JSONSerialization.jsonObject(with:data) as? [String:Any] else { throw WorkbenchError.unavailable("先导入当前 Windows 电脑的 SSH 连接配置") }
        return profile
    }
}

enum WorkbenchError: LocalizedError {
    case unavailable(String)
    var errorDescription: String? { if case .unavailable(let s) = self { return s }; return nil }
}

@MainActor final class DeviceWorkbench: ObservableObject {
    static let shared = DeviceWorkbench()
    @Published var apps: [DeviceAppRecord] = []
    @Published var log = ""
    @Published var busy = false
    @Published var results: [WorkbenchCheck] = []
    @Published var installingName = ""
    @Published var installStage = ""
    @Published var componentStatus: [String: String] = [:]
    @Published var installError = ""
    @Published var installSucceeded = false
    @Published var diagnosticStarted: Date?
    @Published var diagnosticDuration: TimeInterval = 0
    func installFromUI(_ name: String) async {
        guard !busy else { return }
        busy = true; installError = ""; installSucceeded = false
        installingName = name; installStage = "准备"
        defer { busy = false }
        do {
            try await install(name)
            installStage = "完成"; installSucceeded = true
            componentStatus[name] = "已安装 · 启动检查通过"
        } catch {
            installError = error.localizedDescription
            componentStatus[name] = "安装失败 · 可重试"
            record("安装失败：\(error.localizedDescription)")
        }
    }
    let fm = FileManager.default
    var root: URL { SharedContainerStore.storageContainerURL.appendingPathComponent("Workbench", isDirectory: true) }
    var fullRead: Bool { UserDefaults.standard.bool(forKey: "workbench.fullRead") }
    func refreshApps() {
        apps = MinisDeviceBridge.applications().compactMap { item in
            guard let bid = item["bundleID"], let name = item["name"] else { return nil }
            return DeviceAppRecord(bundleID: bid, name: name, bundlePath: item["bundlePath"] ?? "", dataPath: item["dataPath"] ?? "")
        }.sorted { $0.name.localizedStandardCompare($1.name) == .orderedAscending }
    }
    func selected(_ session: String) -> [DeviceAppRecord] {
        guard let data = UserDefaults.standard.data(forKey: "workbench.apps.\(session)"),
              let items = try? JSONDecoder().decode([DeviceAppRecord].self, from: data) else { return [] }
        return items
    }
    func select(_ app: DeviceAppRecord, session: String) throws -> URL {
        var items = selected(session)
        if !items.contains(where: { $0.id == app.id }) { items.append(app) }
        UserDefaults.standard.set(try JSONEncoder().encode(items), forKey: "workbench.apps.\(session)")
        try fm.createDirectory(at: root, withIntermediateDirectories: true)
        let file = root.appendingPathComponent("app-\(UUID().uuidString).json")
        let context: [String: Any] = ["application": app.name, "bundleID": app.bundleID,
            "bundlePath": app.bundlePath, "dataPath": app.dataPath,
            "readable": app.roots.map { fm.isReadableFile(atPath: $0) },
            "tool": "device_app", "actions": ["inspect", "open", "list_files", "read_file", "write_file", "get_ui", "tap", "type", "screenshot"],
            "note": "Native paths belong to this phone, not the iSH guest. Use device_app for native files. UI actions require a reachable WebDriverAgent session; inspect reports actual capability."]
        try JSONSerialization.data(withJSONObject: context, options: [.prettyPrinted, .sortedKeys]).write(to: file, options: .atomic)
        return file
    }
    func checkedPath(_ path: String, session: String) throws -> URL {
        guard path.hasPrefix("/") else { throw WorkbenchError.unavailable("需要绝对设备路径") }
        let url = URL(fileURLWithPath: path).resolvingSymlinksInPath().standardizedFileURL
        let roots = selected(session).flatMap(\.roots) + [SharedContainerStore.storageContainerURL.path, NSHomeDirectory()]
        guard fullRead || roots.contains(where: { base in
            let normalized = URL(fileURLWithPath: base).resolvingSymlinksInPath().standardizedFileURL.path
            return url.path == normalized || url.path.hasPrefix(normalized + "/")
        }) else { throw WorkbenchError.unavailable("先在当前对话添加目标应用，或开启扩展文件访问") }
        return url
    }
    func tool(_ args: [String: Any], session: String) async throws -> String {
        let action = args["action"] as? String ?? "inspect"
        let bid = args["bundle_id"] as? String ?? selected(session).first?.bundleID ?? ""
        switch action {
        case "list":
            refreshApps()
            return String(data: try JSONEncoder().encode(apps), encoding: .utf8) ?? "[]"
        case "inspect":
            let entries = selected(session).filter { bid.isEmpty || $0.bundleID == bid }
            let report: [String: Any] = ["selected": entries.map { ["bundleID":$0.bundleID,"bundlePath":$0.bundlePath,"dataPath":$0.dataPath] },
                "fullReadRequested": fullRead, "varReadable": fm.isReadableFile(atPath: "/var/mobile/Containers/Data/Application"),
                "wdaURL": UserDefaults.standard.string(forKey: "workbench.wdaURL") ?? "", "wdaSession": UserDefaults.standard.string(forKey: "workbench.wdaSession") ?? ""]
            return String(data: try JSONSerialization.data(withJSONObject: report, options: .prettyPrinted), encoding: .utf8) ?? "{}"
        case "open":
            guard selected(session).contains(where: { $0.bundleID == bid }) else { throw WorkbenchError.unavailable("目标应用尚未添加到当前对话") }
            guard MinisDeviceBridge.openApplication(bid) else { throw WorkbenchError.unavailable("系统未允许启动该应用") }
            return "系统已接受打开应用请求：\(bid)"
        case "list_files", "read_file", "write_file":
            let url = try checkedPath(args["path"] as? String ?? "", session: session)
            if action == "list_files" {
                return try fm.contentsOfDirectory(atPath: url.path).prefix(1000).joined(separator: "\n")
            }
            if action == "write_file" {
                // File writes are explicit tool operations, never performed by diagnostics.
                guard let text = args["text"] as? String else { throw WorkbenchError.unavailable("缺少 text") }
                try Data(text.utf8).write(to: url, options: .atomic)
                return "已写入 \(text.utf8.count) 字节：\(url.path)"
            }
            let handle = try FileHandle(forReadingFrom: url); defer { try? handle.close() }
            let data = try handle.read(upToCount: 262144) ?? Data()
            return String(data: data, encoding: .utf8) ?? "二进制文件（前 \(data.count) 字节）：\(data.base64EncodedString())"
        case "get_ui", "tap", "type", "screenshot":
            return try await wda(action, args: args)
        default: throw WorkbenchError.unavailable("未知 device_app 操作：\(action)")
        }
    }
    func wda(_ action: String, args: [String: Any]) async throws -> String {
        let raw = UserDefaults.standard.string(forKey: "workbench.wdaURL") ?? "http://127.0.0.1:8100"
        guard let base = URL(string: raw), ["http","https"].contains(base.scheme ?? "") else { throw WorkbenchError.unavailable("WebDriverAgent 地址无效") }
        let sid = UserDefaults.standard.string(forKey: "workbench.wdaSession") ?? ""
        guard !sid.isEmpty else { throw WorkbenchError.unavailable("尚未配置运行中的 WebDriverAgent session；打开应用和文件读取不依赖 WDA") }
        let suffix: String
        var body: [String: Any]?
        switch action {
        case "tap": suffix = "wda/tap/0"; guard let x=args["x"] as? NSNumber, let y=args["y"] as? NSNumber else { throw WorkbenchError.unavailable("缺少 x/y") }; body=["x":x,"y":y]
        case "type": suffix="wda/keys"; body=["value":Array((args["text"] as? String ?? "").map { String($0) })]
        case "screenshot": suffix="screenshot"
        default: suffix="source"
        }
        var request=URLRequest(url: base.appendingPathComponent("session").appendingPathComponent(sid).appendingPathComponent(suffix))
        request.timeoutInterval=20
        if let body { request.httpMethod="POST"; request.setValue("application/json", forHTTPHeaderField:"Content-Type"); request.httpBody=try JSONSerialization.data(withJSONObject:body) }
        let (data,response)=try await URLSession.shared.data(for: request)
        guard let http=response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else { throw WorkbenchError.unavailable("WDA 请求失败：\((response as? HTTPURLResponse)?.statusCode ?? 0)") }
        if let object = try? JSONSerialization.jsonObject(with: data) as? [String:Any],
           let value = object["value"] as? [String:Any], let error = value["error"] as? String {
            throw WorkbenchError.unavailable("WDA：\(error) \(value["message"] as? String ?? "")")
        }
        if action == "screenshot", let object=try JSONSerialization.jsonObject(with:data) as? [String:Any], let text=object["value"] as? String, let image=Data(base64Encoded:text) {
            try fm.createDirectory(at: root, withIntermediateDirectories:true)
            let file=root.appendingPathComponent("screen-\(UUID().uuidString).png"); try image.write(to:file)
            return "截图已保存：\(file.path)；可用 device_app read_file 读取。"
        }
        return String(data:data,encoding:.utf8) ?? "WDA 返回非文本响应"
    }
    func run(_ command: String, timeout: TimeInterval = 900) async throws -> ISHCommandResult {
        guard !RootfsManager.shared.didResetWhileBooted else { throw WorkbenchError.unavailable("Linux 环境已重置，需要重启应用，不能重用旧内核挂载") }
        if !ISHKernel.shared.isBooted {
            let manager = RootfsManager.shared
            // A diagnostic repair must not silently erase an existing Linux environment.
            if fm.fileExists(atPath: manager.dataPath.path) && !manager.isInstalled {
                throw WorkbenchError.unavailable("已有 Linux 环境的架构标记不完整；保留原数据，请在环境设置中人工检查")
            }
            try await Task.detached(priority: .userInitiated) { try RootfsManager.shared.installIfNeeded() }.value
            let code = await minisBootKernel(rootPath: manager.rootfsPath.path)
            guard code == 0 else { throw WorkbenchError.unavailable("iSH 启动失败：\(code)") }
            installSessionFileChangeTracker(kernel: ISHKernel.shared)
            MinisFsRouter.shared.installHook()
            manager.applyDefaultMountOverlay()
            JailbreakFullAccessManager.shared.enableIfJailbroken()
        }
        return try await ISHExecutionCoordinator.shared.execute(sessionId:"workbench", command:command, timeout:timeout, lineCallback:{ [weak self] line in
            Task { @MainActor in
                guard let self = self else { return }
                if line.contains("MINIS_STAGE:") {
                    self.installStage = String(line.components(separatedBy: "MINIS_STAGE:").last ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
                }
                self.record(line)
            }
        }, pidCallback:{ _ in })
    }
    func record(_ message: String) {
        log += "\n[\(Date())] \(message)"
        if log.count > 200000 { log=String(log.suffix(200000)) }
        try? fm.createDirectory(at:root,withIntermediateDirectories:true)
        try? Data(log.utf8).write(to:root.appendingPathComponent("diagnostics.log"),options:.atomic)
    }
    func diagnose(repair: Bool = false) async {
        guard !busy else { return }; busy=true; defer { busy=false }
        results=[]
        diagnosticStarted=Date()
        defer { diagnosticDuration=Date().timeIntervalSince(diagnosticStarted ?? Date()) }
        if repair {
            do { for (component, probe) in [("CoreTools","command -v curl && command -v git && command -v file"), ("Python","command -v python3"), ("ReverseTools","command -v llvm-objdump && command -v readelf"), ("Codex","codex --version"), ("Theos","test -f /opt/theos/makefiles/common.mk")] {
                    let result = try await run(probe, timeout: 30)
                    if result.exitCode != 0 { do { try await install(component) } catch { record("\(component)：\(error.localizedDescription)") } }
                }
                importAgents() }
            catch { record("修复：\(error.localizedDescription)") }
        }
        let checks: [(String,String)] = [
            ("命令执行", "printf 'shell-ok'"),
            ("项目文件", "p=/tmp/minis-check-$$; printf test > \"$p\" && test \"$(cat \"$p\")\" = test && rm \"$p\""),
            ("Git 与常用工具", "git --version && grep --version >/dev/null && command -v tar"),
            ("代码辅助与 TLS", "command -v clang && command -v openssl && test -s /etc/ssl/certs/ca-certificates.crt"),
            ("Codex", "codex --version"),
            ("CoreTools", "command -v bash && command -v curl && command -v unzip && command -v file"),
            ("Python", "python3 --version && python3 -c 'import ssl,sqlite3,json'"),
            ("ReverseTools", "command -v llvm-objdump && command -v strings && command -v readelf"),
            ("Theos", "test -f /opt/theos/makefiles/common.mk && command -v make && command -v clang"),
            ("Linux C 编译", "p=/tmp/minis-cc-$$; printf 'int main(){return 0;}' > \"$p.c\"; clang \"$p.c\" -o \"$p\" && \"$p\"; r=$?; rm -f \"$p.c\" \"$p\"; exit $r"),
            ("iOS dylib 编译", "p=/tmp/minis-ios-$$; printf 'int minis_probe(void){return 1;}' > \"$p.c\"; clang --target=arm64-apple-ios15.4 -isysroot /opt/theos/sdks/iPhoneOS16.5.sdk -fuse-ld=lld -dynamiclib \"$p.c\" -o \"$p.dylib\" && file \"$p.dylib\"; r=$?; rm -f \"$p.c\" \"$p.dylib\"; exit $r"),
            ("iOS SDK", "for v in 15.6 16.5 17.5 18.6; do s=/opt/theos/sdks/iPhoneOS$v.sdk; test -f \"$s/System/Library/Frameworks/Foundation.framework/Headers/Foundation.h\" && test -f \"$s/usr/lib/libSystem.tbd\" || exit 1; echo \"SDK $v headers + link stubs OK\"; done")]
        for (name,command) in checks {
            do { let result=try await run(command,timeout:60); results.append(WorkbenchCheck(name:name,ok:result.exitCode==0,detail:result.output)); record("\(name) rc=\(result.exitCode)\n\(result.output)") }
            catch { results.append(WorkbenchCheck(name:name,ok:false,detail:error.localizedDescription)); record("\(name)：\(error.localizedDescription)") }
        }
        results.append(WorkbenchCheck(name:"本机文件权限",ok:fm.isReadableFile(atPath:"/var/mobile/Containers/Data/Application"),detail:"按实际目录读取权限检测；iSH 内 root 不等于 iOS root"))
    }
    func install(_ name: String) async throws {
        installStage = "准备"
        let command: String
        switch name {
        case "CoreTools": command="apk add --no-cache bash curl wget git ca-certificates openssl tar unzip zip file coreutils findutils grep sed make perl; command -v git; curl --version; file --version"
        case "Python": command="apk add --no-cache python3 py3-pip; python3 --version; python3 -c 'import ssl,sqlite3,json'"
        case "ReverseTools": command="apk add --no-cache binutils llvm llvm-dev clang lld gdb; llvm-objdump --version; readelf --version"
        case "Theos": command="apk add --no-cache git make perl clang lld && (test -f /opt/theos/makefiles/common.mk || git clone --recursive --depth 1 https://github.com/theos/theos.git /opt/theos); test -f /opt/theos/makefiles/common.mk; make --version"
        case "Codex":
            // Download an actual musl build, not an iOS-incompatible macOS binary.
            let url=URL(string:"https://api.github.com/repos/openai/codex/releases/latest")!
            let (data,response)=try await URLSession.shared.data(from:url)
            guard (response as? HTTPURLResponse)?.statusCode == 200,
                  let release=try JSONSerialization.jsonObject(with:data) as? [String:Any], let assets=release["assets"] as? [[String:Any]],
                  let asset=assets.first(where: { $0["name"] as? String == "codex-aarch64-unknown-linux-musl.tar.gz" }),
                  let digest=asset["digest"] as? String, digest.hasPrefix("sha256:"), digest.count == 71,
                  let link=asset["browser_download_url"] as? String, link.hasPrefix("https://github.com/openai/codex/releases/") else { throw WorkbenchError.unavailable("未找到官方 ARM64 musl 资产；未安装") }
            let hash = String(digest.dropFirst(7))
            guard hash.allSatisfy({ $0.isHexDigit }) else { throw WorkbenchError.unavailable("官方资产摘要无效") }
            command="""
            set -e
            echo MINIS_STAGE:准备
            apk add --no-cache curl ca-certificates tar coreutils
            d=$(mktemp -d /tmp/minis-codex.XXXXXX)
            trap 'rm -rf "$d"' EXIT
            echo MINIS_STAGE:下载
            curl --fail --location --retry 2 --connect-timeout 20 --max-time 900 '\(link)' -o "$d/codex.tar.gz"
            echo MINIS_STAGE:校验
            printf '%s  %s\\n' '\(hash)' "$d/codex.tar.gz" | sha256sum -c -
            echo MINIS_STAGE:解压
            tar -tzf "$d/codex.tar.gz" > "$d/members"
            if grep -Eq '(^/|(^|/)\\.\\.(/|$))' "$d/members"; then echo 'Unsafe archive path'; exit 1; fi
            mkdir "$d/payload"
            tar -xzf "$d/codex.tar.gz" -C "$d/payload" --no-same-owner --no-same-permissions
            b=$(find "$d/payload" -type f -name 'codex*' | head -1)
            test -n "$b"
            chmod 755 "$b"
            echo MINIS_STAGE:启动验证
            timeout 30 "$b" --version
            echo MINIS_STAGE:安装
            install -m 755 "$b" /usr/local/bin/codex.minis-new
            if test -f /usr/local/bin/codex; then cp -p /usr/local/bin/codex /usr/local/bin/codex.minis-backup; fi
            mv /usr/local/bin/codex.minis-new /usr/local/bin/codex
            if ! timeout 30 /usr/local/bin/codex --version; then
                if test -f /usr/local/bin/codex.minis-backup; then mv /usr/local/bin/codex.minis-backup /usr/local/bin/codex; else rm -f /usr/local/bin/codex; fi
                exit 1
            fi
            """
        default: throw WorkbenchError.unavailable("未知组件")
        }
        installStage = "下载安装与验证"
        let result=try await run("set -e; " + command,timeout:1800); record("安装 \(name) rc=\(result.exitCode)\n\(result.output)")
        guard result.exitCode==0 else { throw WorkbenchError.unavailable("\(name) 安装或启动验证失败：\(result.output.suffix(1000))") }
    }
    func buildWorkbench(_ args:[String:Any]) async throws -> String {
        let action=args["action"] as? String ?? "doctor"
        guard ["doctor","install-sdks","build"].contains(action),
              let bundle=Bundle.main.url(forResource:"BuildWorkbench",withExtension:"bundle") else {
            throw WorkbenchError.unavailable("构建工作台资源或动作不可用")
        }
        let setup=try await run("mkdir -p /opt/minis-workbench",timeout:120)
        guard setup.exitCode==0 else { throw WorkbenchError.unavailable(setup.output) }
        guard ISHKernel.shared.bindMountPath("/opt/minis-workbench",toHostPath:bundle.path,readOnly:true)==0 else {
            throw WorkbenchError.unavailable("无法只读挂载内置 SDK 与构建脚本")
        }
        func quote(_ value:String)->String { "'"+value.replacingOccurrences(of:"'",with:"'\"'\"'")+"'" }
        var command="python3 /opt/minis-workbench/minis_build.py "+action
        if action=="build" {
            for key in ["target","project","output"] {
                guard let value=args[key] as? String, !value.isEmpty else { throw WorkbenchError.unavailable("缺少构建参数：\(key)") }
                command += " --\(key) "+quote(value)
            }
            for key in ["sdk","minimum","remote"] {
                if let value=args[key] as? String, !value.isEmpty { command += " --\(key) "+quote(value) }
            }
        }
        let result=try await run(command,timeout:1800)
        record("BuildWorkbench \(action) rc=\(result.exitCode)\n\(result.output)")
        guard result.exitCode==0 else { throw WorkbenchError.unavailable(result.output) }
        return result.output
    }
    func desktopTool(_ args:[String:Any]) async throws -> String {
        let profile=try DesktopSSHProfile.load()
        guard let host=profile["host"] as? String, let user=profile["user"] as? String,
              let key=profile["privateKey"] as? String, let hostKey=profile["hostKey"] as? String else { throw WorkbenchError.unavailable("电脑连接配置缺字段") }
        let port=profile["port"] as? Int ?? 22
        guard (1...65535).contains(port) else { throw WorkbenchError.unavailable("SSH端口无效") }
        let folder=URL(fileURLWithPath:NSHomeDirectory()).appendingPathComponent("Library/MinisDesktopSSH",isDirectory:true)
        try fm.createDirectory(at:folder,withIntermediateDirectories:true)
        let keyFile=folder.appendingPathComponent("identity")
        try Data(key.utf8).write(to:keyFile,options:[.atomic,.completeFileProtectionUnlessOpen])
        try fm.setAttributes([.posixPermissions:0o600],ofItemAtPath:keyFile.path)
        let known=(port==22 ? host : "[\(host)]:\(port)")+" "+hostKey+"\n"
        try Data(known.utf8).write(to:folder.appendingPathComponent("known_hosts"),options:.atomic)
        let setup=try await run("mkdir -p /opt/minis-desktop",timeout:120)
        guard setup.exitCode==0, ISHKernel.shared.bindMountPath("/opt/minis-desktop",toHostPath:folder.path,readOnly:true)==0 else { throw WorkbenchError.unavailable("无法挂载电脑连接密钥") }
        func q(_ value:String)->String { "'"+value.replacingOccurrences(of:"'",with:"'\"'\"'")+"'" }
        let options=" -i /opt/minis-desktop/identity -o BatchMode=yes -o StrictHostKeyChecking=yes -o UserKnownHostsFile=/opt/minis-desktop/known_hosts -o ConnectTimeout=15 "
        let action=args["action"] as? String ?? "probe"
        let command:String
        if action=="upload" || action=="download" {
            guard let path=args["path"] as? String,let remote=args["remotePath"] as? String,!path.isEmpty,!remote.isEmpty else { throw WorkbenchError.unavailable("文件传输需要 path（Linux路径）和 remotePath（Windows路径）") }
            let remoteArg=user+"@"+host+":"+remote
            command="scp -P \(port)"+options+(action=="upload" ? q(path)+" "+q(remoteArg) : q(remoteArg)+" "+q(path))
        } else {
            let script:String
            if action=="probe" {
                script="$names=@('python','git','node','rea','frida','idat64','hopper','dotnet','adb','gradle','wsl','ssh'); $r=@{}; foreach($n in $names){$c=Get-Command $n -ErrorAction SilentlyContinue; $r[$n]=if($c){$c.Source}else{$null}}; @{computer=$env:COMPUTERNAME;user=$env:USERNAME;tools=$r} | ConvertTo-Json -Depth 4"
            } else if action=="run",let text=args["command"] as? String,!text.isEmpty { script=text }
            else { throw WorkbenchError.unavailable("动作需要 probe、run、upload 或 download") }
            let utf8script="[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false);$OutputEncoding=[Console]::OutputEncoding;"+script
            let encoded=(utf8script.data(using:.utf16LittleEndian) ?? Data()).base64EncodedString()
            command="ssh -p \(port)"+options+q(user+"@"+host)+" powershell.exe -NoLogo -NoProfile -NonInteractive -EncodedCommand "+encoded
        }
        let result=try await run(command,timeout:1800)
        guard result.exitCode==0 else { throw WorkbenchError.unavailable("电脑操作失败 rc=\(result.exitCode)\n\(result.output)") }
        return result.output
    }
    func importAgents() {
        let entries=[("device-debug","应用调试","使用 device_app 检查已添加应用的目录和运行状态；UI操作需要实际可用的 WDA 会话。"),
            ("reverse-analysis","逆向分析","先只读排查外来样本的破坏、窃密和持久化，再定位架构、导入、字符串和调用链。区分静态发现与真机验证。"),
            ("toolchain","工具链维护","检查并安装缺失依赖，执行编译探针，记录退出码；不把下载成功当作可执行。"),
            ("diagnostics","运行诊断","依据真实命令、文件读写和权限探针检查环境。保留错误，不伪造全绿结果。")]
        for (name,description,instructions) in entries where !SubAgentStore.shared.subAgents.contains(where:{$0.name==name}) {
            guard SubAgentStore.shared.canAddSubAgent else { record("Agent 名额已满，保留已有配置"); break }
            SubAgentStore.shared.upsertSubAgent(SubAgentDefinition(name:name,description:description,instructions:instructions))
        }
        record("Agent 配置已合并，未覆盖已有项")
    }
    var artifacts: [URL] {
        let documents=fm.urls(for:.documentDirectory,in:.userDomainMask).first ?? root
        var files:[URL]=[]
        var seen=Set<String>()
        for directory in [AIChatViewModel.minisSharedPersistentDir, root, documents] {
            guard let enumerator=fm.enumerator(at:directory,includingPropertiesForKeys:[.isRegularFileKey],options:[.skipsHiddenFiles]) else { continue }
            for case let file as URL in enumerator {
                if files.count>=300 { break }
                if file.lastPathComponent=="alpine-rootfs" { enumerator.skipDescendants(); continue }
                if ["ipa","dylib","zip","deb","apk","exe","png","pdf","json","txt"].contains(file.pathExtension.lowercased()), seen.insert(file.path).inserted,
                   (try? file.resourceValues(forKeys:[.isRegularFileKey]).isRegularFile)==true { files.append(file) }
            }
        }
        return files
    }

}
struct WorkbenchCheck: Identifiable { let id=UUID(); let name:String; let ok:Bool; let detail:String }

struct AttachmentWorkbenchSheet: View {
    let choose: (String) -> Void
    @Environment(\.presentationMode) private var presentation
    let items=[("应用","square.stack.3d.up","选择分析与调用","apps"),("相册","photo.on.rectangle","照片与视频，最多 8 项","photos"),("相机","camera","拍照加入对话","camera"),("文件","paperclip","源码、IPA、dylib","files"),("产物","shippingbox","复用历史输出","artifacts")]
    var body: some View {
        NavigationView {
            ScrollView {
                Text("应用、图片、文件和历史产物仅用于当前对话").font(.footnote).foregroundColor(.secondary).padding()
                LazyVGrid(columns:[GridItem(.flexible()),GridItem(.flexible())],spacing:12) {
                    ForEach(items.indices,id:\.self) { index in
                        let item = items[index]
                        Button { choose(item.3) } label: {
                            VStack(spacing:10) { Image(systemName:item.1).font(.title).foregroundColor(.blue); Text(item.0).font(.headline); Text(item.2).font(.caption).foregroundColor(.secondary) }.frame(maxWidth:.infinity,minHeight:110).background(Color(UIColor.secondarySystemBackground)).cornerRadius(16)
                        }.buttonStyle(.plain)
                    }
                }.padding()
            }.navigationTitle("添加到对话").navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement:.navigationBarTrailing) { Button("关闭") { presentation.wrappedValue.dismiss() } } }
        }.navigationViewStyle(.stack)
    }
}
struct DeviceAppPicker: View {
    let session:String
    let attach:(URL)->Void
    @ObservedObject private var model=DeviceWorkbench.shared
    @State private var query=""
    @State private var error=""
    @Environment(\.presentationMode) private var presentation
    var body: some View {
        NavigationView {
            List {
                if !error.isEmpty { Text(error).foregroundColor(.red) }
                if model.apps.isEmpty { Text("未能枚举应用：检查 TrollStore 安装权限。不会把空列表当成已授权。") }
                ForEach(model.apps.filter { query.isEmpty || $0.name.localizedCaseInsensitiveContains(query) || $0.bundleID.localizedCaseInsensitiveContains(query) }) { app in
                    Button { do { attach(try model.select(app,session:session)); presentation.wrappedValue.dismiss() } catch { self.error=error.localizedDescription } } label: {
                        VStack(alignment:.leading) { Text(app.name); Text(app.bundleID).font(.caption).foregroundColor(.secondary) }
                    }
                }
            }.searchable(text:$query).navigationTitle("添加应用")
            .toolbar { ToolbarItem(placement:.navigationBarTrailing) { Button("刷新") { model.refreshApps() } } }
            .onAppear { model.refreshApps() }
        }.navigationViewStyle(.stack)
    }
}
struct WorkbenchArtifactsView: View {
    let attach:(URL)->Void
    @Environment(\.presentationMode) private var presentation
    var body: some View {
        NavigationView { List(DeviceWorkbench.shared.artifacts,id:\.path) { file in Button(file.lastPathComponent) { attach(file); presentation.wrappedValue.dismiss() } }.navigationTitle("历史产物") }.navigationViewStyle(.stack)
    }
}
struct DevelopmentWorkbenchView: View {
    @ObservedObject private var model=DeviceWorkbench.shared
    @AppStorage("workbench.fullRead") private var fullRead=false
    @AppStorage("workbench.wdaURL") private var wdaURL="http://127.0.0.1:8100"
    @AppStorage("workbench.wdaSession") private var wdaSession=""
    @State private var showLogs=false
    @State private var status=""
    var body: some View {
        List {
            Section(header:Text("开发环境与诊断")) {
                NavigationLink("SDK 与多平台构建工作台") { MultiPlatformWorkbenchView() }
                NavigationLink("内置终端") { ISHTerminalView(showCloseButton: true) }
                NavigationLink("Tools · 三个基础工具包") { List { Text("CoreTools：文件、网络与项目工具"); Text("ReverseTools：LLVM / binutils / GDB"); Text("Python：解释器及 pip") }.navigationTitle("Tools") }
                ForEach(["Codex","Theos","CoreTools","ReverseTools","Python"],id:\.self) { name in
                    NavigationLink { RuntimeComponentView(name:name) } label: {
                        HStack { Text(name); Spacer(); Text(model.componentStatus[name] ?? "查看与安装").font(.caption).foregroundColor(.secondary) }
                    }
                }
                Text("点击组件后在应用内安装。当前 Linux 工具运行于 iSH，并非原生 iOS 可执行文件；完整 iOS 编译需另备匹配 SDK/交叉编译器。").font(.caption).foregroundColor(.secondary)
                NavigationLink("Skills 与扩展") { SkillsManagementView() }
                NavigationLink("Agent 配置") { HelperSettingsView() }
                Button("合并本地调试 Agent") { model.importAgents(); status="已合并；原 Agent 保留" }
                NavigationLink("运行诊断") { WorkbenchDiagnosticsView() }
                NavigationLink("日志") { WorkbenchLogView() }
            }
            Section(header:Text("文件与应用调试权限")) {
                Toggle("扩展文件访问（全权限请求）",isOn:$fullRead).onChange(of:fullRead) { value in
                    if value { JailbreakFullAccessManager.shared.enableIfJailbroken() } else { JailbreakFullAccessManager.shared.disableAccess() }
                }
                Text("开关只启用已获系统权限的访问路径，不伪造授权。无法读取的目录会返回真实错误；受保护、加密、只读系统文件仍可能不可访问。").font(.caption).foregroundColor(.secondary)
                Text("应用数据目录：\(FileManager.default.isReadableFile(atPath:"/var/mobile/Containers/Data/Application") ? "可读" : "当前不可读")")
                NavigationLink("本机文件浏览") { NativeDeviceFileBrowser(path:fullRead ? "/" : NSHomeDirectory()) }
            }
            Section(header:Text("跨应用 UI 调试桥")) {
                TextField("WebDriverAgent URL",text:$wdaURL).textInputAutocapitalization(.never).autocorrectionDisabled()
                TextField("已运行的 WDA Session ID",text:$wdaSession).textInputAutocapitalization(.never).autocorrectionDisabled()
                Text("应用启动、目录分析使用本机桥；触摸、输入、界面树和截图必须连接实际运行的 WDA。未部署时不会报告 UI 控制就绪。").font(.caption).foregroundColor(.secondary)
            }
            if !status.isEmpty { Section { Text(status).font(.caption) } }
            Section(header:Text("实际检测结果：\(model.results.filter(\.ok).count)/\(model.results.count) 通过")) {
                ForEach(model.results) { row in HStack(alignment:.top) { Image(systemName:row.ok ? "checkmark.circle.fill" : "exclamationmark.circle").foregroundColor(row.ok ? .green : .orange); VStack(alignment:.leading) { Text(row.name); Text(row.detail.isEmpty ? (row.ok ? "探针成功" : "探针失败") : String(row.detail.suffix(1500))).font(.caption).foregroundColor(.secondary) } } }
            }
        }.navigationTitle("开发环境与诊断")
    }
}
struct RuntimeComponentView: View {
    let name: String
    @ObservedObject private var model = DeviceWorkbench.shared
    private var active: Bool { model.installingName == name }
    var body: some View {
        ScrollView {
            VStack(alignment:.leading, spacing:20) {
                Text(name).font(.largeTitle.bold())
                Text(model.componentStatus[name] ?? "尚未检查安装状态").foregroundColor(.secondary)
                Text("在应用内准备、下载、校验、解压、安装并运行探针。Alpine 包由 apk 验签；Codex 资产校验 GitHub SHA256。失败保留日志，不显示虚假就绪状态。").font(.callout)
                if active && model.busy { ProgressView(); Text(model.installStage).font(.headline) }
                HStack {
                    ForEach(["准备","下载","校验","解压","安装"],id:\.self) { stage in
                        VStack { Image(systemName: active && model.installSucceeded ? "checkmark.circle.fill" : "circle"); Text(stage).font(.caption) }.frame(maxWidth:.infinity)
                    }
                }.foregroundColor(active && model.installSucceeded ? .green : .secondary)
                if active && !model.installError.isEmpty { Text(model.installError).foregroundColor(.red).textSelection(.enabled) }
                Button(model.busy ? "正在安装…" : "安装 / 修复") { Task { await model.installFromUI(name) } }
                    .buttonStyle(.borderedProminent).disabled(model.busy)
                Text("Theos 的项目文件安装成功不代表已具备 iOS SDK。诊断会单独检查手机编译和 iOS SDK。").font(.caption).foregroundColor(.secondary)
                if active { Text(String(model.log.suffix(6000))).font(.system(.caption,design:.monospaced)).textSelection(.enabled) }
            }.padding()
        }.navigationTitle(name)
    }
}
struct WorkbenchDiagnosticsView: View {
    @ObservedObject private var model = DeviceWorkbench.shared
    var body: some View {
        List {
            Section {
                Label(model.busy ? "正在检查核心能力" : (model.results.isEmpty ? "等待检查" : "检查完成"),systemImage:model.busy ? "clock" : "stethoscope")
                Text("\(model.results.filter(\.ok).count)/\(model.results.count) 项通过 · \(Int(model.diagnosticDuration)) 秒").font(.caption)
                Button("运行诊断") { Task { await model.diagnose() } }.disabled(model.busy)
                Button("自动修复并重新检查") { Task { await model.diagnose(repair:true) } }.disabled(model.busy)
            }
            ForEach(["基础运行","项目能力","可选能力","组件与工具"],id:\.self) { group in
                Section(header:Text(group)) {
                    ForEach(model.results.filter { row in diagnosticGroup(row.name) == group }) { row in
                        HStack(alignment:.top) {
                            Image(systemName:row.ok ? "checkmark.circle" : "exclamationmark.circle").foregroundColor(row.ok ? .green : .orange)
                            VStack(alignment:.leading) { Text(row.name); Text(String(row.detail.suffix(1500))).font(.caption).foregroundColor(.secondary).textSelection(.enabled) }
                        }
                    }
                }
            }
        }.navigationTitle("运行诊断")
        .toolbar { ToolbarItem(placement:.navigationBarTrailing) { Button("复制") { UIPasteboard.general.string=model.results.map { "\($0.ok ? "PASS" : "FAIL") \($0.name)\n\($0.detail)" }.joined(separator:"\n") } } }
        .task { if model.results.isEmpty { await model.diagnose() } }
    }
    private func diagnosticGroup(_ name:String)->String {
        if ["命令执行","项目文件","本机文件权限"].contains(name) { return "基础运行" }
        if ["Git 与常用工具","代码辅助与 TLS"].contains(name) { return "项目能力" }
        if ["Linux C 编译","iOS dylib 编译","iOS SDK"].contains(name) { return "可选能力" }
        return "组件与工具"
    }
}
struct MultiPlatformWorkbenchView:View {
    @ObservedObject private var model=DeviceWorkbench.shared
    @State private var report=""
    @State private var target="dylib"
    @State private var project="/var/minis/workspace"
    @State private var output="/var/minis/shared/output.dylib"
    @State private var sdk="16.5"
    @State private var remote=""
    @State private var importComputer=false
    func perform(_ args:[String:Any]) {
        Task {
            guard !model.busy else { return }; model.busy=true; defer { model.busy=false }
            do { report=try await model.buildWorkbench(args) } catch { report=error.localizedDescription }
        }
    }
    var body:some View {
        Form {
            Section(header:Text("内置 SDK 15–18")) {
                Text("已随包携带：15.6、16.5、17.5、18.6。首次安装四套 SDK 需要至少 2 GB 可用空间；核对 SHA256 后解压到 Theos。SDK 不等于完整 Xcode。").font(.caption)
                Button("安装内置四套 SDK") { perform(["action":"install-sdks"]) }.disabled(model.busy)
                Button("检测所有构建与分析组件") { perform(["action":"doctor"]) }.disabled(model.busy)
                Button("安装构建、文档与分析基础依赖") {
                    Task {
                        guard !model.busy else { return }; model.busy=true; defer { model.busy=false }
                        do { let r=try await model.run("apk add --no-cache dpkg clang lld llvm openjdk17-jre nodejs npm py3-pillow py3-openpyxl py3-reportlab py3-matplotlib",timeout:1800);report="rc=\(r.exitCode)\n\(r.output)" } catch { report=error.localizedDescription }
                    }
                }.disabled(model.busy)
            }
            Section(header:Text("实际构建")) {
                Picker("产物",selection:$target) { ForEach(["dylib","deb","ipa","apk","exe"],id:\.self) { Text($0).tag($0) } }
                TextField("源码／项目／APP 目录",text:$project).textInputAutocapitalization(.never).autocorrectionDisabled()
                TextField("产物输出路径",text:$output).textInputAutocapitalization(.never).autocorrectionDisabled()
                Picker("SDK",selection:$sdk) { ForEach(["15.6","16.5","17.5","18.6"],id:\.self) { Text($0).tag($0) } }
                TextField("可选 SSH 主机别名",text:$remote).textInputAutocapitalization(.never).autocorrectionDisabled()
                Button("构建并校验产物") { perform(["action":"build","target":target,"project":project,"output":output,"sdk":sdk,"remote":remote]) }.disabled(model.busy)
                Text("dylib 为 C/ObjC 交叉编译；DEB 需要 DEBIAN/control；IPA 打包已有 .app，Swift/Xcode 项目需 macOS 构建；APK 需 Gradle/Android SDK；EXE 需 MinGW。SSH 使用已有主机配置与密钥，远端还须具备对应工具链。缺失即报告失败。").font(.caption)
            }
            Section(header:Text("当前 Windows 电脑")) {
                Button("导入电脑 SSH 连接配置") { importComputer=true }
                Button("检测电脑连接与工具路径") {
                    Task { guard !model.busy else { return };model.busy=true;defer { model.busy=false };do { report=try await model.desktopTool(["action":"probe"]) } catch { report=error.localizedDescription } }
                }.disabled(model.busy)
                Text("使用已运行的 Windows OpenSSH，校验服务器固定主机公钥。配置里的专用私钥存入本机钥匙串；需同一局域网或已有 VPN。电脑端 REA/IDA/Frida/编译器按真实安装状态检测。").font(.caption)
            }
            Section(header:Text("分析、文档与 AI")) {
                Text("AI 可通过 workbench_build 与原有 shell/file/device_app 工具分析、修改、构建并记录退出码和 SHA256。REA、IDA、Hopper 需要真实分析引擎／商业安装；Frida CLI 不等于已连接设备。Python 文档与图表依赖按实际导入检查，AI 图像生成另需兼容的图像服务配置。").font(.caption)
            }
            if model.busy { ProgressView("处理中…") }
            if !report.isEmpty { Section(header:Text("真实输出")) { Text(report).font(.system(.caption,design:.monospaced)).textSelection(.enabled) } }
        }.navigationTitle("SDK 与多平台构建")
        .fileImporter(isPresented:$importComputer,allowedContentTypes:[.json]) { result in
            do { let url=try result.get();let access=url.startAccessingSecurityScopedResource();defer { if access { url.stopAccessingSecurityScopedResource() } };try DesktopSSHProfile.save(Data(contentsOf:url));report="电脑配置已保存到钥匙串；请检测连接" } catch { report=error.localizedDescription }
        }
        .onChange(of:target) { value in output=URL(fileURLWithPath:output).deletingPathExtension().path+"."+value }
    }
}
struct NativeDeviceFileBrowser: View {
    let path:String
    @State private var entries:[String]=[]
    @State private var error=""
    var body: some View {
        List {
            if !error.isEmpty { Text(error).foregroundColor(.red) }
            ForEach(entries,id:\.self) { item in
                let full=URL(fileURLWithPath:path).appendingPathComponent(item).path
                var isDir:ObjCBool=false
                let _=FileManager.default.fileExists(atPath:full,isDirectory:&isDir)
                if isDir.boolValue { NavigationLink(item) { NativeDeviceFileBrowser(path:full) } }
                else { NavigationLink(item) { NativeDeviceTextFile(path:full) } }
            }
        }.navigationTitle(URL(fileURLWithPath:path).lastPathComponent).onAppear {
            do { entries=try FileManager.default.contentsOfDirectory(atPath:path).sorted() } catch { self.error=error.localizedDescription }
        }
    }
}
struct NativeDeviceTextFile: View {
    let path:String
    @State private var text=""
    var body: some View { ScrollView { Text(text).font(.system(.caption,design:.monospaced)).textSelection(.enabled).padding() }.navigationTitle(URL(fileURLWithPath:path).lastPathComponent).onAppear {
        do { let h=try FileHandle(forReadingFrom:URL(fileURLWithPath:path)); defer { try? h.close() }; let data=try h.read(upToCount:262144) ?? Data(); text=String(data:data,encoding:.utf8) ?? "二进制文件，\(data.count) 字节" } catch { text=error.localizedDescription }
    } }
}
