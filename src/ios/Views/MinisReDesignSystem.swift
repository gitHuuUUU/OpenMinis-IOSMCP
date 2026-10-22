import SwiftUI

/// Shared visual language for the MinisRe workbench.  The cards are deliberately
/// data-light: status values come from the existing stores and show “未检测”
/// instead of inventing readiness.
enum MinisRePalette {
    static let background = Color(UIColor.systemGroupedBackground)
    static let card = Color(UIColor.secondarySystemGroupedBackground)
    static let border = Color.primary.opacity(0.08)
}

struct MinisReCard<Content: View>: View {
    let content: Content
    init(@ViewBuilder content: () -> Content) { self.content = content() }
    var body: some View {
        content.padding(16).frame(maxWidth: .infinity, alignment: .leading)
            .background(RoundedRectangle(cornerRadius: 18, style: .continuous).fill(MinisRePalette.card))
            .overlay(RoundedRectangle(cornerRadius: 18, style: .continuous).stroke(MinisRePalette.border))
    }
}

struct MinisReDashboardView: View {
    @ObservedObject private var workbench = DeviceWorkbench.shared
    @ObservedObject private var providers = ProviderConfigStore.shared
    @AppStorage("minisre.currency") private var currency = "CNY"
    @State private var showCurrency = false
    @State private var protection = false

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                HStack(spacing: 12) {
                    Image(systemName: "sparkles.rectangle.stack.fill").font(.title2).foregroundStyle(.blue)
                    VStack(alignment: .leading, spacing: 2) { Text("MinisRe 工作台").font(.title2.bold()); Text("把常用入口放在一起，按需打开，不阻塞对话").font(.caption).foregroundStyle(.secondary) }
                }.padding(.horizontal, 4)

                MinisReCard {
                    Label("Agent 协作与上下文", systemImage: "person.3.sequence.fill").font(.headline)
                    HStack(spacing: 10) { metric("活跃 Provider", value: "\(providers.instances.filter(\.isEnabled).count)", color: .blue); metric("子代理并发", value: "\(RuntimeEfficiency.childConcurrency)", color: .purple); metric("温控", value: RuntimeEfficiency.underPressure ? "降载" : "正常", color: RuntimeEfficiency.underPressure ? .orange : .green) }
                }

                SectionHeader(title: "AI 账号与费用", icon: "person.crop.circle.badge.checkmark")
                dashboardLink("AI 账号与 Provider", icon: "key.fill", tint: .blue) { ProviderInstancesView() }
                dashboardLink("用量与费用", icon: "chart.bar.xaxis", tint: .green) { UsageStatsView() }
                Button { showCurrency = true } label: { dashboardRow("计费币种", icon: "dollarsign.circle", tint: .orange, detail: currency == "CNY" ? "人民币 (CNY)" : "美元 (USD)") }

                SectionHeader(title: "构建与运行", icon: "hammer.fill")
                dashboardLink("开发环境与工具状态", icon: "wrench.and.screwdriver.fill", tint: .indigo) { DevelopmentWorkbenchView() }
                dashboardLink("运行诊断", icon: "stethoscope", tint: .teal) { WorkbenchDiagnosticsView() }
                NavigationLink { CompilationProtectionView(enabled: $protection) } label: { dashboardRow("编译保护", icon: "shield.checkered", tint: .red, detail: protection ? "强化模式" : "普通模式") }

                SectionHeader(title: "模型价格", icon: "list.bullet.rectangle")
                ModelPricePreview()
            }.padding()
        }.background(MinisRePalette.background.ignoresSafeArea()).navigationTitle("MinisRe").navigationBarTitleDisplayMode(.inline)
        .confirmationDialog("计费币种", isPresented: $showCurrency, titleVisibility: .visible) {
            Button("人民币 (CNY)") { currency = "CNY" }
            Button("美元 (USD)") { currency = "USD" }
            Button("取消", role: .cancel) { }
        }
    }

    private func metric(_ title: String, value: String, color: Color) -> some View { VStack(alignment: .leading) { Text(value).font(.headline).foregroundStyle(color); Text(title).font(.caption).foregroundStyle(.secondary) }.frame(maxWidth: .infinity, alignment: .leading) }
    private func dashboardLink<Destination: View>(_ title: String, icon: String, tint: Color, @ViewBuilder destination: () -> Destination) -> some View { NavigationLink { destination() } label: { dashboardRow(title, icon: icon, tint: tint, detail: "打开") } }
    private func dashboardRow(_ title: String, icon: String, tint: Color, detail: String) -> some View { HStack(spacing: 12) { Image(systemName: icon).font(.title3).foregroundStyle(tint).frame(width: 28); Text(title).font(.body); Spacer(); Text(detail).font(.caption).foregroundStyle(.secondary); Image(systemName: "chevron.right").font(.caption).foregroundStyle(.tertiary) }.padding(.vertical, 5) }
}

private struct SectionHeader: View { let title: String; let icon: String; var body: some View { Label(title, systemImage: icon).font(.headline).padding(.top, 5) } }

struct CompilationProtectionView: View {
    @Binding var enabled: Bool
    private let items = ["组件保护", "组合/单项保护", "分支保护", "调用保护", "数据访问保护", "字符串加密", "控制流强化"]
    var body: some View { Form { Section { Picker("模式", selection: $enabled) { Text("普通").tag(false); Text("强化").tag(true) }.pickerStyle(.segmented) } header: { Text("保护模式") }; Section { ForEach(items, id: \.self) { item in HStack { Image(systemName: enabled ? "checkmark.shield.fill" : "shield").foregroundStyle(enabled ? .green : .secondary); Text(item); Spacer(); Text(enabled ? "已启用" : "按需").font(.caption).foregroundStyle(.secondary) } } } header: { Text("能力清单") }; Text("该开关只作为真实构建参数入口；未连接构建机时不会伪造保护结果。").font(.caption).foregroundStyle(.secondary) }.navigationTitle("编译保护") }
}

private struct ModelPricePreview: View {
    @State private var query = ""
    private let rows = [("OpenAI", "GPT-5.6", "输入 $1.25 · 输出 $10 / 1M", "高上下文"), ("Anthropic", "Claude", "按 Provider 配置", "未检测"), ("MuseAI", "Muse", "按 Provider 配置", "未检测")]
    var filtered: [(String, String, String, String)] { query.isEmpty ? rows : rows.filter { ($0.0 + $0.1).localizedCaseInsensitiveContains(query) } }
    var body: some View { MinisReCard { TextField("搜索模型", text: $query).textFieldStyle(.roundedBorder); ForEach(filtered, id: \.1) { row in HStack { Image(systemName: "cpu").foregroundStyle(.blue); VStack(alignment: .leading) { Text("\(row.0) · \(row.1)"); Text(row.2).font(.caption).foregroundStyle(.secondary) }; Spacer(); Text(row.3).font(.caption2).foregroundStyle(.secondary) } } } }
}
