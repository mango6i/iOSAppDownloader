# 更新日志

## v1.0.7 — 2026-09-14

### 中文

- 移除会导致 `0xC0000142`、Rust `unwrap` 异常和登录闪退的 `pywinpty/ConPTY` 登录路径。
- 恢复已验证可用的 `ipatool-rs` 非交互式登录与双重认证续接流程；验证码提交固定复用首次登录使用的网络线路。
- 验证码提交后再次读取真实账号状态，避免仅凭一次命令输出误判正确验证码失败。
- 修复已登录账号查询从未获取过的免费应用时出现 `unexpected response: empty songList`：官方列表查询现在会同时传入 App ID 和 Bundle ID，自动获取一次免费许可后重试；付费应用不会自动购买。
- 如果 Apple 在获取免费许可后仍返回空官方列表，自动回退到“免登录查询”填充历史版本表，不再弹窗阻断操作。
- 将内置 `ipatool.exe` 放入独立运行目录，避免与 PyInstaller 内的 Python/Qt DLL 发生加载冲突。
- 打包配置允许在没有本地 SAP 种子缓存时正常构建，并将程序文件名和文件属性升级为 `iOSAppDownloader_v1.0.7.exe`。

### English

- Removed the `pywinpty/ConPTY` sign-in path that could fail with `0xC0000142`, Rust `unwrap` panics, or an application crash.
- Restored the proven non-interactive `ipatool-rs` sign-in and two-factor continuation flow, keeping verification on the same network route as the initial challenge.
- Rechecks the actual account session after code submission instead of rejecting a valid code from one command result.
- Fixes `unexpected response: empty songList` for free apps never obtained by the signed-in account: the official lookup now supplies both App ID and bundle ID, obtains the free license once, and retries. Paid apps are never purchased automatically.
- Falls back to Login-free lookup when Apple still returns an empty official list after the free-license retry, keeping the history table usable instead of blocking with an error dialog.
- Packages `ipatool.exe` in an isolated runtime directory to prevent DLL collisions with bundled Python and Qt libraries.
- Allows builds without a local SAP seed cache and updates the executable name and metadata to `iOSAppDownloader_v1.0.7.exe`.

## v1.0.6 — 2026-09-04

### 中文

- 重做 Apple ID 登录流程：使用 Windows 真实伪终端承载单个 `ipatool-rs` 进程。
- 密码和双重认证码在同一个登录会话内完成，保留 Apple Cookie 与 SAP 签名状态，避免验证码被新进程判定为过期。
- 登录命令不再把密码放入命令行参数；登录结束或退出软件时仍会清理临时会话。
- 增加 `pywinpty` 运行依赖，并加入打包隐藏导入配置。

### English

- Reworked Apple ID sign-in around one `ipatool-rs` process hosted by a real Windows pseudo-terminal.
- The password and two-factor code now use the same Apple session, preserving cookies and the SAP signer so codes are not invalidated by a second process.
- The password is no longer placed in the command-line arguments; the temporary session is still cleared when signing out or exiting.
- Added the `pywinpty` runtime dependency and packaging hidden imports.

## v1.0.5 — 2026-09-02

### 中文

- 修复正确验证码已经完成 Apple 验证，却被软件直接提示“验证码未通过”的误判。
- 验证码提交后先检查真实账号状态；状态尚未写入时，会自动用同一路线完成一次会话确认，不再要求用户手动反复登录。
- 设置窗口底部增加当前软件版本号。
- 修复历史版本 ID 按文本排序导致旧版本错位的问题，现改为数值排序。
- 历史版本表重新固定列宽并居中显示；无法取得的版本、大小或日期显示为统一的短横线，不再让“下载时获取”等提示挤入数据列。
- 打包程序文件名改为 `iOSAppDownloader_v1.0.5.exe`，文件属性版本同步更新。

### English

- Fixed valid Apple verification codes being prematurely reported as rejected.
- The app now verifies the real account state after code submission and automatically completes the session on the same route when necessary.
- Added the current software version at the bottom of Settings.
- Fixed old version IDs being misplaced by text sorting; IDs are now sorted numerically.
- History columns now have stable widths and centered values; unavailable metadata uses a consistent dash instead of status text inside data columns.
- Renamed the packaged executable to `iOSAppDownloader_v1.0.5.exe` and synchronized its file metadata version.

## v1.0.4 — 2026-09-02

### 中文

- 修复登录长时间停留在“登录中”、无法显示验证码输入步骤的问题。
- 恢复最初已验证可用的 `ipatool-rs` 无界面双重认证流程，首次请求触发验证，验证码请求固定复用同一网络线路。
- 修复关闭设置窗口后，未完成的登录任务仍弹出 `login cancelled` 错误的问题。
- 保留验证码空格、短横线和全角数字自动整理，以及验证码被拒绝时的明确提示。
- 打包程序文件名改为 `iOSAppDownloader_v1.0.4.exe`，文件属性版本同步更新。

### English

- Fixed sign-in remaining stuck without revealing the verification-code step.
- Restored the proven non-interactive `ipatool-rs` 2FA flow and pinned the code submission to the same network route that created the challenge.
- Closing Settings during an unfinished sign-in no longer shows a late `login cancelled` error.
- Preserved verification-code normalization and clear rejected-code guidance.
- Renamed the packaged executable to `iOSAppDownloader_v1.0.4.exe` and synchronized its file metadata version.

## v1.0.3 — 2026-09-02

### 中文

- 修复双重认证状态提示文字被裁切或遮挡的问题，增加设置窗口空间并优化换行。
- 双重认证改为使用 `ipatool-rs` 官方交互流程：同一个登录进程保持 Apple Cookie、SAP 会话和代理线路，验证码不再通过第二个新进程提交。
- 修复验证码失败后只会反复提示输入、却不说明验证码被拒绝的问题；现在会明确提示重新获取新验证码。
- 验证码支持粘贴带空格、短横线或全角数字的形式，并会自动转换成 Apple 接受的 6 位半角数字。
- 优化无推送通知时的提示：Apple 会自动尝试发送设备通知，没有弹窗时仍可在手机上手动获取验证码。
- 打包程序文件名改为 `iOSAppDownloader_v1.0.3.exe`，文件属性版本同步更新。

### English

- Fixed clipped or overlapping two-factor authentication text in the Settings dialog.
- Switched 2FA to the official interactive `ipatool-rs` flow, keeping the Apple cookies, SAP session, process, and proxy route alive while the user enters the code.
- Fixed rejected codes causing an endless generic code prompt; the app now clearly asks for a newly generated code.
- Pasted verification codes containing spaces, hyphens, or full-width digits are normalized to the six ASCII digits Apple accepts.
- Improved the fallback guidance when Apple does not show a trusted-device notification.
- Renamed the packaged executable to `iOSAppDownloader_v1.0.3.exe` and synchronized its file metadata version.

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
