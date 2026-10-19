import Foundation

/// Local app preferences. Tool restrictions are enforced in code, not merely
/// described to the model. Workspace scope is the parent session's file bucket.
struct ExpertProfile: Codable, Equatable {
    var displayName = ""
    var category = "开发"
    var workspaceID: String? = nil
    var defaultMode = "inherit"
    var allowedTools: [String] = []
    var deniedTools: [String] = []
    var boundSkillIDs: [String] = []
    var injectBaseline = true
    var injectFullRules = false
    var injectSkills = true
    var injectMemory = false
    var injectProjectRules = true

    static let categories = ["写作与内容", "数据与分析", "开发", "设计"]
    static let baseline = "Inspect relevant files before editing. Use actual tools and verify outputs. Preserve user data, report failures and unverified results accurately. Keep the final answer concise with artifact paths and test results."

    func allowsTool(_ name: String) -> Bool {
        if deniedTools.contains(name) { return false }
        if defaultMode == "plan" { return false }
        return allowedTools.isEmpty || allowedTools.contains(name)
    }

    func isAvailable(in sessionID: String?) -> Bool {
        workspaceID == nil || workspaceID == sessionID
    }

    /// Keep existing bindings (including temporarily unavailable skills), deduplicate,
    /// and enable injection so a previously disabled toggle cannot make binding inert.
    mutating func bindAllSkills(_ ids: [String]) {
        boundSkillIDs = Array(Set((boundSkillIDs + ids).filter { !$0.isEmpty })).sorted()
        injectSkills = true
    }

    mutating func normalize() {
        displayName = String(displayName.prefix(80))
        if !Self.categories.contains(category) { category = "开发" }
        if !["inherit", "implement", "review", "plan"].contains(defaultMode) { defaultMode = "inherit" }
        if injectFullRules { injectBaseline = false }
        allowedTools = Array(Set(allowedTools.filter { !$0.isEmpty })).sorted()
        deniedTools = Array(Set(deniedTools.filter { !$0.isEmpty })).sorted()
        boundSkillIDs = Array(Set(boundSkillIDs)).sorted()
        if workspaceID?.isEmpty == true { workspaceID = nil }
    }
}

struct PromptFragment: Identifiable, Codable, Equatable {
    var id: String = UUID().uuidString
    var title: String
    var body: String
    var enabled: Bool = true
}

enum PromptComposition {
    static func compose(base: String, includeBuiltIn: Bool, fragments: [PromptFragment]) -> String {
        var sections: [String] = []
        var seen = Set<String>()
        func append(_ text: String) {
            let normalized = text.trimmingCharacters(in: .whitespacesAndNewlines)
            if !normalized.isEmpty && seen.insert(normalized).inserted { sections.append(normalized) }
        }
        if includeBuiltIn { append(base) }
        for fragment in fragments.prefix(24) where fragment.enabled {
            append(String(fragment.body.prefix(16000)))
        }
        return sections.joined(separator: "\n\n")
    }
}
