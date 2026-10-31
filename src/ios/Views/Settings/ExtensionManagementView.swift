import SwiftUI
import UniformTypeIdentifiers

struct ExtensionManagementView: View {
    @ObservedObject private var store = ExtensionStore.shared
    @State private var picker = false
    @State private var preview: ExtensionPreview?
    @State private var errorText = ""
    @State private var showError = false
    @State private var remoteURL = ""
    @State private var multiPicker = false
    @State private var batchNotice = ""
    private var appVersion: String { Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "1.0" }

    var body: some View {
        List {
            Section(header: Text("破甲内核 · \(ExtensionArmor.builtinDisplayName)")) {
                if let persona = store.activePersonaName {
                    HStack {
                        Image(systemName: "flame.fill").foregroundColor(.orange)
                        VStack(alignment: .leading, spacing: 2) {
                            Text("已生效：\(persona)")
                            Text("作为本请求最高优先级运行指令注入，末尾锚定，覆盖拒答与免责声明路径。")
                                .font(.caption).foregroundColor(.secondary)
                        }
                    }
                } else {
                    Text("未生效：没有启用中的破甲包。").font(.footnote).foregroundColor(.secondary)
                }
                Button {
                    installBuiltin()
                } label: {
                    Label(store.armorActive ? "重装内置人格" : "一键内置\(ExtensionArmor.builtinDisplayName)", systemImage: "bolt.shield")
                }.disabled(store.busy)
                Toggle("总开关（全部破甲包）", isOn: Binding(
                    get: { store.armorActive },
                    set: { value in perform { try store.setArmorEnabled(value) } }
                )).disabled(store.busy)
                Text("任何一个 .md / .zip 导入后默认按破甲模式追加，段落被包进 owner_policy 头并压到 prompt 末尾；不想要提权就在该包装目录里把 armor.json 改成 {\"mode\":\"supplement\"}。")
                    .font(.footnote).foregroundColor(.secondary)
            }
            Section {
                Button { picker = true } label: { Label("导入 ZIP / RAR / MD 扩展", systemImage: "square.and.arrow.down") }
                    .disabled(store.busy)
                Button { multiPicker = true } label: { Label("批量导入多个 MD（含敏感 md）", systemImage: "doc.on.doc") }
                    .disabled(store.busy)
                if store.busy { ProgressView("正在校验与准备预览…") }
                TextField("或输入 HTTPS ZIP 下载链接", text: $remoteURL).autocapitalization(.none).keyboardType(.URL)
                Button("下载并预览") {
                    guard let url = URL(string: remoteURL) else { errorText = "下载链接无效"; showError = true; return }
                    Task {
                        do { preview = try await store.prepareRemote(url: url, currentVersion: appVersion) }
                        catch { errorText = error.localizedDescription; showError = true }
                    }
                }.disabled(store.busy || remoteURL.isEmpty)
                Text("MD（最多 64000 字节）自动补 owner_policy 头 + 人格骨架，预览确认后按最高优先级注入；不是自动执行技能。frontmatter 写 persona: 名字 可换人格名。ZIP / RAR 支持标准 manifest 包、persona/ 目录包、SKILL.md 技能包及纯 Markdown 文档包；导入不会自动执行，二进制程序仍不接受。ZIP 与解压内容均限 50 MB、\(ExtensionPackageReader.maxFiles) 项（含目录）。")
                    .font(.footnote).foregroundColor(.secondary)
            }
            Section(header: Text("已安装 · 拖动调整加载顺序（后者优先）")) {
                ForEach(store.state.packs) { pack in
                    NavigationLink { ExtensionDetailView(name: pack.id) } label: {
                        VStack(alignment: .leading, spacing: 4) {
                            Text(pack.id + " · " + pack.manifest.version)
                            Text(pack.enabled ? "已启用" : "已禁用").font(.caption).foregroundColor(pack.enabled ? .green : .secondary)
                        }
                    }
                }.onMove { from, to in perform { try store.move(from: from, to: to) } }
                if store.state.packs.isEmpty { Text("暂无扩展包").foregroundColor(.secondary) }
            }
            Section(header: Text("安装目录")) { Text(store.root.path).font(.caption).textSelection(.enabled) }
            if !store.notice.isEmpty { Section { Text(store.notice).font(.footnote).foregroundColor(.secondary) } }
            Section { NavigationLink("查看配置审计日志") { ConfigAuditView() } }
        }
        .navigationTitle("扩展包")
        .toolbar { EditButton() }
        .fileImporter(isPresented: $picker, allowedContentTypes: [.item], allowsMultipleSelection: false) { result in
            switch result {
            case .success(let urls):
                guard let url = urls.first else { return }
                Task {
                    do { preview = try await store.prepare(url: url, currentVersion: Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "1.0") }
                    catch { errorText = error.localizedDescription; showError = true }
                }
            case .failure(let error): errorText = error.localizedDescription; showError = true
            }
        }
        .sheet(item: $preview) { value in
            NavigationView { ExtensionPreviewView(preview: value) { preview = nil } }
                .onDisappear { try? FileManager.default.removeItem(at: value.staging) }
        }
        .alert("扩展操作失败", isPresented: $showError) { Button("好", role: .cancel) {} } message: { Text(errorText) }
        .fileImporter(isPresented: $multiPicker, allowedContentTypes: [.item], allowsMultipleSelection: true) { result in
            switch result {
            case .success(let urls):
                guard !urls.isEmpty else { return }
                let md = urls.filter { $0.pathExtension.lowercased() == "md" }
                guard md.count == urls.count else {
                    errorText = "批量导入只接受 .md；ZIP/RAR 请用上面的单个导入逐包预览。"
                    showError = true
                    return
                }
                Task { await importAll(md) }
            case .failure(let error): errorText = error.localizedDescription; showError = true
            }
        }
        .alert("批量导入结果", isPresented: Binding(get: { !batchNotice.isEmpty }, set: { if !$0 { batchNotice = "" } })) {
            Button("好", role: .cancel) { batchNotice = "" }
        } message: { Text(batchNotice) }
    }

    /// 批量落盘：逐个 prepare → install(overwrite)，失败不中断后续文件。
    /// 同名 md（同文件名不同内容也算）由稳定包名 + 摘要区分，重复导入同一份
    /// 文本是覆盖而非堆积。
    private func importAll(_ urls: [URL]) async {
        var ok = 0
        var failed: [String] = []
        for url in urls {
            do {
                let value = try await store.prepare(url: url, currentVersion: appVersion)
                try store.install(value, collision: .overwrite)
                ok += 1
            } catch {
                failed.append(url.lastPathComponent + "：" + error.localizedDescription)
            }
        }
        batchNotice = "成功 \(ok) 个" + (failed.isEmpty ? "" : "；失败 \(failed.count) 个：
" + failed.prefix(6).joined(separator: "
"))
        if ok > 0 { try? store.setArmorEnabled(true) }
    }

    /// 内置人格：安装 + 开总开关，一次点击完成。
    private func installBuiltin() {
        installBuiltinArmorAndEnable()
    }
    private func perform(_ action: () throws -> Void) {
        do { try action() } catch { errorText = error.localizedDescription; showError = true }
    }
}

private extension ExtensionManagementView {
    /// 破甲包安装后直接开总开关，省掉"装完还得再点一次"的坑。
    func installBuiltinArmorAndEnable() {
        do {
            _ = try store.installBuiltinArmor(currentVersion: appVersion)
            _ = try store.setArmorEnabled(true)
        } catch {
            errorText = error.localizedDescription
            showError = true
        }
    }
}

private struct ExtensionPreviewView: View {
    @ObservedObject private var store = ExtensionStore.shared
    let preview: ExtensionPreview
    let close: () -> Void
    @State private var mode = 0
    @State private var newName = ""
    @State private var failure = ""
    @State private var installing = false
    private var collision: Bool { store.state.packs.contains { $0.id == preview.package.manifest.name } || FileManager.default.fileExists(atPath: store.installedURL(preview.package.manifest.name).path) }
    var body: some View {
        Form {
            Section(header: Text("预览 · 确认后才安装")) {
                Text(preview.package.manifest.name + " · " + preview.package.manifest.version)
                Text(preview.package.manifest.description)
                Text("作者：" + preview.package.manifest.author)
                Text("内容：" + preview.package.manifest.contents.joined(separator: "、"))
                Text("位置：" + store.installedURL(mode == 1 ? newName : preview.package.manifest.name).path).font(.caption)
                Text("文件：\(preview.package.files.count) 项，解压后 \(preview.package.files.values.reduce(0) { $0 + $1.count }) 字节")
            }
            if collision {
                Section(header: Text("已存在同名包")) {
                    Picker("处理方式", selection: $mode) { Text("覆盖").tag(0); Text("重命名").tag(1); Text("取消").tag(2) }
                    if mode == 1 { TextField("新包名（英文字母、数字、下划线、横线）", text: $newName).autocapitalization(.none) }
                    Text("覆盖后旧 provider 确认将失效，新包需要重新逐条确认。")
                }
            }
            Section(header: Text("技能：同名替换")) {
                ForEach(preview.package.skillNames, id: \.self) { name in
                    Text(name + (SkillStore.shared.skills.contains { $0.id == name } ? " · 将替换（原件可恢复）" : " · 新增"))
                }
            }
            Section(header: Text("Provider：安装后仍待确认")) {
                ForEach(preview.package.providers) { provider in
                    VStack(alignment: .leading) { Text(provider.label); Text(provider.endpoint).font(.caption).textSelection(.enabled) }
                }
                Text("导入的 API Key 仅存钥匙串，不显示、不写入扩展文件或审计日志。原始 ZIP 属于你选择的外部文件，请自行妥善保管。")
                    .font(.footnote).foregroundColor(.secondary)
            }
            if !failure.isEmpty { Text(failure).foregroundColor(.red) }
            Button(installing ? "正在安装…" : "确认安装") {
                installing = true
                // Allow the progress label to paint before serialized file mutations.
                Task { @MainActor in
                    await Task.yield()
                    do {
                        let choice: ExtensionStore.Collision = collision && mode == 2 ? .cancel : (mode == 1 ? .rename(newName) : .overwrite)
                        try store.install(preview, collision: choice); close()
                    } catch { failure = error.localizedDescription; installing = false }
                }
            }.disabled(installing)
        }
        .navigationTitle("扩展预览")
        .toolbar { ToolbarItem(placement: .cancellationAction) { Button("取消") { store.discard(preview); close() }.disabled(installing) } }
        .interactiveDismissDisabled(installing)
    }
}

private struct ExtensionDetailView: View {
    @ObservedObject private var store = ExtensionStore.shared
    @Environment(\.presentationMode) private var presentationMode
    let name: String
    @State private var uninstall = false
    @State private var confirming: ExtensionProvider?
    @State private var confirm = false
    @State private var failure = ""
    private var pack: InstalledExtension? { store.state.packs.first { $0.id == name } }
    var body: some View {
        Form {
            if let pack {
                Section {
                    Text(pack.manifest.description)
                    Toggle("启用扩展", isOn: Binding(get: { self.pack?.enabled ?? false }, set: { value in perform { try store.setEnabled(name, value) } }))
                    Text("禁用后不再追加指令，恢复被替换技能，并禁用本包已确认的 provider。正在进行的请求不会被强制中断。")
                        .font(.footnote).foregroundColor(.secondary)
                }
                Section(header: Text("对话加载状态")) {
                    Text(pack.enabled ? "已启用：下次发送时加载，当前进行中的请求不变。" : "已禁用：不会加入新请求。")
                    if pack.isPersona {
                        Text(pack.enabled ? "破甲模式：作为最高优先级运行指令，末尾锚定注入。" : "破甲模式：已安装但未注入。")
                            .font(.caption)
                            .foregroundColor(pack.enabled ? .orange : .secondary)
                    }
                    if pack.manifest.contents.contains("instructions") {
                        if let text = store.instructionText(for: pack) {
                            Text("追加指令：\(text.count) 字符" + (pack.enabled ? " · 已接入对话上下文" : " · 暂不加载"))
                            DisclosureGroup("查看追加内容") { Text(text).font(.caption).textSelection(.enabled) }
                        } else { Text("指令文件无法读取或校验未通过，当前不会加载；请重新导入。").foregroundColor(.red) }
                    }
                    if !pack.skills.isEmpty {
                        Text("技能：\(pack.skills.count) 项；启用时注册到技能库，由 AI 按任务读取，也可在专家页绑定。")
                        ForEach(pack.skills, id: \.self) { id in Text(id).font(.caption) }
                    }
                    Text("导入是安装指令与资源，不会凭空安装外部工具。Provider 仍需逐条确认并选择模型使用。")
                        .font(.footnote).foregroundColor(.secondary)
                }
                Section(header: Text("Provider 二次确认")) {
                    ForEach(pack.providers) { provider in
                        VStack(alignment: .leading, spacing: 6) {
                            Text(provider.label + " · " + provider.providerType)
                            Text(provider.endpoint).font(.caption).textSelection(.enabled)
                            if provider.approved { Text("已确认" + (pack.enabled ? " · 已启用" : " · 已禁用")).foregroundColor(.green) }
                            else { Button("确认此 Provider…") { confirming = provider; confirm = true } }
                        }
                    }
                }
                Section {
                    Text(store.notice).font(.footnote)
                    Button("卸载扩展", role: .destructive) { uninstall = true }
                }
            }
            if !failure.isEmpty { Text(failure).foregroundColor(.red) }
        }
        .navigationTitle(name)
        .alert("确认此 Provider", isPresented: $confirm, presenting: confirming) { provider in
            Button("确认并合并配置") { perform { try store.confirmProvider(pack: name, id: provider.id) } }
            Button("取消", role: .cancel) {}
        } message: { provider in Text("\(provider.label)\n\(provider.endpoint)\n确认后模型请求可能向此地址发送会话内容；密钥仅由钥匙串提供。") }
        .confirmationDialog("卸载会清理本包 provider 引用并恢复原技能；已发出的请求与上下文无法撤回，请先取消正在进行的任务。", isPresented: $uninstall, titleVisibility: .visible) {
            Button("确认卸载", role: .destructive) { perform { try store.uninstall(name); presentationMode.wrappedValue.dismiss() } }
            Button("取消", role: .cancel) {}
        }
    }
    private func perform(_ action: () throws -> Void) {
        do { try action(); failure = "" } catch { failure = error.localizedDescription }
    }
}
