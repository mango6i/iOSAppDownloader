# 更新日志

## v1.0.1 — 2026-09-01

### 中文

- 修复重复搜索或切换历史版本时，旧线程结果覆盖新结果的问题。
- 搜索结果图标改为并发加载并加入缓存，减少等待时间。
- 修复工具输出在部分 Windows 环境中出现乱码的问题。
- 修复多个下载任务的总进度被未知大小任务错误拉低的问题。
- 修复英文界面中的登录、搜索、历史版本、下载和安装包管理文案缺失。
- 修复英文界面“取消 / 否”按钮无法正确取消的问题。
- 修复 SOCKS 代理被错误当作 HTTP 代理使用的问题。
- 修复 PyInstaller 配置使用不存在的 `__file__` 导致无法打包的问题。

### English

- Fixed stale search/history worker results overwriting newer results.
- Search result icons now load concurrently and use a bounded cache.
- Fixed garbled tool output on some Windows locales.
- Fixed overall download progress being pulled down by unknown-size tasks.
- Completed the main English UI for sign-in, search, history, downloads, and package management.
- Fixed English Cancel/No buttons not cancelling dialogs correctly.
- Fixed SOCKS proxy endpoints being incorrectly labeled as HTTP proxies.
- Fixed the PyInstaller spec failing because `__file__` is unavailable in spec execution.

### 已知限制 / Known limitation

The bundled `ipatool-rs` command-line component currently accepts the Apple ID password only through its `--password` argument. The application does not log or persist that argument, but removing the password from the process command line requires an upstream `ipatool-rs` change or rebuild that supports secure stdin/file input.
