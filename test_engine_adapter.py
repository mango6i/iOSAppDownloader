"""Offline regression tests; never use a real Apple ID or make purchases."""
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from engine_adapter import EngineSession, auth_result, version_rows, redact_output


class AdapterTests(unittest.TestCase):
    def test_exit_zero_2fa_is_not_success(self):
        self.assertEqual(auth_result(0, json.dumps({"message": "2FA code is required; supply --auth-code"})),
                         (False, True, ""))

    def test_success_after_prompt_wins(self):
        out = '{"message":"2FA code is required"}\n{"success":true,"email":"test@example.invalid"}'
        self.assertEqual(auth_result(0, out), (True, False, "test@example.invalid"))

    def test_errors_are_not_wrong_codes(self):
        for message in ("Apple rejected the signed authentication request",
                        "2FA verification request failed: HTTP 403", "invalid --auth-code option"):
            self.assertEqual(auth_result(1, json.dumps({"success": False, "error": message})),
                             (False, False, ""))
        self.assertEqual(auth_result(1, '{"error":"apple did not complete verification; try a fresh 2FA code"}'),
                         (False, True, ""))

    def test_only_identity_success_is_authentication(self):
        self.assertEqual(auth_result(0, '{"success":true}'), (False, False, ""))
        self.assertEqual(auth_result(1, '{"success":true,"email":"test@example.invalid"}')[0], False)

    def test_versions_numeric_sorted_deduplicated(self):
        out = json.dumps({"success": True, "externalVersionIdentifiers": ["9", "100", "9", "", "wrong", True]})
        rows = version_rows(out)
        self.assertEqual([row["external_id"] for row in rows], ["100", "9"])
        self.assertTrue(all(row["version"] == "" for row in rows))

    def test_secrets_are_redacted(self):
        text = '{"passwordToken":"secret-token","dsid":1234567,"password":"private"} leaked=p@ssword code=654321'
        safe = redact_output(text, ("p@ssword", "654321"))
        for secret in ("secret-token", "1234567", "private", "p@ssword", "654321"):
            self.assertNotIn(secret, safe)

    def test_windows_home_cache_and_cleanup_are_separate(self):
        with tempfile.TemporaryDirectory() as root:
            first, second = EngineSession(root), EngineSession(root)
            self.assertNotEqual(first.home, second.home)
            self.assertNotEqual(first.passphrase, second.passphrase)
            env = first.environment("http://127.0.0.1:7897")
            self.assertEqual(env["HOMEDRIVE"] + env["HOMEPATH"], str(first.home))
            self.assertTrue(env["XDG_STATE_HOME"].startswith(str(first.home)))
            self.assertEqual(env["LOCALAPPDATA"], str(first.cache))
            marker = first.cache / "cache-kept"
            marker.touch()
            credentials = first.home / "cookies"
            credentials.touch()
            first.clear_credentials()
            self.assertFalse(credentials.exists())
            self.assertTrue(marker.exists())
            self.assertTrue(second.home.exists())

    def test_frozen_child_does_not_inherit_qt_paths(self):
        with tempfile.TemporaryDirectory() as root:
            frozen = str(Path(root) / "_MEI123")
            session = EngineSession(root, frozen_root=frozen)
            with patch.dict(os.environ, {"PATH": frozen + os.sep + "PyQt6" + os.pathsep + "C:\\Windows",
                                         "NO_PROXY": "*", "QT_PLUGIN_PATH": frozen}):
                env = session.environment("http://127.0.0.1:7897")
            self.assertNotIn(frozen, env["PATH"])
            self.assertNotIn("NO_PROXY", env)
            self.assertNotIn("QT_PLUGIN_PATH", env)

    def test_timeout_terminates_child(self):
        with tempfile.TemporaryDirectory() as root:
            session = EngineSession(root)
            start = time.monotonic()
            rc, _ = session.execute([sys.executable, "-c", "import time;time.sleep(10)"],
                                    os.environ.copy(), 0.25)
            self.assertEqual(rc, -2)
            self.assertLess(time.monotonic() - start, 3)
            self.assertFalse(session._processes)

    def test_cancel_terminates_child(self):
        with tempfile.TemporaryDirectory() as root:
            session, event = EngineSession(root), threading.Event()
            timer = threading.Timer(0.25, event.set)
            timer.start()
            try:
                rc, _ = session.execute([sys.executable, "-c", "import time;time.sleep(10)"],
                                        os.environ.copy(), 20, event)
                self.assertEqual(rc, -4)
                self.assertFalse(session._processes)
            finally:
                timer.cancel()


class GuiIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import ios_old_app_downloader as gui
        cls.gui = gui
        cls.app = gui.QApplication.instance() or gui.QApplication([])

    def setUp(self):
        self.diagnostics = patch.object(self.gui, "_diagnostic")
        self.diagnostics.start()
        self.dialogs = patch.object(self.gui.MacStyleMessageBox, "exec", return_value=0)
        self.dialogs.start()
        with patch.object(self.gui.SettingsDialog, "_refresh_status"):
            self.dialog = self.gui.SettingsDialog()

    def tearDown(self):
        self.dialog.reject()
        self.dialog.deleteLater()
        self.dialogs.stop()
        self.diagnostics.stop()

    def test_code_failure_does_not_start_another_login(self):
        with patch.object(self.dialog, "_run_tool_async") as run:
            self.dialog._on_login_done(1, '{"error":"Apple rejected the signed authentication request","success":false}', True)
            run.assert_not_called()
        self.assertEqual(self.dialog._login_phase, "waiting_code")

    def test_success_requires_info_confirmation(self):
        with patch.object(self.dialog, "_run_tool_async") as run:
            self.dialog._on_login_done(0, '{"success":true,"email":"test@example.invalid"}', True)
            self.assertEqual(run.call_args.args[0][:2], ["auth", "info"])

    def test_confirmation_failure_never_replays_password(self):
        with patch.object(self.dialog, "_run_tool_async") as run:
            self.dialog._on_login_verified(1, '{"error":"not logged in"}', True)
            run.assert_not_called()

    def test_success_ok_closes_settings_without_signing_out(self):
        def confirm(message):
            self.assertTrue(self.dialog.isVisible())
            self.assertFalse(self.dialog._closing)
            self.gui.QTimer.singleShot(0, message.findChild(self.gui.QPushButton).click)
            return self.gui.QDialog.exec(message)

        self.dialog.pwd_edit.setText("not-a-real-password")
        self.dialog._pending_pwd = "not-a-real-password"
        self.dialog.twofa_edit.setText("123456")
        self.dialog.show()
        with patch.object(self.gui.MacStyleMessageBox, "exec", new=confirm), \
                patch.object(self.gui, "_clear_runtime_auth") as clear_auth:
            self.dialog._on_login_verified(0, '{"success":true,"email":"test@example.invalid"}', True)
            clear_auth.assert_not_called()
        self.assertFalse(self.dialog.isVisible())
        self.assertEqual(self.dialog.result(), self.gui.QDialog.DialogCode.Accepted)
        self.assertTrue(self.dialog._closing)
        self.assertEqual(self.dialog.pwd_edit.text(), "")
        self.assertEqual(self.dialog.twofa_edit.text(), "")
        self.assertEqual(self.dialog._pending_pwd, "")

    def test_dismissed_success_notice_keeps_settings_open(self):
        self.dialog.show()
        self.dialog._on_login_verified(0, '{"success":true,"email":"test@example.invalid"}', False)
        self.assertTrue(self.dialog.isVisible())
        self.assertFalse(self.dialog._closing)

    def test_failed_confirmation_keeps_settings_open(self):
        self.dialog.show()
        self.dialog._on_login_verified(1, '{"error":"not logged in"}', True)
        self.assertTrue(self.dialog.isVisible())
        self.assertFalse(self.dialog._closing)

    def test_long_message_is_scrollable_with_visible_ok_button(self):
        message = self.gui.MacStyleMessageBox(message="Long authentication error. " * 500)
        message.show()
        self.app.processEvents()
        self.assertIsNotNone(message._scroll_host)
        self.assertGreater(message._scroll_host.verticalScrollBar().maximum(), 0)
        button = message.findChild(self.gui.QPushButton)
        self.assertLessEqual(button.mapTo(message, button.rect().bottomRight()).y(), message.height())
        message.reject()
        message.deleteLater()

    def test_busy_submit_is_ignored(self):
        self.dialog._login_busy = True
        with patch.object(self.dialog, "_run_tool_async") as run:
            self.dialog._do_login_with_2fa()
            run.assert_not_called()

    def test_official_cli_commands(self):
        args = self.gui._official_version_list_args(123, "com.test.app")
        self.assertEqual(args[0], "list-versions")
        self.assertIn("iphone", args)

    def test_auto_proxy_falls_back_to_direct_without_listeners(self):
        with patch.object(self.gui, "PROXY_MODE", "auto"), patch.object(self.gui, "_local_proxy_cache", None), \
                patch.object(self.gui, "_windows_system_proxy", return_value=""), \
                patch.object(self.gui, "_env_proxy", return_value=""), patch.object(self.gui.socket, "socket") as socket:
            socket.return_value.connect.side_effect = OSError("no listener")
            self.assertEqual(self.gui._candidate_proxies(), [""])
            self.assertEqual(self.gui._resolve_proxy(), "")
            self.assertEqual(socket.call_count, len(self.gui._LOCAL_PROXY_PORTS))

    def test_auto_proxy_finds_local_listener(self):
        def connect(address):
            if address != ("127.0.0.1", 7897):
                raise OSError("no listener")
        with patch.object(self.gui, "PROXY_MODE", "auto"), patch.object(self.gui, "_local_proxy_cache", None), \
                patch.object(self.gui, "_windows_system_proxy", return_value=""), \
                patch.object(self.gui, "_env_proxy", return_value=""), patch.object(self.gui.socket, "socket") as socket:
            socket.return_value.connect.side_effect = connect
            self.assertEqual(self.gui._resolve_proxy(), "http://127.0.0.1:7897")
            self.assertEqual(self.gui._candidate_proxies(), ["http://127.0.0.1:7897", ""])

    def test_password_login_entry_reaches_engine_in_auto_mode(self):
        def run_worker(args, callback, timeout=60, proxy=None):
            worker = self.gui.ToolWorker(args, timeout, proxy=proxy)
            worker.done.connect(callback)
            worker.run()
        self.dialog.email_edit.setText("integration-check@example.invalid")
        self.dialog.pwd_edit.setText("not-a-real-password")
        with patch.object(self.gui, "PROXY_MODE", "auto"), patch.object(self.gui, "_local_proxy_cache", None), \
                patch.object(self.gui, "APPLE_ID_SAVE", ""), patch.object(self.gui, "save_config"), \
                patch.object(self.gui, "_windows_system_proxy", return_value=""), \
                patch.object(self.gui, "_env_proxy", return_value=""), patch.object(self.gui.socket, "socket") as socket, \
                patch.object(self.dialog, "_run_tool_async", side_effect=run_worker), \
                patch.object(self.gui._ENGINE_SESSION, "execute", return_value=(0, '{"message":"2FA code is required"}')) as execute:
            socket.return_value.connect.side_effect = OSError("no listener")
            self.dialog._do_login()
            execute.assert_called_once()
            self.assertEqual(self.dialog._login_phase, "waiting_code")
            self.assertFalse(self.dialog._login_busy)

    def test_no_undefined_global_names_in_app(self):
        import builtins
        import symtable
        path = Path(self.gui.__file__)
        symbols = symtable.symtable(path.read_text(encoding="utf-8"), str(path), "exec")
        known = {s.get_name() for s in symbols.get_symbols()
                 if s.is_assigned() or s.is_imported() or s.is_namespace()}
        known.update(dir(builtins))
        known.update(("__file__", "__name__", "__package__", "__doc__", "__builtins__"))
        missing = set()
        def check(table):
            for symbol in table.get_symbols():
                if symbol.is_global() and symbol.is_referenced() and symbol.get_name() not in known:
                    missing.add(symbol.get_name())
            for child in table.get_children():
                check(child)
        check(symbols)
        self.assertEqual(missing, set())

    def test_code_is_never_retried_on_another_route(self):
        self.gui._set_login_challenge_proxy("http://127.0.0.1:7897")
        with patch.object(self.gui._ENGINE_SESSION, "execute", return_value=(1, '{"error":"connection reset"}')) as execute:
            self.gui.run_tool(["auth", "login", "--email", "test@example.invalid", "--password", "fake",
                               "--auth-code", "123456"], timeout=5)
            self.assertEqual(execute.call_count, 1)
            self.assertEqual(execute.call_args.args[1]["HTTPS_PROXY"], "http://127.0.0.1:7897")

    def test_password_sign_in_clears_old_credentials_and_cookies(self):
        with tempfile.TemporaryDirectory() as root:
            session = EngineSession(root)
            session.environment("")
            cookie = session.home / "state" / "ipatool" / "cookies"
            cookie.parent.mkdir(parents=True)
            cookie.write_text("old-cookie", encoding="utf-8")
            account = cookie.parent / "account"
            account.write_text("old-account", encoding="utf-8")
            asset = session.cache / "asset-kept"
            asset.touch()
            def execute(*args):
                self.assertFalse(cookie.exists())
                self.assertFalse(account.exists())
                self.assertTrue(asset.exists())
                return 0, '{"message":"2FA code is required"}'
            with patch.object(self.gui, "_ENGINE_SESSION", session), \
                    patch.object(session, "execute", side_effect=execute) as run:
                self.gui.run_tool(["auth", "login", "--email", "test@example.invalid", "--password", "fake"],
                                  timeout=5, proxy="")
                run.assert_called_once()

    def test_code_continuation_preserves_challenge_cookies(self):
        with tempfile.TemporaryDirectory() as root:
            session = EngineSession(root)
            session.environment("")
            cookie = session.home / "cookies"
            cookie.write_text("challenge-cookie", encoding="utf-8")
            with patch.object(self.gui, "_ENGINE_SESSION", session), \
                    patch.object(session, "clear_credentials", wraps=session.clear_credentials) as clear, \
                    patch.object(session, "execute", return_value=(0, '{"success":true,"email":"test@example.invalid"}')):
                self.gui.run_tool(["auth", "login", "--email", "test@example.invalid", "--password", "fake",
                                   "--auth-code", "123456"], timeout=5, proxy="")
                clear.assert_not_called()
                self.assertEqual(cookie.read_text(encoding="utf-8"), "challenge-cookie")

    def test_password_sign_in_stops_if_state_cleanup_fails(self):
        with patch.object(self.gui._ENGINE_SESSION, "clear_credentials", side_effect=OSError("locked")), \
                patch.object(self.gui._ENGINE_SESSION, "execute") as execute:
            rc, _ = self.gui.run_tool(["auth", "login", "--email", "test@example.invalid", "--password", "fake"],
                                      timeout=5, proxy="")
            self.assertEqual(rc, -3)
            execute.assert_not_called()

    def test_version_metadata_uses_same_id(self):
        responses = [(0, '{"success":true,"externalVersionIdentifiers":["100"]}'),
                     (0, '{"success":true,"externalVersionID":"100","displayVersion":"8.0","releaseDate":"2026-10-10T00:00:00Z"}')]
        with patch.object(self.gui, "run_tool", side_effect=responses) as run, patch.object(self.gui, "api_fetch_history_local", return_value=[]):
            rows = self.gui.api_fetch_history_apple(123, "com.test.app")
        self.assertEqual(rows[0]["version"], "8.0")
        self.assertEqual(run.call_args_list[1].args[0][0], "get-version-metadata")

    def test_paid_app_never_auto_purchased(self):
        with patch.object(self.gui, "run_tool", return_value=(1, '{"error":"license is required"}')) as run, patch.object(self.gui, "api_fetch_history_local", return_value=[]):
            self.gui.api_fetch_history_apple(123, "com.test.app", allow_auto_purchase=False)
            self.assertEqual(run.call_count, 1)

    def test_free_license_retry_only_once(self):
        responses = [(1, '{"error":"license is required"}'),
                     (0, '{"success":true}'),
                     (0, '{"success":true,"externalVersionIdentifiers":["100"]}')]
        metadata = [{"external_id": "100", "version": "8.0", "date": "", "size": 0}]
        with patch.object(self.gui, "run_tool", side_effect=responses) as run, patch.object(self.gui, "api_fetch_history_local", return_value=metadata):
            rows = self.gui.api_fetch_history_apple(123, "com.test.app", allow_auto_purchase=True)
        self.assertEqual([call.args[0][0] for call in run.call_args_list], ["list-versions", "purchase", "list-versions"])
        self.assertEqual(rows[0]["version"], "8.0")

    def test_busy_password_submit_does_not_change_pending_credentials(self):
        self.dialog._login_busy = True
        self.dialog._pending_pwd = "first"
        self.dialog.pwd_edit.setText("second")
        self.dialog._do_login()
        self.assertEqual(self.dialog._pending_pwd, "first")

    def test_settings_layout_with_code(self):
        self.dialog.twofa_row_widget.setVisible(True)
        self.dialog.status_card.setText(self.gui.tr("twofa_status_html"))
        self.dialog.show()
        self.app.processEvents()
        self.assertGreaterEqual(self.dialog.status_card.height(), self.dialog.status_card.sizeHint().height())
        self.assertLessEqual(self.dialog.twofa_row_widget.geometry().bottom(), self.dialog.height())
        self.dialog.hide()


if __name__ == "__main__":
    unittest.main()
