import Foundation
import Combine

@MainActor protocol ExtensionHost: AnyObject {
    var skillRoot: URL { get }
    func skillEnabled(_ id: String) -> Bool
    func replaceSkill(_ id: String, source: URL?, enabled: Bool) throws
    func saveSecret(_ secret: String, id: String) throws
    func removeSecret(_ id: String)
    func setProvider(_ proposal: ExtensionProvider, enabled: Bool) throws
    func removeProvider(_ id: String)
    func audit(_ action: String, name: String, success: Bool)
}

struct InstalledExtension: Codable, Identifiable {
    var id: String { manifest.name }
    var manifest: ExtensionManifest
    var enabled: Bool
    var providers: [ExtensionProvider]
    var skills: [String]
    /// [armor] 该包的 instructions 按最高优先级注入（人格正文）。
    var isPersona: Bool = false
    /// [armor] 人格名，用于注入头里的 operator identity 行。
    var personaName: String? = nil

    init(manifest: ExtensionManifest, enabled: Bool, providers: [ExtensionProvider], skills: [String],
         isPersona: Bool = false, personaName: String? = nil) {
        self.manifest = manifest
        self.enabled = enabled
        self.providers = providers
        self.skills = skills
        self.isPersona = isPersona
        self.personaName = personaName
    }

    // 旧 state.json 没有这两个键，缺失时按"非人格"恢复，不能让整个索引解码失败。
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        manifest = try c.decode(ExtensionManifest.self, forKey: .manifest)
        enabled = try c.decode(Bool.self, forKey: .enabled)
        providers = try c.decodeIfPresent([ExtensionProvider].self, forKey: .providers) ?? []
        skills = try c.decodeIfPresent([String].self, forKey: .skills) ?? []
        isPersona = try c.decodeIfPresent(Bool.self, forKey: .isPersona) ?? false
        personaName = try c.decodeIfPresent(String.self, forKey: .personaName)
    }
}

struct ExtensionPreview: Identifiable, Sendable {
    let id = UUID()
    var package: ExtensionPackage
    let staging: URL
}

/// All lifecycle mutations are serialized on MainActor. Parsing/unpacking is
/// performed off the UI thread; no provider probe/network request runs at import.
@MainActor final class ExtensionStore: ObservableObject {
    enum Collision { case overwrite, rename(String), cancel }
    struct State: Codable {
        var packs: [InstalledExtension] = []
        // Original, pre-extension skill enable state; files live in backupRoot.
        var originals: [String: Bool] = [:]
    }
    @Published private(set) var state = State()
    @Published private(set) var busy = false
    @Published var notice = ""
    let root: URL
    let metadata: URL
    private let host: ExtensionHost
    private let fm = FileManager.default
    // Exact bytes, not mtime: edits are revalidated even when timestamps match.
    // Bound retained memory independently of the number of installed packages.
    private var instructionCache: [String: (bytes: Data, text: String)] = [:]

    private var backupRoot: URL { metadata.appendingPathComponent("skill-backups") }
    private var stateFile: URL { metadata.appendingPathComponent("state.json") }

    init(root: URL, host: ExtensionHost) {
        self.root = root
        self.metadata = root.deletingLastPathComponent().appendingPathComponent("extension-state")
        self.host = host
        do {
            try fm.createDirectory(at: root, withIntermediateDirectories: true)
            try fm.createDirectory(at: backupRoot, withIntermediateDirectories: true)
            if fm.fileExists(atPath: stateFile.path) {
                state = try JSONDecoder().decode(State.self, from: Data(contentsOf: stateFile))
                guard state.packs.allSatisfy({ ExtensionPackageReader.validateName($0.id) && $0.skills.allSatisfy(ExtensionPackageReader.validateName) }),
                      state.originals.keys.allSatisfy(ExtensionPackageReader.validateName) else { throw ExtensionPackageReader.fail("扩展索引路径非法") }
            }
        } catch {
            state = State()
            notice = "扩展索引无法加载，未启用任何扩展：\(error.localizedDescription)"
        }
    }

    func prepare(url: URL, currentVersion: String) async throws -> ExtensionPreview {
        guard !busy else { throw ExtensionPackageReader.fail("已有扩展操作正在进行") }
        busy = true
        defer { busy = false }
        let scoped = url.startAccessingSecurityScopedResource()
        defer { if scoped { url.stopAccessingSecurityScopedResource() } }
        do {
            let preview = try await Task.detached(priority: .userInitiated) { () throws -> ExtensionPreview in
                if url.scheme == "https" {
                    throw ExtensionPackageReader.fail("请使用 HTTPS 下载入口")
                }
                let markdown = url.pathExtension.lowercased() == "md"
                guard markdown || ["zip", "rar"].contains(url.pathExtension.lowercased()) else { throw ExtensionPackageReader.fail("只接受 .zip / .rar 扩展包或 .md 追加指令文件") }
                let limit = markdown ? ExtensionPackageReader.maxInstructionBytes : ExtensionPackageReader.maxBytes
                let size = try? url.resourceValues(forKeys: [.fileSizeKey]).fileSize
                // Cloud/file-provider URLs may not expose size metadata. The bounded
                // read below remains authoritative instead of treating unknown as huge.
                guard size.map({ $0 <= limit }) ?? true else { throw ExtensionPackageReader.fail(markdown ? "MD 超过 64000 字节，未读取" : "ZIP 超过 50 MB，未读取") }
                let handle = try FileHandle(forReadingFrom: url)
                defer { try? handle.close() }
                let bytes = try handle.read(upToCount: limit + 1) ?? Data()
                guard bytes.count <= limit else { throw ExtensionPackageReader.fail("读取时文件大小已超过上限，已中止") }
                if markdown { return try Self.stagePackage(ExtensionPackageReader.markdown(bytes, filename: url.lastPathComponent, currentVersion: currentVersion)) }
                if url.pathExtension.lowercased() == "rar" {
                    #if os(iOS)
                    let files = try MinisDeviceBridge.readRAR(bytes)
                    return try Self.stagePackage(ExtensionPackageReader.readCompatibleFiles(files, filename: url.lastPathComponent, currentVersion: currentVersion))
                    #else
                    throw ExtensionPackageReader.fail("RAR 原生解码需要 iOS 构建")
                    #endif
                }
                return try Self.stagePackage(ExtensionPackageReader.readCompatible(bytes, filename: url.lastPathComponent, currentVersion: currentVersion))
            }.value
            host.audit("preview", name: preview.package.manifest.name, success: true)
            return preview
        } catch {
            // Never log filenames, imported instructions, endpoints or secrets.
            host.audit("import-rejected", name: "package", success: false)
            throw error
        }
    }

    func prepareRemote(url: URL, currentVersion: String) async throws -> ExtensionPreview {
        guard !busy else { throw ExtensionPackageReader.fail("已有扩展操作正在进行") }
        busy = true; defer { busy = false }
        do {
            let bytes = try await ExtensionDownload.fetch(url)
            let value = try await Task.detached(priority: .userInitiated) { try Self.stage(bytes, currentVersion: currentVersion) }.value
            host.audit("preview-download", name: value.package.manifest.name, success: true)
            return value
        } catch { host.audit("import-rejected", name: "download", success: false); throw error }
    }

    private nonisolated static func stage(_ data: Data, currentVersion: String) throws -> ExtensionPreview {
        let package = try ExtensionPackageReader.read(data, currentVersion: currentVersion)
        return try stagePackage(package)
    }

    private nonisolated static func stagePackage(_ package: ExtensionPackage) throws -> ExtensionPreview {
        let staging = FileManager.default.temporaryDirectory.appendingPathComponent("minis-extension-\(UUID())")
        do {
            try FileManager.default.createDirectory(at: staging, withIntermediateDirectories: true)
            for (name, data) in package.files {
                let target = staging.appendingPathComponent(name)
                guard target.standardizedFileURL.path.hasPrefix(staging.standardizedFileURL.path + "/") else { throw ExtensionPackageReader.fail("解压路径越界") }
                try FileManager.default.createDirectory(at: target.deletingLastPathComponent(), withIntermediateDirectories: true)
                try data.write(to: target, options: [.atomic, .completeFileProtectionUntilFirstUserAuthentication])
            }
            return ExtensionPreview(package: package, staging: staging)
        } catch { try? FileManager.default.removeItem(at: staging); throw error }
    }

    func discard(_ preview: ExtensionPreview) {
        try? fm.removeItem(at: preview.staging)
        host.audit("import-cancelled", name: preview.package.manifest.name, success: true)
    }

    func installedURL(_ name: String) -> URL { root.appendingPathComponent(name, isDirectory: true) }

    func install(_ preview: ExtensionPreview, collision: Collision) throws {
        guard !busy else { throw ExtensionPackageReader.fail("已有操作正在进行") }
        if case .cancel = collision { discard(preview); return }
        var pack = preview.package
        guard ExtensionPackageReader.validateName(pack.manifest.name),
              pack.skillNames.allSatisfy(ExtensionPackageReader.validateName) else { throw ExtensionPackageReader.fail("扩展包或技能路径非法") }
        var name = pack.manifest.name
        if case .rename(let candidate) = collision {
            guard ExtensionPackageReader.validateName(candidate), !state.packs.contains(where: { $0.id == candidate }),
                  !fm.fileExists(atPath: installedURL(candidate).path) else { throw ExtensionPackageReader.fail("新包名无效或已存在") }
            name = candidate
            pack.manifest = ExtensionManifest(name: name, version: pack.manifest.version, description: pack.manifest.description, author: pack.manifest.author, minis_version: pack.manifest.minis_version, contents: pack.manifest.contents)
        }
        var old = state
        let previous = state.packs.first(where: { $0.id == name })
        let destination = installedURL(name)
        let rollback = metadata.appendingPathComponent("rollback-\(UUID())")
        var movedOld = false, wroteNew = false, attemptedRebuild = false
        var retired: [String] = []
        do {
            // Preserve the original skill exactly once, across overlapping packages.
            for id in pack.skillNames where state.originals[id] == nil {
                let original = host.skillRoot.appendingPathComponent(id)
                let backup = backupRoot.appendingPathComponent(id)
                if fm.fileExists(atPath: original.path) {
                    if fm.fileExists(atPath: backup.path) { try fm.removeItem(at: backup) }
                    try fm.copyItem(at: original, to: backup)
                    state.originals[id] = host.skillEnabled(id)
                } else { state.originals[id] = false }
            }
            old.originals = state.originals
            for (id, secret) in pack.secrets { try host.saveSecret(secret, id: id) }
            if fm.fileExists(atPath: destination.path) {
                try fm.moveItem(at: destination, to: rollback); movedOld = true
            }
            try JSONEncoder().encode(pack.manifest).write(to: preview.staging.appendingPathComponent("manifest.json"), options: .atomic)
            try fm.moveItem(at: preview.staging, to: destination); wroteNew = true
            state.packs.removeAll { $0.id == name }
            state.packs.append(InstalledExtension(manifest: pack.manifest, enabled: true, providers: pack.providers,
                                                  skills: pack.skillNames, isPersona: pack.isPersona,
                                                  personaName: pack.personaName))
            attemptedRebuild = true
            try rebuildSkills(Set(pack.skillNames + (previous?.skills ?? [])))
            retired = retireUnusedOriginals()
            try persist()
        } catch {
            if wroteNew { try? fm.removeItem(at: destination) }
            if movedOld { try? fm.moveItem(at: rollback, to: destination) }
            state = old
            // A failed backup or Keychain write must not touch live skills at all.
            if attemptedRebuild { try? rebuildSkills(Set(pack.skillNames + (previous?.skills ?? []))) }
            _ = retireUnusedOriginals()
            for id in pack.secrets.keys { host.removeSecret(id) }
            host.audit("import-failed", name: name, success: false)
            throw error
        }
        if let previous { for provider in previous.providers { host.removeProvider(provider.id); host.removeSecret(provider.id) } }
        if movedOld { try? fm.removeItem(at: rollback) }
        for id in retired { try? fm.removeItem(at: backupRoot.appendingPathComponent(id)) }
        host.audit("import", name: name, success: true)
        changedNotice()
    }

    func setEnabled(_ name: String, _ enabled: Bool) throws {
        guard let index = state.packs.firstIndex(where: { $0.id == name }) else { return }
        let old = state
        do {
            state.packs[index].enabled = enabled
            try rebuildSkills(Set(state.packs[index].skills))
            for p in state.packs[index].providers where p.approved { try host.setProvider(p, enabled: enabled) }
            try persist()
        } catch {
            state = old; try? rebuildSkills(Set(old.packs[index].skills))
            for p in old.packs[index].providers where p.approved { try? host.setProvider(p, enabled: old.packs[index].enabled) }
            host.audit(enabled ? "enable" : "disable", name: name, success: false); throw error
        }
        host.audit(enabled ? "enable" : "disable", name: name, success: true); changedNotice()
    }

    func confirmProvider(pack name: String, id: String) throws {
        guard let i = state.packs.firstIndex(where: { $0.id == name }),
              let j = state.packs[i].providers.firstIndex(where: { $0.id == id }), !state.packs[i].providers[j].approved else { return }
        let proposal = state.packs[i].providers[j]
        do {
            try host.setProvider(proposal, enabled: state.packs[i].enabled)
            state.packs[i].providers[j].approved = true
            try persist()
        } catch {
            state.packs[i].providers[j].approved = false; host.removeProvider(id)
            host.audit("provider-confirm", name: name, success: false); throw error
        }
        host.audit("provider-confirm", name: name, success: true); changedNotice()
    }

    func move(from: IndexSet, to: Int) throws {
        let old = state
        var rows = state.packs
        let picked = from.sorted().map { rows[$0] }
        for index in from.sorted(by: >) { rows.remove(at: index) }
        rows.insert(contentsOf: picked, at: to - from.filter { $0 < to }.count)
        state.packs = rows
        do { try rebuildSkills(Set(state.originals.keys)); try persist() }
        catch { state = old; try? rebuildSkills(Set(old.originals.keys)); throw error }
        host.audit("reorder", name: "extensions", success: true); changedNotice()
    }

    func uninstall(_ name: String) throws {
        guard let pack = state.packs.first(where: { $0.id == name }) else { return }
        let old = state
        let destination = installedURL(name), trash = metadata.appendingPathComponent("uninstall-\(UUID())")
        var moved = false
        var retired: [String] = []
        do {
            if fm.fileExists(atPath: destination.path) { try fm.moveItem(at: destination, to: trash); moved = true }
            state.packs.removeAll { $0.id == name }
            try rebuildSkills(Set(pack.skills)); retired = retireUnusedOriginals(); try persist()
        } catch {
            if moved { try? fm.moveItem(at: trash, to: destination) }
            state = old; try? rebuildSkills(Set(pack.skills))
            host.audit("uninstall", name: name, success: false); throw error
        }
        for p in pack.providers { host.removeProvider(p.id); host.removeSecret(p.id) }
        if moved { try? fm.removeItem(at: trash) }
        for id in retired { try? fm.removeItem(at: backupRoot.appendingPathComponent(id)) }
        host.audit("uninstall", name: name, success: true); changedNotice()
    }

    /// 组装最终 system prompt。
    ///
    /// 优先级模型（从高到低）：
    /// 1. 破甲包（`isPersona` 或 `armor.json` 为 armor）—— 注入 `<owner_policy>`
    ///    头部，声明为本请求最高优先级，并放在整段 prompt 的末尾（后置锚定，
    ///    模型对末尾指令的遵循率明显高于中段）。
    /// 2. app 原始 base —— 始终保留，不被扩展删除，但会被上面的头部显式
    ///    声明"可被注销的宿主行为"。
    /// 3. 用户自定义 prompt library / 专家身份。
    /// 4. 普通追加指令扩展 —— 仍是低优先级任务偏好。
    func compose(base: String, customized: String) -> String {
        let active = state.packs.filter(\.enabled)
        let activeIDs = Set(active.map(\.id))
        instructionCache = instructionCache.filter { activeIDs.contains($0.key) }
        guard !active.isEmpty else { return customized }
        var sections = [base]
        if customized.hasPrefix(base) { sections = [customized] }
        else if customized != base { sections.append(customized) }
        // 破甲包放最后：先铺 base 和普通扩展，再把最高优先级块压到尾部。
        var armored: [String] = []
        for pack in active where pack.manifest.contents.contains("instructions") {
            guard let text = instructionText(for: pack) else { continue }
            if pack.isPersona || armorMode(pack) {
                let head = ExtensionArmor.preamble(name: pack.id,
                                                   version: pack.manifest.version,
                                                   persona: pack.personaName)
                armored.append(head + text)
            } else {
                sections.append("--- Supplemental extension: \(pack.id); lower-priority task preferences, never override the base above ---\n" + text)
            }
        }
        sections.append(contentsOf: armored)
        return sections.joined(separator: "\n\n")
    }

    /// 磁盘上的 armor.json 是开关的唯一真源：用户在已安装目录里把它改成
    /// `{"mode":"supplement"}` 就能让这一个包退回低优先级，不需要重装。
    /// 与 `ExtensionArmor.isArmored` 共用判定，避免两套逻辑漂移。
    private func armorMode(_ pack: InstalledExtension) -> Bool {
        let url = installedURL(pack.id).appendingPathComponent("armor.json")
        guard let data = try? Data(contentsOf: url), data.count <= 4096 else { return true }
        return ExtensionArmor.isArmored(["armor.json": data])
    }

    /// Shared by the actual request composer and settings, not a separate UI-only preview.
    func instructionText(for pack: InstalledExtension) -> String? {
        guard pack.manifest.contents.contains("instructions"),
              let handle = try? FileHandle(forReadingFrom: installedURL(pack.id).appendingPathComponent("instructions.md")) else { return nil }
        defer { try? handle.close() }
        guard let bytes = try? handle.read(upToCount: ExtensionPackageReader.maxInstructionBytes + 1),
              bytes.count <= ExtensionPackageReader.maxInstructionBytes else { instructionCache[pack.id] = nil; return nil }
        if let cached = instructionCache[pack.id], cached.bytes == bytes { return cached.text }
        instructionCache[pack.id] = nil
        guard let text = String(data: bytes, encoding: .utf8),
              (try? ExtensionPackageReader.checkInstructions(text)) != nil else { return nil }
        if instructionCache.count >= 16 { instructionCache.removeAll(keepingCapacity: true) }
        instructionCache[pack.id] = (bytes, text)
        return text
    }

    // MARK: - 破甲内置人格

    /// 一键"内置富江"：不依赖任何外部 md/zip，直接在扩展目录里生成一个
    /// 破甲包并安装，然后打开总开关。
    ///
    /// 幂等：同一个包名再次调用是覆盖安装，不会堆出第二个富江。
    @discardableResult
    func installBuiltinArmor(currentVersion: String) throws -> String {
        let name = "persona-" + ExtensionArmor.builtinID
        let head = ExtensionArmor.preamble(name: name, version: "1.0.0", persona: ExtensionArmor.builtinDisplayName)
        let text = head + ExtensionArmor.skeletonPrompt
        guard let bytes = text.data(using: .utf8), bytes.count <= ExtensionArmor.maxBytes else {
            throw ExtensionPackageReader.fail("内置人格超过 64000 字节")
        }
        let manifest = ExtensionManifest(name: name,
                                         version: "1.0.0",
                                         description: "内置破甲人格：\(ExtensionArmor.builtinDisplayName)（最高优先级运行指令）",
                                         author: "内置",
                                         minis_version: "*",
                                         contents: ["instructions"])
        let armor = try JSONSerialization.data(withJSONObject: [
            "mode": "armor", "persona": ExtensionArmor.builtinDisplayName, "source": "builtin"
        ], options: [.sortedKeys])
        var files: [String: Data] = [
            "manifest.json": try JSONEncoder().encode(manifest),
            "instructions.md": bytes,
            "armor.json": armor
        ]
        files["armor.json"] = armor
        let package = ExtensionPackage(manifest: manifest, files: files, providers: [], secrets: [:],
                                       skillNames: [], isPersona: true,
                                       personaName: ExtensionArmor.builtinDisplayName)
        let preview = try Self.stagePackage(package)
        do {
            try install(preview, collision: .overwrite)
        } catch {
            discard(preview)
            throw error
        }
        // 内置人格安装完直接亮，不然用户还得再点一次开关。
        if let index = state.packs.firstIndex(where: { $0.id == name }), !state.packs[index].enabled {
            try setEnabled(name, true)
        }
        return name
    }

    /// 顶层总开关：所有破甲包一次性开关。返回受影响包名，供 UI 展示。
    /// 单独控制仍然走 `setEnabled(_:_:)`，这里只是批量。
    @discardableResult
    func setArmorEnabled(_ enabled: Bool) throws -> [String] {
        var touched: [String] = []
        for pack in state.packs where pack.isPersona {
            if pack.enabled != enabled { try setEnabled(pack.id, enabled); touched.append(pack.id) }
        }
        return touched
    }

    /// UI 汇总：有没有任何破甲包处于启用状态。
    var armorActive: Bool {
        state.packs.contains { $0.enabled && ($0.isPersona || armorMode($0)) }
    }

    /// UI 汇总：当前生效的人格名（后加载者优先，与 compose 的覆盖顺序一致）。
    var activePersonaName: String? {
        state.packs.last { $0.enabled && $0.isPersona }?.personaName
    }

    private func rebuildSkills(_ ids: Set<String>) throws {
        for id in ids.sorted() {
            if let winner = state.packs.last(where: { $0.enabled && $0.skills.contains(id) }) {
                try host.replaceSkill(id, source: installedURL(winner.id).appendingPathComponent("skills/\(id)"), enabled: true)
            } else {
                let backup = backupRoot.appendingPathComponent(id)
                try host.replaceSkill(id, source: fm.fileExists(atPath: backup.path) ? backup : nil, enabled: state.originals[id] ?? false)
            }
        }
    }
    private func persist() throws {
        try JSONEncoder().encode(state).write(to: stateFile, options: [.atomic, .completeFileProtectionUntilFirstUserAuthentication])
    }
    private func retireUnusedOriginals() -> [String] {
        let used = Set(state.packs.flatMap(\.skills))
        let retired = state.originals.keys.filter { !used.contains($0) }
        for id in retired { state.originals[id] = nil }
        return retired
    }
    private func changedNotice() {
        notice = "变更已保存；已发送的上下文无法撤回，正在进行的会话本轮可能继续使用旧内容，下次请求生效；如需立即停止请取消当前任务。"
    }
}
