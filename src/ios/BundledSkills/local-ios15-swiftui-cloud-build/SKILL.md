---
name: local-ios15-swiftui-cloud-build
description: 将含较新 SwiftUI、AppIntents API 的原生 iOS 源码回移到 iOS 15，并在已批准的 GitHub macOS Actions 构建 IPA；适用于 Windows 缺 Xcode 或最低版本标注与真实 API 不符的项目，不适用于 IPA 二进制破解。
---

# iOS 15 源码兼容与云端构建
- 明确实际设备最低系统。不能通过提高 deployment target 掩盖兼容错误。Windows 无 Xcode 时诚实使用用户批准的远端 macOS，已有私有仓库优先复用，不输出令牌。
- 审查外来源码的构建脚本、启动代码、子模块与权限；下载 rootfs/预编译依赖是审计边界，源码无匹配不是无病毒证明。
- 新 SDK 可编译受 availability 保护的 iOS 26 API；旧 Xcode 即使加 guard 仍不识别新 API。按项目需求明确选择 runner 中的 Xcode，不把 SDK 版本等同最低系统。
- 先 swiftc -frontend -parse 做语法预检；批量预检排除独立顶层测试脚本（Tests 等），避免把测试运行器入口当产品语法失败。
- AppIntents/WeatherKit 本身要求 iOS 16，guard 实际调用；复用普通业务逻辑时提取到不受限的共享类型，不能顺手禁用 iOS 15 的后台任务。
- 常见回移：NavigationPath→可绑定数组并保留 NavigationView 的程序化链接；Layout→真正可用的旧版布局；UIHostingConfiguration→UIContentConfiguration+UIHostingController；多行 TextField→TextEditor；Duration sleep→纳秒 sleep；Swift Regex/Locale.language→NSRegularExpression/Locale.languageCode；UITextView TextKit2、toolbar visibility、范围 lineLimit 均需旧版分支。
- ToolbarContentBuilder 在旧系统不支持条件项目时，把条件移入固定 ToolbarItem 的 ViewBuilder 内容，而不是删按钮。对 View 的 fontWeight 和对 Text 的 fontWeight 不混淆。
- 实际 CI 报错按轮修复。gh run view --log-failed 偶有日志截断，必须核对完成时间；需要时用 gh api repos/OWNER/REPO/actions/jobs/JOB_ID/logs 下载完整原始日志，不能因截断日志没有 error 就声称通过。
- 发布使用提交号唯一文件名，不能无故覆盖旧发行文件；下载后验 SHA256、ZIP 完整性、主 Info.plist MinimumOSVersion 及所有内嵌 Mach-O 的 LC_BUILD_VERSION/LC_VERSION_MIN_IPHONEOS。扩展最低版本不兼容可明确排除并披露功能缺失，不能伪造其最低版本。
- 无签名 IPA 不是任意设备可直接安装的软件；交付声明签名状态和安装前提。源码包包含相同提交、子模块精确 SHA、依赖与构建说明。区分编译通过、包结构检查和真机功能验证。

## 已验证案例边界
2026-10-16 OpenMinis IOS-MCP：最终 e5c38a8，macos-15/Xcode26.3、Go1.25.14，主目标15.4，云端 run38867152307成功；本地 ZIP CRC、发行 SHA256、主程序15.4及7个内嵌库14.0最低版本检查通过。最初610条编译问题→26条→编译成功，但 a7440be 包仍因强链接的第三方 VAD 库真实 minOS15.6不合格；替换为基础能量 VAD 后再次完整构建通过，并在 CI 发布前加原生载体最低系统校验。不要仅改该预编译库的版本字段伪装适配。未真机验证；能量 VAD 不等同原神经网络降噪，AppIntents、WeatherKit及排除的扩展在15.4不可用。不能证明所有功能正常。


## 启动闪退补充案例
- e5c38a8 已由用户报告在 iOS 15.4 / TrollStore 启动 SIGTRAP，前述包检查通过不表示能启动。先核对 LC_UUID；本次一致，但系统报告无 threads/usedImages，不能把绝对 PC 当无 ASLR 地址直接找函数。
- 主程序 minisAppGroupRoot、minisConfigRoot 和启动迁移三处对 containerURL 强制解包。App Group entitlement 不可用是确定性 nil 崩溃条件；回退路径必须共享同一持久 Library 目录，不能分散到临时目录或删除已有 Group 数据。有权限时保留旧路径。
- 91dedb4 已完成 macOS Foundation 回归：nil 容器回退、稳定路径、文件写入读回、有权限路径保持；云端 run38873271876完整构建成功。修复是否解决用户这次闪退仍需覆盖安装真机复测，不把候选地址匹配冒称完整符号化。
- 后续构建保留 dSYM 到私有 Release；诊断时结合 UUID、真实加载基址和完整线程，避免丢失符号后只凭猜测改代码。
