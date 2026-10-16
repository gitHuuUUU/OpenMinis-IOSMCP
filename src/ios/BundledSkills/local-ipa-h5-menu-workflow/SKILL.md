---
name: local-ipa-h5-menu-workflow
description: Analyze IPA game execution paths and implement native menus backed by the actual native or WKWebView/H5 gameplay. Use for IPA menu development or menus that appear but have no gameplay effect; not for ordinary website development.
---

# IPA 游戏菜单：先定位后端，再交付

用户偏好：同时提供插件/安装包等产物与对应源码包、构建说明、验证报告；不要只交付界面或代码片段。

## 决策顺序

1. 核对输入 IPA/源码、包结构、架构、加密状态、加载库、主程序身份与用户截图。确认真正运行的是原生游戏、Unity 还是 WebKit/H5。原生伪代码、资源名称和菜单出现本身不足以证明目标正确。
2. 若是 WKWebView，追踪配置响应、加载请求、SDK/登录壳、重定向与游戏 iframe，定位实际业务包。只获取本次任务所需材料，不复制会话/凭据到交付包。
3. 优先沿实际伤害/冷却调用链定位可验证的方法。对于混淆 JS，静态解码常量并提取关键模块；区分活跃接口和遗留方法，先看调用方再挂接。
4. 确定状态权威：本地血量、预测血量、服务器确认血量不可混同。界面写出真实连接状态、命中计数和待确认结果。

若 IPA 已含第三方菜单/验证模块，先审计输入是否已经被部分修改；递归检查框架依赖闭包中的独立验证，再分别追踪 ObjC `+load`、Mach-O `__mod_init_func` 和绘制启动链。不要清空整个初始化数组，也不要重复修改已经返回真的入口。相关失败案例及修复候选的验证边界见 [references/honor-native-verification-case.md](references/honor-native-verification-case.md)。多模块修复必须明确要求一并替换，不能仅交付其中一个模块让用户误装。

## WK/H5 菜单实现经验

- 原生菜单状态与游戏脚本状态分离；功能默认关闭，主题等外观设置可单独保存。
- 在页面加载前安装所有 frame 的用户脚本；检查多层跨域 iframe 的状态传递。不要替换游戏原有导航代理。
- 使用重试、脚本版本检查、每 frame 心跳与明确诊断；SDK 外层未就绪消息不能覆盖内层游戏已就绪消息。不要把首次失败永久缓存。
- 保留原方法参数、返回值和异常行为；临时字段在 finally 恢复。保持治疗、阵营、敌方速度等无关路径不变。
- 冷却修改须核对单位、旧剩余冷却转换、新对象初始化与 ON/OFF，避免重复缩放。不要为局部攻速修改全局时间。
- 模块/原型被游戏重载时检查钩子并恢复；重复安装不得多重包装。

## 验证与交付

- 尽可能从真实解码模块提取函数做回归；模拟网络依赖时明确说明，不把模拟服务器结果冒称真实网络验证。
- 覆盖默认关闭、阵营隔离、治疗、异常恢复、状态切换、新对象、延迟模块、重复注入、多层 frame 和钩子重载。
- 编译只是一级证据；另查导出符号、依赖、包内脚本和版本、Mach-O 加载命令、ZIP CRC、签名页哈希。不要信任仅返回 0 的假签名脚本。
- 若修复旧版错误目标，从原始包重建并检查无关原生 section 未被改动，不叠加旧补丁。
- 产物和源码使用相同版本名；附构建/签名流程、校验值、诊断说明及尚未完成的真机/服务端验证。需要设备重签则标明。

具体案例、方法及证据见 [references/pvz-v2-case.md](references/pvz-v2-case.md)。需要实现 WK 桥或菜单时可参考 `assets/wk-menu-example/`，这是特定版本案例，必须适配当前目标，不能直接承诺通用有效。
