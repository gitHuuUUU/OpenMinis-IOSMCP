import SwiftUI

enum MinisReComposerVisibility {
    // Keep context accounting and detail pages; remove the inline figures.
    static let showsContextText = false
}

enum MinisRePalette {
    static let background = Color(UIColor.systemGroupedBackground)
    static let card = Color(UIColor.secondarySystemGroupedBackground)
    static let border = Color.primary.opacity(0.08)
}

struct MinisReCard<Content: View>: View {
    let content: Content
    init(@ViewBuilder content: () -> Content) { self.content = content() }
    var body: some View {
        VStack(alignment: .leading, spacing: 10) { content }
            .padding(12).frame(maxWidth: .infinity, alignment: .leading)
            .background(RoundedRectangle(cornerRadius: 14, style: .continuous).fill(MinisRePalette.card))
            .overlay(RoundedRectangle(cornerRadius: 14, style: .continuous).stroke(MinisRePalette.border))
    }
}

struct MinisReFeatureRow: View {
    let title: String
    let subtitle: String
    let icon: String
    var color: Color = .blue
    var body: some View {
        HStack(spacing: 10) {
            Image(systemName: icon).font(.system(size: 12, weight: .medium))
                .foregroundStyle(.white).frame(width: 24, height: 24)
                .background(RoundedRectangle(cornerRadius: 7).fill(color))
            VStack(alignment: .leading, spacing: 3) {
                Text(title).font(.subheadline).foregroundStyle(.primary)
                if !subtitle.isEmpty { Text(subtitle).font(.caption2).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true) }
            }
            Spacer(minLength: 4)
        }.frame(minHeight: 44).frame(maxWidth: .infinity, alignment: .leading)
            .contentShape(Rectangle())
    }
}

struct MinisReAccountsView: View {
    @ObservedObject private var providers = ProviderConfigStore.shared
    @AppStorage("minisre.currency") private var currency = "USD"
    @State private var showCurrency = false
    private var chatGPT: ProviderInstance? {
        providers.instances.first { ($0.providerType == .openAI || $0.providerType == .openAIResponses) && $0.credentialType == .oauth }
    }
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                MinisReCard {
                    if let account = chatGPT {
                        NavigationLink { ProviderInstanceDetailView(instanceId: account.id) } label: {
                            MinisReFeatureRow(title: "ChatGPT", subtitle: "\(account.label) · 点击检查登录状态", icon: "bubble.left.and.bubble.right.fill")
                        }
                    } else {
                        NavigationLink { AddProviderView() } label: {
                            MinisReFeatureRow(title: "ChatGPT", subtitle: "添加账号 · 选择 OpenAI OAuth 登录", icon: "bubble.left.and.bubble.right.fill")
                        }
                    }
                    Divider()
                    NavigationLink { ProviderInstancesView() } label: {
                        MinisReFeatureRow(title: "第三方服务商", subtitle: "\(providers.instances.count) 个已配置 · 管理登录与密钥", icon: "globe", color: .purple)
                    }
                }
                Text("管理").font(.caption).foregroundStyle(.secondary).padding(.leading, 6)
                MinisReCard {
                    Button { showCurrency = true } label: {
                        MinisReFeatureRow(title: "计费币种", subtitle: currency == "CNY" ? "人民币 (CNY)" : "美元 (USD)", icon: "dollarsign.circle.fill")
                    }
                    Divider()
                    NavigationLink { MinisReUsageView() } label: {
                        MinisReFeatureRow(title: "用量与费用", subtitle: "本机记录与参考价格估算", icon: "chart.bar.fill", color: .green)
                    }
                    Divider()
                    NavigationLink { MinisRePricesView() } label: {
                        MinisReFeatureRow(title: "模型价格", subtitle: "models.dev 参考目录 · 支持搜索刷新", icon: "tag.fill", color: .orange)
                    }
                }
            }.padding(16)
        }.background(MinisRePalette.background.ignoresSafeArea())
            .navigationTitle("AI 账号").navigationBarTitleDisplayMode(.inline)
            .confirmationDialog("计费币种（只影响估算显示）", isPresented: $showCurrency, titleVisibility: .visible) {
                Button("人民币 (CNY)" + (currency == "CNY" ? " ✓" : "")) { currency = "CNY" }
                Button("美元 (USD)" + (currency == "USD" ? " ✓" : "")) { currency = "USD" }
                Button("取消", role: .cancel) {}
            }
    }
}

struct MinisRePricesView: View {
    @State private var query = ""
    @State private var rows: [ModelsDevAPI.PriceRow] = []
    @State private var refreshing = false
    @State private var loaded = false
    @State private var refreshMessage = ""
    private var groups: [(String, [ModelsDevAPI.PriceRow])] {
        let matches = rows.filter { query.isEmpty || ($0.providerName + $0.model + $0.name).localizedCaseInsensitiveContains(query) }
        return Dictionary(grouping: matches, by: \.providerName).sorted { $0.key < $1.key }.map { ($0.key, $0.value) }
    }
    var body: some View {
        List {
            Section {
                Text("USD / 百万 token；来自 models.dev 缓存或内置目录，不代表第三方转发、订阅或优惠后的实际收费。未提供价格不按免费处理。").font(.caption).foregroundStyle(.secondary)
                if refreshing { ProgressView("同步目录…") }
                if !refreshMessage.isEmpty { Text(refreshMessage).font(.caption).foregroundStyle(.secondary) }
                if loaded && rows.isEmpty { Text("目录暂无数据") }
            }
            ForEach(groups, id: \.0) { group in
                Section(group.0) {
                    ForEach(group.1) { row in
                        VStack(alignment: .leading, spacing: 5) {
                            Label(row.name, systemImage: "cpu").font(.subheadline.weight(.semibold))
                            Text(row.model).font(.caption).foregroundStyle(.secondary).textSelection(.enabled)
                            Text("输入 \(price(row.input)) · 输出 \(price(row.output)) / 1M").font(.caption)
                            if let context = row.context { Text("上下文 \(context.formatted()) token").font(.caption).foregroundStyle(.secondary) }
                        }.padding(.vertical, 5)
                    }
                }
            }
        }.searchable(text: $query, prompt: "搜索模型或服务商")
            .navigationTitle("模型价格").navigationBarTitleDisplayMode(.inline)
            .task { if !loaded { rows = await Task.detached(priority: .utility) { ModelsDevAPI.priceCatalog() }.value; loaded = true } }
            .toolbar { ToolbarItem(placement: .navigationBarTrailing) {
                Button { Task { refreshing = true; let success = await ModelsDevAPI.refreshPriceCatalog(); rows = await Task.detached(priority: .utility) { ModelsDevAPI.priceCatalog() }.value; refreshMessage = success ? "已从 models.dev 同步" : "同步失败，保留缓存/内置参考目录"; refreshing = false } } label: { Image(systemName: "arrow.clockwise") }
                    .disabled(refreshing).accessibilityLabel("刷新模型价格")
            } }
    }
    private func price(_ rate: Double?) -> String { rate.map { String(format: "$%.4g", $0) } ?? "暂无" }
}

struct MinisReUsageView: View {
    @AppStorage("minisre.currency") private var currency = "USD"
    @AppStorage("minisre.usdToCNY") private var exchange = 0.0
    @State private var todayTokens = 0
    @State private var totalTokens = 0
    @State private var todayCost: Double?
    @State private var totalCost: Double?
    @State private var covered = 0
    @State private var count = 0
    @State private var loaded = false
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 12) {
                Text("本机用量估算").foregroundStyle(.secondary)
                MinisReCard {
                    Label("Token 用量统计", systemImage: "chart.bar.fill").font(.subheadline.weight(.semibold))
                    HStack { metric("今日 Token", value: todayTokens.formatted()); metric("累计 Token", value: totalTokens.formatted()) }
                }
                MinisReCard {
                    Label("API 参考费用", systemImage: "dollarsign.circle").font(.subheadline.weight(.semibold))
                    HStack { metric("今日已匹配部分", value: display(todayCost)); metric("累计已匹配部分", value: display(totalCost)) }
                    Text("匹配 \(covered)/\(count) 条记录。只使用精确模型 ID 与服务商类别；未知模型、缓存单价和旧记录不冒充免费。代理商收费、订阅额度和实际账单请以服务商为准。").font(.caption).foregroundStyle(.secondary)
                    if currency == "CNY" {
                        HStack { Text("USD/CNY 参考汇率"); TextField("手动设置", value: $exchange, format: .number).keyboardType(.decimalPad).multilineTextAlignment(.trailing) }
                        Text("手动汇率，仅用于显示估算；未设置则不换算。").font(.caption).foregroundStyle(.secondary)
                    }
                }
                NavigationLink { UsageStatsView() } label: {
                    MinisReFeatureRow(title: "详细 Token 与子代理统计", subtitle: "保留原有分模型、缓存及归属明细", icon: "list.bullet.rectangle")
                }
                if !loaded { ProgressView("读取本机记录…") }
            }.padding(16)
        }.background(MinisRePalette.background.ignoresSafeArea()).navigationTitle("用量与费用").navigationBarTitleDisplayMode(.inline)
            .task { await load() }
    }
    private func display(_ usd: Double?) -> String { UsageCostPolicy.display(usd, currency: currency, usdToCNY: exchange) }
    private func metric(_ title: String, value: String) -> some View {
        VStack(alignment: .leading, spacing: 5) { Text(title).font(.caption2).foregroundStyle(.secondary); Text(value).font(.headline).minimumScaleFactor(0.7).lineLimit(1) }.frame(maxWidth: .infinity, alignment: .leading)
    }
    private func load() async {
        let records = await ChatStore.shared.fetchUsageStats()
        let result = await Task.detached(priority: .utility) {
            let catalog = Dictionary(ModelsDevAPI.priceCatalog().map { ($0.id, $0) }, uniquingKeysWith: { a, _ in a })
            let providers = ["openAI": "openai", "openAIResponses": "openai", "anthropic": "anthropic", "gemini": "google", "openRouter": "openrouter", "xAI": "xai"]
            var today = 0, total = 0, matched = 0, matchedToday = 0
            var cost = 0.0, daily = 0.0
            for record in records {
                let u = record.usage
                let tokens = u.inputTokens + u.outputTokens + u.cacheReadTokens + u.cacheCreationTokens
                let isToday = Calendar.current.isDateInToday(record.date)
                total += tokens
                if isToday { today += tokens }
                guard record.hasSnapshot, let vendor = providers[record.providerType ?? ""],
                      let price = catalog[vendor + "/" + record.modelId],
                      let amount = UsageCostPolicy.estimate(input: u.inputTokens, output: u.outputTokens, read: u.cacheReadTokens, write: u.cacheCreationTokens, inputRate: price.input, outputRate: price.output, readRate: price.cacheRead, writeRate: price.cacheWrite) else { continue }
                matched += 1; cost += amount
                if isToday { matchedToday += 1; daily += amount }
            }
            return (today, total, matched, matchedToday, cost, daily)
        }.value
        todayTokens = result.0; totalTokens = result.1; covered = result.2
        totalCost = result.2 > 0 ? result.4 : nil; todayCost = result.3 > 0 ? result.5 : nil
        count = records.count; loaded = true
    }
}

// Pure selection/report policy is shared by the settings view and host regression tests.
enum CompilationProtectionPolicy {
    static let order = ["bcf", "indcall", "indgv", "sobf", "fla"]

    static func normalized(_ raw: String, selection: String) -> String {
        let selected = Set(raw.split(separator: ",").map { $0.trimmingCharacters(in: .whitespacesAndNewlines) })
        let ordered = order.filter { selected.contains($0) }
        return (selection == "single" ? Array(ordered.prefix(1)) : ordered).joined(separator: ",")
    }

    static func toggled(_ pass: String, in raw: String, selection: String) -> String {
        guard order.contains(pass) else { return normalized(raw, selection: selection) }
        var selected = Set(normalized(raw, selection: selection).split(separator: ",").map(String.init))
        if selected.contains(pass) { selected.remove(pass) }
        else if selection == "single" { selected = [pass] }
        else { selected.insert(pass) }
        return normalized(selected.joined(separator: ","), selection: selection)
    }

    static func validationError(mode: String, passes: String, selection: String) -> String? {
        guard mode == "enhanced" else { return nil }
        guard ["single", "combined"].contains(selection) else { return "请选择单项或组合保护方式" }
        let selected = passes.split(separator: ",").map(String.init)
        guard !selected.isEmpty else { return "请至少选择一项保护能力；未选择时不能执行强化编译" }
        guard selected.allSatisfy({ order.contains($0) }) else { return "包含当前版本无法识别的保护能力" }
        guard selection != "single" || Set(selected).count == 1 else { return "单项模式只能选择一项保护能力" }
        return nil
    }

    // Commands emit stage lines followed by compact and/or pretty-printed JSON.
    // Scan complete objects, respecting quoted braces/escapes; do not grep a ready string.
    static func reports(in text: String) -> [[String: Any]] {
        var results: [[String: Any]] = []
        var object = "", depth = 0, quoted = false, escaped = false
        for char in text {
            if depth == 0 {
                guard char == "{" else { continue }
                object = "{"; depth = 1; quoted = false; escaped = false
                continue
            }
            object.append(char)
            if quoted {
                if escaped { escaped = false }
                else if char == "\\" { escaped = true }
                else if char == "\"" { quoted = false }
            } else if char == "\"" { quoted = true }
            else if char == "{" { depth += 1 }
            else if char == "}" {
                depth -= 1
                if depth == 0, let data = object.data(using: .utf8),
                   let value = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] {
                    results.append(value)
                }
            }
        }
        return results
    }
}

struct CompilationProtectionView: View {
    @ObservedObject private var model = DeviceWorkbench.shared
    @AppStorage("build.protection") private var mode = "normal"
    @AppStorage("build.protectionCompiler") private var compiler = "/opt/minis-protection/bin/clang"
    @AppStorage("build.protectionPasses") private var passes = "bcf,sobf"
    @AppStorage("build.protectionSelection") private var selection = "combined"
    @State private var result = ""
    @State private var busy = false
    @State private var showReport = false
    @State private var probePassed = false
    @State private var checked = false
    @State private var installed: Bool?
    @State private var installedBytes: Int64?
    @State private var version = ""
    @State private var availablePasses: Set<String> = []
    @State private var acceptedPasses: Set<String> = []

    private struct Option: Identifiable {
        let id: String, title: String, subtitle: String, icon: String
        let color: Color
    }
    private let items = [
        Option(id: "bcf", title: "分支保护", subtitle: "增加虚假分支，隐藏关键跳转路径", icon: "arrow.triangle.branch", color: .blue),
        Option(id: "indcall", title: "调用保护", subtitle: "间接化直接函数调用关系", icon: "point.3.connected.trianglepath.dotted", color: .purple),
        Option(id: "indgv", title: "数据访问保护", subtitle: "间接化全局数据地址访问", icon: "externaldrive", color: .cyan),
        Option(id: "sobf", title: "字符串加密", subtitle: "隐藏支持的字符串明文内容", icon: "textformat", color: .orange),
        Option(id: "fla", title: "控制流强化", subtitle: "平坦化函数控制流程", icon: "shuffle", color: .pink)
    ]
    private var isBusy: Bool { busy || model.busy }
    private var validationError: String? { CompilationProtectionPolicy.validationError(mode: mode, passes: passes, selection: selection) }
    private var componentSummary: String {
        if installed == true {
            var parts = ["已安装"]
            if !version.isEmpty { parts.append(version) }
            if let bytes = installedBytes, bytes > 0 {
                parts.append(ByteCountFormatter.string(fromByteCount: bytes, countStyle: .file))
            }
            return parts.joined(separator: " · ")
        }
        if installed == false { return "未通过检测 · 点击安装或修复" }
        if let previous = model.componentStatus["OLLVM"] { return "上次状态：" + previous }
        return "未检测 · 点击安装或修复"
    }

    var body: some View {
        Form {
            Section(header: Text("编译方式"), footer: Text("强化模式支持本地 C/ObjC/C++ dylib 与 Theos 源码 DEB；不适用于 Swift/APK/EXE，也不能通过重打包保护已有 IPA/DEB。编译时间和成品体积可能增加。")) {
                HStack(spacing: 10) {
                    smallIcon("shield.lefthalf.filled", color: .purple)
                    Text("编译模式").font(.subheadline)
                    Spacer(minLength: 8)
                    Picker("编译模式", selection: $mode) {
                        Text("普通").tag("normal")
                        Text("强化").tag("enhanced")
                    }.pickerStyle(.segmented).frame(maxWidth: 190)
                        .accessibilityLabel("编译模式")
                }
            }
            Section(header: Text("保护能力")) {
                NavigationLink { RuntimeComponentView(name: "OLLVM") } label: {
                    MinisReFeatureRow(title: "保护编译组件", subtitle: componentSummary, icon: "cpu", color: .cyan)
                }.disabled(isBusy)
                HStack(spacing: 10) {
                    smallIcon("slider.horizontal.3", color: .blue)
                    Text("保护方式").font(.subheadline)
                    Spacer(minLength: 8)
                    Picker("保护方式", selection: $selection) {
                        Text("单项").tag("single")
                        Text("组合").tag("combined")
                    }.pickerStyle(.segmented).frame(maxWidth: 190)
                        .accessibilityLabel("保护方式")
                }.disabled(mode != "enhanced" || isBusy)
                ForEach(items) { item in
                    Button {
                        passes = CompilationProtectionPolicy.toggled(item.id, in: passes, selection: selection)
                    } label: {
                        HStack(spacing: 8) {
                            MinisReFeatureRow(title: item.title, subtitle: optionSubtitle(item), icon: item.icon, color: item.color)
                            Image(systemName: selected(item.id) ? "checkmark" : "circle")
                                .font(.system(size: 16, weight: .semibold))
                                .foregroundColor(selected(item.id) ? .accentColor : .secondary.opacity(0.35))
                                .frame(width: 22)
                        }.contentShape(Rectangle())
                    }.buttonStyle(.plain).disabled(mode != "enhanced" || isBusy)
                        .accessibilityLabel(item.title)
                        .accessibilityValue(selected(item.id) ? "已选择" : "未选择")
                }
                if let error = validationError { Text(error).font(.caption).foregroundColor(.orange) }
                if mode == "normal" { Text("普通模式不应用上述保护；所选项目会保留供强化模式使用。").font(.caption).foregroundColor(.secondary) }
            }
            Section(header: Text("实际能力验证"), footer: Text("只在点击检测或实际强化编译时运行探针；首次使用会准备内置组件。检测成功仅代表选中能力通过编译探针，不等于任意源码均已受到保护。")) {
                Button { Task { await checkProtection() } } label: {
                    HStack {
                        Label("检测选中编译器与保护能力", systemImage: "checkmark.shield")
                        Spacer(minLength: 8)
                        if busy { ProgressView() }
                    }.font(.subheadline)
                }.disabled(isBusy || validationError != nil || mode != "enhanced")
                if checked {
                    Label(probePassed ? "选中 \(acceptedPasses.count) 项编译探针通过" : "检测未通过 · 查看详细结果", systemImage: probePassed ? "checkmark.circle" : "exclamationmark.circle")
                        .font(.caption).foregroundColor(probePassed ? .green : .orange)
                }
                if !result.isEmpty {
                    Button { showReport = true } label: { Label("查看检测结果与日志", systemImage: "doc.text.magnifyingglass") }.font(.subheadline)
                }
            }
            Section {
                DisclosureGroup("高级编译器设置") {
                    TextField("编译器路径", text: $compiler).font(.caption)
                        .textInputAutocapitalization(.never).autocorrectionDisabled()
                        .disabled(isBusy)
                    Text("默认使用内置编译器；自定义编译器也必须实际支持所选参数，不会静默回退普通编译。").font(.caption).foregroundColor(.secondary)
                }.font(.subheadline)
            }
        }.navigationTitle("编译保护").navigationBarTitleDisplayMode(.inline)
            .onAppear { normalizeSelection() }
            .onChange(of: selection) { _ in normalizeSelection(); invalidateProbe() }
            .onChange(of: passes) { _ in invalidateProbe() }
            .onChange(of: mode) { _ in invalidateProbe() }
            .onChange(of: compiler) { _ in
                installed = nil; installedBytes = nil; version = ""; availablePasses = []
                invalidateProbe()
            }
            .sheet(isPresented: $showReport) { reportSheet }
    }

    private func smallIcon(_ icon: String, color: Color) -> some View {
        Image(systemName: icon).font(.system(size: 12, weight: .medium))
            .foregroundColor(.white).frame(width: 24, height: 24)
            .background(RoundedRectangle(cornerRadius: 7).fill(color))
    }
    private func selected(_ pass: String) -> Bool { passes.split(separator: ",").contains(Substring(pass)) }
    private func optionSubtitle(_ option: Option) -> String {
        if installed == true, !availablePasses.isEmpty, !availablePasses.contains(option.id) {
            return option.subtitle + " · 当前引擎未通过此项检测"
        }
        return option.subtitle
    }
    private func normalizeSelection() {
        if !["single", "combined"].contains(selection) { selection = "combined" }
        passes = CompilationProtectionPolicy.normalized(passes, selection: selection)
    }
    private func invalidateProbe() { checked = false; probePassed = false; acceptedPasses = [] }

    @MainActor private func checkProtection() async {
        guard !isBusy, mode == "enhanced", validationError == nil else { return }
        busy = true; checked = false; probePassed = false; acceptedPasses = []
        installed = nil; installedBytes = nil; version = ""; availablePasses = []
        let startingCompiler = compiler, startingPasses = passes, startingSelection = selection
        defer { busy = false }
        do {
            let output = try await model.buildWorkbench(["action": "protection-status"])
            result = output
            // Settings may change elsewhere while the guest compiler runs.
            guard mode == "enhanced", compiler == startingCompiler, passes == startingPasses,
                  selection == startingSelection else { return }
            for report in CompilationProtectionPolicy.reports(in: output) {
                if let present = report["installed"] as? Bool { installed = present }
                if let bytes = report["installedBytes"] as? NSNumber, bytes.int64Value > 0 { installedBytes = bytes.int64Value }
                if let clang = report["clang"] as? String { version = clang.replacingOccurrences(of: "Alpine clang version ", with: "Clang ") }
                if let available = report["availablePasses"] as? [String] { availablePasses = Set(available) }
                else if let available = report["passes"] as? [String] { availablePasses = Set(available) }
                if report["mode"] as? String == "enhanced", let accepted = report["acceptedPasses"] as? [String] {
                    acceptedPasses = Set(accepted)
                    let expected = Set(startingPasses.split(separator: ",").map(String.init))
                    probePassed = !expected.isEmpty && acceptedPasses == expected
                }
            }
            checked = true
        } catch {
            result = error.localizedDescription
            installed = false; installedBytes = nil; version = ""; availablePasses = []; acceptedPasses = []
            probePassed = false; checked = true
        }
    }
    private var reportSheet: some View {
        NavigationView {
            ScrollView {
                Text(result).font(.system(.caption, design: .monospaced)).textSelection(.enabled)
                    .frame(maxWidth: .infinity, alignment: .leading).padding()
            }.navigationTitle("编译保护检测").navigationBarTitleDisplayMode(.inline)
                .toolbar {
                    ToolbarItem(placement: .navigationBarLeading) { Button("关闭") { showReport = false } }
                    ToolbarItem(placement: .navigationBarTrailing) { Button("复制") { UIPasteboard.general.string = result } }
                }
        }.navigationViewStyle(.stack)
    }
}

struct MinisReAgentStrip: View {
    @ObservedObject private var jobs = AgentJobRegistry.shared
    let session: String?
    var body: some View {
        let active = session.map { jobs.activeChildren(parent: $0).count } ?? 0
        if active > 0 {
            HStack(spacing: 9) {
                Image(systemName: "person.3.fill").foregroundStyle(.blue)
                Text("Agent 协作中 · \(active) 个任务").font(.caption).lineLimit(2)
                Spacer(minLength: 0)
            }.padding(.horizontal, 14).padding(.vertical, 8).background(.ultraThinMaterial)
        }
    }
}

struct MinisReRuntimeCards: View {
    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            MinisReCard {
                Label("目录访问", systemImage: "folder.badge.gearshape").font(.subheadline.weight(.semibold))
                Text(FileManager.default.isReadableFile(atPath: "/var/jb") ? "检测到 /var/jb 可读" : "未检测到 /var/jb 可读").font(.caption).foregroundStyle(.secondary)
                Text("不据此推断越狱类型").font(.caption2).foregroundStyle(.secondary)
            }
            MinisReCard {
                Label("签名权限", systemImage: "checkmark.seal").font(.subheadline.weight(.semibold))
                Text(AppSigningCapabilities.canAccessOutsideAppContainer ? "有效扩展权限" : "普通沙盒权限").font(.caption).foregroundStyle(.secondary)
                Text("以系统实际权限为准").font(.caption2).foregroundStyle(.secondary)
            }
        }.padding(.vertical, 5)
    }
}
