# 本机 AI 逆向、爬虫、密码恢复工具手册

核查日期：2026-10-12。GitHub 搜索是本次筛选快照，不代表覆盖全部项目。源码清单及固定提交见 source-inventory.json；星数证据见 catalog.json、crypto-catalog.json 和 github-search.json。API 限流缺失项不估算星数。

## 已安装与验证

|用途|安装结果|验证与限制|
|---|---|---|
|逆向|REA 6.4.0 + Ghidra 12.1.2 + Java 21|REA 已分析 whoami.exe；GhidraMCP 与 ReVa 扩展编译安装完成，GUI 插件需重启并启用|
|IDA|ida-pro-mcp 2.0.0，插件已写入 IDA 用户目录|需打开 IDA 并重启；Hex-Rays 官方另一项目要求 IDA 9.4，当前9.0，保留源码|
|爬虫|Crawl4AI 0.9.4、Scrapling 0.4.15、browser-use 0.13.11|Crawl4AI 实际抓取 example.com；browser-use 自主任务需要模型密钥|
|渗透框架|HexStrike Python 环境、Strix 1.7.0、PentestGPT 1.0.0|HexStrike API /health 返回 healthy，但仅检测到12/127项工具，4/8项基础工具；完整工具链仍待补齐；Strix 缺 Docker 与模型配置；PentestGPT 为 legacy CLI|
|密码恢复|WSL Hashcat 7.1.2、John 1.9.0、hashID、fcrackzip、pdfcrack|Hashcat 已识别 CPU OpenCL；GPU 尚未验证；John 为基础版，非 Jumbo|
|解码与密码分析|CyberChef MCP 4.2.0、Ciphey 0.12.1、RsaCtfTool 0.1.0、pyWhat 5.1.0|CyberChef 和 Ciphey 实际输出 Hello world；RSA 工具帮助命令通过，部分攻击需要 SageMath|
|密码学库|PyCryptodome、cryptography、gmpy2、SymPy、Z3、msoffcrypto-tool、pikepdf|独立 crypto-env，处理已知密钥解密、数学分析和文档加密|

## MCP 接入

Codex 配置：C:/Users/launca/.codex/config.toml。增量添加配置，备份记录见 config-backup.txt。重启 Codex 后加载新注册项。

10 个 MCP 已通过 initialize/tools/list：Playwright、Chrome DevTools、Context7、Sequential Thinking、Memory、Fetch、Scrapling、Serena、Ghidra GUI bridge、CyberChef。握手通过不等于所有外部后端已运行。Playwright 已实际导航；Memory 已读取图；CyberChef 已实际解码。

Fetch 在当前网络将 example.com 解析为198.18.0.64，触发非公网地址检查，实际抓取受阻；浏览器与 Crawl4AI 实测成功。Firecrawl 需要 API key；Firecrawl 和 jshook 的 npm 依赖审计发现高危项，已安装但禁用，证据见 npm-audit.json。没有自动执行强制降级修复。

CyberChef 使用本目录 runtimes/node26.exe，其他 Node MCP 保留原 Node 环境。CyberChef 提供23个 MCP 工具，其中工具封装多种操作，不把操作数当工具数。

## 选型与学习路线

二进制先用 REA 静态画像和反编译；需要 GUI 当前工程时用 GhidraMCP/ReVa 或 IDA bridge。网页静态内容优先 Scrapling/Crawl4AI；交互页面用 Playwright/Chrome DevTools；模型规划用 browser-use。Serena 用于源码符号导航，Context7 查询版本文档。Shannon、Strix 等独立自主框架先核对 Docker、模型与成本配置。

密码任务先区分：编码可逆无需密钥；哈希需要候选验证；加密需要密钥或具体弱点；文件口令还受文件格式/KDF影响。使用 pyWhat/hashID 辅助识别后核对格式。Hashcat 用于离线候选验证，John 基础版格式覆盖较少。CyberChef 适合可解释配方，Ciphey 适合自动尝试常见编码；RSA 先检查参数关系再用 RsaCtfTool。强加密或高熵口令不存在通用快速解法。执行恢复时记录输入哈希、格式、资源预算及结果证据，保留原文件。

## 本机命令

PowerShell 先运行 `. .\Activate-Toolkit.ps1`，仅修改当前会话 PATH。

- `wsl -d Ubuntu -- hashcat -I`：设备检测。
- `wsl -d Ubuntu -- john`：格式/版本帮助。
- `& .\ciphey\ciphey.exe -t SGVsbG8gd29ybGQ= -d`：解码验证。
- `RsaCtfTool --help` / `what --help`。
- `& .\crypto-env\Scripts\python.exe`：独立密码学环境。
- `scrapling mcp`：启动爬虫 MCP。
- HexStrike 环境：WSL `/root/.local/share/hexstrike-env`，源代码位于 `/mnt/d/Codex/小飞机/ai-toolkit/repos/0x4m4--hexstrike-ai`。本机 API 启动脚本 `start_hexstrike.py` 仅监听127.0.0.1:8888，停止时 Ctrl+C。

工具脚本使用上游原版。源码下载和 CLI 安装与完整运行分别列出，不把依赖待配项目标成部署完成。没有下载大模型，没有配置付费密钥，没有开展外部目标扫描或密码攻击。

## 持久技能与维护

新增 local-ai-research-toolkit、local-crypto-recovery 两个技能，保存在 C:/Users/launca/.agents/skills，引用本手册与证据。所谓学习是可复用技能和本地资料整理，不是改变模型训练权重。

更新前查看官方 README、版本约束与依赖审计，再更新对应隔离环境。不要覆盖其他 MCP 配置；回退时按 mcp-entries.json 逐项移除本次添加的同名配置，先比较现值并保留后续人工修改。备份文件可用于对照。

HexStrike API 已完成本机健康检查并停止临时服务，未驻留后台。angr 环境固定 bitstring 4.3.1、pycparser 2.22 以解决上游新版本接口不兼容。
