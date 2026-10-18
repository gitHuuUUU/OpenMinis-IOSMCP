"""Extract the real VM edit methods into a Foundation-only Swift regression.
Run: python3 tools/prepare_assistant_edit_tests.py /tmp/AssistantEditTests.swift
     swiftc -parse-as-library /tmp/AssistantEditTests.swift -o /tmp/AssistantEditTests && /tmp/AssistantEditTests
No iOS UI/framework behavior is mocked as verified by this test.
"""
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
vm = (ROOT / 'src/ios/Agent/Chat/AIChatViewModel.swift').read_text(encoding='utf-8')
body = vm.split('    // MARK: - In-place editing of completed assistant text', 1)[1].split('    // MARK: - Browser', 1)[0]
pre = r'''
import Foundation
@propertyWrapper struct Published<T> { var wrappedValue: T }
enum Role { case user, assistant }
enum Kind { case text, tool, thinking }
struct ToolUse: Hashable { let toolUseId: String }
enum ContentPart: Hashable { case text(String), toolUse(ToolUse), toolResult(String), mediaRef(String) }
struct RawMessage: Identifiable {
 let id: String; let sessionId: String; let role: Role; let parts: [ContentPart]
 var sortOrder: Int = 0
 var isInternalBridge: Bool = false
 var isToolResultOnly: Bool { role == .user && !parts.isEmpty && parts.allSatisfy { if case .toolResult = $0 { return true }; return false } }
 static func stripSystemReminders(_ text: String) -> String { text.replacingOccurrences(of: "<system-reminder>hidden</system-reminder>", with: "") }
 static func splitLongAssistantText(_ text: String) -> [String] { text.contains("|SPLIT|") ? text.components(separatedBy: "|SPLIT|") : [text] }
}
final class AssistantBlock {
 let id = UUID(); let kind: Kind; var content: String; var toolUseId: String?
 init(kind: Kind, content: String, toolUseId: String? = nil) { self.kind = kind; self.content = content; self.toolUseId = toolUseId }
}
final class ChatMessage {
 let id = UUID(); let role = Role.assistant; var blocks: [AssistantBlock]; var content = ""
 var isCompactedHistory = false; var error: String?; var sourceSortOrder: Int?; var lastSourceSortOrder: Int?
 init(_ blocks: [AssistantBlock]) { self.blocks = blocks }
}
struct AgentMessage { var role = Role.assistant; var parts: [ContentPart]; var dbMessageId: String?; var reasoningContent = "reasoning-preserved" }
actor ChatStore {
 static let shared = ChatStore(); var rows: [RawMessage] = []; var rejectWrite = false
 func configure(_ rows: [RawMessage], reject: Bool = false) { self.rows = rows; rejectWrite = reject }
 func loadMessages(sessionId: String) -> [RawMessage] { rows.filter { $0.sessionId == sessionId } }
 func updateMessageParts(messageId: String, parts: [ContentPart]) {
  guard !rejectWrite, let index = rows.firstIndex(where: { $0.id == messageId }) else { return }
  let old = rows[index]
  rows[index] = RawMessage(id: old.id, sessionId: old.sessionId, role: old.role, parts: parts, sortOrder: old.sortOrder)
 }
}
struct Signal { func send() {} }
@MainActor final class AIChatViewModel {
 var isProcessing = false; var isTruncatingForRetry = false; var remoteDeviceId: String?; var sessionId: String? = "s"
 var messages: [ChatMessage] = []; var agentHistory: [AgentMessage] = []; var keepAliveHistory: [AgentMessage] = []
 let retrySnapshotReloadSignal = Signal()
 func effectiveAgentHistory() -> [AgentMessage] { agentHistory }
'''
post = r'''
}
@main struct Regression {
 @MainActor static func main() async throws {
  var checks = 0
  func check(_ condition: @autoclosure () -> Bool, _ label: String) { precondition(condition(), label); checks += 1 }
  func row(_ id: String, _ parts: [ContentPart], role: Role = .assistant, order: Int = 0) -> RawMessage {
   RawMessage(id: id, sessionId: "s", role: role, parts: parts, sortOrder: order)
  }
  @MainActor func setup(_ raws: [RawMessage], _ blocks: [AssistantBlock], reject: Bool = false) async -> (AIChatViewModel, ChatMessage) {
   await ChatStore.shared.configure(raws, reject: reject)
   let vm = AIChatViewModel(); let message = ChatMessage(blocks)
   vm.messages = [message]; vm.agentHistory = raws.map { AgentMessage(role: $0.role, parts: $0.parts, dbMessageId: $0.id) }
   return (vm, message)
  }
  let base = row("a", [.text("original")])
  var (vm, message) = await setup([base], [AssistantBlock(kind: .text, content: "original")])
  var edits = try await vm.assistantTextEdits(for: message)
  check(edits.count == 1, "live simple reply maps")
  edits[0].text = "edited"; try await vm.saveAssistantTextEdit(edits[0])
  check(vm.agentHistory[0].parts == [.text("edited")], "model context updated")
  check(vm.keepAliveHistory[0].parts == [.text("edited")], "keepalive refreshed")
  check(message.blocks[0].content == "edited", "UI updated")
  check(vm.agentHistory[0].reasoningContent == "reasoning-preserved", "reasoning preserved")
  let read = await ChatStore.shared.loadMessages(sessionId: "s")
  check(read[0].parts == [.text("edited")], "DB readback")
  let tool = ToolUse(toolUseId: "tool1")
  let rows = [row("a", [.text("before"), .toolUse(tool)]), row("r", [.toolResult("tool1")], role: .user), row("b", [.text("after"), .mediaRef("attachment")]), row("u", [.text("later")], role: .user)]
  let toolBlock = AssistantBlock(kind: .tool, content: "output", toolUseId: "tool1")
  let thinking = AssistantBlock(kind: .thinking, content: "thinking")
  (vm, message) = await setup(rows, [thinking, AssistantBlock(kind: .text, content: "before"), toolBlock, AssistantBlock(kind: .text, content: "after")])
  edits = try await vm.assistantTextEdits(for: message)
  check(edits.map { $0.raw.id } == ["a", "b"], "merged raw rows mapped by IDs")
  edits[1].text = "new after"; try await vm.saveAssistantTextEdit(edits[1])
  check(vm.agentHistory[0].parts == rows[0].parts && vm.agentHistory[1].parts == rows[1].parts, "tool pair untouched")
  check(vm.agentHistory[2].parts == [.text("new after"), .mediaRef("attachment")], "attachment untouched")
  check(vm.agentHistory[3].parts == rows[3].parts && vm.agentHistory.count == 4, "later context not truncated")
  check(message.blocks[0] === thinking && message.blocks[2] === toolBlock, "thinking/tool blocks not replaced")
  (vm, message) = await setup([base], [AssistantBlock(kind: .text, content: "original")], reject: true)
  edits = try await vm.assistantTextEdits(for: message); edits[0].text = "failed"
  do { try await vm.saveAssistantTextEdit(edits[0]); preconditionFailure("write failure accepted") } catch { checks += 1 }
  check(message.blocks[0].content == "original" && vm.agentHistory[0].parts == base.parts, "failed write cannot fake save")
  check(!vm.isSavingAssistantEdit && !vm.isTruncatingForRetry, "locks released on error")
  (vm, message) = await setup([base], [AssistantBlock(kind: .text, content: "original")])
  vm.agentHistory[0].dbMessageId = nil
  do { _ = try await vm.assistantTextEdits(for: message); preconditionFailure("missing mapping accepted") } catch { checks += 1 }
  let duplicates = [base, row("u", [.text("next")], role: .user, order: 1), row("b", [.text("original")], order: 2)]
  (vm, message) = await setup(duplicates, [AssistantBlock(kind: .text, content: "original")])
  do { _ = try await vm.assistantTextEdits(for: message); preconditionFailure("ambiguous mapping accepted") } catch { checks += 1 }
  message.sourceSortOrder = 2; message.lastSourceSortOrder = 2
  edits = try await vm.assistantTextEdits(for: message)
  check(edits[0].raw.id == "b", "sort range disambiguates duplicate text after reload")
  vm.isProcessing = true
  do { _ = try await vm.assistantTextEdits(for: message); preconditionFailure("stream edit accepted") } catch { checks += 1 }
  (vm, message) = await setup([row("long", [.text("one|SPLIT|two")])], [AssistantBlock(kind: .text, content: "one"), AssistantBlock(kind: .text, content: "two")])
  edits = try await vm.assistantTextEdits(for: message)
  check(edits.count == 1 && edits[0].blockIds.count == 2, "split display maps to one raw text part")
  edits[0].text = "new|SPLIT|parts"; try await vm.saveAssistantTextEdit(edits[0])
  check(message.blocks.map { $0.content } == ["new", "parts"], "long edited text is resplit")
  (vm, message) = await setup([base], [AssistantBlock(kind: .text, content: "original")])
  edits = try await vm.assistantTextEdits(for: message)
  edits[0].text = "replacement"
  await ChatStore.shared.configure([row("a", [.text("external edit")])])
  do { try await vm.saveAssistantTextEdit(edits[0]); preconditionFailure("stale draft accepted") } catch { checks += 1 }
  check(message.blocks[0].content == "original", "stale draft leaves UI unchanged")
  (vm, message) = await setup([base], [AssistantBlock(kind: .text, content: "original")])
  edits = try await vm.assistantTextEdits(for: message); edits[0].text = "  \n"
  do { try await vm.saveAssistantTextEdit(edits[0]); preconditionFailure("blank edit accepted") } catch { checks += 1 }
  (vm, message) = await setup([row("hidden", [.text("original<system-reminder>hidden</system-reminder>")])], [AssistantBlock(kind: .text, content: "original")])
  do { _ = try await vm.assistantTextEdits(for: message); preconditionFailure("hidden metadata exposed") } catch { checks += 1 }
  print("Assistant text edit production-method regression: \(checks) checks passed (Foundation doubles, no device UI).")
 }
}
'''
out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / 'tools/AssistantTextEditTests.generated.swift'
helper = vm.split('// MARK: - Assistant edit persistence compare/write/read-back', 1)[1]
out.write_text(pre + body + post + helper, encoding='utf-8')
print(out)
