# 植物融合杂交版 2.0 / 王炸菜单 V2 案例

## 已观察到的失败

V1 菜单可显示，但功能处于未连接状态。原生备用小游戏的 ARM64 补丁测试通过，不代表用户截图里的城堡/英雄战斗有效。实际玩法是 WKWebView 中的 Cocos Creator H5 游戏。

## 采用的方法

追踪原生配置数组第 52 项的 SDK URL，再追踪实际游戏入口；静态解码业务 JS 的 26,734 项常量与 912 个模块。主包 `assets/main/index.3b2f6.js` SHA-256 为 `d140fbe160630c35adec5e052cab6a0b97b70edd6e568d56c62658cc63d86022`。这些版本信息仅用于历史证据，不适用于其他目标。

真实调用链 `CombatObj.attackTarget → recvDamage → chgHp`。旧 `calcDamage` 有未定义变量引用，不作为钩子依据。

- 秒杀：在 `chgHp` 修改我方阵营 1 对敌方 2/4 的负血量变化，临时设置 `bBreakDropHpLimit` 后恢复。保留无敌等命中前判定，不等同全屏清怪。
- `bRobot=1` 路径直接更新 hp；联网路径记录伤害并改 tmpHp，真实 hp 等待服务端。不能根据 tmpHp=0 宣称服务端确认死亡。
- 攻速：真实 `Skill.getCD/update`，只影响我方英雄。单位毫秒，典型 2000→125，最低 16 ms；处理旧冷却切换和新技能初始化，避免重复除以 16。
- 原生桥：WKUserScript DocumentStart、所有 frame、独立消息 handler；顶层定时下发带序号开关，逐层 iframe 转发；每 frame 心跳，具体错误提示，掉线/原型替换后恢复。

## 验证级别（截至本次交付）

- ARM64 iOS 12 动态库编译成功。
- 从真实解码函数提取的 11 项回归通过；依赖的引擎与网络环境为模拟。
- 1000 次 10 ms update：正常我方 4 次、加速我方 71 次、敌方 4 次。离散帧影响次数，不能将次数比声称为精确倍率。
- 35 个原生 section 保留；主程序 264 页、菜单库 27 页 CodeDirectory 哈希和 ZIP CRC 通过。
- **没有 iPhone 真机验证，也没有服务端接受高伤害的验证。** 用户认可交付，不改变这一证据边界。

## 本地可回查项目

`D:/Codex/杂交版植物大战僵尸/`

- `reports/H5_V2_REPORT.md`、`h5_regression.json`、`h5_package_verification.json`
- `tools/test_h5_features.cjs`、`build_h5_ipa.py`、`verify_h5_ipa.py`
- `src/PvZFeatures.m`、`PvZFeatures.js`、`FrostMenu.m`

案例模板已复制在本技能 `assets/wk-menu-example/`；它不包含游戏原始 IPA、SDK、登录响应或设备签名材料。新目标应重新确认模块名、导出格式、阵营、权威状态和方法签名。
