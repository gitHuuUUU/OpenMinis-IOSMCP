import Foundation
import Combine

@MainActor final class ExpertProfileStore: ObservableObject {
    static let shared = ExpertProfileStore()
    @Published private(set) var profiles: [String: ExpertProfile] = [:]
    @Published var error: String?
    private let file: URL
    init() {
        let library = FileManager.default.urls(for: .libraryDirectory, in: .userDomainMask)[0]
        file = library.appendingPathComponent("MinisChat/expert-profiles.json")
        if let data = try? Data(contentsOf: file), let saved = try? JSONDecoder().decode([String: ExpertProfile].self, from: data) { profiles = saved }
    }
    func profile(for id: String) -> ExpertProfile { profiles[id] ?? ExpertProfile() }
    @discardableResult func save(_ profile: ExpertProfile, for id: String) -> Bool {
        var normalized = profile; normalized.normalize()
        var next = profiles; next[id] = normalized
        do {
            try FileManager.default.createDirectory(at: file.deletingLastPathComponent(), withIntermediateDirectories: true)
            try JSONEncoder().encode(next).write(to: file, options: .atomic)
            profiles = next; error = nil; return true
        } catch { self.error = error.localizedDescription; return false }
    }
    func boundSkillFragment(profile: ExpertProfile) -> String {
        var remaining = 24000
        var sections: [String] = []
        for id in profile.boundSkillIDs {
            guard remaining > 0, let skill = SkillStore.shared.skills.first(where: { $0.id == id }),
                  let body = SkillStore.shared.readSkillContent(id) else { continue }
            let text = String(body.prefix(min(8000, remaining)))
            sections.append("--- Bound skill: \(skill.name) (\(id)) ---\n\(text)" + (text.count < body.count ? "\n[Excerpt; use skills tool to read remaining content.]" : ""))
            remaining -= text.count
        }
        return sections.joined(separator: "\n\n")
    }
    func projectRulesFragment(sessionId: String?) -> String {
        guard let sid = sessionId, UUID(uuidString: sid) != nil else { return "" }
        let workspace = AIChatViewModel.minisPersistentBase.appendingPathComponent(sid).appendingPathComponent("workspace").resolvingSymlinksInPath()
        var sections: [String] = []
        for name in ["AGENTS.md", "CLAUDE.md"] {
            let url = workspace.appendingPathComponent(name).resolvingSymlinksInPath()
            guard url.path.hasPrefix(workspace.path + "/"),
                  let handle = try? FileHandle(forReadingFrom: url) else { continue }
            defer { try? handle.close() }
            let bytes = (try? handle.read(upToCount: 8192)) ?? Data()
            guard let text = String(data: bytes, encoding: .utf8), !text.isEmpty else { continue }
            sections.append("--- Workspace instructions: \(name) (up to 8 KB; read file for remainder) ---\n\(text)")
        }
        return sections.joined(separator: "\n\n")
    }
}

@MainActor final class PromptLibraryStore: ObservableObject {
    static let shared = PromptLibraryStore()
    struct State: Codable { var includeBuiltIn: Bool; var fragments: [PromptFragment] }
    @Published private(set) var state = State(includeBuiltIn: true, fragments: [])
    @Published var error: String?
    private let file: URL
    init() {
        let library = FileManager.default.urls(for: .libraryDirectory, in: .userDomainMask)[0]
        file = library.appendingPathComponent("MinisChat/prompt-library.json")
        if let data = try? Data(contentsOf: file), let saved = try? JSONDecoder().decode(State.self, from: data) { state = saved }
        else {
            state.fragments = [
                PromptFragment(title: "00 · identity", body: "Help with the user's requested task; state assumptions clearly.", enabled: false),
                PromptFragment(title: "10 · communication", body: "Use concise answers in the user's language. Report meaningful progress, not repeated status.", enabled: false),
                PromptFragment(title: "15 · project-rules", body: "Read relevant project instructions and preserve existing conventions.", enabled: false),
                PromptFragment(title: "20 · coding-discipline", body: "Make minimal coherent changes and test the actual changed code.", enabled: false),
                PromptFragment(title: "30 · comments", body: "Explain non-obvious reasons in comments, not obvious syntax.", enabled: false),
                PromptFragment(title: "40 · approach", body: "Inspect, implement, verify, then report evidence and remaining gaps.", enabled: false),
                PromptFragment(title: "50 · confirmation", body: "Confirm irreversible destructive actions before execution and preserve user data.", enabled: false),
                PromptFragment(title: "60 · tools-and-paths", body: "Use existing tools and actual paths. Never claim an operation succeeded without its result.", enabled: false)
            ]
        }
    }
    @discardableResult func save(_ value: State) -> Bool {
        var bounded = value
        bounded.fragments = Array(value.fragments.prefix(24)).map { var v=$0; v.title=String(v.title.prefix(100));v.body=String(v.body.prefix(16000));return v }
        do {
            try FileManager.default.createDirectory(at: file.deletingLastPathComponent(), withIntermediateDirectories: true)
            try JSONEncoder().encode(bounded).write(to: file, options: .atomic)
            state = bounded; error=nil; return true
        } catch { self.error=error.localizedDescription; return false }
    }
    func compose(base: String) -> String {
        PromptComposition.compose(base: base, includeBuiltIn: state.includeBuiltIn, fragments: state.fragments)
    }
}
