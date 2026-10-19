import Foundation

final class ExtensionHTTPFixture: URLProtocol {
    static var mode = "valid"
    static var body = Data()
    static var gets = 0
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        let head = request.httpMethod == "HEAD"
        if !head { Self.gets += 1 }
        var length = Self.body.count
        if Self.mode == "head-large" && head { length = ExtensionPackageReader.maxBytes + 1 }
        if Self.mode == "get-large" && !head { length = ExtensionPackageReader.maxBytes + 1 }
        var headers = ["Content-Length": String(length)]
        if Self.mode == "unknown" { headers = [:] }
        let response = HTTPURLResponse(url: request.url!, statusCode: 200, httpVersion: "HTTP/1.1", headerFields: headers)!
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        if !head { client?.urlProtocol(self, didLoad: Self.mode == "truncated" ? Data(Self.body.dropLast()) : Self.body) }
        client?.urlProtocolDidFinishLoading(self)
    }
    override func stopLoading() {}
}

@MainActor final class FixtureHost: ExtensionHost {
    let skillRoot: URL
    var secrets: [String: String] = [:]
    var providers: [String: Bool] = [:]
    var auditEvents: [String] = []
    var failSecret = false
    var enabled: [String: Bool] = [:]
    init(_ root: URL) throws { skillRoot = root; try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true) }
    func skillEnabled(_ id: String) -> Bool { enabled[id] ?? true }
    func replaceSkill(_ id: String, source: URL?, enabled: Bool) throws {
        let target = skillRoot.appendingPathComponent(id)
        if FileManager.default.fileExists(atPath: target.path) { try FileManager.default.removeItem(at: target) }
        if let source { try FileManager.default.copyItem(at: source, to: target) }
        self.enabled[id] = enabled
    }
    func saveSecret(_ secret: String, id: String) throws {
        if failSecret { throw ExtensionPackageReader.fail("Simulated Keychain unavailable") }
        secrets[id] = secret
    }
    func removeSecret(_ id: String) { secrets[id] = nil }
    func setProvider(_ proposal: ExtensionProvider, enabled: Bool) throws { providers[proposal.id] = enabled }
    func removeProvider(_ id: String) { providers[id] = nil }
    func audit(_ action: String, name: String, success: Bool) { auditEvents.append(action + (success ? ":ok" : ":failed")) }
}

@main struct ExtensionImporterTests {
    struct Case: Decodable { let file: String; let valid: Bool }
    @MainActor static func main() async throws {
        let root = URL(fileURLWithPath: CommandLine.arguments[1])
        var checks = 0
        func check(_ condition: @autoclosure () -> Bool, _ text: String) {
            precondition(condition(), text); checks += 1
        }
        let cases = try JSONDecoder().decode([Case].self, from: Data(contentsOf: root.appendingPathComponent("cases.json")))
        for test in cases {
            do {
                _ = try ExtensionPackageReader.read(Data(contentsOf: root.appendingPathComponent(test.file)), currentVersion: "1.0")
                check(test.valid, "Must reject " + test.file)
            } catch { check(!test.valid, "Unexpected rejection \(test.file): \(error)") }
        }
        let host = try FixtureHost(root.appendingPathComponent("work/skills"))
        let original = host.skillRoot.appendingPathComponent("example")
        try FileManager.default.createDirectory(at: original, withIntermediateDirectories: true)
        try "Original skill".write(to: original.appendingPathComponent("SKILL.md"), atomically: true, encoding: .utf8)
        host.enabled["example"] = false
        let store = ExtensionStore(root: root.appendingPathComponent("work/.minis/extensions"), host: host)
        let zip = root.appendingPathComponent("valid.zip")
        let preview = try await store.prepare(url: zip, currentVersion: "1.0")
        check(store.state.packs.isEmpty && host.providers.isEmpty && host.secrets.isEmpty, "Preview must not activate anything")
        let sanitized = try String(contentsOf: preview.staging.appendingPathComponent("providers.json"), encoding: .utf8)
        check(!sanitized.contains("fixture-secret") && !sanitized.contains("api_key"), "No plaintext keys in staging")
        try store.install(preview, collision: .overwrite)
        check(store.state.packs.count == 1 && host.providers.isEmpty, "Providers must remain pending")
        check(host.secrets.count == 1, "Secrets go to credential store at install")
        let provider = store.state.packs[0].providers[0]
        check(!provider.approved, "Pending flag")
        try store.confirmProvider(pack: "demo", id: provider.id)
        check(host.providers[provider.id] == true && store.state.packs[0].providers[0].approved, "Explicit provider confirmation")
        try store.confirmProvider(pack: "demo", id: provider.id)
        check(host.providers.count == 1, "Confirm idempotent")
        check(store.compose(base: "BASE", customized: "CUSTOM").hasPrefix("BASE\n"), "Base cannot be replaced")
        check(store.compose(base: "BASE", customized: "BASE\nCUSTOM").components(separatedBy: "BASE").count == 2, "Base not duplicated")
        try store.setEnabled("demo", false)
        check(host.providers[provider.id] == false && store.compose(base: "BASE", customized: "CUSTOM") == "CUSTOM", "Disable must skip instructions and provider")
        let originalText = try String(contentsOf: original.appendingPathComponent("SKILL.md"), encoding: .utf8)
        check(originalText == "Original skill" && host.enabled["example"] == false, "Disable restores original skill and enabled state")
        try store.setEnabled("demo", true)
        check(host.providers[provider.id] == true, "Reenable confirmed provider")
        let second = try await store.prepare(url: root.appendingPathComponent("second.zip"), currentVersion: "1.0")
        try store.install(second, collision: .overwrite)
        var text = try String(contentsOf: original.appendingPathComponent("SKILL.md"), encoding: .utf8)
        check(text == "Second skill contents", "Last enabled package wins duplicate skills")
        try store.move(from: IndexSet(integer: 1), to: 0)
        text = try String(contentsOf: original.appendingPathComponent("SKILL.md"), encoding: .utf8)
        check(text != "Second skill contents", "Reorder changes duplicate skill winner")
        let composed = store.compose(base: "BASE", customized: "BASE")
        check(composed.range(of: "Supplemental extension: second")!.lowerBound < composed.range(of: "Supplemental extension: demo")!.lowerBound, "Instruction order")
        try store.uninstall("demo")
        check(host.providers[provider.id] == nil && host.secrets[provider.id] == nil, "Uninstall clears provider references and keys")
        text = try String(contentsOf: original.appendingPathComponent("SKILL.md"), encoding: .utf8)
        check(text == "Second skill contents", "Uninstall reveals next active skill")
        try store.uninstall("second")
        text = try String(contentsOf: original.appendingPathComponent("SKILL.md"), encoding: .utf8)
        check(text == "Original skill", "Last uninstall restores original")
        let cancel = try await store.prepare(url: zip, currentVersion: "1.0")
        try store.install(cancel, collision: .cancel)
        check(store.state.packs.isEmpty && !FileManager.default.fileExists(atPath: cancel.staging.path), "Cancel cleans staging")
        let renamed = try await store.prepare(url: zip, currentVersion: "1.0")
        try store.install(renamed, collision: .rename("renamed"))
        check(store.state.packs[0].id == "renamed", "Rename collision option")
        let replace = try await store.prepare(url: zip, currentVersion: "1.0")
        try store.install(replace, collision: .rename("other"))
        let replacement = try await store.prepare(url: zip, currentVersion: "1.0")
        try store.install(replacement, collision: .rename("demo"))
        let overwrittenID = store.state.packs.last!.providers[0].id
        try store.confirmProvider(pack: "demo", id: overwrittenID)
        let overwrite = try await store.prepare(url: zip, currentVersion: "1.0")
        try store.install(overwrite, collision: .overwrite)
        check(host.providers[overwrittenID] == nil && !store.state.packs.last!.providers[0].approved, "Overwrite removes old approvals")
        let loaded = ExtensionStore(root: store.root, host: host)
        check(loaded.state.packs.map(\.id) == store.state.packs.map(\.id), "Lifecycle persists across relaunch")
        let failed = try await store.prepare(url: zip, currentVersion: "1.0")
        let before = store.state.packs.map(\.id)
        host.failSecret = true
        do { try store.install(failed, collision: .rename("failed")); preconditionFailure("Must fail closed on unavailable Keychain") }
        catch { check(store.state.packs.map(\.id) == before, "Failed import rolls back state"); store.discard(failed) }
        host.failSecret = false
        let files = FileManager.default.enumerator(at: root.appendingPathComponent("work/.minis"), includingPropertiesForKeys: [.isRegularFileKey])!
        var noPlaintext = true
        let persistedFiles = files.allObjects.compactMap { $0 as? URL }
        for url in persistedFiles {
            if (try? url.resourceValues(forKeys: [.isRegularFileKey]))?.isRegularFile == true,
               let bytes = try? Data(contentsOf: url), String(decoding: bytes, as: UTF8.self).contains("fixture-secret") { noPlaintext = false }
        }
        check(noPlaintext, "No imported plaintext key anywhere in extension storage/metadata")
        for action in ["import:ok", "enable:ok", "disable:ok", "uninstall:ok", "provider-confirm:ok", "reorder:ok", "import-failed:failed"] {
            check(host.auditEvents.contains(action), "Audit " + action)
        }
        check(store.notice.contains("正在进行"), "Active sessions receive change notice")
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [ExtensionHTTPFixture.self]
        ExtensionHTTPFixture.body = try Data(contentsOf: zip)
        let remote = URL(string: "https://extensions.invalid/fixture.zip")!
        let downloaded = try await ExtensionDownload.fetch(remote, configuration: configuration)
        check(downloaded == ExtensionHTTPFixture.body, "Real downloader HEAD + GET path using URLProtocol")
        for mode in ["head-large", "get-large", "unknown", "truncated"] {
            ExtensionHTTPFixture.mode = mode; ExtensionHTTPFixture.gets = 0
            do { _ = try await ExtensionDownload.fetch(remote, configuration: configuration); preconditionFailure("Download should fail: \(mode)") }
            catch { check(true, "Rejected download \(mode)") }
            if mode == "head-large" || mode == "unknown" { check(ExtensionHTTPFixture.gets == 0, "Reject before body download") }
        }
        print("Extension importer: \(checks) production Swift checks PASSED (filesystem + mocked host/Keychain, not iPhone verification)")
    }
}
