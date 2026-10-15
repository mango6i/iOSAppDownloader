# 更新日志

## v1.0.7 审查修订发布 — 2026-10-15（同版本覆盖）

- 完整过滤 IPA 文件名的名称、版本和 ID 字段，加入应用 / 历史版本 ID，防止路径越界、同名应用或空版本号互相覆盖。
- 下载完成及已有文件检查改为校验 IPA 容器、应用 Info.plist 和包名，不再仅凭文件大小判定成功。
- 修复暂停 / 取消发生在下载进程启动前时仍继续下载的竞态，以及输出读取异常时的进程 / 监控线程收尾。
- 搜索、图标和历史查询贯通取消信号；HTTP 重试共用超时预算，限制响应体大小、历史分页等待时间和图标缓存字节数。
- 退出时取消全部工作线程，并等待线程结束再退出 Qt；下载期间不允许重新登录或注销清除在用凭据。
- 清理已退出进程遗留的本软件会话目录，不处理仍运行的实例、不跟随链接、不删除非敏感运行缓存。
- 删除无调用的旧 Apple Cookie / 购买 / IPA 补丁代码和空配置接口；源码测试不再依赖预先下载的组件。
- 当前源码目录仅保留一套原版源码、必要资源、许可证、当前发布说明及回归检查。旧源码副本、测试成品和构建缓存移入回收站。
- 安装包列表忽略同名目录和并发删除的文件，避免刷新失败。新增检查后共 55 项离线回归通过。完整说明见 `docs/PROJECT_AUDIT.md`。按用户要求保持版本号 1.0.7，同步更新 GitHub 源码、发布说明和成品，并覆盖桌面正式版。

## v1.0.7 修订发布 — 2026-10-13

- 修正构建机字体差异造成的文字高度检查误报，按实际宽度检查换行文本，并增加长状态提示滚动检查及完整构建检查日志。
- 每次主动点击登录 / 重新登录前清理旧的本地凭据及 Cookie，清理失败则停止登录；验证码续接保留当前挑战。此操作不撤销 Apple 服务端设备信任，也不保证每次收到验证码。
- 登录成功后点击“确定”同时关闭设置 / 登录窗口，回到主界面，保留已登录会话；失败或等待验证码时仍保持窗口打开。
- 保留远端的弹窗不透明背景、长文案和状态卡片滚动修复，移除已经弃用的独立 Python 认证及其打包依赖。
- 修复自动代理检测缺少端口列表定义导致点击登录立即出现 NameError；新增实际登录入口、代理回退和未定义名称检查。
- 原版改用官方 majd/ipatool v2.7.0：新版签名认证、重定向处理、手机号账号、版本列表 / 元数据与历史 IPA 下载。
- 正确区分验证码挑战、认证成功和组件 / 网络错误；移除验证码自动重放和无验证码自动重登。
- 登录可取消、线路共用总超时；独立临时凭据目录和随机加密口令，正常退出清除凭据 / Cookie，运行组件缓存单独保留。
- 修正双重认证提示区域高度，增加接口与成品检查；软件版本和 EXE 名称仍保持 1.0.7。
- 用户已确认本次测试版登录成功；下载未在自动检查中使用真实账号验证。不接入 MCP 或其他平台界面。详见 docs/releases/v1.0.7.md。

## v1.0.7 — 2026-09-14

### 中文

- 移除会导致 `0xC0000142`、Rust `unwrap` 异常和登录闪退的 `pywinpty/ConPTY` 登录路径。
- 恢复已验证可用的 `ipatool-rs` 非交互式登录与双重认证续接流程；验证码提交固定复用首次登录使用的网络线路。
- 验证码提交后再次读取真实账号状态，避免仅凭一次命令输出误判正确验证码失败。
- 修复验证码提交后 Apple 仍要求双重认证时又自动发起无验证码登录补救的问题，避免界面表现为“一直提交”。
- 关闭或退出软件时会主动撤销并删除本地 Apple 登录会话，下次打开需要重新登录和重新完成双重认证。
- 修复已登录账号查询从未获取过的免费应用时出现 `unexpected response: empty songList`：官方列表查询现在会同时传入 App ID 和 Bundle ID，自动获取一次免费许可后重试；付费应用不会自动购买。
- 如果 Apple 在获取免费许可后仍返回空官方列表，自动回退到“免登录查询”填充历史版本表，不再弹窗阻断操作。
- 将内置 `ipatool.exe` 放入独立运行目录，避免与 PyInstaller 内的 Python/Qt DLL 发生加载冲突。
- 打包配置允许在没有本地 SAP 种子缓存时正常构建，并将程序文件名和文件属性升级为 `iOSAppDownloader_v1.0.7.exe`。

### English

- Removed the `pywinpty/ConPTY` sign-in path that could fail with `0xC0000142`, Rust `unwrap` panics, or an application crash.
- Restored the proven non-interactive `ipatool-rs` sign-in and two-factor continuation flow, keeping verification on the same network route as the initial challenge.
- Rechecks the actual account session after code submission instead of rejecting a valid code from one command result.
- Stops the automatic no-code recovery when Apple still explicitly requires two-factor authentication after code submission, preventing the UI from looking like it is repeatedly submitting the same code.
- Revokes and deletes the local Apple sign-in session when the app exits, so the next launch requires signing in and completing two-factor authentication again.
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
