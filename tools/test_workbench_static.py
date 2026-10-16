import unittest, pathlib, plistlib, json
ROOT=pathlib.Path(__file__).resolve().parents[1]
def read(path): return (ROOT/path).read_text(encoding='utf-8-sig')
class WorkbenchContracts(unittest.TestCase):
    def test_sources_registered(self):
        pbx=read('src/ios/Minis.xcodeproj/project.pbxproj')
        for name in ['Workbench.swift','WorkbenchBridge.m']:
            self.assertIn(name+' in Sources',pbx)
        self.assertIn('WorkbenchBridge.h',read('src/ios/MinisApp-Bridging-Header.h'))
    def test_tool_registered_and_executed(self):
        self.assertIn('name: "device_app"',read('src/ios/Agent/Chat/AIChatViewModel+ToolDefinitions.swift'))
        dispatch=read('src/ios/Agent/Chat/AIChatViewModel+ConcurrentTools.swift')
        self.assertIn('case "device_app":',dispatch)
        self.assertIn('DeviceWorkbench.shared.tool',dispatch)
    def test_menu_is_real_sheet(self):
        view=read('src/ios/Views/Chat/AIChatView.swift')
        self.assertIn('AttachmentWorkbenchSheet',view)
        self.assertIn('DeviceAppPicker',view)
        self.assertIn('WorkbenchArtifactsView',view)
        self.assertIn('maxSelectionCount: 8',view)
    def test_entitlements_without_banned_flags(self):
        data=plistlib.loads((ROOT/'src/ios/TrollStore.entitlements').read_bytes())
        self.assertTrue(data['com.apple.private.security.no-sandbox'])
        self.assertTrue(data['com.apple.private.security.storage.AppDataContainers'])
        for banned in ['com.apple.private.cs.debugger','dynamic-codesigning','com.apple.private.skip-library-validation']:
            self.assertNotIn(banned,data)
    def test_mounts_require_switch_and_are_revocable(self):
        manager=read('src/ios/Agent/ISH/JailbreakFullAccessManager.swift')
        self.assertIn('workbench.fullRead',manager)
        self.assertIn('bindUnmountPath',manager)
        self.assertNotIn('toHostPath: "/var", readOnly: false',manager)
    def test_no_fake_health_results(self):
        code=read('src/ios/Workbench.swift')
        self.assertIn('result.exitCode==0',code)
        self.assertIn('kernelNotBooted',read('src/ios/Agent/ISH/ISHExecutionCoordinator.swift'))
        self.assertIn('let digest=asset["digest"]',code)
        self.assertIn('sha256sum -c -',code)
    def test_signature_after_plugin_exclusion(self):
        workflow=read('.github/workflows/build-ipa.yml')
        self.assertLess(workflow.index('rm -rf "$STAGED_APP/PlugIns"'),workflow.index('--entitlements src/ios/TrollStore.entitlements'))
        self.assertIn('codesign --verify --deep --strict',workflow)
    def test_skill_resources_and_async_import(self):
        code=read('src/ios/Agent/Session/SkillStore.swift')
        self.assertIn('installBundledSkillsFromDirectory() async',code)
        self.assertIn('await Task.yield()',code)
        self.assertIn('fm.copyItem(at: file, to: target)',code)
        manifest=json.loads(read('tools/local-skills-import-manifest.json'))
        self.assertEqual(len(manifest['included']),126)
        self.assertFalse((ROOT/'src/ios/BundledSkills/local-redteam-jailbreak-detail-pack').exists())
if __name__=='__main__':unittest.main()
