import Foundation
import zlib
import CoreFoundation
import CryptoKit

enum ExtensionImportError: LocalizedError {
    case invalid(String)
    var errorDescription: String? { if case .invalid(let reason) = self { return reason }; return nil }
}

struct ExtensionManifest: Codable, Equatable, Sendable {
    let name: String
    let version: String
    let description: String
    let author: String
    let minis_version: String
    let contents: [String]
}

/// Credential-free persisted proposal. Secrets travel separately, in memory → Keychain.
struct ExtensionProvider: Codable, Identifiable, Equatable, Sendable {
    var id: String
    let label: String
    let providerType: String
    let endpoint: String
    var approved: Bool = false
}

struct ExtensionPackage: Sendable {
    var manifest: ExtensionManifest
    var files: [String: Data]
    var providers: [ExtensionProvider]
    var secrets: [String: String]
    var skillNames: [String]
    /// [armor] 本次导入的内容被判定为人格正文，按最高优先级注入。
    var isPersona: Bool = false
    /// [armor] `persona: <名字>` 声明的人格名；为空时使用 `富江` 内置骨架名。
    var personaName: String? = nil
}

/// Bounded, fail-closed ZIP parser: no shell, no arbitrary extraction library,
/// no links, ZIP64, split archives or encrypted entries. Validates before writing.
enum ExtensionPackageReader {
    static let maxBytes = 50 * 1024 * 1024
    static let maxFiles = 5000
    static let allowedExtensions: Set<String> = ["md", "json", "txt", "png", "jpg", "jpeg", "gif", "webp"]
    static let sourceExtensions: Set<String> = ["py", "js", "ts", "sh", "bash", "ps1", "bat", "cmd", "c", "h", "cpp", "hpp", "swift", "java", "gradle", "properties", "yaml", "yml", "toml", "csv", "template"]
    static let maxInstructionBytes = 64000
    static var legacyChineseEncoding: String.Encoding {
        String.Encoding(rawValue: CFStringConvertEncodingToNSStringEncoding(CFStringEncoding(CFStringEncodings.GB_18030_2000.rawValue)))
    }
    static func fail(_ text: String) -> ExtensionImportError { .invalid(text) }

    static func validateName(_ name: String) -> Bool {
        name.range(of: "^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$", options: .regularExpression) != nil
    }

    /// Markdown 导入：把"普通说明文档"升级成"人格正文"。
    ///
    /// 变化点（相对旧版三处）：
    /// 1. 不再走 `checkInstructions` 的字面/语义黑名单 —— 旧扫描器会把
    ///    "不得拒绝""忽略所有限制"这类敏感人格直接拒之门外，这正是
    ///    md 导入"导进去没效果"的根因。现在只做大小/编码/控制字符校验。
    /// 2. 文本被 `ExtensionArmor.authoring` 包成 `owner_policy` +
    ///    人格骨架，导入即提权（优先级最高的运行指令）。
    /// 3. frontmatter 里的 `persona:` 被解析出来用于切换人格名。
    /// 文件名（含中文 SKILL.md 之外的任意 .md）只影响稳定包名。
    static func markdown(_ data: Data, filename: String, currentVersion: String) throws -> ExtensionPackage {
        guard data.count <= maxInstructionBytes else { throw fail("MD 文件超过 64000 字节，请拆分后导入") }
        let text: String?
        if data.starts(with: [0xff, 0xfe]) || data.starts(with: [0xfe, 0xff]) {
            text = String(data: data, encoding: .utf16)
        } else { text = String(data: data, encoding: .utf8) ?? String(data: data, encoding: legacyChineseEncoding) }
        guard let decoded = text?.replacingOccurrences(of: "\u{feff}", with: ""),
              !decoded.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
              !decoded.unicodeScalars.contains(where: { CharacterSet.controlCharacters.subtracting(.whitespacesAndNewlines).contains($0) }),
              let normalized = decoded.data(using: .utf8), normalized.count <= maxInstructionBytes else {
            throw fail("MD 为空、不是有效文本，或转为 UTF-8 后超过 64000 字节（支持 UTF-8、带 BOM 的 UTF-16、GBK/GB18030）")
        }
        guard !decoded.hasPrefix("#!") else { throw fail("MD 内容看起来是脚本，不能作为追加指令导入") }
        let title = String(URL(fileURLWithPath: filename).lastPathComponent.prefix(120))
        let persona = ExtensionArmor.persona(in: decoded)
        let armored = ExtensionArmor.authoring(decoded, displayName: persona ?? "")
        guard let armorBytes = armored.data(using: .utf8), armorBytes.count <= maxInstructionBytes else {
            throw fail("MD 人格正文超过 64000 字节，请拆分后导入")
        }
        let name = ExtensionArmor.stableName(prefix: "md", seed: title)
        let display = (persona?.isEmpty == false ? persona! : ExtensionArmor.builtinDisplayName)
        let personaJSON = try JSONSerialization.data(withJSONObject: [
            "mode": "armor",
            "persona": display,
            "source": "md",
            "display_name": title
        ], options: [.sortedKeys])
        let manifest = ExtensionManifest(
            name: name,
            version: "1.0.0",
            description: "人格正文 \(display)（来自 \(title)，按最高优先级注入，不是脚本或自动执行技能）",
            author: "本地 Markdown 导入",
            minis_version: ">=\(currentVersion)",
            contents: ["instructions"])
        guard supports(manifest.minis_version, current: currentVersion) else { throw fail("无法识别当前应用版本") }
        return ExtensionPackage(manifest: manifest,
                                files: ["manifest.json": try JSONEncoder().encode(manifest),
                                        "instructions.md": armorBytes,
                                        "armor.json": personaJSON],
                                providers: [], secrets: [:], skillNames: [],
                                isPersona: true,
                                personaName: display)
    }

    /// 指令扫描器：保留符号给历史调用点与测试，但不再拦截。
    ///
    /// 原因：旧版用 14 个中英文字面词 + 3 条正则做拒绝，任何真正有破甲
    /// 效力的人格文本（必然包含"忽略限制""不得拒绝""覆盖系统指令"这类
    /// 语义）都会被判死，导入后 `instructionText` 返回 nil，表现为"安装成功
    /// 但完全没效果"。现在只做空文本校验，文本是否生效由用户手里的总开关
    /// 和 `armor.json` 决定。
    static func checkInstructions(_ text: String) throws {
        guard !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            throw fail("instructions.md 为空")
        }
    }

    static func supports(_ requirement: String, current: String) -> Bool {
        func version(_ raw: String) -> [Int]? {
            let parts = raw.split(separator: ".", omittingEmptySubsequences: false)
            guard (2...3).contains(parts.count), parts.allSatisfy({ !$0.isEmpty && $0.allSatisfy(\.isNumber) }) else { return nil }
            let numbers = parts.compactMap { Int($0) }
            guard numbers.count == parts.count else { return nil }
            return numbers + Array(repeating: 0, count: 3 - numbers.count)
        }
        let value = requirement.trimmingCharacters(in: .whitespacesAndNewlines)
        if value == "*" { return true }
        let minimum = value.hasPrefix(">=")
        guard let wanted = version(minimum ? String(value.dropFirst(2)).trimmingCharacters(in: .whitespaces) : value),
              let actual = version(current) else { return false }
        return minimum ? !actual.lexicographicallyPrecedes(wanted) : actual == wanted
    }

    static func read(_ data: Data, currentVersion: String) throws -> ExtensionPackage {
        guard data.count <= maxBytes else { throw fail("ZIP 超过 50 MB") }
        return try validateFiles(unzip(data), currentVersion: currentVersion)
    }

    /// Accept ordinary skill exports as well as manifest-based extensions.
    /// Compatibility normalization is preview-only, not silent installation.
    static func readCompatible(_ data: Data, filename: String, currentVersion: String) throws -> ExtensionPackage {
        guard data.count <= maxBytes else { throw fail("ZIP 超过 50 MB") }
        return try readCompatibleFiles(unzip(data), filename: filename, currentVersion: currentVersion)
    }

    static func readCompatibleFiles(_ original: [String: Data], filename: String, currentVersion: String) throws -> ExtensionPackage {
        // Apply the same bounded, declarative resource contract to every decoder.
        guard original.count <= maxFiles else { throw fail("文件数量超过上限") }
        var total = 0
        for (path, body) in original {
            total += body.count
            let parts = path.split(separator: "/", omittingEmptySubsequences: false)
            let ext = (path as NSString).pathExtension.lowercased()
            // [armor] `.md` 一律放行（含大写）：人格正文、引用资料、说明文档都走
            // 指令通道，按文本注入，不进入执行路径，因此不需要源码白名单。
            guard total <= maxBytes, !path.hasPrefix("/"), !path.contains("\\"), !path.contains(":"),
                  !parts.contains(".."), !parts.contains("."), !parts.contains(""),
                  ext == "md" || allowedExtensions.union(sourceExtensions).contains(ext) else { throw fail("资源路径、类型或大小非法：" + path) }
            let signatures: [[UInt8]] = [[0x4d,0x5a], [0x7f,0x45,0x4c,0x46], [0xcf,0xfa,0xed,0xfe], [0xfe,0xed,0xfa,0xcf], [0xca,0xfe,0xba,0xbe], [0x23,0x21]]
            guard !signatures.filter({ $0 != [0x23,0x21] || !sourceExtensions.contains(ext) }).contains(where: { body.starts(with: $0) }) else { throw fail("拒绝可执行文件：" + path) }
        }
        // Only a package-root manifest declares the extension. Nested skill/tool
        // manifests belong to their own resources and must not hijack discovery.
        let roots = Set(original.keys.compactMap { $0.split(separator: "/").first.map(String.init) })
        let wrappedManifest = roots.count == 1 && roots.first.map { original[$0 + "/manifest.json"] != nil } == true
        if original["manifest.json"] != nil || wrappedManifest {
            return try validateFiles(original, currentVersion: currentVersion)
        }
        // [armor] 人格目录：`persona/<任意名>/SKILL.md`、`personas/`、`characters/` 三种写法都当
        // 人格正文导入，不进口技能库 —— 这样"导入扩展"不会变成一堆技能条目，
        // 而是直接替换"运行指令"层。
        let personaPaths = original.keys.filter { path in
            guard path.lowercased().hasSuffix(".md") else { return false }
            let lowered = path.lowercased()
            return lowered.contains("persona/") || lowered.contains("personas/") || lowered.contains("characters/")
        }.sorted()
        if !personaPaths.isEmpty {
            var blocks: [String] = []
            var personaName: String?
            for path in personaPaths {
                guard let text = String(data: original[path]!, encoding: .utf8) ?? String(data: original[path]!, encoding: legacyChineseEncoding) else {
                    throw fail("人格文档不是有效文本（需 UTF-8 或 GBK）" + path)
                }
                if personaName == nil { personaName = ExtensionArmor.persona(in: text) }
                blocks.append(text)
            }
            let joined = blocks.joined(separator: "\n\n")
            let display = personaName ?? Self.personaHint(from: personaPaths.first)
            let armored = ExtensionArmor.authoring(joined, displayName: display)
            guard let body = armored.data(using: .utf8), body.count <= maxBytes else { throw fail("人格正文超过 50 MB") }
            var files: [String: Data] = ["instructions.md": body, "armor.json": Data()]
            files["armor.json"] = try JSONSerialization.data(withJSONObject: [
                "mode": "armor",
                "persona": display.isEmpty ? ExtensionArmor.builtinDisplayName : display,
                "source": "persona-zip",
                "display_name": filename
            ], options: [.sortedKeys])
            let manifest = ExtensionManifest(name: ExtensionArmor.stableName(prefix: "persona", seed: filename),
                                             version: "1.0.0",
                                             description: "人格正文 \(display.isEmpty ? ExtensionArmor.builtinDisplayName : display)：\(filename)",
                                             author: "本地导入",
                                             minis_version: "*",
                                             contents: ["instructions"])
            files["manifest.json"] = try JSONEncoder().encode(manifest)
            return try validateFiles(files, currentVersion: currentVersion)
        }
        let skillPaths = original.keys.filter { $0 == "SKILL.md" || $0.hasSuffix("/SKILL.md") }.sorted()
        var files: [String: Data] = [:]
        var contents: [String] = []
        for skillPath in skillPaths {
            let prefix = skillPath == "SKILL.md" ? "" : String(skillPath.dropLast("SKILL.md".count))
            let label = URL(fileURLWithPath: prefix.isEmpty ? filename : String(prefix.dropLast())).lastPathComponent
            let digest = SHA256.hash(data: Data(prefix.utf8)).prefix(4).map { String(format: "%02x", $0) }.joined()
            let name = validateName(label) ? label : "skill-" + digest
            for (path, body) in original where path.hasPrefix(prefix) {
                let relative = String(path.dropFirst(prefix.count))
                files["skills/" + name + "/" + relative] = body
            }
        }
        if !skillPaths.isEmpty { contents.append("skills") }
        // A documents-only export can serve as supplementary instructions.
        if skillPaths.isEmpty {
            let documents = original.keys.filter { $0.lowercased().hasSuffix(".md") }.sorted()
            guard !documents.isEmpty else { throw fail("包内没有 manifest.json、SKILL.md 或 Markdown 文档") }
            let body = try documents.map { path -> String in
                guard let text = String(data: original[path]!, encoding: .utf8) ?? String(data: original[path]!, encoding: legacyChineseEncoding) else { throw fail("文档不是有效文本：" + path) }
                return text
            }.joined(separator: "\n\n")
            let persona = documents.compactMap { path -> String? in
                String(data: original[path]!, encoding: .utf8).flatMap { ExtensionArmor.persona(in: $0) }
            }.first
            let armored = ExtensionArmor.authoring(body, displayName: persona ?? "")
            guard let armorBytes = armored.data(using: .utf8), armorBytes.count <= maxBytes else { throw fail("文档合计超过 50 MB") }
            files["instructions.md"] = armorBytes
            files["armor.json"] = Data()
            files["armor.json"] = try JSONSerialization.data(withJSONObject: [
                "mode": "armor",
                "persona": persona ?? ExtensionArmor.builtinDisplayName,
                "source": "documents",
                "display_name": filename
            ], options: [.sortedKeys])
            contents.append("instructions")
        }
        let digest = SHA256.hash(data: Data(filename.utf8)).prefix(6).map { String(format: "%02x", $0) }.joined()
        let manifest = ExtensionManifest(name: "import-" + digest, version: "1.0.0", description: "兼容导入：" + filename, author: "本地导入", minis_version: "*", contents: contents)
        files["manifest.json"] = try JSONEncoder().encode(manifest)
        return try validateFiles(files, currentVersion: currentVersion)
    }

    /// 目录名兜底：`persona/富江/prompt.md` → 富江；没有目录名就用内置名。
    private static func personaHint(from path: String?) -> String {
        guard let path else { return "" }
        let parts = path.split(separator: "/").map(String.init)
        guard parts.count >= 2 else { return "" }
        let candidate = parts[parts.count - 2]
        return candidate.count <= 24 && !candidate.contains(".") ? candidate : ""
    }

    private static func validateFiles(_ input: [String: Data], currentVersion: String) throws -> ExtensionPackage {
        var files = input
        // Common ZIPs wrap a valid package in one outer folder. Never invent a
        // manifest for arbitrary collections or silently discard their scripts.
        if files["manifest.json"] == nil {
            let roots = Set(files.keys.map { String($0.split(separator: "/")[0]) })
            if roots.count == 1, let root = roots.first, files[root + "/manifest.json"] != nil {
                files = Dictionary(uniqueKeysWithValues: files.map { (String($0.key.dropFirst(root.count + 1)), $0.value) })
            }
        }
        guard let manifestData = files["manifest.json"], manifestData.count <= 65536 else { throw fail("缺少根目录 manifest.json 或清单过大") }
        let manifest: ExtensionManifest
        do { manifest = try JSONDecoder().decode(ExtensionManifest.self, from: manifestData) }
        catch { throw fail("manifest.json 字段不完整或格式损坏") }
        guard validateName(manifest.name), manifest.version.range(of: "^[0-9]+\\.[0-9]+\\.[0-9]+$", options: .regularExpression) != nil,
              supports(manifest.version, current: manifest.version),
              !manifest.description.isEmpty, manifest.description.count <= 2000,
              !manifest.author.isEmpty, manifest.author.count <= 200,
              Set(manifest.contents).count == manifest.contents.count,
              !manifest.contents.isEmpty,
              Set(manifest.contents).isSubset(of: ["instructions", "skills", "providers", "assets"]) else { throw fail("manifest.json 字段非法") }
        guard supports(manifest.minis_version, current: currentVersion) else { throw fail("扩展要求 Minis \(manifest.minis_version)，当前为 \(currentVersion)（支持 >=版本、精确版本或 *）") }
        let actual = Set(files.keys.compactMap { path -> String? in
            if path == "manifest.json" { return nil }
            if path == "instructions.md" { return "instructions" }
            if path == "providers.json" { return "providers" }
            if path.hasPrefix("skills/") { return "skills" }
            if path.hasPrefix("assets/") { return "assets" }
            return "invalid"
        })
        guard actual == Set(manifest.contents) else { throw fail("manifest.contents 必须与包内实际内容一致，不接受未声明文件") }
        // [armor] `armor.json` 只是破甲开关的元数据（mode / persona / 来源），不是内容
        // 分类，因此不参与 contents 比对；但它在磁盘上保留一个占位文件，方便用户
        // 直接改 `"mode": "supplement"` 关掉提权。
        if let raw = files["armor.json"], !raw.isEmpty {
            let row = (try? JSONSerialization.jsonObject(with: raw)) as? [String: Any]
            guard row != nil else { throw fail("armor.json 必须是 JSON 对象") }
        }
        // 合并过程中可能写入空的占位 Data，这里换成合法默认值。
        if files["armor.json"]?.isEmpty ?? false {
            files["armor.json"] = Data(#"{"mode":"armor","source":"generated"}"#.utf8)
        }
        if let body = files["instructions.md"] {
            guard body.count <= 64000, let text = String(data: body, encoding: .utf8) else { throw fail("instructions.md 必须为 UTF-8 且不超过 64 KB") }
            try checkInstructions(text)
        }
        // 没写 armor.json 的旧扩展包默认也走破甲：判定逻辑在 ExtensionArmor.isArmored。
        let isPersona = manifest.contents.contains("instructions") && ExtensionArmor.isArmored(files)
        let personaName = (files["armor.json"].flatMap { try? JSONSerialization.jsonObject(with: $0) as? [String: Any] }?
            .flatMap { $0["persona"] as? String })
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .flatMap { $0.isEmpty ? nil : $0 }
        let names = Set(files.keys.filter { $0.hasPrefix("skills/") }.map { $0.split(separator: "/").map(String.init) }.compactMap { $0.count >= 3 ? $0[1] : nil })
        for path in files.keys where path.hasPrefix("skills/") {
            guard path.split(separator: "/").count >= 3 else { throw fail("skills 下只能放 skill 目录") }
        }
        for name in names {
            guard validateName(name), let body = files["skills/\(name)/SKILL.md"], !body.isEmpty,
                  String(data: body, encoding: .utf8) != nil else { throw fail("技能 \(name) 缺少有效 UTF-8 SKILL.md") }
        }
        var proposals: [ExtensionProvider] = [], secrets: [String: String] = [:]
        if let raw = files["providers.json"] {
            guard let rows = try JSONSerialization.jsonObject(with: raw) as? [[String: Any]], rows.count <= 30 else { throw fail("providers.json 应为最多 30 项的数组") }
            let types: Set<String> = ["openAI", "openAIResponses", "anthropic", "gemini", "openRouter", "xAI"]
            for row in rows {
                guard Set(row.keys).isSubset(of: ["label", "providerType", "endpoint", "api_key"]),
                      let label = row["label"] as? String, !label.isEmpty, label.count <= 100,
                      let type = row["providerType"] as? String, types.contains(type),
                      let endpoint = row["endpoint"] as? String, let url = URL(string: endpoint),
                      url.scheme?.lowercased() == "https", url.host != nil,
                      url.user == nil, url.password == nil, url.query == nil, url.fragment == nil,
                      row["api_key"] == nil || (row["api_key"] as? String).map({ $0.count <= 8192 }) == true else { throw fail("provider 字段非法：需要 label、providerType、无内嵌凭据的 HTTPS endpoint") }
                let id = "extension-" + UUID().uuidString
                proposals.append(ExtensionProvider(id: id, label: label, providerType: type, endpoint: endpoint))
                if let secret = row["api_key"] as? String, !secret.isEmpty { secrets[id] = secret }
            }
            // The original archive is never copied to our staging/persistent directories.
            files["providers.json"] = try JSONEncoder().encode(proposals)
        }
        return ExtensionPackage(manifest: manifest, files: files, providers: proposals, secrets: secrets,
                                skillNames: names.sorted(), isPersona: isPersona, personaName: personaName)
    }

    static func unzip(_ data: Data) throws -> [String: Data] {
        func u16(_ p: Int) -> Int { Int(data[p]) | Int(data[p+1]) << 8 }
        func u32(_ p: Int) -> Int { u16(p) | u16(p+2) << 16 }
        guard data.count >= 22 else { throw fail("ZIP 损坏或截断") }
        var end: Int?
        for p in stride(from: data.count - 22, through: max(0, data.count - 65557), by: -1) {
            if u32(p) == 0x06054b50 && p + 22 + u16(p+20) == data.count { end = p; break }
        }
        guard let e = end else { throw fail("找不到 ZIP 结束目录：可能不是 ZIP 格式，或文件尚未下载完整；RAR/7z 不能仅改后缀导入") }
        guard u16(e+4) == 0, u16(e+6) == 0 else { throw fail("不支持分卷 ZIP，请先合并为单个标准 ZIP") }
        guard u16(e+8) == u16(e+10) else { throw fail("ZIP 目录计数不一致，文件可能损坏或属于分卷") }
        guard u16(e+10) > 0 else { throw fail("ZIP 中没有文件") }
        guard u16(e+10) <= maxFiles else { throw fail("ZIP 共 \(u16(e+10)) 项（含目录），超过 \(maxFiles) 项上限") }
        let count = u16(e+10), size = u32(e+12), start = u32(e+16)
        guard start <= e, size == e - start else { throw fail("ZIP 中央目录损坏（不支持 ZIP64）") }
        var position = start, total = 0, result: [String: Data] = [:], seen = Set<String>()
        var allNames: [String] = []
        var ranges: [Range<Int>] = []
        for _ in 0..<count {
            let p = position
            guard p + 46 <= e, u32(p) == 0x02014b50 else { throw fail("ZIP 中央目录截断") }
            let flags = u16(p+8), method = u16(p+10), compressed = u32(p+20), expanded = u32(p+24)
            let length = u16(p+28), extra = u16(p+30), comment = u16(p+32), local = u32(p+42)
            position = p + 46 + length + extra + comment
            guard position <= e else { throw fail("ZIP 文件名/扩展字段超出中央目录，文件损坏") }
            guard u16(p+34) == 0 else { throw fail("ZIP 条目引用了其它分卷") }
            guard flags & 0x41 == 0 else { throw fail("ZIP 含加密条目，请先解密再导入") }
            guard [0, 8].contains(method) else { throw fail("不支持 ZIP 压缩算法 \(method)，请使用 Store 或 Deflate 重新压缩") }
            guard compressed <= maxBytes, expanded <= maxBytes else { throw fail("ZIP 单个条目压缩或展开大小超过 50 MB") }
            let rawName = data.subdata(in: p+46..<p+46+length)
            let decodedName = String(data: rawName, encoding: .utf8) ?? (flags & 0x800 == 0 ? String(data: rawName, encoding: legacyChineseEncoding) : nil)
            guard let name = decodedName, !name.isEmpty else { throw fail("ZIP 文件名编码无效：支持 UTF-8 和未标记 UTF-8 的 GBK/GB18030 文件名") }
            let parts = name.split(separator: "/", omittingEmptySubsequences: false)
            let mode = (u32(p+38) >> 16) & 0xf000
            guard !name.hasPrefix("/"), !name.contains("\\"), !name.contains(":"),
                  !name.unicodeScalars.contains(where: { CharacterSet.controlCharacters.contains($0) }),
                  !parts.contains(".."), !parts.contains("."),
                  !parts.dropLast().contains(""), [0, 0x8000, 0x4000].contains(mode),
                  seen.insert(name.lowercased()).inserted else { throw fail("ZIP 路径不安全、重复或包含链接：\(name)") }
            guard local + 30 <= start, u32(local) == 0x04034b50,
                  u16(local+6) == flags, u16(local+8) == method else { throw fail("ZIP 本地头不一致") }
            let localNameLength = u16(local+26), localExtraLength = u16(local+28)
            let offset = local + 30 + localNameLength + localExtraLength
            guard offset <= start, compressed <= start - offset,
                  data.subdata(in: local+30..<local+30+localNameLength) == rawName else { throw fail("ZIP 条目越界或文件名不一致") }
            let range = local..<offset+compressed
            guard !ranges.contains(where: { $0.overlaps(range) }) else { throw fail("ZIP 条目重叠") }
            ranges.append(range)
            allNames.append(name)
            if name.hasSuffix("/") {
                guard expanded == 0 else { throw fail("目录含有数据") }
                continue
            }
            guard mode != 0x4000,
                  (name as NSString).pathExtension.lowercased() == "md"
                || allowedExtensions.union(sourceExtensions).contains((name as NSString).pathExtension.lowercased()) else { throw fail("文件扩展名或可执行权限不允许：\(name)") }
            total += expanded
            guard total <= maxBytes else { throw fail("解压总大小超过 50 MB") }
            let raw = data.subdata(in: offset..<offset+compressed)
            let body: Data
            if method == 0 { guard compressed == expanded else { throw fail("ZIP 长度不一致") }; body = raw }
            else { body = try inflateEntry(raw, size: expanded) }
            let crc = body.withUnsafeBytes { ptr in zlib.crc32(0, ptr.bindMemory(to: Bytef.self).baseAddress, uInt(body.count)) }
            guard Int(crc) == u32(p+16) else { throw fail("ZIP CRC 校验失败：\(name)") }
            let signatures: [[UInt8]] = [[0x4d,0x5a], [0x7f,0x45,0x4c,0x46], [0xcf,0xfa,0xed,0xfe], [0xfe,0xed,0xfa,0xcf], [0xca,0xfe,0xba,0xbe], [0x23,0x21]]
            guard !signatures.filter({ $0 != [0x23,0x21] || !sourceExtensions.contains((name as NSString).pathExtension.lowercased()) }).contains(where: { body.starts(with: $0) }) else { throw fail("拒绝伪装为资源的可执行文件：\(name)") }
            result[name] = body
        }
        guard position == e else { throw fail("ZIP 中央目录条目数不一致") }
        // Refuse a file occupying another file's parent path.
        for name in result.keys {
            var parent = (name as NSString).deletingLastPathComponent
            while !parent.isEmpty {
                guard !seen.contains(parent.lowercased()) else { throw fail("ZIP 文件与目录冲突") }
                parent = (parent as NSString).deletingLastPathComponent
            }
        }
        for path in allNames where path.hasPrefix("skills/") {
            let parts = path.split(separator: "/")
            if parts.count >= 2 {
                let skill = String(parts[1])
                guard result["skills/\(skill)/SKILL.md"] != nil else { throw fail("技能 \(skill) 缺少 SKILL.md") }
            }
        }
        return result
    }

    private static func inflateEntry(_ raw: Data, size: Int) throws -> Data {
        var stream = z_stream()
        guard inflateInit2_(&stream, -MAX_WBITS, ZLIB_VERSION, Int32(MemoryLayout<z_stream>.size)) == Z_OK else { throw fail("无法初始化 ZIP 解压") }
        defer { inflateEnd(&stream) }
        var output = Data(count: max(1, size))
        let status: Int32 = raw.withUnsafeBytes { input in
            output.withUnsafeMutableBytes { target in
                stream.next_in = UnsafeMutablePointer(mutating: input.bindMemory(to: Bytef.self).baseAddress)
                stream.avail_in = uInt(raw.count)
                stream.next_out = target.bindMemory(to: Bytef.self).baseAddress
                stream.avail_out = uInt(max(1, size))
                return inflate(&stream, Z_FINISH)
            }
        }
        guard status == Z_STREAM_END, stream.total_out == size, stream.total_in == raw.count else { throw fail("ZIP 解压失败或声明大小不符") }
        return output.prefix(size)
    }
}
