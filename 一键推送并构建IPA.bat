@echo off
chcp 65001 >nul
echo ============================================
echo   IOS-MCP IPA 一键构建（全自动）
echo ============================================
echo.
echo 需要：1) GitHub token（https://github.com/settings/tokens
echo        Generate new token(classic) - 勾 repo - 有效期7天）
echo        2) GitHub CLI（未装则运行: winget install GitHub.cli）
echo.
set /p TOKEN=粘贴 ghp_ 开头的 token 后回车: 
if "%TOKEN%"=="" echo 未输入 token，退出 & pause & exit /b
echo.
echo [1/5] 登录 GitHub...
echo %TOKEN% | gh auth login --with-token
if errorlevel 1 echo 登录失败：token 无效或未勾 repo 权限 & pause & exit /b
echo.
echo [2/5] 提交本地改动...
cd /d "%~dp0"
git config user.email iosmcp@local.build
git config user.name IOS-MCP
git add -A
git commit -m "IOS-MCP 二开: 换皮/iOS15兼容/Skills/全权限/工具集/GA流水线" 2>nul
echo.
echo [3/5] 创建私有仓库并推送...
for /f %%u in ('gh api user --jq .login') do set GH_USER=%%u
gh repo create %GH_USER%/OpenMinis-IOSMCP --private --source . --push --remote iosmcp
if errorlevel 1 echo 推送失败：网络或 token 权限问题 & pause & exit /b
echo.
echo [4/5] 触发 macOS 云构建（约 30-60 分钟）...
gh workflow run -R %GH_USER%/OpenMinis-IOSMCP "Build IOS-MCP IPA"
if errorlevel 1 echo 触发失败：确认仓库里存在 .github/workflows/build-ipa.yml & pause & exit /b
echo.
echo [5/5] 完成！
echo.
echo 构建进度查看:  https://github.com/%GH_USER%/OpenMinis-IOSMCP/actions
echo 构建完成后下载 artifact "IOS-MCP-unsigned-ipa"，解压即得 IOS-MCP.ipa
echo 用 TrollStore 安装即可。用完后去 https://github.com/settings/tokens 删除该 token。
pause
