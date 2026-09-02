## 中文

- 修复正确验证码已经完成 Apple 验证，却被软件直接提示“验证码未通过”的误判。
- 验证码提交后先检查真实账号状态；状态尚未写入时，会自动用同一路线完成一次会话确认，不再要求用户手动反复登录。
- 设置窗口底部增加当前软件版本号。
- 修复历史版本 ID 按文本排序导致旧版本错位的问题，现改为数值排序。
- 历史版本表重新固定列宽并居中显示；无法取得的版本、大小或日期显示为统一的短横线。
- 打包程序文件名改为 `iOSAppDownloader_v1.0.5.exe`，文件属性版本同步更新。

## English

- Fixed valid Apple verification codes being prematurely reported as rejected.
- The app now verifies the real account state after code submission and automatically completes the session on the same route when necessary.
- Added the current software version at the bottom of Settings.
- Fixed old version IDs being misplaced by text sorting; IDs are now sorted numerically.
- History columns now have stable widths and centered values; unavailable metadata uses a consistent dash.
- Renamed the packaged executable to `iOSAppDownloader_v1.0.5.exe` and synchronized its file metadata version.
