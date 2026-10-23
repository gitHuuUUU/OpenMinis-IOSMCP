# Cockpit 与其他供应商共存

本版基于 `ed88573`，保留 OLLVM 离线安装修复、输入栏图标清理和原有供应商。Cockpit 是独立的 OpenAI 兼容账号预设，不接管已有账号、默认模型、会话绑定或其他供应商的密钥。

## 手机首次使用

1. 覆盖安装前备份会话与配置；安装后彻底退出再重开。
2. AI 账号 → 添加 AI 服务商 → Cockpit。
3. 默认局域网 `http://192.168.0.39:61722/v1`；同一 Wi-Fi 下使用。也可一键选 Tailscale `http://100.116.107.1:61722/v1`，两端均须连接对应网络。电脑 IP 改变时可编辑地址。
4. 填入自己的网关 API Key 后添加；地址已含 `/v1`，无需再追加。密钥通过现有每账号 Keychain 存储，不放入 IPA、源码、日志或普通配置。可继续添加/使用其他服务商。
5. 在对话模型选择中选择该 Cockpit 账号下的真实模型，发送“只回复OK”。需要时可切换 Chat Completions / Responses API 协议；新增账号不会自动改变已有对话的模型。

不内置私人密钥意味着需要首次填写一次，不能称为安装后自动登录。此包可分享，但内置的两个电脑地址是可见的连接提示。

## 模型与错误状态

- 内置目录保留原 223 项并新增 Cockpit 三个已从网关返回的 ID：`gpt-6.1-sol`、`gpt-6-astra`、`gpt-6-sol`。
- 公共目录网络刷新和旧磁盘缓存不会移除本地 Cockpit。其他供应商内容不受其影响，私有网关元数据不进入跨供应商能力/价格/版本推断。
- 已知端点有离线模型目录，不表示网络已连接或密钥有效；生成请求仍发给选定端点。刷新只保留实际返回的模型列表，不用内置列表伪造在线模型。
- API-key 模型缓存按解析后的 endpoint、密钥及影响结果的请求选项隔离；同一个密钥配置在不同端点也不会串模型。
- 电脑端 `/models` HTTP200 不等于手机能连或生成可用。401检查网关密钥，连接失败检查网络/防火墙，503是网关/上游服务不可用，不会自动借用其他供应商账号发送。

## 构建和验证

- macOS/Xcode26+，iOS最低15.4，沿用 `BUILDING.md` 和 `.github/workflows/build-ipa.yml`；固定离线 OLLVM 资源和源说明见 `deps/ollvm/README.md`。
- 新增回归：`python3 tools/test_cockpit_coexistence.py`、`python3 tools/test_cockpit_catalog.py --require-swift`、`python3 tools/test_openai_model_cache.py --require-swift`。
- Cockpit 是源码整合后在签名前生成资源，不再对旧 IPA 签名后的 JSON 做热补丁。CI 对 TrollStore、普通证书载体分别执行 `codesign --verify --deep --strict`，最终再检查资源封签、真实权限、ZIP/CRC、最低系统和资源/源码对应关系。
- 普通自签载体需要自己的有效证书和描述文件重签；RootHide/TrollStore和普通自签权限不同。构建与探针不能替代 iPhone 真机启动、UI、温控、手机到网关端到端验证。
