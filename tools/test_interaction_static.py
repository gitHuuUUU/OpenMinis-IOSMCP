"""Source contracts and original-resource hashes, not iPhone UI tests."""
import hashlib
import json
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
def read(path): return (ROOT/path).read_text(encoding='utf-8-sig')

class InteractionContracts(unittest.TestCase):
    def test_busy_attachment_presentation_is_chat_root_owned(self):
        s=read('src/ios/Views/Chat/AIChatView.swift')
        button=s.split('private var attachmentMenuButton: some View {',1)[1].split('/// Bottom toolbar',1)[0]
        self.assertNotIn('.sheet(',button)
        self.assertNotIn('.disabled(',button)
        self.assertIn('showAttachmentMenu = true',button)
        self.assertIn('|| showAttachmentMenu || showDeviceApps || showWorkbenchArtifacts',s)
        self.assertIn('vm.errorMessage = "文件导入失败："',s)
    def test_queue_default_direct_and_attachment_only(self):
        s=read('src/ios/Views/Chat/AIChatView.swift')
        self.assertIn('performEnqueue(direct: Bool = false)',s)
        self.assertIn('vm.enqueuePrompt(deferUntilIdle: !direct)',s)
        self.assertIn('onDirect: { performEnqueue(direct: true) }',s)
        gate=s.split('private var canEnqueue: Bool {',1)[1].split('/// Whether',1)[0]
        self.assertIn('!vm.hasLoadingAttachments',gate)
        self.assertIn('vm.attachments.contains { $0.loadState == .ready }',gate)
        self.assertIn('Text("☞")',s)
    def test_direct_drain_preserves_waiting_queue(self):
        s=read('src/ios/Agent/Chat/AIChatViewModel.swift')
        drain=s.split('private func injectQueuedPromptsAsNewTurn(',1)[1].split('// Mark corresponding',1)[0]
        self.assertIn('urgentOnly ? promptQueue.filter { !$0.deferUntilIdle } : promptQueue',drain)
        self.assertIn('promptQueue.removeAll { consumed.contains($0.id) }',drain)
        self.assertNotIn('promptQueue.removeAll()',drain)
        self.assertIn('urgentOnly: true',s)
        misc=read('src/ios/Agent/Chat/AIChatViewModel+Misc.swift')
        self.assertIn('if usingComposer && hasLoadingAttachments { return }',misc)
        self.assertIn('if usingComposer { attachments = [] }',misc)

    def test_composer_library_icon_and_draft_only(self):
        s=read('src/ios/Views/Chat/AIChatView.swift')
        button=s.split('private var composerLibraryButton: some View {',1)[1].split('/// `/` button',1)[0]
        self.assertIn('Image(systemName: "person.2")',button)
        self.assertNotIn('Text(',button)
        self.assertIn('showComposerLibrary = true',button)
        sheet=s.split('.sheet(isPresented: $showComposerLibrary)',1)[1].split('.sheet(isPresented: $showTokenUsage)',1)[0]
        self.assertIn('vm.inputText +=',sheet)
        self.assertNotIn('performSend',sheet)
        self.assertIn('|| showComposerLibrary',s)
    def test_composer_library_scope_and_existing_stores(self):
        s=read('src/ios/Views/Settings/ExpertLibraryView.swift').split('struct ComposerLibraryPicker:',1)[1]
        for part in ['PromptLibraryStore.shared','SubAgentStore.shared','isAvailable(in: sessionId)','insert(item.body)','agent=\\(name)','ExpertLibraryView(sessionId: sessionId)']:
            self.assertIn(part,s)

    def test_live_scroll_observation_not_lazy_sentinel(self):
        s=read('src/ios/Views/Chat/AIChatView.swift')
        self.assertNotIn('LegacyTranscriptBottomKey',s)
        self.assertIn('.background(LegacyTranscriptScrollProbe',s)
        for piece in ['found.observe(\\.contentOffset','found.observe(\\.contentSize','scroll.isDecelerating','legacyFollowBottom=false','removeTarget(self','settled?.cancel()']:
            self.assertIn(piece,s)
    def test_follow_latches_during_growth_and_drag(self):
        s=read('src/ios/Views/Chat/AIChatView.swift')
        self.assertIn('else if near { legacyFollowBottom = true }',s)
        self.assertNotIn('else { legacyFollowBottom = near }',s)
        self.assertIn('guard !legacyScrollInteracting else { return }',s)
        self.assertIn('if legacyFollowBottom && !legacyScrollInteracting',s)
    def test_legacy_history_does_not_recycle_giant_turns(self):
        s=read('src/ios/Views/Chat/AIChatView.swift')
        part=s.split('private var legacyMessagesArea:',1)[1].split('/// Shared label style',1)[0]
        self.assertIn('VStack(alignment:.leading,spacing:20)',part)
        self.assertNotIn('LazyVStack(',part)
        self.assertIn('trackWindowPosition:false',part)
        self.assertIn('if vm.isNearBottom != shouldFollow',part)
    def test_scroll_callbacks_deduplicate_and_cancel(self):
        s=read('src/ios/Views/Chat/AIChatView.swift')
        self.assertIn('if near != lastNear || interacting != lastInteracting',s)
        self.assertIn('pendingSample?.cancel(); pendingSample=nil',s)
        row=read('src/ios/Views/Chat/ChatMessageViews.swift')
        self.assertIn('trackWindowPosition ? proxy.frame(in: .global) : .zero',row)
        self.assertIn('Label("用量详情", systemImage: "chart.bar")',row)
    def test_app_auto_scope_has_reversible_switch(self):
        s=read('src/ios/Workbench.swift')
        for piece in ['workbench.autoApps','func accessibleApps','accessibleApps(session).flatMap','MinisDeviceBridge.openApplication','自动选择并打开已安装应用']:
            self.assertIn(piece,s)
    def test_wda_install_is_real_status_and_not_fake_in_app_install(self):
        s=read('src/ios/Workbench.swift')
        for piece in ['func wdaStatus()', 'prepareWDAInstall()', 'requires_host_sign_and_launch', 'guard status.reachable', 'wda_status', 'prepare_wda', '不会伪造已安装状态']:
            self.assertIn(piece,s)
        self.assertIn('wda_status", "prepare_wda", "get_ui"',read('src/ios/Agent/Chat/AIChatViewModel+ToolDefinitions.swift'))

    def test_wda_is_real_not_permission_flag(self):
        s=read('src/ios/Workbench.swift')
        for piece in ['verifyCached:true','wdaJSON(base,"sessions")','wdaJSON(base,"session",','wda/apps/activate','wda/dragfromtoforduration','suffix = "wda/tap"','无法连接 WDA']:
            self.assertIn(piece,s)
        self.assertNotIn('guard !sid.isEmpty else',s)
    def test_tool_actions_registered(self):
        s=read('src/ios/Agent/Chat/AIChatViewModel+ToolDefinitions.swift')
        for action in ['"ui_status"','"swipe"','"end_x"','"end_y"']:
            self.assertIn(action,s)
    def test_editor_uses_database_identity_and_readback(self):
        s=read('src/ios/Agent/Chat/AIChatViewModel.swift')
        for piece in ['assistantTextEdits(for','replaceAssistantTextPartsIfUnchanged','dbMessageId == raw.id','raw.parts == edit.raw.parts','keepAliveHistory = effectiveAgentHistory()']:
            self.assertIn(piece,s)
        self.assertIn('AssistantMessageActions',read('src/ios/Views/Chat/ChatMessageViews.swift'))
        self.assertIn('AssistantMessageActions',read('src/ios/Agent/MessageList/CollectionViewMessageListV3.swift'))
    def test_compaction_respects_edit_save_lock(self):
        self.assertGreaterEqual(read('src/ios/Agent/Chat/AIChatViewModel+Compaction.swift').count('guard !isSavingAssistantEdit'),3)
    def test_original_bytes_preserved(self):
        m=json.loads(read('tools/instruct-reference-manifest.json'))
        self.assertEqual(len(m['original_files']),95)
        self.assertEqual(m['ordinary_skills'],47)
        for item in m['original_files']:
            p=(ROOT/item['packaged_path']).resolve()
            self.assertTrue(p.is_relative_to(ROOT.resolve()))
            self.assertEqual(hashlib.sha256(p.read_bytes()).hexdigest(),item['sha256'],item['packaged_path'])
    def test_excluded_governing_prompts_not_packaged(self):
        m=json.loads(read('tools/instruct-reference-manifest.json'))
        for item in m['original_files']:
            path=item['archive_path']
            self.assertNotIn('/bridge.md',path)
            self.assertNotIn('/deploy_prompt.py',path)
            self.assertNotIn('/Skills/zxwn-activation/',path)
            self.assertNotIn('/Skills/full-pentest/',path)
            self.assertNotIn('/Skills/creative-writing/',path)

if __name__=='__main__': unittest.main()
