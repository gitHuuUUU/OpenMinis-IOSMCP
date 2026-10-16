import unittest, pathlib, plistlib, json
ROOT=pathlib.Path(__file__).resolve().parents[1]
def read(path): return (ROOT/path).read_text(encoding='utf-8-sig')
class WorkbenchContracts(unittest.TestCase):
    def test_first_send_install_off_main_actor(self):
        code=read('src/ios/Agent/Chat/AIChatViewModel+Misc.swift')
        self.assertIn('try await Task.detached(priority: .userInitiated)',code)
        self.assertIn('rootfs-install-finished',code)
        self.assertIn('installLock.lock()',read('src/ios/iSH/RootfsManager.swift'))
    def test_no_host_graph_mutation_during_measurement(self):
        code=read('src/ios/Shared/AppLocalization.swift')
        start=code.index('private func fittedHeight')
        end=code.index('final class MinisBadgeCenter',start)
        self.assertNotIn('updateRoot(',code[start:end])
        self.assertIn('guard !sizing',code[start:end])
    def test_automatic_install_and_rollback(self):
        code=read('src/ios/Workbench.swift')
        for item in ['installFromUI','RuntimeComponentView','WorkbenchDiagnosticsView','codex.minis-backup','MINIS_STAGE:校验','timeout 30']:
            self.assertIn(item,code)
        self.assertNotIn('Link("工具源',code)
    def test_exit_report_does_not_invent_signal(self):
        code=read('src/ios/Diagnostics/CrashReporter.swift')
        self.assertIn('cause unknown — stale launch marker',code)
        self.assertIn('Last Send Checkpoint',code)
    def test_background_native_bootstrap(self):
        code=read('src/ios/iSH/ISHKernel.m')
        self.assertIn('dispatch_queue_create("com.minisapp.ish.bootstrap", DISPATCH_QUEUE_SERIAL)',code)
        self.assertIn('minis_boot_checkpoint("mount-root-start")',code)
        self.assertIn('minis_previous_signal_actions[SIGTRAP]',code)
        self.assertNotIn('ISHKernel.shared.boot(withRootPath:',read('src/ios/Agent/Chat/AIChatViewModel+Misc.swift'))
    def test_plain_chat_lazy_kernel_with_real_shell_boot(self):
        self.assertIn('ensureKernelBooted(eager: false)',read('src/ios/Agent/Chat/AIChatViewModel.swift'))
        self.assertIn('ensureKernelBooted()',read('src/ios/Agent/Chat/AIChatViewModel+ISHCommand.swift'))
        self.assertIn('while kernelStatus == .booting',read('src/ios/Agent/Chat/AIChatViewModel+ISHCommand.swift'))
    def test_txt_export_not_clipboard_only(self):
        code=read('src/ios/Views/Settings/LogManagementView.swift')
        self.assertIn('UIDocumentPickerViewController(forExporting:files,asCopy:true)',code)
        self.assertIn('copyItem(at:url,to:output)',code)
        self.assertIn('LogTXTExportSheet(urls:[url])',code)
        self.assertIn('WorkbenchLogView()',read('src/ios/Workbench.swift'))
    def test_legacy_host_growth_updates_layout_async(self):
        code=read('src/ios/Shared/AppLocalization.swift')
        self.assertIn('onPreferenceChange(MinisLegacyHostedHeight.self)',code)
        self.assertIn('revision == self.rootRevision',code)
        self.assertIn('cell.clearCachedHeight()',code)
        self.assertIn('cell.seedMeasuredHeight(rounded,width:width)',code)
        self.assertIn('layout.setCachedHeight(rounded,at:indexPath.item)',code)
        self.assertIn('collection.collectionViewLayout.invalidateLayout()',code)
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
