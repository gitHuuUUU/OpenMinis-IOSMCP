import Foundation

@MainActor final class MinisExtensionHost: ExtensionHost {
    var skillRoot: URL { AIChatViewModel.minisSkillsPersistentDir }
    func skillEnabled(_ id: String) -> Bool { SkillStore.shared.skills.first(where: { $0.id == id })?.isEnabled ?? true }
    func replaceSkill(_ id: String, source: URL?, enabled: Bool) throws {
        try SkillStore.shared.replaceFromExtension(id: id, source: source, enabled: enabled)
    }
    func saveSecret(_ secret: String, id: String) throws {
        ProviderKeychainHelper.saveAPIKey(secret, instanceId: id)
        guard ProviderKeychainHelper.loadAPIKey(instanceId: id) == secret else {
            throw ExtensionPackageReader.fail("钥匙串写入失败，未安装扩展；请解锁设备后重试")
        }
    }
    func removeSecret(_ id: String) { ProviderKeychainHelper.deleteAPIKey(instanceId: id) }
    func setProvider(_ proposal: ExtensionProvider, enabled: Bool) throws {
        guard let type = ProviderType(rawValue: proposal.providerType), type != .unsupported else { throw ExtensionPackageReader.fail("不支持的 provider 类型") }
        let store = ProviderConfigStore.shared
        if var existing = store.instance(for: proposal.id) {
            existing.isEnabled = enabled
            store.updateInstance(existing)
        } else {
            store.addInstance(ProviderInstance(id: proposal.id, label: proposal.label, providerType: type, credentialType: .apiKey, isEnabled: enabled, customBaseURL: proposal.endpoint, appendV1Suffix: false))
        }
    }
    func removeProvider(_ id: String) {
        if ProviderConfigStore.shared.instance(for: id) != nil { ProviderConfigStore.shared.removeInstance(id) }
    }
    func audit(_ action: String, name: String, success: Bool) {
        ConfigAuditLog.shared.append(ConfigAuditEntry(id: UUID().uuidString, at: Date(), actor: .user, sessionId: nil, scope: "extensions", key: "extensions.\(name).\(action)", oldValueJSON: "", newValueJSON: "", confirmedAt: Date(), status: success ? .applied : .rejected, revertOf: nil, caption: "扩展：\(action)"))
    }
}

extension ExtensionStore {
    static let shared = ExtensionStore(root: URL(fileURLWithPath: NSHomeDirectory(), isDirectory: true).appendingPathComponent(".minis/extensions", isDirectory: true), host: MinisExtensionHost())
}
