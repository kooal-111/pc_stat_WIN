from __future__ import annotations

import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import patch

import win32gui

from pc_stat_win import autostart, foreground
from pc_stat_win.single_instance import DEFAULT_MUTEX_NAME, SingleInstance


class _RegistryKey:
    def __enter__(self) -> "_RegistryKey":
        return self

    def __exit__(self, *_args: object) -> None:
        return None


class AutostartV130Tests(unittest.TestCase):
    def test_sync_removes_stale_run_entry_when_setting_is_disabled(self) -> None:
        with patch("pc_stat_win.autostart.set_enabled", return_value=True) as set_enabled:
            self.assertTrue(autostart.sync_run_key(False))
        set_enabled.assert_called_once_with(False)

    def test_disable_reports_permission_failure_but_accepts_missing_key(self) -> None:
        with patch("pc_stat_win.autostart.winreg.OpenKey", side_effect=FileNotFoundError):
            self.assertTrue(autostart.set_enabled(False))
        with patch("pc_stat_win.autostart.winreg.OpenKey", return_value=_RegistryKey()), patch(
            "pc_stat_win.autostart.winreg.DeleteValue", side_effect=PermissionError
        ):
            self.assertFalse(autostart.set_enabled(False))

    def test_sync_does_not_rewrite_an_exact_command(self) -> None:
        command = autostart.launch_command()
        with patch("pc_stat_win.autostart.winreg.OpenKey", return_value=_RegistryKey()), patch(
            "pc_stat_win.autostart.winreg.QueryValueEx", return_value=(command, 1)
        ), patch("pc_stat_win.autostart.set_enabled") as set_enabled:
            self.assertTrue(autostart.sync_run_key(True))
        set_enabled.assert_not_called()


class ForegroundV130Tests(unittest.TestCase):
    def tearDown(self) -> None:
        foreground._PROCESS_CACHE.clear()

    def test_title_failure_keeps_process_identity(self) -> None:
        title_error = win32gui.error(5, "GetWindowText", "denied")
        with patch("pc_stat_win.foreground.win32gui.GetForegroundWindow", return_value=77), patch(
            "pc_stat_win.foreground.win32process.GetWindowThreadProcessId",
            return_value=(1, 42),
        ), patch(
            "pc_stat_win.foreground.win32gui.GetWindowText", side_effect=title_error
        ), patch(
            "pc_stat_win.foreground._process_identity",
            return_value=(r"C:\Apps\editor.exe", "editor.exe"),
        ):
            info = foreground.get_foreground_app(monotonic_clock=lambda: 1.0)
        self.assertIsNotNone(info)
        assert info is not None
        self.assertEqual(info.exe_name, "editor.exe")
        self.assertEqual(info.window_title, "")

    def test_cache_key_includes_window_handle_to_reduce_pid_reuse_risk(self) -> None:
        process = SimpleNamespace(exe=lambda: r"C:\Apps\editor.exe")
        with patch("pc_stat_win.foreground.psutil.Process", return_value=process) as factory:
            foreground._process_identity(42, 100, 0.0)
            foreground._process_identity(42, 101, 0.1)
        self.assertEqual(factory.call_count, 2)


class SingleInstanceV130Tests(unittest.TestCase):
    def test_default_lock_is_user_scoped(self) -> None:
        self.assertTrue(DEFAULT_MUTEX_NAME.startswith("PCStatWin.SingleInstance."))
        self.assertGreater(len(DEFAULT_MUTEX_NAME.rsplit(".", 1)[-1]), 4)

    def test_lock_permission_failure_fails_closed(self) -> None:
        class DeniedLock:
            class LockError:
                LockFailedError = 1

            def __init__(self, _path: str) -> None:
                pass

            def setStaleLockTime(self, _milliseconds: int) -> None:
                pass

            def tryLock(self, _timeout: int) -> bool:
                return False

            def error(self) -> int:
                return 2

        with patch("pc_stat_win.single_instance.QLockFile", DeniedLock):
            with self.assertRaises(OSError):
                SingleInstance()

    def test_local_ipc_is_restricted_to_current_user(self) -> None:
        from PySide6.QtCore import QCoreApplication
        from PySide6.QtNetwork import QLocalServer

        app = QCoreApplication.instance() or QCoreApplication([])
        self.assertIsNotNone(app)

        class FakeLocalServer:
            SocketOption = QLocalServer.SocketOption

            @staticmethod
            def removeServer(_name: str) -> bool:
                return True

            def __init__(self) -> None:
                self._options = QLocalServer.SocketOption.NoOptions
                self.newConnection = SimpleNamespace(connect=lambda _slot: None)

            def setSocketOptions(self, options: QLocalServer.SocketOption) -> None:
                self._options = options

            def socketOptions(self) -> QLocalServer.SocketOption:
                return self._options

            def listen(self, _name: str) -> bool:
                return True

            def isListening(self) -> bool:
                return True

            def close(self) -> None:
                return None

            def deleteLater(self) -> None:
                return None

        class FakeLock:
            def __init__(self, _path: str) -> None:
                pass

            def setStaleLockTime(self, _milliseconds: int) -> None:
                pass

            def tryLock(self, _timeout: int) -> bool:
                return True

            def unlock(self) -> None:
                pass

        suffix = f".SecurityTest.{uuid.uuid4().hex}"
        with patch("pc_stat_win.single_instance.QLocalServer", FakeLocalServer), patch(
            "pc_stat_win.single_instance.QLockFile", FakeLock
        ):
            instance = SingleInstance(
                name=DEFAULT_MUTEX_NAME + suffix,
                server_name="PCStatWin.SecurityTest.IPC" + suffix,
            )
            try:
                self.assertIsNotNone(instance._server)
                assert instance._server is not None
                self.assertEqual(
                    instance._server.socketOptions(),
                    QLocalServer.SocketOption.UserAccessOption,
                )
            finally:
                instance.close()


if __name__ == "__main__":
    unittest.main()
