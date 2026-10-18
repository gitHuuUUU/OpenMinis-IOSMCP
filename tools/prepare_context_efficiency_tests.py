"""Extract unchanged production Swift helpers for a Foundation-only native test.

Run on macOS: python3 tools/prepare_context_efficiency_tests.py /tmp/ContextEfficiencyExtractedTests.swift
              swiftc -parse-as-library /tmp/ContextEfficiencyExtractedTests.swift -o /tmp/context-efficiency-tests
              /tmp/context-efficiency-tests
"""

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
CHAT = ROOT / "src/ios/Agent/Chat"


def production_method(path: Path, name: str) -> str:
    source = path.read_text(encoding="utf-8")
    needle = f"func {name}("
    at = source.find(needle)
    if at < 0:
        raise ValueError(f"missing {needle} in {path}")
    line_start = source.rfind("\n", 0, at) + 1
    end = source.find("\n    }", at)
    if end < 0:
        raise ValueError(f"unterminated {name} in {path}")
    return source[line_start : end + len("\n    }")]


vm = CHAT / "AIChatViewModel.swift"
compact = CHAT / "AIChatViewModel+Compaction.swift"
offload = CHAT / "AIChatViewModel+Offloading.swift"
methods = "\n\n".join(
    [
        production_method(vm, "appendUniquePromptFragment"),
        production_method(vm, "ensureContextFixedTokens"),
        production_method(compact, "compactSummaryWrappedText"),
        production_method(offload, "latestUserTurnIndexToPreserve"),
    ]
)

test = r'''
import Foundation

enum AgentRole { case user, assistant }
enum AgentPart {
    case text(String)
    case imageData(Data, String, String?)
    case toolResult(String)
}
struct AgentMessage {
    let role: AgentRole
    let parts: [AgentPart]
}

enum ContextSizeMeter {
    static func estimateTokens(_ text: String) -> Int { text.count }
    static func estimateFixedTokens(systemPrompt: String, tools: [Int]) -> Int {
        systemPrompt.count + 10 + tools.count
    }
}
final class AIChatViewModel {
    var composedBaseSystemPrompt = "base"
    var contextFixedTokens = 0
    var contextFixedBasePrompt: String?
    func makeAgentTools() -> [Int] { [1, 2] }
}
extension AIChatViewModel {
PRODUCTION_METHODS

    static func runTests() {
        func check(_ condition: Bool, _ label: String) {
            if !condition { fatalError("FAIL: " + label) }
            print("PASS: " + label)
        }
        var prompt = "BASE"
        appendUniquePromptFragment("  SKILL CONTENT  ", to: &prompt)
        appendUniquePromptFragment("SKILL CONTENT", to: &prompt)
        appendUniquePromptFragment("MCP CONTENT", to: &prompt)
        check(prompt.components(separatedBy: "SKILL CONTENT").count - 1 == 1,
              "identical injected block appears only once")
        check(prompt.contains("MCP CONTENT"), "different block remains")

        let vm = AIChatViewModel()
        vm.ensureContextFixedTokens()
        check(vm.contextFixedTokens == 16, "initial fixed estimate includes base and tools")
        vm.composedBaseSystemPrompt = "new larger base"
        vm.ensureContextFixedTokens()
        check(vm.contextFixedTokens == 27, "prompt edit invalidates fixed-token estimate")
        vm.ensureContextFixedTokens()
        check(vm.contextFixedTokens == 27, "unchanged prompt does not inflate estimate")

        let wrapped = compactSummaryWrappedText("Pending: fix open user bug. Completed: located file.")
        check(wrapped.contains("Preserve unfinished user goals"), "summary retains open goals")
        check(wrapped.contains("latest user message takes precedence"), "latest user still wins")
        check(wrapped.components(separatedBy: "Pending: fix open user bug.").count - 1 == 1,
              "summary body injected once")

        let history = [
            AgentMessage(role: .user, parts: [.text("request")]),
            AgentMessage(role: .assistant, parts: [.text("reply")]),
            AgentMessage(role: .user, parts: [.toolResult("synthetic")]),
            AgentMessage(role: .user, parts: [.imageData(Data([1]), "image/png", nil)]),
            AgentMessage(role: .user, parts: [.toolResult("another synthetic")]),
        ]
        check(latestUserTurnIndexToPreserve(in: history) == 3,
              "image-only user input protected, later tool result not mistaken for user")
        check(latestUserTurnIndexToPreserve(in: Array(history.prefix(3))) == 0,
              "latest real text user protected")
        check(latestUserTurnIndexToPreserve(in: [.init(role: .user, parts: [.toolResult("x")])]) == nil,
              "tool-only history has no user turn to protect")
    }
}

@main struct Main {
    static func main() { AIChatViewModel.runTests() }
}
'''.replace("PRODUCTION_METHODS", methods)

output = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/ContextEfficiencyExtractedTests.swift")
output.write_text(test, encoding="utf-8")
print(output)
