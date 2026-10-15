"""Offline regression tests; never use a real Apple ID or make purchases."""
import json
import plistlib
import zipfile
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch, Mock, MagicMock
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from engine_adapter import EngineSession, auth_result, version_rows, redact_output


class AdapterTests(unittest.TestCase):
    def test_engine_archive_rejects_a_changed_checksum(self):
        from prepare_engine import unpack_verified
        with self.assertRaisesRegex(ValueError, "checksum mismatch"):
            unpack_verified(b"not the official archive")

    def test_failed_engine_preparation_preserves_existing_file(self):
        from prepare_engine import prepare
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "ipatool" / "majd" / "ipatool.exe"
            target.parent.mkdir(parents=True)
            target.write_bytes(b"existing file")
            archive = Path(folder) / "bad.tar.gz"
            archive.write_bytes(b"tampered archive")
            with self.assertRaisesRegex(ValueError, "checksum mismatch"):
                prepare(folder, archive)
            self.assertEqual(target.read_bytes(), b"existing file")
            self.assertFalse(list(target.parent.glob("*.tmp")))

    def test_only_dead_process_session_directories_are_removed(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            dead = root / "sessions" / "run-424242-dead"
            live = root / "sessions" / "run-101-live"
            unrelated = root / "sessions" / "documents"
            cache = root / "engine-cache"
            for directory in (dead, live, unrelated, cache):
                directory.mkdir(parents=True)
                (directory / "keep.txt").write_text("fixture", encoding="utf-8")
            with patch("engine_adapter.process_is_running", side_effect=lambda pid: pid == 101):
                session = EngineSession(root)
            self.assertFalse(dead.exists())
            self.assertTrue(live.exists())
            self.assertTrue(unrelated.exists())
            self.assertTrue((cache / "keep.txt").exists())
            session.clear_credentials()

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
        # This offline suite mocks the CLI; no downloaded binary is needed.
        cls.engine_fixture = tempfile.TemporaryDirectory()
        executable = Path(cls.engine_fixture.name) / "offline-engine.exe"
        executable.write_bytes(b"offline test placeholder; never executed")
        cls.engine_path = patch.object(gui, "IPATOOL_PATH", str(executable))
        cls.engine_path.start()

    @classmethod
    def tearDownClass(cls):
        cls.engine_path.stop()
        cls.engine_fixture.cleanup()

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

    def test_filename_fields_cannot_escape_download_directory(self):
        name = self.gui.safe_filename("..\\CON:/app", "../../1:2\\3", "123", "456")
        self.assertNotRegex(name, r'[\\/:*?"<>|]')
        self.assertFalse(name.startswith("."))
        self.assertTrue(name.endswith(".ipa"))
        self.assertLessEqual(len(self.gui.safe_filename("长" * 1000, "9" * 1000, 123, 456)), 165)

    def test_filename_distinguishes_same_names_and_unknown_versions(self):
        file_name = self.gui.safe_filename
        self.assertNotEqual(file_name("App", "1.0", 123, 1), file_name("App", "1.0", 456, 1))
        self.assertNotEqual(file_name("App", "", 123, 1), file_name("App", "", 123, 2))

    def test_ipa_validation_rejects_html_and_wrong_bundle(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "example.ipa"
            path.write_bytes(b"<html>not an IPA</html>" * 100)
            self.assertFalse(self.gui._is_valid_ipa(path))
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("Payload/App.app/Info.plist", plistlib.dumps({"CFBundleIdentifier": "com.test.app"}))
            self.assertTrue(self.gui._is_valid_ipa(path, "com.test.app"))
            self.assertFalse(self.gui._is_valid_ipa(path, "com.different.app"))

    def test_ipa_validation_rejects_invalid_plist(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "invalid.ipa"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("Payload/App.app/Info.plist", b"<?xml version='1.0'?><plist><broken>")
            self.assertFalse(self.gui._is_valid_ipa(path))

    def test_package_list_skips_directories_named_as_ipa(self):
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / "not-a-file.ipa").mkdir()
            path = Path(folder) / "package.ipa"
            path.write_bytes(b"package listing fixture")
            listing = self.gui.QListWidget()
            with patch.object(self.gui, "IPAS_DIR", folder):
                self.gui.TransparentMacWindow._refresh_install_list(SimpleNamespace(install_list=listing))
            self.assertEqual(listing.count(), 1)
            self.assertEqual(listing.item(0).data(self.gui.Qt.ItemDataRole.UserRole), str(path))
            listing.deleteLater()

    def test_cancelled_http_request_does_not_open_connection(self):
        cancel = threading.Event()
        cancel.set()
        with patch.object(self.gui, "_build_opener") as opener:
            with self.assertRaises(self.gui.RequestCancelled):
                self.gui._http_get_bytes("https://example.invalid", cancel=cancel)
            opener.assert_not_called()

    def test_http_retries_share_one_timeout_budget(self):
        opener = Mock()
        opener.open.side_effect = OSError("offline")
        with patch.object(self.gui, "_http_route_candidates", return_value=["", "http://proxy.invalid"]), \
                patch.object(self.gui, "_build_opener", return_value=opener), \
                patch.object(self.gui.time, "monotonic", side_effect=[0, 0, 30, 30]), \
                patch.object(self.gui.time, "sleep"):
            with self.assertRaises(TimeoutError):
                self.gui._http_get_bytes("https://example.invalid", timeout=25)
        opener.open.assert_called_once()

    def test_http_read_stops_when_cancelled(self):
        cancel = threading.Event()
        response = Mock()
        def read(_size):
            cancel.set()
            return b"partial"
        response.read1.side_effect = read
        opener = MagicMock()
        opener.open.return_value.__enter__.return_value = response
        with patch.object(self.gui, "_http_route_candidates", return_value=[""]), \
                patch.object(self.gui, "_build_opener", return_value=opener):
            with self.assertRaises(self.gui.RequestCancelled):
                self.gui._http_get_bytes("https://example.invalid", cancel=cancel)
        response.read1.assert_called_once()

    def test_http_response_size_is_limited(self):
        response = Mock()
        response.read1.return_value = b"123456789"
        opener = MagicMock()
        opener.open.return_value.__enter__.return_value = response
        with patch.object(self.gui, "_http_route_candidates", return_value=[""]), \
                patch.object(self.gui, "_build_opener", return_value=opener), \
                patch.object(self.gui.time, "sleep"):
            with self.assertRaisesRegex(ValueError, "size limit"):
                self.gui._http_get_bytes("https://example.invalid", max_bytes=8)

    def test_icon_cache_has_a_byte_budget(self):
        with patch.dict(self.gui._ICON_CACHE, {"a": b"aa", "b": b"bb"}, clear=True), \
                patch.object(self.gui, "_ICON_CACHE_BYTE_LIMIT", 5), \
                patch.object(self.gui, "_http_get_bytes", return_value=b"cccc"):
            self.assertEqual(self.gui._get_cached_icon("c"), b"cccc")
            self.assertLessEqual(sum(map(len, self.gui._ICON_CACHE.values())), 5)

    def test_local_history_filters_invalid_identifiers_and_sizes(self):
        data = {"code": 200, "total": 1, "data": [
            {"bundle_version": "1.0", "external_identifier": "9", "size": "invalid"},
            {"bundle_version": "bad", "external_identifier": "../unsafe"}]}
        with patch.object(self.gui, "_http_get_json", return_value=data):
            rows = self.gui.api_fetch_history_local(123)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["external_id"], "9")
        self.assertEqual(rows[0]["size"], 0)

    def test_paused_download_does_not_launch_a_process(self):
        worker = self.gui.DownloadWorker("", {"id": "1", "out": "unused.ipa"})
        worker.pause()
        with patch.object(self.gui, "_ipatool_env") as environment, \
                patch.object(self.gui._ENGINE_SESSION, "launch") as launch:
            self.assertEqual(worker._stream(worker.task, []), ("paused", ""))
            environment.assert_not_called()
            launch.assert_not_called()

    def test_cancel_during_preparation_does_not_launch_a_process(self):
        worker = self.gui.DownloadWorker("", {"id": "1", "out": "unused.ipa"})
        with patch.object(self.gui, "_ipatool_env", side_effect=lambda **kw: worker.cancel() or {}), \
                patch.object(self.gui._ENGINE_SESSION, "launch") as launch:
            self.assertEqual(worker._stream(worker.task, []), ("cancelled", ""))
            launch.assert_not_called()

    def test_stream_error_stops_monitor_and_child_process(self):
        worker = self.gui.DownloadWorker("", {"id": "1", "out": "unused.ipa"})
        process = MagicMock()
        process.stdout.__iter__.side_effect = OSError("broken pipe")
        process.poll.return_value = None
        monitor = Mock()
        with patch.object(self.gui, "_ipatool_env", return_value={}), \
                patch.object(self.gui._ENGINE_SESSION, "launch", return_value=process), \
                patch.object(self.gui.threading, "Thread", return_value=monitor):
            with self.assertRaisesRegex(OSError, "broken pipe"):
                worker._stream(worker.task, [])
        process.kill.assert_called_once()
        process.stdout.close.assert_called_once()
        monitor.join.assert_called_once()
        self.assertIsNone(worker._proc)

    def test_stream_checks_real_child_output_and_ipa_before_success(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "result.ipa"
            task = {"id": "1", "out": str(path), "bundle": "com.test.app"}
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("Payload/App.app/Info.plist", plistlib.dumps({"CFBundleIdentifier": "com.test.app"}))
            command = [sys.executable, "-c", "print('component finished')"]
            with patch.object(self.gui, "_ipatool_env", return_value=os.environ.copy()), \
                    patch.object(self.gui, "_ipatool_command", return_value=command):
                valid = self.gui.DownloadWorker("", task)
                self.assertEqual(valid._stream(task, [])[0], "completed")
                path.write_bytes(b"not an IPA" * 200)
                invalid = self.gui.DownloadWorker("", task)
                status, reason = invalid._stream(task, [])
                self.assertEqual(status, "failed")
                self.assertIn("IPA", reason)

    def test_active_downloads_prevent_account_state_reset(self):
        parent = SimpleNamespace(_download_workers={"1": object()})
        with patch.object(self.dialog, "parent", return_value=parent), \
                patch.object(self.dialog, "_run_tool_async") as run:
            self.dialog._do_login()
            self.dialog._do_logout()
            run.assert_not_called()

    def test_search_cancellation_is_not_reported_as_an_error(self):
        worker = self.gui.SearchWorker("example")
        errors = []
        worker.signals.error.connect(errors.append)
        worker.stop()
        with patch.object(self.gui, "_build_opener") as opener:
            worker.run()
            opener.assert_not_called()
        self.assertFalse(errors)

    def test_history_cancellation_is_not_reported_as_an_error(self):
        worker = self.gui.HistoryWorker(123)
        errors = []
        worker.signals.error.connect(errors.append)
        worker.stop()
        with patch.object(self.gui, "_http_get_json") as query:
            worker.run()
            query.assert_not_called()
        self.assertFalse(errors)

    def test_exit_waits_for_running_workers_before_quitting_qt(self):
        worker = Mock()
        state = SimpleNamespace(_exit_workers=[worker], _finish_exit=Mock())
        with patch.object(self.gui.QTimer, "singleShot") as timer, \
                patch.object(self.gui.QApplication, "quit") as quit_app:
            worker.isRunning.return_value = True
            self.gui.TransparentMacWindow._finish_exit(state)
            quit_app.assert_not_called()
            timer.assert_called_once_with(100, state._finish_exit)
            worker.isRunning.return_value = False
            self.gui.TransparentMacWindow._finish_exit(state)
            quit_app.assert_called_once()

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
                patch.object(self.gui, "APPLE_ID_SAVE", ""), \
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
        # QLabel.sizeHint() uses a preferred width, not the width supplied by
        # the scroll area. Font fallback on CI can make that hint much taller.
        self.assertGreaterEqual(self.dialog.status_card.height(),
                                self.dialog.status_card.heightForWidth(self.dialog.status_card.width()))

    def test_long_status_text_is_fully_reachable_by_scrolling(self):
        self.dialog.twofa_row_widget.setVisible(True)
        self.dialog.status_card.setText("Long authentication failure. " * 300)
        self.dialog.show()
        self.app.processEvents()
        label = self.dialog.status_card
        scroll = self.dialog.status_scroll
        self.assertGreaterEqual(label.height(), label.heightForWidth(label.width()))
        self.assertGreater(scroll.verticalScrollBar().maximum(), 0)
        self.assertGreaterEqual(scroll.verticalScrollBar().maximum(),
                                label.height() - scroll.viewport().height())
        self.assertLessEqual(self.dialog.twofa_row_widget.geometry().bottom(), self.dialog.height())
        self.dialog.hide()


if __name__ == "__main__":
    unittest.main()
