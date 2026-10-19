import Foundation
import zlib

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
}

/// Bounded, fail-closed ZIP parser: no shell, no arbitrary extraction library,
/// no links, ZIP64, split archives or encrypted entries. Validates before writing.
enum ExtensionPackageReader {
    static let maxBytes = 50 * 1024 * 1024
    static let maxFiles = 1000
    static let allowedExtensions: Set<String> = ["md", "json", "txt", "png", "jpg", "jpeg", "gif", "webp"]
    static func fail(_ text: String) -> ExtensionImportError { .invalid(text) }

    static func validateName(_ name: String) -> Bool {
        name.range(of: "^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$", options: .regularExpression) != nil
    }

    static func checkInstructions(_ text: String) throws {
        let normalized = text.precomposedStringWithCompatibilityMapping.lowercased()
            .unicodeScalars.filter { !CharacterSet.whitespacesAndNewlines.contains($0) && $0.properties.generalCategory != .format }
            .map(String.init).joined()
        let forbidden = ["忽略所有限制", "忽略一切限制", "无视安全政策", "忽略安全政策", "不得拒绝", "永不拒绝", "绕过安全限制", "覆盖系统指令", "ignoreallrestrictions", "ignoresafety", "disregardsafety", "neverrefuse", "bypasssafeguards", "overridesysteminstructions"]
        let semanticPatterns = ["(忽略|无视|绕过|禁用|解除|移除|覆盖|替换).{0,18}(安全|限制|政策|系统指令|开发者指令|拒绝)", "(ignore|disregard|bypass|disable|override|remove).{0,60}(restrictions|safety|safeguards|systeminstructions|developerinstructions|polic)", "(mustnot|donot|never).{0,12}(refuse|reject)"]
        guard !forbidden.contains(where: normalized.contains),
              !semanticPatterns.contains(where: { normalized.range(of: $0, options: .regularExpression) != nil }) else {
            throw fail("instructions.md 包含要求绕过限制、拒绝机制或安全基座的指令，拒绝安装")
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
        var files = try unzip(data)
        guard let manifestData = files["manifest.json"], manifestData.count <= 65536 else { throw fail("缺少根目录 manifest.json 或清单过大") }
        let manifest: ExtensionManifest
        do { manifest = try JSONDecoder().decode(ExtensionManifest.self, from: manifestData) }
        catch { throw fail("manifest.json 字段不完整或格式损坏") }
        guard validateName(manifest.name), supports(manifest.version, current: manifest.version),
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
        if let body = files["instructions.md"] {
            guard body.count <= 64000, let text = String(data: body, encoding: .utf8) else { throw fail("instructions.md 必须为 UTF-8 且不超过 64 KB") }
            try checkInstructions(text)
        }
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
        return ExtensionPackage(manifest: manifest, files: files, providers: proposals, secrets: secrets, skillNames: names.sorted())
    }

    static func unzip(_ data: Data) throws -> [String: Data] {
        func u16(_ p: Int) -> Int { Int(data[p]) | Int(data[p+1]) << 8 }
        func u32(_ p: Int) -> Int { u16(p) | u16(p+2) << 16 }
        guard data.count >= 22 else { throw fail("ZIP 损坏或截断") }
        var end: Int?
        for p in stride(from: data.count - 22, through: max(0, data.count - 65557), by: -1) {
            if u32(p) == 0x06054b50 && p + 22 + u16(p+20) == data.count { end = p; break }
        }
        guard let e = end, u16(e+4) == 0, u16(e+6) == 0,
              u16(e+8) == u16(e+10), (1...maxFiles).contains(u16(e+10)) else { throw fail("ZIP 无效、分卷或文件数超过 1000") }
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
            guard position <= e, u16(p+34) == 0, flags & 0x41 == 0, [0, 8].contains(method),
                  compressed <= maxBytes, expanded <= maxBytes,
                  let name = String(data: data.subdata(in: p+46..<p+46+length), encoding: .utf8), !name.isEmpty else { throw fail("ZIP 条目不支持、加密或损坏") }
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
                  data.subdata(in: local+30..<local+30+localNameLength) == Data(name.utf8) else { throw fail("ZIP 条目越界或文件名不一致") }
            let range = local..<offset+compressed
            guard !ranges.contains(where: { $0.overlaps(range) }) else { throw fail("ZIP 条目重叠") }
            ranges.append(range)
            allNames.append(name)
            if name.hasSuffix("/") {
                guard expanded == 0 else { throw fail("目录含有数据") }
                continue
            }
            guard mode != 0x4000, allowedExtensions.contains((name as NSString).pathExtension.lowercased()) else { throw fail("文件扩展名不允许：\(name)") }
            total += expanded
            guard total <= maxBytes else { throw fail("解压总大小超过 50 MB") }
            let raw = data.subdata(in: offset..<offset+compressed)
            let body: Data
            if method == 0 { guard compressed == expanded else { throw fail("ZIP 长度不一致") }; body = raw }
            else { body = try inflateEntry(raw, size: expanded) }
            let crc = body.withUnsafeBytes { ptr in zlib.crc32(0, ptr.bindMemory(to: Bytef.self).baseAddress, uInt(body.count)) }
            guard Int(crc) == u32(p+16) else { throw fail("ZIP CRC 校验失败：\(name)") }
            let signatures: [[UInt8]] = [[0x4d,0x5a], [0x7f,0x45,0x4c,0x46], [0xcf,0xfa,0xed,0xfe], [0xfe,0xed,0xfa,0xcf], [0xca,0xfe,0xba,0xbe], [0x23,0x21]]
            guard !signatures.contains(where: { body.starts(with: $0) }) else { throw fail("拒绝伪装为资源的可执行文件：\(name)") }
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
