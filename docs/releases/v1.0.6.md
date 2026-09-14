# iOSAppDownloader v1.0.6

## 中文

- 重做 Apple ID 登录流程：密码和双重验证码现在在同一个 `ipatool-rs` 进程内完成。
- 使用 Windows 真实伪终端承载交互式登录，不依赖浏览器。
- 保留同一登录会话的 Cookie 与 SAP 签名状态，修复验证码明明正确却反复提示失败的问题。
- 登录命令不再把 Apple ID 密码放到进程命令行中。
- 打包流程已加入 `pywinpty` 依赖，成品会自带交互式登录所需组件。

## English

- Reworked Apple ID sign-in so the password and two-factor code are handled by one `ipatool-rs` process.
- Uses a real Windows pseudo-terminal for desktop authentication; no browser is involved.
- Preserves the same session's cookies and SAP signing state, fixing repeated rejection of valid codes.
- The Apple ID password is no longer exposed in the process command line.
- The packaging workflow now installs `pywinpty`, so the release includes the interactive sign-in component.
