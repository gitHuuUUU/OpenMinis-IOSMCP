"""Source contracts and original-resource hashes, not iPhone UI tests."""
import hashlib
import json
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
def read(path): return (ROOT/path).read_text(encoding='utf-8-sig')

class InteractionContracts(unittest.TestCase):
    def test_live_scroll_observation_not_lazy_sentinel(self):
        s=read('src/ios/Views/Chat/AIChatView.swift')
        self.assertNotIn('LegacyTranscriptBottomKey',s)
        for piece in ['found.observe(\\.contentOffset','found.observe(\\.contentSize','scroll.isDecelerating','legacyFollowBottom=false','removeTarget(self','settled?.cancel()']:
            self.assertIn(piece,s)
    def test_follow_latches_during_growth_and_drag(self):
        s=read('src/ios/Views/Chat/AIChatView.swift')
        self.assertIn('else if near { legacyFollowBottom = true }',s)
        self.assertNotIn('else { legacyFollowBottom = near }',s)
        self.assertIn('guard !legacyScrollInteracting else { return }',s)
        self.assertIn('if legacyFollowBottom && !legacyScrollInteracting',s)
    def test_app_auto_scope_has_reversible_switch(self):
        s=read('src/ios/Workbench.swift')
        for piece in ['workbench.autoApps','func accessibleApps','accessibleApps(session).flatMap','MinisDeviceBridge.openApplication','自动选择并打开已安装应用']:
            self.assertIn(piece,s)
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
