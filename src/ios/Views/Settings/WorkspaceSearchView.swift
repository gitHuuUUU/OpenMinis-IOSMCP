import SwiftUI
import UIKit

/// Search the workbench's Linux filesystem without blocking the UI thread.
/// Chat agents use the same guest program in their own session fs_context.
struct WorkspaceSearchView: View {
    @State private var root = "/var/minis/workspace"
    @State private var query = ""
    @State private var glob = "*"
    @State private var mode = "content"
    @State private var regex = false
    @State private var includeIgnored = false
    @State private var results: [[String: Any]] = []
    @State private var summary = ""
    @State private var error = ""
    @State private var nextOffset: Int? = nil
    @State private var running = false
    @State private var searchTask: Task<Void, Never>? = nil

    var body: some View {
        List {
            Section("搜索范围") {
                TextField("Linux 绝对目录", text: $root)
                    .textInputAutocapitalization(.never).autocorrectionDisabled()
                TextField("文件通配符，例如 *.swift", text: $glob)
                    .textInputAutocapitalization(.never).autocorrectionDisabled()
                Text("此处搜索工作台会话的 Linux 目录；聊天 AI 的 workspace_search 会搜索该对话自己的工作区。未授权或不可访问会显示错误，不等于零条结果。")
                    .font(.caption).foregroundColor(.secondary)
            }
            Section("查询") {
                TextField("文件名或代码内容", text: $query)
                    .textInputAutocapitalization(.never).autocorrectionDisabled()
                Picker("搜索模式", selection: $mode) {
                    Text("文件名").tag("name")
                    Text("代码内容").tag("content")
                }.pickerStyle(.segmented)
                Toggle("正则表达式", isOn: $regex)
                Toggle("包含依赖与生成目录", isOn: $includeIgnored)
                HStack {
                    Button(running ? "搜索中…" : "搜索") { search(offset: 0) }
                        .disabled(running || query.isEmpty)
                    if running {
                        Button("取消") { searchTask?.cancel() }
                    }
                }
            }
            if !error.isEmpty { Section { Text(error).foregroundColor(.red) } }
            if !summary.isEmpty { Section { Text(summary).font(.caption).foregroundColor(.secondary) } }
            Section("结果") {
                ForEach(Array(results.enumerated()), id: \.offset) { entry in
                    let item = entry.element
                    let path = item["path"] as? String ?? ""
                    let line = item["line"] as? Int
                    VStack(alignment: .leading, spacing: 4) {
                        Text("\(path)\(line.map { ":\($0)" } ?? "")")
                            .font(.system(.footnote, design: .monospaced)).textSelection(.enabled)
                        if let snippet = item["snippet"] as? String {
                            Text(snippet).font(.caption).foregroundColor(.secondary).textSelection(.enabled)
                        }
                        HStack {
                            Button("复制路径") { UIPasteboard.general.string = path }
                                .font(.caption)
                            if path.hasPrefix("/var/minis/"),
                               let url = URL(string: "minis://" + String(path.dropFirst("/var/minis/".count))) {
                                Button("打开") { MinisOpenURLBroker.shared.offer(url) }
                                    .font(.caption)
                            }
                        }.buttonStyle(.borderless)
                    }
                }
                if let nextOffset {
                    Button("下一页") { search(offset: nextOffset) }.disabled(running)
                }
                if !running && results.isEmpty && error.isEmpty && !summary.isEmpty {
                    Text("未找到匹配项").foregroundColor(.secondary)
                }
            }
        }
        .navigationTitle("工作区搜索")
        .onDisappear { searchTask?.cancel() }
    }

    private func search(offset: Int) {
        searchTask?.cancel()
        let request: [String: Any] = [
            "root": root, "query": query, "glob": glob.isEmpty ? "*" : glob,
            "mode": mode, "regex": regex, "include_ignored": includeIgnored,
            "offset": offset, "limit": 50, "timeout": 10
        ]
        guard let data = try? JSONSerialization.data(withJSONObject: request) else {
            error = "无法编码搜索参数"; return
        }
        let payload = data.base64EncodedString()
        running = true; error = ""; summary = ""; nextOffset = nil
        if offset == 0 { results = [] }
        searchTask = Task {
            do {
                let command = "if ! command -v python3 >/dev/null 2>&1; then apk add --no-cache python3 >/dev/null 2>&1 || { echo 'Python runtime unavailable: apk install failed'; exit 127; }; fi; python3 /usr/local/bin/minis-workspace-search '\(payload)'"
                let result = try await DeviceWorkbench.shared.run(command, timeout: 180)
                try Task.checkCancellation()
                guard result.exitCode == 0,
                      let body = result.output.data(using: .utf8),
                      let response = try JSONSerialization.jsonObject(with: body) as? [String: Any] else {
                    error = "搜索不可用：\(result.output)"; running = false; return
                }
                let status = response["status"] as? String ?? "error"
                if status == "error" || status == "unavailable" {
                    error = response["error"] as? String ?? "搜索不可用"
                } else {
                    results = response["results"] as? [[String: Any]] ?? []
                    nextOffset = response["next_offset"] as? Int
                    let stats = response["stats"] as? [String: Any] ?? [:]
                    let visited = stats["visited_files"] as? Int ?? 0
                    let reason = response["stop_reason"] as? String
                    summary = "\(status == "partial" ? "部分结果" : "完成") · 扫描 \(visited) 个文件 · 本页 \(results.count) 条"
                    if let reason, reason != "page_full" { summary += " · 限制：\(reason)" }
                    if let errors = response["errors"] as? [String], !errors.isEmpty {
                        summary += " · 跳过不可读路径：\(errors.joined(separator: "; "))"
                    }
                }
            } catch is CancellationError {
                error = "已取消搜索"
            } catch {
                self.error = "搜索不可用：\(error.localizedDescription)"
            }
            running = false
        }
    }
}
