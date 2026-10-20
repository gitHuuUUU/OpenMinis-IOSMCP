import SwiftUI
import Foundation
import UIKit
import Security
import UniformTypeIdentifiers

enum RuntimeEfficiency {
    static var fast:Bool { UserDefaults.standard.object(forKey:"runtime.fast") as? Bool ?? true }
    static var thermal:Bool { UserDefaults.standard.object(forKey:"runtime.thermal") as? Bool ?? true }
    static var underPressure:Bool {
        thermal && (ProcessInfo.processInfo.thermalState == .serious || ProcessInfo.processInfo.thermalState == .critical || ProcessInfo.processInfo.isLowPowerModeEnabled)
    }
    /// Keep the fast defaults aggressive while retaining a hard thermal/low-
    /// power brake.  The old fixed value of four made normal-temperature
    /// fan-out needlessly serial on newer devices.  This is deliberately a
    /// computed value so a temperature transition takes effect on the next
    /// batch without restarting the app.
    static var toolConcurrency:Int {
        if underPressure { return 1 }
        if thermal { return fast ? 6 : 4 }
        return fast ? 10 : 8
    }

    /// Child sessions have a separate cap because a parent session already
    /// owns a SessionConcurrencyManager slot.  Raising this only in fast mode
    /// improves fan-out latency without allowing an unbounded task storm.
    static var childConcurrency:Int {
        if underPressure { return 1 }
        if thermal { return fast ? 4 : 3 }
        return fast ? 6 : 4
    }

    /// Polling is only a fallback for child sessions that do not emit a
    /// completion notification.  Shorter intervals make the fast path feel
    /// immediate; pressure mode keeps the old interval to avoid wakeups.
    static var childPollNanoseconds: UInt64 {
        if underPressure { return 500_000_000 }
        if thermal { return fast ? 250_000_000 : 400_000_000 }
        return fast ? 150_000_000 : 250_000_000
    }

    /// Per-turn fan-out guard.  It tracks the same safety envelope as the
    /// running-child cap so queued work remains bounded on older phones.
    static var childTurnLimit:Int {
        if underPressure { return 2 }
        if thermal { return fast ? 4 : 3 }
        return fast ? 5 : 4
    }
    static var decorativeAnimations:Bool { !thermal && !underPressure }
    static var prompt:String {
        fast ? "\n\nExecution preference: minimize latency. Batch related file reads and independent checks; reuse confirmed tool paths, warm MCP sessions and existing SDKs. Use the connected Windows computer for CPU-heavy builds/analysis when appropriate; transfer only needed files. Give concise progress and results. Do not repeatedly run full diagnostics. Preserve required validation and report actual failures; do not trade correctness for speed or assume a remote connection is available." : ""
    }
}

struct RuntimeEfficiencyView:View {
    @AppStorage("runtime.fast") private var fast=true
    @AppStorage("runtime.thermal") private var thermal=true
    var body:some View {
        Form {
            Section(header:Text("执行效率")) {
                Toggle("快速工作流",isOn:$fast)
                Text("合并读取与独立检查、复用已安装组件、避免反复全量诊断；仍保留必要测试。不会自动切换模型或降低你选定的思考等级。长时间等待也可能来自模型服务或网络。").font(.caption)
            }
            Section(header:Text("温控与省电")) {
                Toggle("自适应温控（建议开启）",isOn:$thermal)
                Text("减少逐字淡入和资源采样；快速模式在正常温度最多 \(RuntimeEfficiency.toolConcurrency) 项工具、\(RuntimeEfficiency.childConcurrency) 个子代理并发，高温或低电量模式降为 1 项，新任务排队而不丢弃。流式显示适度合并，结束时完整刷新。编译/逆向优先使用已连接电脑。").font(.caption)
                Text("持续 CPU 工作、充电、第三方高刷插件和环境温度仍会影响发热；本设置不关闭前台任务或后台音频，也不保证手机完全不热。").font(.caption).foregroundColor(.secondary)
            }
        }.navigationTitle("提速与温控")
    }
}

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
    private var reverseRuntimeBusy = false
    // WDA is queried for every UI action. Keep a very short readiness cache so
    // a burst of taps/types does not add one network round-trip per action;
    // the cache is deliberately short and is invalidated when the configured
    // endpoint changes, so a crashed runner is rediscovered quickly.
    private var wdaStatusCache: (url: String, reachable: Bool, detail: String, at: Date)?
    private var wdaAutoStartAttemptAt: Date?
    private var diagnosticTask: Task<Void, Never>?
    private var componentProbeTask: Task<Void, Never>?
    private var componentProbeStarted = false
    @Published var diagnosticInterrupted = false
    @Published var diagnosticCurrentProbe = ""
    @Published var diagnosticStarted: Date?
    @Published var diagnosticDuration: TimeInterval = 0
    @Published var desktopStatus = UserDefaults.standard.string(forKey:"desktop.lastStatus") ?? "尚未从手机检测连接"
    private static let componentNames = ["Codex","Theos","CoreTools","ReverseTools","Python","Frida","REA"]
    private static let verifiedComponentsKey = "workbench.verifiedComponents"
    init() {
        UserDefaults.standard.register(defaults: [
            "workbench.wdaURL": "http://127.0.0.1:8100",
            "workbench.wdaSession": ""
        ])
        let cached = Set(UserDefaults.standard.stringArray(forKey: Self.verifiedComponentsKey) ?? [])
        for name in Self.componentNames where cached.contains(name) {
            componentStatus[name] = "上次验证已安装 · 待运行复检"
        }
    }
    private func rememberVerified(_ name: String) {
        var names = Set(UserDefaults.standard.stringArray(forKey: Self.verifiedComponentsKey) ?? [])
        names.insert(name)
        UserDefaults.standard.set(names.sorted(), forKey: Self.verifiedComponentsKey)
    }
    private func reaProof(_ output: String) -> (cached: Bool, liveReady: Bool)? {
        let json = output.components(separatedBy: "\n").first ?? ""
        guard let data = json.data(using: .utf8),
              let result = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let verification = result["verification"] as? [String: Any] else { return nil }
        let live = verification["live"] as? Bool == true
        let cached = result["status"] as? String == "last_verified" && verification["cached"] as? Bool == true && !live
        let ready = result["status"] as? String == "ready" && result["registrationReady"] as? Bool == true && live
        return (cached, ready)
    }
    func startDiagnosis(repair: Bool = false, onlyIfEmpty: Bool = false) {
        guard diagnosticTask == nil, !busy, !(onlyIfEmpty && !results.isEmpty) else { return }
        busy = true
        let priorProbe = componentProbeTask
        priorProbe?.cancel()
        // Owned by the model, not SwiftUI .task: navigating away must not cancel the guest command.
        diagnosticTask = Task.detached(priority: .userInitiated) { [weak self] in
            if let priorProbe { await priorProbe.value }
            guard let self else { return }
            await self.diagnose(repair: repair)
        }
    }
    func startComponentProbeIfNeeded() {
        guard !componentProbeStarted, componentProbeTask == nil, diagnosticTask == nil, !busy else { return }
        componentProbeStarted = true
        componentProbeTask = Task.detached(priority: .utility) { [weak self] in
            guard let self else { return }
            await self.probeComponents()
        }
    }
    private func probeComponents() async {
        defer { componentProbeTask = nil }
        let probes: [(String,String)] = [
            ("Codex","codex --version"),
            ("Theos","test -f /opt/theos/makefiles/common.mk && command -v make && command -v clang"),
            ("CoreTools","command -v bash && command -v curl && command -v git && command -v file"),
            ("ReverseTools","command -v llvm-objdump && command -v strings && command -v readelf"),
            ("Python","python3 --version && python3 -c 'import ssl,sqlite3,json'"),
            ("Frida","python3 /usr/local/lib/minis-frida/install.py status"),
            ("REA","python3 /usr/local/lib/minis-reverse-tools/rea_install.py status")
        ]
        for (name, command) in probes {
            if Task.isCancelled { componentProbeStarted = false; return }
            if busy { componentProbeStarted = false; return }
            do {
                if name == "REA" { componentStatus[name] = "状态检查中 · 缓存缺失时冷启动最多约 12 分钟" }
                let result = try await run(command, timeout: name == "REA" ? 720 : 60, sessionId: "workbench-component-status")
                if Task.isCancelled { componentProbeStarted = false; return }
                if name == "REA", result.exitCode == 0, reaProof(result.output)?.cached == true {
                    componentStatus[name] = "已安装 · 上次验证（待实时复检）"
                    rememberVerified(name)
                } else if result.exitCode == 0 && (name != "REA" || reaProof(result.output)?.liveReady == true) {
                    componentStatus[name] = "已安装 · 运行探针通过"
                    rememberVerified(name)
                } else {
                    componentStatus[name] = "未通过运行探针 · rc=\(result.exitCode)"
                }
            } catch is CancellationError {
                componentProbeStarted = false
                return
            } catch {
                componentStatus[name] = "待复检 · \(error.localizedDescription)"
                record("组件复检 \(name)：\(error.localizedDescription)")
            }
        }
    }
    func checkRuntimeComponent(_ name: String) async {
        guard !busy, name == "Frida" || name == "REA" else { return }
        busy = true
        defer { busy = false }
        if let task = componentProbeTask { task.cancel(); await task.value }
        do {
            if name == "REA" { componentStatus[name] = "冷启动实时复检中 · 最长约 12 分钟" }
            let output = try await reverseRuntime(name == "Frida" ? ["action":"status-frida"] : ["action":"status-rea","deep":true])
            if name == "REA", reaProof(output)?.liveReady != true { throw WorkbenchError.unavailable("REA 未返回实时就绪证据") }
            componentStatus[name] = "已安装 · 运行探针通过"
            rememberVerified(name)
            record(output)
        } catch is CancellationError {
            componentStatus[name] = "待复检 · 检测已取消"
        } catch {
            componentStatus[name] = "未通过运行探针"
            record(error.localizedDescription)
        }
    }
    func installFromUI(_ name: String) async {
        guard !busy else { return }
        busy = true; installError = ""; installSucceeded = false
        if let task = componentProbeTask { task.cancel(); await task.value }
        installingName = name; installStage = "准备"
        defer { busy = false }
        do {
            try await install(name)
            installStage = "完成"; installSucceeded = true
            componentStatus[name] = "已安装 · 启动检查通过"
            rememberVerified(name)
        } catch is CancellationError {
            installError = "安装已取消；请重新运行探针确认当前状态"
            componentStatus[name] = "待复检 · 安装中断"
        } catch {
            installError = error.localizedDescription
            componentStatus[name] = "安装失败 · 可重试"
            record("安装失败：\(error.localizedDescription)")
        }
    }
    let fm = FileManager.default
    var root: URL { SharedContainerStore.storageContainerURL.appendingPathComponent("Workbench", isDirectory: true) }
    var fullRead: Bool { UserDefaults.standard.bool(forKey: "workbench.fullRead") }
    var automaticApps:Bool { UserDefaults.standard.object(forKey:"workbench.autoApps") as? Bool ?? true }
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
    func accessibleApps(_ session:String)->[DeviceAppRecord] {
        if automaticApps {
            if apps.isEmpty { refreshApps() }
            return apps
        }
        return selected(session)
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
        let roots = accessibleApps(session).flatMap(\.roots) + [SharedContainerStore.storageContainerURL.path, NSHomeDirectory()]
        guard fullRead || roots.contains(where: { base in
            let normalized = URL(fileURLWithPath: base).resolvingSymlinksInPath().standardizedFileURL.path
            return url.path == normalized || url.path.hasPrefix(normalized + "/")
        }) else { throw WorkbenchError.unavailable("先在当前对话添加目标应用，或开启扩展文件访问") }
        return url
    }
    /// Probe the real WebDriverAgent endpoint. A configured URL alone is never
    /// treated as installed or ready. On a jailbroken device, automatically
    /// try the common local runner ports and wake an already-installed runner;
    /// success is still gated on a real `/status` response.
    func wdaStatus() async -> (reachable: Bool, detail: String) {
        await wdaStatus(force: false)
    }

    private func wdaStatus(force: Bool) async -> (reachable: Bool, detail: String) {
        let configured = UserDefaults.standard.string(forKey: "workbench.wdaURL") ?? "http://127.0.0.1:8100"
        if !force, let cache = wdaStatusCache,
           cache.url == configured, Date().timeIntervalSince(cache.at) < 2.0 {
            return (cache.reachable, cache.detail)
        }
        let candidates = wdaCandidateURLs(configured: configured)
        var lastDetail = "未发现可用的 WDA /status"
        for raw in candidates {
            guard let base = URL(string: raw), ["http", "https"].contains(base.scheme ?? "") else { continue }
            do {
                let object = try await wdaJSON(base, "status", nil, timeout: 1.5)
                let value = object["value"] as? [String: Any] ?? [:]
                let ready = value["ready"] as? Bool ?? false
                let message = value["message"] as? String ?? (ready ? "WDA 已就绪" : "WDA 已连接但未就绪")
                if ready {
                    if raw != configured { UserDefaults.standard.set(raw, forKey: "workbench.wdaURL") }
                    wdaStatusCache = (raw, true, message, Date())
                    return (true, message + "（(raw)）")
                }
                lastDetail = message
            } catch { lastDetail = error.localizedDescription }
        }
        // A jailbreak install may have the runner registered but suspended.
        // Wake only once per 10 seconds; never report success until the probe
        // below observes ready=true.
        if JailbreakFullAccessManager.shared.isJailbroken,
           wdaAutoStartAttemptAt.map({ Date().timeIntervalSince($0) > 10 }) ?? true {
            wdaAutoStartAttemptAt = Date()
            for bundleID in ["com.facebook.WebDriverAgentRunner.xctrunner", "com.facebook.WebDriverAgentRunner"] {
                _ = MinisDeviceBridge.openApplication(bundleID)
            }
            try? await Task.sleep(nanoseconds: 350_000_000)
            for raw in candidates {
                guard let base = URL(string: raw) else { continue }
                if let object = try? await wdaJSON(base, "status", nil, timeout: 1.5),
                   let value = object["value"] as? [String: Any], value["ready"] as? Bool == true {
                    UserDefaults.standard.set(raw, forKey: "workbench.wdaURL")
                    wdaStatusCache = (raw, true, "WDA 已就绪（越狱服务自动唤醒）", Date())
                    return (true, "WDA 已就绪（越狱服务自动唤醒）")
                }
            }
        }
        wdaStatusCache = (configured, false, lastDetail, Date())
        return (false, lastDetail + (JailbreakFullAccessManager.shared.isJailbroken ? "；已自动扫描本机 WDA 端口并尝试唤醒服务" : "；已自动扫描默认端口"))
    }

    private func wdaCandidateURLs(configured: String) -> [String] {
        var result = [configured]
        if JailbreakFullAccessManager.shared.isJailbroken {
            result += (8100...8103).map { "http://127.0.0.1:\($0)" }
            result += ["http://127.0.0.1:9001", "http://localhost:8100"]
        }
        var seen = Set<String>()
        return result.filter { seen.insert($0).inserted }
    }

    /// Generate an auditable setup artifact and instructions for a developer-
    /// signed WDA runner. A normal iOS app cannot install or launch an XCTest
    /// runner on-device by itself; this deliberately never reports a fake install.
    func prepareWDAInstall() throws -> String {
        let file = root.appendingPathComponent("wda-install.json")
        try fm.createDirectory(at: root, withIntermediateDirectories: true)
        let payload: [String: Any] = [
            "component": "WebDriverAgent",
            "status": "requires_host_sign_and_launch",
            "url": UserDefaults.standard.string(forKey: "workbench.wdaURL") ?? "http://127.0.0.1:8100",
            "requirements": ["macOS + Xcode", "paired iPhone", "Apple Developer signing or an already-running WDA backend"],
            "steps": ["Build WebDriverAgentRunner for the paired iPhone", "Sign with a development profile", "Launch the runner and expose its HTTP port", "Set this URL in Minis, then run device_app ui_status"],
            "note": "TrollStore/self-signing Minis does not grant XCTest runner installation rights. UI actions remain disabled until /status reports ready.",
            "generatedAt": ISO8601DateFormatter().string(from: Date())
        ]
        let data = try JSONSerialization.data(withJSONObject: payload, options: [.prettyPrinted, .sortedKeys])
        try data.write(to: file, options: .atomic)
        UserDefaults.standard.set("prepared", forKey: "workbench.wdaInstallState")
        return "WDA 安装准备已生成：\(file.path)\n当前仍需在配对 Mac/Xcode 或已有 WDA 主机上签名并启动 WebDriverAgentRunner；应用不会伪造已安装状态。"
    }

    func tool(_ args: [String: Any], session: String) async throws -> String {
        let action = args["action"] as? String ?? "inspect"
        let bid = args["bundle_id"] as? String ?? selected(session).first?.bundleID ?? ""
        if automaticApps, !bid.isEmpty, !apps.contains(where:{$0.bundleID==bid}) { refreshApps() }
        switch action {
        case "list":
            refreshApps()
            return String(data: try JSONEncoder().encode(apps), encoding: .utf8) ?? "[]"
        case "inspect":
            let entries = accessibleApps(session).filter { bid.isEmpty || $0.bundleID == bid }
            let report: [String: Any] = ["selected": entries.map { ["bundleID":$0.bundleID,"bundlePath":$0.bundlePath,"dataPath":$0.dataPath] },
                "fullReadRequested": fullRead, "automaticApps":automaticApps, "varReadable": fm.isReadableFile(atPath: "/var/mobile/Containers/Data/Application"),
                "wdaURL": UserDefaults.standard.string(forKey: "workbench.wdaURL") ?? "", "wdaSession": UserDefaults.standard.string(forKey: "workbench.wdaSession") ?? ""]
            return String(data: try JSONSerialization.data(withJSONObject: report, options: .prettyPrinted), encoding: .utf8) ?? "{}"
        case "open":
            guard accessibleApps(session).contains(where: { $0.bundleID == bid }) else { throw WorkbenchError.unavailable("未找到目标应用；可刷新应用列表或开启自动应用访问") }
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
        case "wda_status":
            let result = await wdaStatus(force: true)
            return try String(data: JSONSerialization.data(withJSONObject: ["reachable": result.reachable, "detail": result.detail, "url": UserDefaults.standard.string(forKey: "workbench.wdaURL") ?? ""], options: [.prettyPrinted, .sortedKeys]), encoding: .utf8) ?? "{}"
        case "prepare_wda":
            return try prepareWDAInstall()
        case "ui_status":
            if !bid.isEmpty, !accessibleApps(session).contains(where:{$0.bundleID==bid}) { throw WorkbenchError.unavailable("目标应用不在可访问列表") }
            let status = await wdaStatus()
            guard status.reachable else { throw WorkbenchError.unavailable("WDA 尚未运行：\(status.detail)。可先执行 prepare_wda 生成安装准备说明；应用启动和目录读取仍可用，UI 操作需真实 WDA。") }
            let base=try wdaBase()
            let sid=try await ensureWDASession(base:base,bundleID:bid,verifyCached:true)
            return "WDA 已建立会话：\(sid)。应用启动和目录读取使用原生桥；UI 操作将使用此会话。"
        case "get_ui", "tap", "type", "screenshot", "swipe":
            guard !bid.isEmpty, accessibleApps(session).contains(where:{$0.bundleID==bid}) else { throw WorkbenchError.unavailable("请先列出应用并指定 bundle_id，或在当前对话添加目标应用") }
            var targetArgs=args; targetArgs["bundle_id"]=bid
            return try await wda(action, args: targetArgs)
        default: throw WorkbenchError.unavailable("未知 device_app 操作：\(action)")
        }
    }
    func wdaBase() throws -> URL {
        let raw = UserDefaults.standard.string(forKey: "workbench.wdaURL") ?? "http://127.0.0.1:8100"
        guard let base = URL(string: raw), ["http","https"].contains(base.scheme ?? "") else { throw WorkbenchError.unavailable("WebDriverAgent 地址无效") }
        return base
    }
    func wdaJSON(_ base:URL,_ path:String,_ body:[String:Any]?=nil, timeout: TimeInterval = 15) async throws -> [String:Any] {
        var request=URLRequest(url:base.appendingPathComponent(path)); request.timeoutInterval=timeout
        if let body { request.httpMethod="POST"; request.setValue("application/json",forHTTPHeaderField:"Content-Type"); request.httpBody=try JSONSerialization.data(withJSONObject:body) }
        let data:Data; let response:URLResponse
        do { (data,response)=try await URLSession.shared.data(for:request) }
        catch { throw WorkbenchError.unavailable("无法连接 WDA：\(error.localizedDescription)。应用启动/目录读取仍可用；触摸和输入需要设备上实际运行的 UI 后端。") }
        guard let object=try JSONSerialization.jsonObject(with:data) as? [String:Any] else { throw WorkbenchError.unavailable("WDA 返回非 JSON") }
        let value=object["value"] as? [String:Any]
        if let error=value?["error"] as? String {
            if error == "invalid session id" { UserDefaults.standard.removeObject(forKey:"workbench.wdaSession") }
            throw WorkbenchError.unavailable("WDA \(error)：\(value?["message"] as? String ?? "")")
        }
        guard let http=response as? HTTPURLResponse,(200..<300).contains(http.statusCode) else { throw WorkbenchError.unavailable("WDA HTTP \((response as? HTTPURLResponse)?.statusCode ?? 0)") }
        return object
    }
    func ensureWDASession(base:URL,bundleID:String,verifyCached:Bool=false) async throws -> String {
        if let sid=UserDefaults.standard.string(forKey:"workbench.wdaSession"),!sid.isEmpty {
            if !verifyCached { return sid }
            if let live=try? await wdaJSON(base,"session/\(sid)"),
               let value=live["value"] as? [String:Any],value["sessionId"] as? String == sid { return sid }
            UserDefaults.standard.removeObject(forKey:"workbench.wdaSession")
        }
        if let existing=try? await wdaJSON(base,"sessions"),let sessions=existing["value"] as? [[String:Any]],
           let sid=sessions.compactMap({$0["id"] as? String ?? $0["sessionId"] as? String}).first {
            UserDefaults.standard.set(sid,forKey:"workbench.wdaSession"); return sid
        }
        var capabilities:[String:Any]=[:]
        if !bundleID.isEmpty { capabilities["bundleId"]=bundleID }
        let object=try await wdaJSON(base,"session",["capabilities":["alwaysMatch":capabilities]])
        let value=object["value"] as? [String:Any]
        guard let sid=object["sessionId"] as? String ?? value?["sessionId"] as? String,!sid.isEmpty else { throw WorkbenchError.unavailable("WDA 未返回实际会话 ID") }
        UserDefaults.standard.set(sid,forKey:"workbench.wdaSession"); return sid
    }
    func wda(_ action: String, args: [String: Any]) async throws -> String {
        let status = await wdaStatus()
        guard status.reachable else { throw WorkbenchError.unavailable("WDA 未就绪：\(status.detail)。先执行 prepare_wda 或启动已签名的 WebDriverAgentRunner。") }
        let base=try wdaBase()
        let sid=try await ensureWDASession(base:base,bundleID:args["bundle_id"] as? String ?? "")
        if let bid=args["bundle_id"] as? String,!bid.isEmpty {
            _ = try await wdaJSON(base,"session/\(sid)/wda/apps/activate",["bundleId":bid])
        }
        let suffix: String
        var body: [String: Any]?
        switch action {
        case "tap": suffix = "wda/tap"; guard let x=args["x"] as? NSNumber, let y=args["y"] as? NSNumber else { throw WorkbenchError.unavailable("缺少 x/y") }; body=["x":x,"y":y]
        case "type": suffix="wda/keys"; body=["value":Array((args["text"] as? String ?? "").map { String($0) })]
        case "swipe":
            guard let x=args["x"] as? NSNumber,let y=args["y"] as? NSNumber,let endX=args["end_x"] as? NSNumber,let endY=args["end_y"] as? NSNumber else { throw WorkbenchError.unavailable("滑动需要 x/y/end_x/end_y") }
            suffix="wda/dragfromtoforduration"; body=["fromX":x,"fromY":y,"toX":endX,"toY":endY,"duration":0.4]
        case "screenshot": suffix="screenshot"
        default: suffix="source"
        }
        var request=URLRequest(url: base.appendingPathComponent("session").appendingPathComponent(sid).appendingPathComponent(suffix))
        request.timeoutInterval=20
        if let body { request.httpMethod="POST"; request.setValue("application/json", forHTTPHeaderField:"Content-Type"); request.httpBody=try JSONSerialization.data(withJSONObject:body) }
        var (data,response)=try await URLSession.shared.data(for: request)
        if action == "tap",(response as? HTTPURLResponse)?.statusCode == 404 {
            request.url=base.appendingPathComponent("session/\(sid)/wda/tap/0")
            (data,response)=try await URLSession.shared.data(for:request)
        }
        guard let http=response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else { throw WorkbenchError.unavailable("WDA 请求失败：\((response as? HTTPURLResponse)?.statusCode ?? 0)") }
        if let object = try? JSONSerialization.jsonObject(with: data) as? [String:Any],
           let value = object["value"] as? [String:Any], let error = value["error"] as? String {
            if error == "invalid session id" { UserDefaults.standard.removeObject(forKey:"workbench.wdaSession") }
            throw WorkbenchError.unavailable("WDA：\(error) \(value["message"] as? String ?? "")")
        }
        if action == "screenshot", let object=try JSONSerialization.jsonObject(with:data) as? [String:Any], let text=object["value"] as? String, let image=Data(base64Encoded:text) {
            try fm.createDirectory(at: root, withIntermediateDirectories:true)
            let file=root.appendingPathComponent("screen-\(UUID().uuidString).png"); try image.write(to:file)
            return "截图已保存：\(file.path)；可用 device_app read_file 读取。"
        }
        return String(data:data,encoding:.utf8) ?? "WDA 返回非文本响应"
    }
    func run(_ command: String, timeout: TimeInterval = 900, sessionId: String = "workbench") async throws -> ISHCommandResult {
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
        return try await ISHExecutionCoordinator.shared.execute(sessionId:sessionId, command:command, timeout:timeout, lineCallback:{ [weak self] line in
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
    private func diagnose(repair: Bool = false) async {
        defer { busy = false; diagnosticTask = nil }
        results=[]
        diagnosticInterrupted = false
        diagnosticCurrentProbe = ""
        diagnosticStarted=Date()
        defer { diagnosticDuration=Date().timeIntervalSince(diagnosticStarted ?? Date()); diagnosticCurrentProbe = "" }
        if repair {
            do { for (component, probe) in [("CoreTools","command -v curl && command -v git && command -v file"), ("Python","command -v python3"), ("ReverseTools","command -v llvm-objdump && command -v readelf"), ("Codex","codex --version"), ("Theos","test -f /opt/theos/makefiles/common.mk")] {
                    try Task.checkCancellation()
                    let result = try await run(probe, timeout: 30, sessionId: "workbench-diagnostics")
                    if result.exitCode != 0 { do { try await install(component) } catch is CancellationError { throw CancellationError() } catch { record("\(component)：\(error.localizedDescription)") } }
                }
                importAgents() }
            catch is CancellationError { diagnosticInterrupted = true; record("修复诊断已取消"); return }
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
            ("Frida Python 与 CLI", "python3 /usr/local/lib/minis-frida/install.py status"),
            ("REA CLI 与 MCP", "python3 /usr/local/lib/minis-reverse-tools/rea_install.py status"),
            ("Theos", "test -f /opt/theos/makefiles/common.mk && command -v make && command -v clang"),
            ("Linux C 编译", "p=/tmp/minis-cc-$$; printf 'int main(){return 0;}' > \"$p.c\"; clang \"$p.c\" -o \"$p\" && \"$p\"; r=$?; rm -f \"$p.c\" \"$p\"; exit $r"),
            ("iOS dylib 编译", "s=; for v in 16.5 15.6 17.5 18.6; do p=/opt/theos/sdks/iPhoneOS$v.sdk; if test -f \"$p/usr/lib/libSystem.tbd\"; then s=$p; break; fi; done; test -n \"$s\" || exit 1; p=/tmp/minis-ios-$$; printf 'int minis_probe(void){return 1;}' > \"$p.c\"; clang --target=arm64-apple-ios15.4 -isysroot \"$s\" -fuse-ld=lld -dynamiclib \"$p.c\" -o \"$p.dylib\" && file \"$p.dylib\"; r=$?; rm -f \"$p.c\" \"$p.dylib\"; exit $r"),
            ("iOS SDK", "found=0; for v in 15.6 16.5 17.5 18.6; do s=/opt/theos/sdks/iPhoneOS$v.sdk; if test -f \"$s/System/Library/Frameworks/Foundation.framework/Headers/Foundation.h\" && test -f \"$s/usr/lib/libSystem.tbd\"; then echo \"SDK $v headers + link stubs OK\"; found=1; fi; done; test $found -eq 1")]
        for (name,command) in checks {
            if Task.isCancelled { diagnosticInterrupted = true; record("诊断已取消，后续探针未运行"); break }
            do {
                diagnosticCurrentProbe = name == "REA CLI 与 MCP" ? "REA 状态检查中（缓存缺失时冷启动最多约 12 分钟）" : name
                let result=try await run(command,timeout:name == "REA CLI 与 MCP" ? 720 : 60,sessionId:"workbench-diagnostics")
                if result.exitCode == -1 && result.output.contains("Command cancelled") { diagnosticInterrupted = true; record("诊断命令被取消，后续探针未运行"); break }
                let proof = name == "REA CLI 与 MCP" ? reaProof(result.output) : nil
                let pending = result.exitCode == 0 && proof?.cached == true
                let passed = result.exitCode == 0 && !pending && (name != "REA CLI 与 MCP" || proof?.liveReady == true)
                let detail = pending ? "已安装，上次验证通过；本次仅读取缓存，待点击组件内的实时复检。\n" + result.output : result.output
                results.append(WorkbenchCheck(name:name,ok:passed,detail:detail,pending:pending))
                if let component = ["Frida Python 与 CLI":"Frida","REA CLI 与 MCP":"REA"][name] ?? (Self.componentNames.contains(name) ? name : nil) {
                    componentStatus[component] = pending ? "已安装 · 上次验证（待实时复检）" : (passed ? "已安装 · 运行探针通过" : "未通过运行探针 · rc=\(result.exitCode)")
                    if passed || pending { rememberVerified(component) }
                }
                record("\(name) rc=\(result.exitCode)\n\(result.output)")
            } catch is CancellationError {
                diagnosticInterrupted = true; record("诊断已取消，后续探针未运行"); break
            } catch {
                results.append(WorkbenchCheck(name:name,ok:false,detail:error.localizedDescription)); record("\(name)：\(error.localizedDescription)")
            }
        }
        if !diagnosticInterrupted { results.append(WorkbenchCheck(name:"本机文件权限",ok:fm.isReadableFile(atPath:"/var/mobile/Containers/Data/Application"),detail:"按实际目录读取权限检测；iSH 内 root 不等于 iOS root")) }
    }
    func install(_ name: String) async throws {
        if name == "Frida" || name == "REA" {
            _ = try await reverseRuntime(["action": name == "Frida" ? "install-frida" : "install-rea"])
            return
        }
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
        let result=try await run("set -e; " + command,timeout:1800,sessionId:"workbench-install"); record("安装 \(name) rc=\(result.exitCode)\n\(result.output)")
        guard result.exitCode==0 else { throw WorkbenchError.unavailable("\(name) 安装或启动验证失败：\(result.output.suffix(1000))") }
    }
    func reverseRuntime(_ args: [String:Any]) async throws -> String {
        guard !reverseRuntimeBusy else { throw WorkbenchError.unavailable("另一个逆向工具安装/诊断任务正在执行") }
        reverseRuntimeBusy = true
        defer { reverseRuntimeBusy = false }
        let action = args["action"] as? String ?? "status-frida"
        guard ["install-frida","status-frida","install-rea","status-rea"].contains(action) else {
            throw WorkbenchError.unavailable("动作需要 install-frida、status-frida、install-rea 或 status-rea")
        }
        let installing = action.hasPrefix("install-")
        if installing {
            installStage = "准备 Python 依赖"
            let setup = try await run("set -e; if ! command -v python3 >/dev/null || ! python3 -m pip --version >/dev/null 2>&1; then apk add --no-cache python3 py3-pip; fi; test -f /usr/lib/libgcc_s.so.1 || apk add --no-cache libgcc",timeout:300,sessionId:"workbench-reverse")
            guard setup.exitCode == 0 else { throw WorkbenchError.unavailable(setup.output) }
        }
        if action == "install-rea" {
            installStage = "准备 Node.js 与 npm"
            let setup = try await run("apk add --no-cache --upgrade nodejs npm",timeout:600,sessionId:"workbench-reverse")
            guard setup.exitCode == 0 else { throw WorkbenchError.unavailable(setup.output) }
        }
        let command: String
        if action == "install-frida" {
            guard let bundle = Bundle.main.url(forResource:"BuildWorkbench",withExtension:"bundle") else { throw WorkbenchError.unavailable("缺少内置 Frida wheel 资源") }
            let setup=try await run("mkdir -p /opt/minis-workbench",timeout:60,sessionId:"workbench-reverse")
            guard setup.exitCode == 0, ISHKernel.shared.bindMountPath("/opt/minis-workbench",toHostPath:bundle.path,readOnly:true) == 0 else { throw WorkbenchError.unavailable("无法挂载内置 Frida 资源") }
            command = "python3 /usr/local/lib/minis-frida/install.py install --bundle /opt/minis-workbench/frida"
        } else if action == "status-frida" {
            command = "python3 /usr/local/lib/minis-frida/install.py status"
        } else {
            command = "python3 /usr/local/lib/minis-reverse-tools/rea_install.py " + (installing ? "install" : "status") + ((!installing && (args["deep"] as? Bool == true)) ? " --deep" : "")
        }
        let result = try await run(command,timeout:installing ? 1800 : (action == "status-rea" ? 720 : 240),sessionId:"workbench-reverse")
        record("逆向工具 \(action) rc=\(result.exitCode)\n\(result.output)")
        guard result.exitCode == 0 else { throw WorkbenchError.unavailable("工具尚未就绪 rc=\(result.exitCode)\n\(result.output.suffix(3000))") }
        if action == "install-rea" {
            guard MCPStore.shared.registerInstalledREA(verifiedInstallResult: Data(result.output.trimmingCharacters(in: .whitespacesAndNewlines).utf8)) else {
                return result.output + "\nREA 已安装，但未覆盖现有自定义或禁用的 MCP 配置；请在 MCP 设置中核对。"
            }
        }
        return result.output + "\n注意：Linux guest Frida 客户端不等于原生 iOS 进程附加权限；REA MCP 握手不等于全部分析引擎就绪。"
    }
    func buildWorkbench(_ args:[String:Any]) async throws -> String {
        let action=args["action"] as? String ?? "doctor"
        if action=="build", args["remote"] as? String == "windows" {
            guard let output=args["output"] as? String else { throw WorkbenchError.unavailable("缺少电脑输出路径") }
            let payload=try JSONSerialization.data(withJSONObject:args).base64EncodedString()
            let script="$a=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('"+payload+"')) | ConvertFrom-Json; & (Join-Path $env:USERPROFILE '.minis/minis-build.ps1') -Target $a.target -Project $a.project -Output $a.output -Sdk $a.sdk"
            let built=try await desktopTool(["action":"run","command":script])
            let name=URL(fileURLWithPath:output.replacingOccurrences(of:"\\",with:"/")).lastPathComponent
            let local="/var/minis/shared/"+name
            _ = try await desktopTool(["action":"download","path":local,"remotePath":output])
            return built+"\n已下载到手机共享产物目录："+local
        }
        guard ["doctor","sdk-status","install-sdk","build"].contains(action),
              let bundle=Bundle.main.url(forResource:"BuildWorkbench",withExtension:"bundle") else {
            throw WorkbenchError.unavailable("构建工作台资源或动作不可用")
        }
        let setup=try await run("mkdir -p /opt/minis-workbench",timeout:120)
        guard setup.exitCode==0 else { throw WorkbenchError.unavailable(setup.output) }
        guard ISHKernel.shared.bindMountPath("/opt/minis-workbench",toHostPath:bundle.path,readOnly:true)==0 else {
            throw WorkbenchError.unavailable("无法只读挂载 SDK 目录与构建脚本")
        }
        func quote(_ value:String)->String { "'"+value.replacingOccurrences(of:"'",with:"'\"'\"'")+"'" }
        var command="python3 /opt/minis-workbench/minis_build.py "+action
        if action=="install-sdk" {
            guard let value=args["sdk"] as? String, !value.isEmpty else { throw WorkbenchError.unavailable("缺少 SDK 版本") }
            command += " --sdk "+quote(value)
        } else if action=="build" {
            for key in ["target","project","output"] {
                guard let value=args[key] as? String, !value.isEmpty else { throw WorkbenchError.unavailable("缺少构建参数：\(key)") }
                command += " --\(key) "+quote(value)
            }
            for key in ["sdk","minimum","remote"] {
                if let value=args[key] as? String, !value.isEmpty { command += " --\(key) "+quote(value) }
            }
        }
        let result=try await run(command,timeout:action=="install-sdk" ? 3600 : 1800)
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
        if (try? Data(contentsOf:keyFile)) != Data(key.utf8) {
            try Data(key.utf8).write(to:keyFile,options:[.atomic,.completeFileProtectionUnlessOpen])
        }
        try fm.setAttributes([.posixPermissions:0o600],ofItemAtPath:keyFile.path)
        let known=(port==22 ? host : "[\(host)]:\(port)")+" "+hostKey+"\n"
        try Data(known.utf8).write(to:folder.appendingPathComponent("known_hosts"),options:.atomic)
        let setup=try await run("mkdir -p /opt/minis-desktop",timeout:120)
        guard setup.exitCode==0, ISHKernel.shared.bindMountPath("/opt/minis-desktop",toHostPath:folder.path,readOnly:true)==0 else { throw WorkbenchError.unavailable("无法挂载电脑连接密钥") }
        let prepared=try await run("sh /usr/local/lib/minis-desktop-ssh/prepare.sh /opt/minis-desktop /tmp/minis-desktop-ssh",timeout:30)
        guard prepared.exitCode==0 else { throw WorkbenchError.unavailable("SSH 私钥权限准备失败：\(prepared.output)") }
        func q(_ value:String)->String { "'"+value.replacingOccurrences(of:"'",with:"'\"'\"'")+"'" }
        // iSH fakefs cannot reliably host AF_UNIX sockets: do not enable ControlMaster.
        let options=" -i /tmp/minis-desktop-ssh/identity -o BatchMode=yes -o StrictHostKeyChecking=yes -o UserKnownHostsFile=/tmp/minis-desktop-ssh/known_hosts -o ConnectTimeout=10 -o ServerAliveInterval=15 -o ServerAliveCountMax=2 "
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
            command="ssh -p \(port)"+options+q(user+"@"+host)+" powershell.exe -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -EncodedCommand "+encoded
        }
        let started=Date()
        let result=try await run(command,timeout:1800)
        let elapsed=Date().timeIntervalSince(started)
        desktopStatus="\(Date().formatted(date:.numeric,time:.standard)) · \(host):\(port) · \(String(format:"%.2f",elapsed)) 秒 · "+(result.exitCode==0 ? "SSH 操作成功" : "失败 rc=\(result.exitCode)")
        UserDefaults.standard.set(desktopStatus,forKey:"desktop.lastStatus")
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
struct WorkbenchCheck: Identifiable {
    let id=UUID(); let name:String; let ok:Bool; let detail:String; let pending:Bool
    init(name:String,ok:Bool,detail:String,pending:Bool=false) { self.name=name; self.ok=ok; self.detail=detail; self.pending=pending }
}

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
    @AppStorage("workbench.autoApps") private var autoApps=true
    @AppStorage("workbench.wdaURL") private var wdaURL="http://127.0.0.1:8100"
    @AppStorage("workbench.wdaSession") private var wdaSession=""
    @State private var showLogs=false
    @State private var status=""
    var body: some View {
        List {
            Section(header:Text("开发环境与诊断")) {
                NavigationLink("SDK 与多平台构建工作台") { MultiPlatformWorkbenchView() }
                NavigationLink("内置终端") { ISHTerminalView(showCloseButton: true) }
                NavigationLink("Tools · 基础与逆向工具") { List { Text("CoreTools：文件、网络与项目工具"); Text("ReverseTools：LLVM / binutils / GDB"); Text("Python：解释器及 pip"); Text("Frida：内置 ARM64/musl Python 模块与 CLI，实际启动验证"); Text("REA：固定版本 CLI、官方技能及 MCP；引擎另行检测") }.navigationTitle("Tools") }
                ForEach(["Codex","Theos","CoreTools","ReverseTools","Python","Frida","REA"],id:\.self) { name in
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
                Toggle("允许 AI 自动选择并打开已安装应用",isOn:$autoApps)
                Text("开启后无需逐个从 + 添加应用；AI 可列出应用、按 bundle ID 启动，并在系统实际允许时读取其安装/数据目录。关闭后恢复仅当前对话所选应用范围。").font(.caption)
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
                Button("检测并自动建立 UI 会话") { Task { do { status=try await model.tool(["action":"ui_status"],session:"workbench") } catch { status=error.localizedDescription } } }
                Button("检查 WDA 真实运行状态") { Task { do { status=try await model.tool(["action":"wda_status"],session:"workbench") } catch { status=error.localizedDescription } } }
                Button("准备 WDA 安装与签名说明") { do { status=try model.prepareWDAInstall() } catch { status=error.localizedDescription } }
                Text("应用可自动检测并调用真实 WDA；无法在普通 iOS 应用内部直接安装 XCTest runner。免越狱使用需配对 Mac + Xcode + 开发签名（或已有 WDA 主机），启动后填入 URL；未返回 ready 前不会报告 UI 控制就绪。").font(.caption).foregroundColor(.secondary)
            }
            if !status.isEmpty { Section { Text(status).font(.caption) } }
            Section(header:Text("实际检测结果：\(model.results.filter(\.ok).count)/\(model.results.count) 通过")) {
                ForEach(model.results) { row in HStack(alignment:.top) { Image(systemName:row.pending ? "clock" : (row.ok ? "checkmark.circle.fill" : "exclamationmark.circle")).foregroundColor(row.ok ? .green : .orange); VStack(alignment:.leading) { Text(row.name); Text(row.detail.isEmpty ? (row.pending ? "待实时复检" : (row.ok ? "探针成功" : "探针失败")) : String(row.detail.suffix(1500))).font(.caption).foregroundColor(.secondary) } } }
            }
        }.navigationTitle("开发环境与诊断")
        .onAppear { model.startComponentProbeIfNeeded() }
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
                if name == "Frida" || name == "REA" {
                    Text("Frida 安装真实 Linux ARM64/musl 模块及 CLI，不代理到电脑；访问原生 iOS 目标仍需实际 Frida Server/Gadget 和权限。REA 会独立报告 MCP 握手与分析引擎状态。").font(.caption).foregroundColor(.secondary)
                    Button("检测实际运行状态") { Task { await model.checkRuntimeComponent(name) } }.disabled(model.busy)
                }
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
                Label(model.busy ? "正在检查核心能力" : (model.diagnosticInterrupted ? "检查已中断" : (model.results.isEmpty ? "等待检查" : "检查完成")),systemImage:model.busy ? "clock" : "stethoscope")
                Text("\(model.results.filter(\.ok).count)/\(model.results.count) 项通过 · \(Int(model.diagnosticDuration)) 秒").font(.caption)
                if model.busy && !model.diagnosticCurrentProbe.isEmpty { Text(model.diagnosticCurrentProbe).font(.caption).foregroundColor(.secondary) }
                if model.diagnosticInterrupted { Text("仅显示已运行探针；取消后的项目未计为失败。").font(.caption).foregroundColor(.secondary) }
                Button("运行诊断") { model.startDiagnosis() }.disabled(model.busy)
                Button("自动修复并重新检查") { model.startDiagnosis(repair:true) }.disabled(model.busy)
            }
            ForEach(["基础运行","项目能力","可选能力","组件与工具"],id:\.self) { group in
                Section(header:Text(group)) {
                    ForEach(model.results.filter { row in diagnosticGroup(row.name) == group }) { row in
                        HStack(alignment:.top) {
                            Image(systemName:row.pending ? "clock" : (row.ok ? "checkmark.circle" : "exclamationmark.circle")).foregroundColor(row.ok ? .green : .orange)
                            VStack(alignment:.leading) { Text(row.name); Text(String(row.detail.suffix(1500))).font(.caption).foregroundColor(.secondary).textSelection(.enabled) }
                        }
                    }
                }
            }
        }.navigationTitle("运行诊断")
        .toolbar { ToolbarItem(placement:.navigationBarTrailing) { Button("复制") { UIPasteboard.general.string=model.results.map { "\($0.pending ? "PENDING" : ($0.ok ? "PASS" : "FAIL")) \($0.name)\n\($0.detail)" }.joined(separator:"\n") } } }
        .onAppear { model.startDiagnosis(onlyIfEmpty:true) }
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
    @AppStorage("workbench.selectedSDK") private var sdk="16.5"
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
            Section { NavigationLink("提速与温控",destination:RuntimeEfficiencyView()) }
            Section(header:Text("按需下载 iOS SDK 15–18")) {
                Text("选择一套 SDK 单独下载并安装到 Theos；下载后核对字节数和 SHA256。已有 SDK 不覆盖，四套归档均不随 IPA 携带；单次安装需要至少 2 GB 可用空间。SDK 不等于完整 Xcode。").font(.caption)
                Picker("SDK 版本",selection:$sdk) { ForEach(["15.6","16.5","17.5","18.6"],id:\.self) { Text($0).tag($0) } }
                Button("下载并安装所选 SDK") { perform(["action":"install-sdk","sdk":sdk]) }.disabled(model.busy)
                Button("查看 SDK 安装状态") { perform(["action":"sdk-status"]) }.disabled(model.busy)
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
                Picker("执行位置",selection:$remote) { Text("手机本地").tag("");Text("当前 Windows 电脑").tag("windows") }
                TextField("可选 Mac/Linux SSH 主机别名",text:$remote).textInputAutocapitalization(.never).autocorrectionDisabled()
                Button("构建并校验产物") { perform(["action":"build","target":target,"project":project,"output":output,"sdk":sdk,"remote":remote]) }.disabled(model.busy)
                Text("dylib 为 C/ObjC 交叉编译；DEB 需要 DEBIAN/control；IPA 打包已有 .app，Swift/Xcode 项目需 macOS 构建；APK 需 Gradle/Android SDK；EXE 需 MinGW。SSH 使用已有主机配置与密钥，远端还须具备对应工具链。缺失即报告失败。").font(.caption)
            }
            Section(header:Text("当前 Windows 电脑")) {
                Text(model.desktopStatus).font(.caption).textSelection(.enabled)
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
