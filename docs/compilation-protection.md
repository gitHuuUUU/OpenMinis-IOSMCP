# MinisRe 编译保护：五项能力与验证边界

## 使用
1. 覆盖安装本轮 TrollStore 包后彻底退出并重新打开 MinisRe，保留原会话与配置，不必先卸载。
2. 设置 → 编译保护 → 保护编译组件 → 安装／修复。内置离线资源按需安装，旧三项版本会升级到 runtimeVersion 2；需要至少 1.5 GB guest 可用空间。
3. 编译模式选「强化」，保护方式选「单项」或「组合」，勾选需要的能力。
4. 点击「检测选中编译器与保护能力」；摘要显示当前真实检测结果，完整 JSON／日志可从详情复制。
5. 在构建工作台选择本地 C/ObjC/C++ dylib 或 Theos **源码**项目的 DEB 构建。保护设置会传入本轮构建，不会只改变界面。

默认内置编译器：`/opt/minis-protection/bin/clang`；不会覆盖系统 clang 或 ldid。不要把普通 Clang 路径当作已支持混淆的编译器。普通模式不执行保护，也不会因打开设置页自动反复启动 LLVM。

## 能力
| 选项 | 实际行为 |
| --- | --- |
| 分支保护 bcf | 为适用代码增加虚假条件分支 |
| 调用保护 indcall | 把适用直接调用／invoke 通过可变表和 volatile 读取间接化 |
| 数据访问保护 indgv | 把适用全局数据地址访问通过指针表间接化 |
| 字符串加密 sobf | 处理引擎支持的字符串全局变量，隐藏对应明文 |
| 控制流强化 fla | 平坦化适用函数的控制流 |

单项模式严格只选一项，组合模式至少一项；缺失、失败或未选择都会报错，不静默回退成普通编译。组件体积来自实际安装文件，不填固定数字。

## Theos 接线和产物校验
源项目需有引用 THEOS 的 Makefile、真实 SDK、链接工具和项目依赖。保护前端接入 TARGET_CC/TARGET_CXX；保留 Theos 的链接流程，支持仅链接调用的透传，不把混淆参数错误交给链接器。

内置强化路径使用真实静态 ARM64 ldid 签名，并检查新 DEB 内实际 thin arm64 Mach-O 的 CodeDirectory 逐页哈希后才原子交付。旧输出不会被失败产物覆盖。签名结构／页面哈希不等于 Apple 证书信任或手机安装成功。

## 不覆盖的范围
- 不是原生 iOS 编译器进程；Clang/LLVM 在手机内置 ARM64 Linux guest 中运行，再交叉生成 iOS arm64 产物。
- 不通过重新打包已有 IPA／DEB 添加源码保护；Swift、APK、EXE 不由本引擎保护。
- 当前签名复核需要 thin arm64，Theos 项目使用 `ARCHS=arm64`；fat 多架构输出会明确拒绝。
- intrinsic、inline asm、musttail/callbr、TLS、ABI 特殊 section 等边界有意保留；指针间接化不等于不可逆加密，也不是每一种调用和数据形式都适用。
- 不保证任意源码、Logos 插件、第三方静态库都能直接保护；遇到不支持的编译模式会报告具体失败。

## 构建与复测
完整依赖、固定提交与许可证见 `deps/ollvm/README.md`。运行时资源的精确来源、长度和 SHA256 由 `tools/ollvm-runtime-catalog.json` 固定，先 `python3 tools/prepare_ollvm_workbench.py` 校验并准备资源，再按 `.github/workflows/build-ipa.yml` 用 macOS/Xcode 构建。

原生 ARM64 回归入口为 `tools/run_protection_native_ci.sh`；依次执行 31 个非空组合的实际运行／IR 检查、C++ 异常边界、iOS15.4 arm64 dylib 链接、真实 ldid 签名、Theos 普通／强化 DEB 编译签名，以及实际 shipped rootfs 的离线安装与 curl/git 保持检查。每一关失败均停止发布。最终交付 `verification.json` 记录已完成的 CI 与资源校验。

真机请验证：覆盖安装启动 → 安装／修复组件 → 单项调用保护检测 → 单项数据访问保护检测 → 五项组合检测 → 构建自己的 small Theos arm64 项目 → 导出 DEB 与日志。真机安装、运行、温度和 FPS 没有自动由 Linux 测试或 Xcode 编译证明。
