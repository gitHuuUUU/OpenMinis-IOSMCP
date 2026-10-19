import SwiftUI

private struct ExpertTemplate: Identifiable {
    let id: String
    let title: String
    let category: String
    let instructions: String
    init(_ id: String, _ title: String, _ category: String, _ instructions: String) {
        self.id=id;self.title=title;self.category=category;self.instructions=instructions
    }
}

private struct ExpertEditTarget: Identifiable {
    let id = UUID()
    let definition: SubAgentDefinition?
}

struct ExpertLibraryView: View {
    var sessionId: String? = nil
    @ObservedObject private var store = SubAgentStore.shared
    @ObservedObject private var profiles = ExpertProfileStore.shared
    @State private var query = ""
    @State private var category = "全部"
    @State private var target: ExpertEditTarget?
    private var filtered: [SubAgentDefinition] {
        store.subAgents.filter { def in
            let profile=profiles.profile(for: def.id)
            return (category == "全部" || profile.category == category)
                && (query.isEmpty || (def.name + def.description + profile.displayName).localizedCaseInsensitiveContains(query))
        }
    }
    private let presets: [ExpertTemplate] = [
        .init("android-developer", "安卓开发专家", "开发", "Inspect actual Kotlin/Java/Gradle sources; implement minimal changes and run available builds/tests. Report missing Android SDK or remote tools accurately."),
        .init("algorithm-coach", "算法教练", "开发", "Explain problem constraints, derive an algorithm, analyze time/space complexity, then verify runnable code on edge cases."),
        .init("backend-architect", "后端架构师", "开发", "Inspect existing services and schemas; propose concrete API/data models and migrations, then validate consistency, concurrency and failure handling."),
        .init("chart-designer", "图表设计师", "数据与分析", "Inspect actual data and units. Choose appropriate charts, create an artifact with installed tools and check labels, scales and readability."),
        .init("code-reviewer", "代码评审官", "开发", "Read actual changes and surrounding code. Prioritize correctness, security, concurrency and maintainability findings with file/line evidence. Distinguish verified defects from hypotheses."),
        .init("writing-editor", "写作与内容编辑", "写作与内容", "Edit for structure, clarity, accuracy and the requested audience. Preserve intended facts and distinguish suggestions from source material."),
        .init("interface-designer", "界面设计师", "设计", "Inspect current UI conventions and constraints. Produce concrete adaptive layouts, accessibility considerations and implementation-ready design details.")
    ]
    var body: some View {
        List {
            Section {
                TextField("搜索专家", text: $query)
                Picker("分类", selection: $category) {
                    ForEach(["全部"] + ExpertProfile.categories, id: \.self) { Text($0).tag($0) }
                }
                Text("保存后通过现有 subagent_task 实际调用；模型继承、工具限制和绑定技能在子会话中生效。项目作用域对应一条对话的独立工作区。")
                    .font(.caption).foregroundColor(.secondary)
            }
            Section("已启用专家") {
                ForEach(filtered) { def in
                    Button { target=ExpertEditTarget(definition:def) } label: {
                        VStack(alignment:.leading,spacing:5) {
                            Text(profiles.profile(for:def.id).displayName.isEmpty ? def.displayName : profiles.profile(for:def.id).displayName).font(.headline)
                            Text(def.description).font(.caption).foregroundColor(.secondary).lineLimit(3)
                            Text(profiles.profile(for:def.id).workspaceID == nil ? "全局" : "项目工作区限定").font(.caption2).foregroundColor(.secondary)
                        }.padding(.vertical,4)
                    }
                }.onDelete { indices in
                    let ids=indices.map { filtered[$0] }.filter { !$0.isBuiltIn }.map(\.id)
                    for id in ids { store.removeSubAgent(id:id) }
                }
            }
            Section("内置专家模板 · 保存后启用") {
                ForEach(presets.filter { p in
                    !store.subAgents.contains(where: { $0.name == p.id })
                        && (category == "全部" || p.category == category)
                        && (query.isEmpty || (p.id+p.title).localizedCaseInsensitiveContains(query))
                }) { p in
                    Button(p.title) {
                        let def=SubAgentDefinition(name:p.id,description:p.title,instructions:p.instructions)
                        var profile=ExpertProfile();profile.displayName=p.title;profile.category=p.category
                        if profiles.save(profile,for:def.id) { target=ExpertEditTarget(definition:def) }
                    }.disabled(!store.canAddSubAgent)
                }
                if !store.canAddSubAgent { Text("专家数量已达到 \(SubAgentLimits.maxCount)；请编辑或删除不需要的自定义项。").font(.caption) }
            }
            if let error=profiles.error { Text(error).foregroundColor(.red) }
        }
        .navigationTitle("专家")
        .toolbar { ToolbarItem(placement:.navigationBarTrailing) { Button { target=ExpertEditTarget(definition:nil) } label: { Image(systemName:"plus") }.disabled(!store.canAddSubAgent) } }
        .sheet(item:$target) { item in ExpertEditorView(existing:item.definition,sessionId:sessionId) }
    }
}

private struct ExpertEditorView: View {
    let existing: SubAgentDefinition?
    let sessionId: String?
    @Environment(\.dismiss) private var dismiss
    @ObservedObject private var providers=ProviderConfigStore.shared
    @ObservedObject private var skills=SkillStore.shared
    @State private var id=UUID().uuidString
    @State private var name=""
    @State private var description=""
    @State private var instructions=""
    @State private var group: String? = nil
    @State private var thinking: ThinkingLevel? = nil
    @State private var profile=ExpertProfile()
    @State private var scoped=false
    @State private var scopeID=""
    @State private var error=""
    private let toolNames=["shell_execute","file_read","file_write","file_edit","workspace_search","browser_use","read_image","memory_get","memory_write","desktop_tool","device_app","reverse_runtime","workbench_build","subagent_task"]
    var body: some View {
        NavigationView {
            Form {
                Section("基本信息") {
                    TextField("名称／调用标识",text:$name).disabled(existing?.isBuiltIn == true)
                    TextField("展示名",text:$profile.displayName)
                    TextField("用途描述",text:$description).disabled(existing?.isBuiltIn == true)
                    Picker("分类",selection:$profile.category) { ForEach(ExpertProfile.categories,id:\.self) { Text($0).tag($0) } }
                    Toggle("仅当前项目工作区",isOn:$scoped)
                    if scoped { TextField("对话工作区 ID（UUID）",text:$scopeID).autocorrectionDisabled().textInputAutocapitalization(.never) }
                    Text("在对话内进入专家时会自动填写该对话 ID；在全局设置创建时可填写目标对话工作区 ID。不会把其它工作区的文件自动混入上下文。").font(.caption).foregroundColor(.secondary)
                }
                Section("模型与模式") {
                    Picker("模型组",selection:$group) {
                        Text("继承父会话／自动选择").tag(String?.none)
                        ForEach(providers.config.modelGroups) { Text($0.name).tag(String?.some($0.id)) }
                    }
                    Picker("思考强度",selection:$thinking) {
                        Text("继承父会话").tag(ThinkingLevel?.none)
                        ForEach(ThinkingLevel.allCases,id:\.self) { Text($0.displayName).tag(ThinkingLevel?.some($0)) }
                    }
                    Picker("默认模式",selection:$profile.defaultMode) {
                        Text("继承").tag("inherit");Text("实现").tag("implement");Text("审查优先").tag("review");Text("纯规划（不开放工具）").tag("plan")
                    }
                    Text("实际思考强度会按模型支持的上限限制。审查优先是工作方式，不是文件系统只读隔离；可配合下方工具限制。").font(.caption).foregroundColor(.secondary)
                }
                Section("工具集") {
                    NavigationLink("工具白名单（\(profile.allowedTools.count)，空=继承）") { StringSetPicker(title:"工具白名单",choices:toolNames,selected:$profile.allowedTools) }
                    NavigationLink("工具黑名单（\(profile.deniedTools.count)，优先）") { StringSetPicker(title:"工具黑名单",choices:toolNames,selected:$profile.deniedTools) }
                    NavigationLink("绑定技能（\(profile.boundSkillIDs.count)）") {
                        List {
                            Section {
                                Button("一键绑定全部（\(skills.skills.count)）") {
                                    profile.bindAllSkills(skills.skills.map(\.id))
                                }.disabled(skills.skills.isEmpty)
                                Button("清空绑定", role: .destructive) { profile.boundSkillIDs = [] }
                                    .disabled(profile.boundSkillIDs.isEmpty)
                                Toggle("在专家对话中加载绑定技能", isOn: $profile.injectSkills)
                                Text("已选 \(profile.boundSkillIDs.count) 项。返回后点“保存”生效；仅对调用此专家的子会话生效，不会全量塞入每次主对话。正文按预算加载，其余通过 skills 工具按需读取。")
                                    .font(.footnote).foregroundColor(.secondary)
                            }
                            Section("技能") {
                                ForEach(skills.skills) { skill in
                                    Toggle(skill.name, isOn: Binding(get: { profile.boundSkillIDs.contains(skill.id) }, set: { on in
                                        if on {
                                            if !profile.boundSkillIDs.contains(skill.id) { profile.boundSkillIDs.append(skill.id) }
                                        } else { profile.boundSkillIDs.removeAll { $0 == skill.id } }
                                    }))
                                }
                            }
                        }.navigationTitle("绑定技能")
                    }
                }
                Section("上下文注入") {
                    Toggle("子代理精简基线",isOn:Binding(get:{profile.injectBaseline},set:{profile.injectBaseline=$0;if $0 {profile.injectFullRules=false}}))
                    Toggle("完整应用规则",isOn:Binding(get:{profile.injectFullRules},set:{profile.injectFullRules=$0;if $0 {profile.injectBaseline=false}}))
                    Toggle("技能清单与绑定正文",isOn:$profile.injectSkills)
                    Toggle("记忆摘要",isOn:$profile.injectMemory)
                    Toggle("项目规则 AGENTS.md／CLAUDE.md",isOn:$profile.injectProjectRules)
                    Text("精简基线与完整规则互斥；绑定技能每项最多8,000字符，总计24,000字符，超出时提供继续读取提示。项目规则来自该会话 workspace 根目录。").font(.caption).foregroundColor(.secondary)
                }
                Section("专家提示词") { TextEditor(text:$instructions).frame(minHeight:180) }
                if !error.isEmpty { Text(error).foregroundColor(.red) }
            }
            .navigationTitle(existing == nil ? "新建专家" : "编辑专家")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement:.cancellationAction) { Button("取消") {dismiss()} }
                ToolbarItem(placement:.confirmationAction) { Button("保存",action:save) }
            }
            .onAppear {
                if let def=existing {id=def.id;name=def.name;description=def.description;instructions=def.instructions;group=def.modelGroupId;thinking=def.thinkingLevelOverride;profile=ExpertProfileStore.shared.profile(for:def.id)}
                scoped=profile.workspaceID != nil;scopeID=profile.workspaceID ?? sessionId ?? ""
            }
        }
    }
    private func save() {
        let store=SubAgentStore.shared
        guard !name.trimmingCharacters(in:.whitespacesAndNewlines).isEmpty else {error="名称不能为空";return}
        guard !store.subAgentNameIsTaken(name,excluding:id) else {error="名称已存在";return}
        guard store.subAgents.contains(where:{$0.id==id}) || store.canAddSubAgent else {error="专家数量达到上限";return}
        if scoped && UUID(uuidString:scopeID)==nil {error="项目工作区 ID 需要是有效的会话 UUID";return}
        profile.workspaceID=scoped ? scopeID : nil
        guard ExpertProfileStore.shared.save(profile,for:id) else {error=ExpertProfileStore.shared.error ?? "保存失败";return}
        var def=existing ?? SubAgentDefinition(id:id,name:name,description:description)
        def.name=name;def.description=description;def.instructions=instructions;def.modelGroupId=group;def.thinkingLevelOverride=thinking
        store.upsertSubAgent(def);dismiss()
    }
}

private struct StringSetPicker: View {
    let title: String
    let choices: [String]
    @Binding var selected: [String]
    @State private var customName = ""
    var body: some View {
        List {
            Section("按工具调用名称添加") {
                TextField("工具名称", text: $customName).autocorrectionDisabled().textInputAutocapitalization(.never)
                Button("添加到当前列表") {
                    let name=customName.trimmingCharacters(in:.whitespacesAndNewlines)
                    if !name.isEmpty && !selected.contains(name) {selected.append(name)}
                    customName=""
                }.disabled(customName.trimmingCharacters(in:.whitespacesAndNewlines).isEmpty)
            }
            Section("可选工具") {
                ForEach(Array(Set(choices+selected)).sorted(),id:\.self) { name in
                    Toggle(name,isOn:Binding(get:{selected.contains(name)},set:{on in if on {selected.append(name)} else {selected.removeAll {$0==name}}}))
                }
            }
        }.navigationTitle(title)
    }
}

struct PromptLibraryView: View {
    @ObservedObject private var store=PromptLibraryStore.shared
    @State private var target: PromptFragment?
    var body: some View {
        List {
            Section {
                Toggle("使用应用内置提示词",isOn:Binding(get:{store.state.includeBuiltIn},set:{value in var next=store.state;next.includeBuiltIn=value;store.save(next)}))
                Text("关闭仅影响本应用拼装的默认提示词；不会改变服务商或模型自身的规则。下列片段按顺序拼装，完全相同的内容只发送一次。改动下次请求生效。").font(.caption).foregroundColor(.secondary)
            }
            Section("本地片段") {
                ForEach(store.state.fragments) { item in
                    HStack {
                        Toggle("",isOn:Binding(get:{store.state.fragments.first(where:{$0.id==item.id})?.enabled ?? false},set:{enabled in var next=store.state;if let i=next.fragments.firstIndex(where:{$0.id==item.id}) {next.fragments[i].enabled=enabled;store.save(next)}})).labelsHidden()
                        Button {target=item} label:{VStack(alignment:.leading) {Text(item.title);Text(item.body).font(.caption).lineLimit(2).foregroundColor(.secondary)}}
                    }
                }.onDelete { positions in var next=store.state;next.fragments.remove(atOffsets:positions);store.save(next) }
                .onMove { source,destination in var next=store.state;next.fragments.move(fromOffsets:source,toOffset:destination);store.save(next) }
            }
            if let error=store.error {Text(error).foregroundColor(.red)}
        }
        .navigationTitle("提示词")
        .toolbar {
            ToolbarItem(placement:.navigationBarLeading) {EditButton()}
            ToolbarItem(placement:.navigationBarTrailing) {Button {target=PromptFragment(title:"新片段",body:"")} label:{Image(systemName:"plus")}.disabled(store.state.fragments.count>=24)}
        }
        .sheet(item:$target) { item in PromptFragmentEditor(fragment:item) }
    }
}

private struct PromptFragmentEditor: View {
    @State var fragment: PromptFragment
    @State private var error=""
    @Environment(\.dismiss) private var dismiss
    var body: some View {
        NavigationView {
            Form {
                TextField("标题",text:$fragment.title)
                Toggle("启用",isOn:$fragment.enabled)
                TextEditor(text:$fragment.body).frame(minHeight:300)
                Text("\(fragment.body.count) / 16000 字符").font(.caption)
                if !error.isEmpty {Text(error).foregroundColor(.red)}
            }.navigationTitle("编辑片段")
            .toolbar {
                ToolbarItem(placement:.cancellationAction) {Button("取消") {dismiss()}}
                ToolbarItem(placement:.confirmationAction) {Button("保存") {
                    guard !fragment.title.isEmpty,fragment.body.count<=16000 else {error="需要标题，正文最多16000字符";return}
                    var next=PromptLibraryStore.shared.state
                    if let i=next.fragments.firstIndex(where:{$0.id==fragment.id}) {next.fragments[i]=fragment} else {next.fragments.append(fragment)}
                    if PromptLibraryStore.shared.save(next) {dismiss()} else {error=PromptLibraryStore.shared.error ?? "保存失败"}
                }}
            }
        }
    }
}

struct ContextTokenStatisticsView: View {
    @ObservedObject var viewModel: AIChatViewModel
    @State private var snapshot: AIChatViewModel.ContextEfficiencyStats?
    var body: some View {
        List {
            if let stats=snapshot {
                Section("聊天请求累计（服务商已报告）") {
                    row("新输入",stats.actualFreshInputTokens);row("缓存读取",stats.actualCacheReadTokens)
                    row("缓存写入",stats.actualCacheWriteTokens);row("输出",stats.actualOutputTokens)
                    Text("来自已持久化的聊天／工具循环用量；不包含独立摘要请求，不代表所有 API 账单。").font(.caption).foregroundColor(.secondary)
                }
                Section("上下文") {
                    row("下一次请求估算",stats.estimatedNextContextTokens)
                    if let n=stats.actualLastReportedContextTokens {row("上一次请求实测",n)}
                    if let n=stats.modelContextWindow {row("模型上下文窗口",n)}
                    Text("估算值不是精确计费；不承诺固定节省比例。压缩保留对话原记录与可恢复的工具输出。").font(.caption).foregroundColor(.secondary)
                }
            }
            Button("刷新统计") {snapshot=viewModel.contextEfficiencyStats}
        }.navigationTitle("Token 统计").onAppear {snapshot=viewModel.contextEfficiencyStats}
    }
    private func row(_ label:String,_ value:Int)->some View { HStack {Text(label);Spacer();Text(value.formatted()).monospacedDigit()} }
}


/// Lightweight draft picker. Expert requests use the existing named subagent tool,
/// rather than replacing the main conversation's identity or provider settings.
struct ComposerLibraryPicker: View {
    let sessionId: String?
    let insert: (String) -> Void
    @Environment(\.dismiss) private var dismiss
    @ObservedObject private var prompts = PromptLibraryStore.shared
    @ObservedObject private var experts = SubAgentStore.shared
    @ObservedObject private var profiles = ExpertProfileStore.shared
    @State private var tab = 0
    @State private var query = ""

    private var availableExperts: [SubAgentDefinition] {
        experts.subAgents.filter { definition in
            profiles.profile(for: definition.id).isAvailable(in: sessionId)
                && (query.isEmpty || (definition.displayName + definition.name + definition.description).localizedCaseInsensitiveContains(query))
        }
    }
    private var availablePrompts: [PromptFragment] {
        prompts.state.fragments.filter { query.isEmpty || ($0.title + $0.body).localizedCaseInsensitiveContains(query) }
    }
    var body: some View {
        NavigationView {
            List {
                Picker("选择类型", selection: $tab) {
                    Text("提示词").tag(0)
                    Text("专家").tag(1)
                }.pickerStyle(.segmented)
                if tab == 0 {
                    Section {
                        Text("点选插入草稿，不会自动发送或改变全局开关；已启用的片段也会随系统上下文加载。")
                            .font(.footnote).foregroundColor(.secondary)
                        ForEach(availablePrompts) { item in
                            Button { insert(item.body) } label: {
                                VStack(alignment: .leading, spacing: 4) {
                                    Text(item.title)
                                    Text(item.body).font(.caption).foregroundColor(.secondary).lineLimit(2)
                                }
                            }.disabled(item.body.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                        }
                        if availablePrompts.isEmpty { Text("没有匹配的提示词").foregroundColor(.secondary) }
                    }
                    NavigationLink("管理提示词") { PromptLibraryView() }
                } else {
                    Section {
                        Text("点选在草稿中加入调用指定专家的请求；补充任务后点发送。这里不是立即启动或切换主对话模型。")
                            .font(.footnote).foregroundColor(.secondary)
                        ForEach(availableExperts) { expert in
                            Button {
                                let name = String(data: (try? JSONEncoder().encode(expert.name)) ?? Data(), encoding: .utf8) ?? "\"general\""
                                insert("请使用 subagent_task 调用专家（agent=\(name)）处理以下任务：")
                            } label: {
                                VStack(alignment: .leading, spacing: 4) {
                                    let profile = profiles.profile(for: expert.id)
                                    Text(profile.displayName.isEmpty ? expert.displayName : profile.displayName)
                                    Text(expert.description).font(.caption).foregroundColor(.secondary).lineLimit(2)
                                }
                            }
                        }
                        if availableExperts.isEmpty { Text("当前工作区没有匹配的专家").foregroundColor(.secondary) }
                    }
                    NavigationLink("管理专家") { ExpertLibraryView(sessionId: sessionId) }
                }
            }
            .searchable(text: $query, prompt: "搜索")
            .navigationTitle("选择")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .cancellationAction) { Button("关闭") { dismiss() } } }
        }.navigationViewStyle(.stack)
    }
}
