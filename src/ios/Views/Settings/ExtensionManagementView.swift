import SwiftUI
import UniformTypeIdentifiers

struct ExtensionManagementView: View {
    @ObservedObject private var store = ExtensionStore.shared
    @State private var picker = false
    @State private var preview: ExtensionPreview?
    @State private var errorText = ""
    @State private var showError = false
    @State private var remoteURL = ""

    var body: some View {
        List {
            Section {
                Button { picker = true } label: { Label("导入 ZIP / MD 扩展", systemImage: "square.and.arrow.down") }
                    .disabled(store.busy)
                if store.busy { ProgressView("正在校验与准备预览…") }
                TextField("或输入 HTTPS ZIP 下载链接", text: $remoteURL).autocapitalization(.none).keyboardType(.URL)
                Button("下载并预览") {
                    guard let url = URL(string: remoteURL) else { errorText = "下载链接无效"; showError = true; return }
                    Task {
                        do { preview = try await store.prepareRemote(url: url, currentVersion: Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "1.0") }
                        catch { errorText = error.localizedDescription; showError = true }
                    }
                }.disabled(store.busy || remoteURL.isEmpty)
                Text("MD（最多 64000 字节）自动生成包信息，预览确认后作为追加指令；不是自动执行技能。ZIP 需含 manifest.json，含脚本的普通资料包不能直接导入。ZIP 与解压内容均限 50 MB、1000 项，仍不允许可执行文件。")
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
        .fileImporter(isPresented: $picker, allowedContentTypes: [.zip, UTType(filenameExtension: "md") ?? .plainText], allowsMultipleSelection: false) { result in
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
    }
    private func perform(_ action: () throws -> Void) {
        do { try action() } catch { errorText = error.localizedDescription; showError = true }
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
