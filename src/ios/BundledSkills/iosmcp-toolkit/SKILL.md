---
name: iosmcp-toolkit
version: 1.0.0
description: IOS-MCP 内置工具集使用指南。当用户需要在设备端进行 iOS 逆向、Theos 插件编译、脚本处理或越狱工具操作时使用，涵盖内置工具的位置与用法。
---

# IOS-MCP Toolkit

本技能描述 IOS-MCP 内置的开发与逆向工具集。所有工具运行在设备内 Linux 沙箱（iSH，aarch64 Alpine）中。

## 工具位置

- Python 3: `python3` / `pip3`
- 编译工具链: `clang`、`make`、`cmake`、`git`
- Theos: `$THEOS`（默认 `/opt/theos`），含精简 iOS SDK headers
- 逆向工具: `lldb`、`gdb`、`nm`、`objdump`、`strings`、`file`、`class-dump`
- 签名工具: `ldid`
- 网络: `curl`、`wget`、`openssh-client`

## 常用流程

### 编译一个 Theos 插件（Tweak）

```bash
export THEOS=/opt/theos
export THEOS_DEVICE_IP=127.0.0.1  # 本机沙箱
# 创建项目
$THEOS/bin/nic.pl  # 或手工布局
# 在项目目录下：
make clean && make
# 产物 .deb / .theos/_ 目录
```

### 快速逆向一个二进制

```bash
file <target>
strings <target> | grep -iE "http|key|secret"
nm -gU <target> 2>/dev/null | head
class-dump -H <target> -o /tmp/headers
```

## 注意事项

- 沙箱为 root 全权限运行（越狱环境），可直接读写 /var、/usr 等真实目录
- 编译插件需要 iOS SDK headers，精简版仅含 Foundation/UIKit 等核心头，缺头文件时用 `apt`/手动补
- 设备端编译较慢，小插件可用；大工程建议在 PC 上交叉编译后拷贝产物
