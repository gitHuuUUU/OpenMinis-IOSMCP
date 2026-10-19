# MinisRe 扩展包导入器

## Markdown 与 ZIP 兼容性补充

设置入口现支持直接选择 `.md`（最多64000字节），按文件名生成稳定包名与manifest；UTF-8、带BOM的UTF-16、GBK/GB18030文本归一化为UTF-8，预览确认后仅作为追加指令启用，支持同名处理、禁用及卸载，不自动执行文件。即使文件名是SKILL.md，也不会自动变成技能；真正技能仍需使用标准ZIP内skills结构。所有Markdown经过相同的指令安全扫描，不能用改扩展名绕过。

ZIP支持UTF-8及未标记UTF-8的GBK/GB18030文件名，本地/中央目录仍比对原始文件名字节，解码后再次严格防路径逃逸；兼容“一个外层目录包着标准manifest”的ZIP。非标准的多分类资料包不自动生成manifest或悄悄丢弃脚本。RAR/7z、分卷、超限、编码、加密和压缩算法错误现在分别显示具体原因。

用户提供的普通渗透/逆向技能资料ZIP为760项、381文件（其中181个Python脚本），不是超过1000项；它使用GBK文件名、没有扩展manifest，仍不能按既定的无可执行文件扩展规则直接安装。此诊断不等于这些脚本已完成安全审查或可以自动执行。模型越狱/覆写约束的内容不因新入口而获得安装许可。

基线：42766e972e2fe3508b3c7232614ccc40810bd933；目标 iOS 15.4+。
本文按用户提供的三节包规范及此前的安全、测试、交付要求组织；不存在未提供的“第六节原文”。

## 1. 包格式与兼容性

ZIP 根目录必须包含 `manifest.json`，可包含 `instructions.md`、`skills/<id>/SKILL.md`、`providers.json`、`assets/`。

```json
{
  "name": "my-pack",
  "version": "1.0.0",
  "description": "项目开发偏好与文档技能",
  "author": "作者",
  "minis_version": ">=1.0",
  "contents": ["instructions", "skills", "providers"]
}
```

`contents` 必须与实际存在内容一致；包名/技能 ID 为 1–64 位字母、数字、下划线、横线，首位是字母或数字。
版本要求支持 `>=1.0.0`、精确版本或 `*`，不支持的版本范围拒绝而非忽略；本应用版本是 1.0，示例中的 `>=1.2.0` 会被正确拒绝。

`providers.json` 格式是数组（不直接接受现有应用完整配置，以免批量覆盖）：

```json
[
  {"label":"示例服务商","providerType":"openAI","endpoint":"https://example.com/v1","api_key":""}
]
```

支持 openAI/openAIResponses/anthropic/gemini/openRouter/xAI，最多 30 项；endpoint 必须 HTTPS，禁止 URL 内用户名、密码、查询串、fragment；URL 按原样作为 baseURL，不自动追加 v1。
Key 可留空，之后在现有服务商设置里填写；非空时仅在内存和 Keychain 间传递。

## 2. 五步导入

1. 设置 → 扩展包导入器 → 文件导入，或 HTTPS 下载并预览；本地文件读入前检查大小，远程下载前 HEAD 检查 Content-Length，GET 响应和每个数据块再次检查。
2. 工作线程校验 ZIP/manifest/全部内容后，解压到 UUID 临时目录；任何校验失败即拒绝。ZIP 不落入应用暂存目录；providers.json 在写临时目录之前剥离 api_key。
3. 展示包名、版本、作者、内容、路径、覆盖技能、待确认 provider；同名包有覆盖/重命名/取消；未确认不修改有效配置。
4. 确认安装后移入扩展目录；密钥写 Keychain 并读回验证。Provider 仍处于待确认状态，必须进入包详情逐条确认 endpoint 与数据发送说明。
5. 列表编辑按钮提供拖动排序，详情提供启停与卸载；配置审计页记录成功/失败/拒绝/取消和 provider 确认，不记录指令、endpoint、密钥。

## 3. 目录与生效

首次引入专用约定：`~/.minis/extensions/<name>/`，这里的 `~` 是本应用 iOS 沙盒主目录，**不是** Linux guest 的 `/root` 或 iOS `/var/mobile`。
私有状态/原技能备份放在同级 `~/.minis/extension-state/`，不暴露为 iOS 文件提供器目录。

- 指令：只能追加；扩展启用时强制保留应用原始 base，不受已有 prompt-library 的关闭内置开关影响；请求前再次扫描磁盘指令，防止安装后修改绕过扫描。上下文中标记为低优先级任务偏好，不能替代基座。
- 技能：复用 `SkillStore` 的数据库、元信息、rootfs/fakefs 注册和正常技能发现路径；同名完整目录替换，先备份原件及启用状态；多个包冲突时列表后者优先，禁用/卸载恢复上一个启用包或原件。
- Provider：安装绝不合并；确认后通过现有 `ProviderConfigStore` 接入。禁用设置 provider.isEnabled=false，重新启用恢复；卸载/覆盖删除旧 provider、关联模型/组引用和 Keychain 项，不触碰其它用户服务商。
- 在途会话：不强行修改已经发给模型的内容或中断任务；显示“本轮可能继续使用旧内容，下次请求生效，可取消当前任务”的提示。已暴露给某 provider 的历史内容无法撤回。

## 4. 安全约束与边界

- ZIP 与总解压量各 50 MiB；最多 1000 项（含目录）；单独 instructions.md 最大 64 KB，manifest 最大 64 KB。
- ZIP slip、绝对路径、反斜杠/盘符、控制字符、链接/特殊文件、重复/大小写冲突、本地头与目录不一致、重叠条目、CRC 错误、截断、解压尺寸不符均拒绝。
- 只允许 md/json/txt/png/jpg/jpeg/gif/webp；拒绝脚本、二进制、SVG/HTML 以及明显伪装为资源的 ELF/PE/Mach-O/shebang 文件；ZIP64、分卷、加密 ZIP 不支持。
- 指令规范化后扫描中英文绕过安全/限制、禁用拒绝、覆盖系统指令等语义模式；采用保守规则，可能拒绝包含相关词语的正常说明。它不是完整自然语言安全证明，仍必须保留模型/服务端本身的约束。
- 输入 ZIP 可能本来就含明文 key，那是用户选择的外部文件；导入器不拷贝该 ZIP，不把其中 key 写到自己的扩展目录、临时目录或日志。请妥善保管或删除原始 ZIP。
- 一次性安全校验与目录替换不是对本机已获文件写权限攻击者的完整隔离；强杀/断电时的跨文件系统事务恢复与恶意本地篡改不在本轮验证保证内。
- 本轮只提供 iOS UI，不增加未接线的空壳 CLI；不改变 Android。

## 5. 测试入口

```sh
python3 tools/test_extensions.py --require-swift
```

调用真实 `ExtensionPackageReader`、`ExtensionStore`、`ExtensionDownload` 源文件；文件系统是真实临时目录，宿主技能接口/provider/Keychain 为测试替身，不宣称等价 iPhone Keychain 真机验证。
32 种 ZIP fixture 覆盖正常 deflate/stored、大小写技能名、路径、manifest、CRC、数量、解压超限、链接、伪装程序/可执行权限、目录无 SKILL、指令拒绝、provider 等；生命周期覆盖预览不生效、安装、确认、禁用启用、冲突恢复、排序、重命名、取消、覆盖后确认失效、重启持久化、Keychain 失败回滚、审计及密钥不落盘。
远程 HTTP 的具体请求与超限处理另外由 URLProtocol 测试；iPhone 网络与文件选择器、真机安装、真实 provider 调用需要设备复测。

## 6. 交付验收项

以交付报告记录实际结果，不把本文的测试清单预先标作成功：
格式/manifest、五阶段导入、路径/大小/白名单、预览三选一、技能替换恢复、基座保留、Keychain、二次确认、启停卸载排序审计、在途提示、既有回归、IPA 包结构/权限/最低系统、真机验证。
