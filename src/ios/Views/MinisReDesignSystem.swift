import SwiftUI

enum MinisRePalette {
    static let background = Color(UIColor.systemGroupedBackground)
    static let card = Color(UIColor.secondarySystemGroupedBackground)
    static let border = Color.primary.opacity(0.08)
}

struct MinisReCard<Content: View>: View {
    let content: Content
    init(@ViewBuilder content: () -> Content) { self.content = content() }
    var body: some View {
        VStack(alignment: .leading, spacing: 14) { content }
            .padding(16).frame(maxWidth: .infinity, alignment: .leading)
            .background(RoundedRectangle(cornerRadius: 20, style: .continuous).fill(MinisRePalette.card))
            .overlay(RoundedRectangle(cornerRadius: 20, style: .continuous).stroke(MinisRePalette.border))
    }
}

struct MinisReFeatureRow: View {
    let title: String
    let subtitle: String
    let icon: String
    var color: Color = .blue
    var body: some View {
        HStack(spacing: 13) {
            Image(systemName: icon).font(.system(size: 19, weight: .semibold))
                .foregroundStyle(.white).frame(width: 40, height: 40)
                .background(RoundedRectangle(cornerRadius: 12).fill(color))
            VStack(alignment: .leading, spacing: 4) {
                Text(title).foregroundStyle(.primary)
                if !subtitle.isEmpty { Text(subtitle).font(.caption).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true) }
            }
            Spacer(minLength: 4)
        }.padding(.vertical, 3).frame(maxWidth: .infinity, alignment: .leading)
    }
}

struct MinisReDashboardView: View {
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                Text("你的开发空间").font(.largeTitle.bold())
                Text("账号、工具与运行状态，一处掌握").font(.subheadline).foregroundStyle(.secondary)
                MinisReCard {
                    NavigationLink { MinisReAccountsView() } label: {
                        MinisReFeatureRow(title: "AI 账号", subtitle: "登录 · 服务商 · 用量与模型价格", icon: "person.crop.circle.fill", color: .blue)
                    }
                    Divider()
                    NavigationLink { DevelopmentWorkbenchView() } label: {
                        MinisReFeatureRow(title: "开发能力", subtitle: "按需安装，保留真实探针结果", icon: "hammer.fill", color: .orange)
                    }
                    Divider()
                    NavigationLink { CompilationProtectionView() } label: {
                        MinisReFeatureRow(title: "编译保护", subtitle: "普通 / 强化 · 编译器与能力检测", icon: "shield.lefthalf.filled", color: .purple)
                    }
                }
                MinisReCard {
                    NavigationLink { WorkbenchDiagnosticsView() } label: {
                        MinisReFeatureRow(title: "运行诊断", subtitle: "签名权限、工具与环境检查", icon: "stethoscope", color: .teal)
                    }
                    Divider()
                    NavigationLink { RuntimeEfficiencyView() } label: {
                        MinisReFeatureRow(title: "提速与温控", subtitle: "按需并发，热压力下自动降载", icon: "bolt.fill", color: .green)
                    }
                }
            }.padding(18)
        }.background(MinisRePalette.background.ignoresSafeArea())
            .navigationTitle("MinisRe").navigationBarTitleDisplayMode(.inline)
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
            VStack(alignment: .leading, spacing: 20) {
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
                Text("管理").font(.subheadline).foregroundStyle(.secondary).padding(.leading, 6)
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
            }.padding(18)
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
                            Label(row.name, systemImage: "cpu").font(.headline)
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
            VStack(alignment: .leading, spacing: 18) {
                Text("本机用量估算").foregroundStyle(.secondary)
                MinisReCard {
                    Label("Token 用量统计", systemImage: "chart.bar.fill").font(.headline)
                    HStack { metric("今日 Token", value: todayTokens.formatted()); metric("累计 Token", value: totalTokens.formatted()) }
                }
                MinisReCard {
                    Label("API 参考费用", systemImage: "dollarsign.circle").font(.headline)
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
            }.padding(18)
        }.background(MinisRePalette.background.ignoresSafeArea()).navigationTitle("用量与费用").navigationBarTitleDisplayMode(.inline)
            .task { await load() }
    }
    private func display(_ usd: Double?) -> String { UsageCostPolicy.display(usd, currency: currency, usdToCNY: exchange) }
    private func metric(_ title: String, value: String) -> some View {
        VStack(alignment: .leading, spacing: 7) { Text(title).font(.caption).foregroundStyle(.secondary); Text(value).font(.title3.bold()).minimumScaleFactor(0.7).lineLimit(1) }.frame(maxWidth: .infinity, alignment: .leading)
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

struct CompilationProtectionView: View {
    @AppStorage("build.protection") private var mode = "normal"
    @AppStorage("build.protectionCompiler") private var compiler = "/opt/minis-protection/bin/clang"
    @AppStorage("build.protectionPasses") private var passes = "bcf,sobf"
    @State private var result = ""
    @State private var busy = false
    private let items = [("bcf", "分支保护", "arrow.triangle.branch"), ("indcall", "调用保护", "point.3.connected.trianglepath.dotted"), ("indgv", "数据访问保护", "externaldrive"), ("sobf", "字符串加密", "textformat"), ("fla", "控制流强化", "shuffle")]
    var body: some View {
        Form {
            Section {
                Picker("编译模式", selection: $mode) { Text("普通").tag("normal"); Text("强化").tag("enhanced") }.pickerStyle(.segmented)
                Text("普通模式兼容性优先；强化模式首次使用会自动安装内置 Clang19/Hikari 离线组件，无需填路径。用于工作台本地 C/ObjC dylib 编译；预编译 IPA/DEB 不能靠打包补加保护。").font(.caption).foregroundStyle(.secondary)
            }
            if mode == "enhanced" {
                Section("保护编译组件") {
                    TextField("编译器路径", text: $compiler).textInputAutocapitalization(.never).autocorrectionDisabled()
                    Button("安装 / 修复内置 OLLVM") { Task { busy = true; defer { busy = false }; do { result = try await DeviceWorkbench.shared.buildWorkbench(["action":"install-ollvm"]) } catch { result = error.localizedDescription } } }.disabled(busy)
                    Text("内置版本提供分支保护、字符串加密与控制流平坦化；缺少组件或所选 pass 不支持时明确失败，不伪造成功。完整 LLVM 较大，首次解包需 1.5GB 空闲空间，编译会占用 CPU。").font(.caption).foregroundStyle(.secondary)
                }
                Section("保护方式 · 多选组合") {
                    ForEach(items, id: \.0) { item in
                        Toggle(isOn: binding(item.0)) {
                            VStack(alignment:.leading) {
                                Label(item.1, systemImage:item.2)
                                if ["indcall","indgv"].contains(item.0) { Text("本内置引擎未提供此项").font(.caption).foregroundStyle(.secondary) }
                            }
                        }.disabled(compiler == "/opt/minis-protection/bin/clang" && ["indcall","indgv"].contains(item.0))
                    }
                }
            }
            Section {
                Button { Task { busy = true; defer { busy = false }; do { result = try await DeviceWorkbench.shared.buildWorkbench(["action": "protection-status"]) } catch { result = error.localizedDescription } } } label: { Label("检测选中编译器与保护能力", systemImage: "checkmark.shield") }.disabled(busy)
                if busy { ProgressView() }
                if !result.isEmpty { Text(result).font(.system(.caption, design: .monospaced)).textSelection(.enabled) }
            }
        }.navigationTitle("编译保护").navigationBarTitleDisplayMode(.inline)
            .onAppear { normalizeBuiltinPasses() }
            .onChange(of:compiler) { _ in normalizeBuiltinPasses() }
    }
    private func normalizeBuiltinPasses() {
        guard compiler == "/opt/minis-protection/bin/clang" else { return }
        let supported = passes.split(separator:",").map(String.init).filter { ["bcf","fla","sobf"].contains($0) }
        passes = supported.isEmpty ? "bcf,sobf" : supported.joined(separator:",")
    }
    private func binding(_ pass: String) -> Binding<Bool> {
        Binding(get: { passes.split(separator: ",").contains(Substring(pass)) }, set: { value in
            var selected = Set(passes.split(separator: ",").map(String.init))
            if value { selected.insert(pass) } else { selected.remove(pass) }
            passes = selected.sorted().joined(separator: ",")
        })
    }
}

struct MinisReAgentStrip: View {
    @ObservedObject private var jobs = AgentJobRegistry.shared
    let session: String?
    let context: String?
    var body: some View {
        let active = session.map { jobs.activeChildren(parent: $0).count } ?? 0
        if active > 0 || context != nil {
            HStack(spacing: 9) {
                Image(systemName: active > 0 ? "person.3.fill" : "chart.bar.fill").foregroundStyle(.blue)
                Text(active > 0 ? "Agent 协作中 · \(active) 个任务" : (context ?? "")).font(.caption).lineLimit(2)
                Spacer(minLength: 0)
            }.padding(.horizontal, 14).padding(.vertical, 8).background(.ultraThinMaterial)
        }
    }
}

struct MinisReRuntimeCards: View {
    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            MinisReCard {
                Label("目录访问", systemImage: "folder.badge.gearshape").font(.headline)
                Text(FileManager.default.isReadableFile(atPath: "/var/jb") ? "检测到 /var/jb 可读" : "未检测到 /var/jb 可读").font(.caption).foregroundStyle(.secondary)
                Text("不据此推断越狱类型").font(.caption2).foregroundStyle(.secondary)
            }
            MinisReCard {
                Label("签名权限", systemImage: "checkmark.seal").font(.headline)
                Text(AppSigningCapabilities.canAccessOutsideAppContainer ? "有效扩展权限" : "普通沙盒权限").font(.caption).foregroundStyle(.secondary)
                Text("以系统实际权限为准").font(.caption2).foregroundStyle(.secondary)
            }
        }.padding(.vertical, 5)
    }
}
