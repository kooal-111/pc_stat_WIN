from __future__ import annotations

import getpass
import hashlib
from collections.abc import Callable

import win32api
import win32con
import win32security
from PySide6.QtCore import QCoreApplication, QLockFile
from PySide6.QtNetwork import QLocalServer, QLocalSocket

from pc_stat_win.config import default_db_path


SHOW_COMMAND = "show"
MAX_COMMAND_BYTES = 1024


def current_user_identity() -> str:
    """Return a stable, kernel-object-safe identity for the current Windows user."""
    try:
        token = win32security.OpenProcessToken(
            win32api.GetCurrentProcess(),
            win32con.TOKEN_QUERY,
        )
        sid = win32security.GetTokenInformation(token, win32security.TokenUser)[0]
        return win32security.ConvertSidToStringSid(sid)
    except (OSError, AttributeError, win32security.error):
        fallback = getpass.getuser().encode("utf-8", errors="replace")
        return hashlib.sha256(fallback).hexdigest()[:24]


_USER_IDENTITY = current_user_identity()
DEFAULT_MUTEX_NAME = f"PCStatWin.SingleInstance.{_USER_IDENTITY}"
DEFAULT_SERVER_NAME = f"PCStatWin.SingleInstance.IPC.{_USER_IDENTITY}"


def _lock_path(identifier: str) -> str:
    digest = hashlib.sha256(identifier.encode("utf-8", errors="replace")).hexdigest()[:24]
    return str(default_db_path().parent / f"instance-{digest}.lock")


class SingleInstance:
    """Per-profile file lock with user-only local IPC for activation."""

    def __init__(
        self,
        name: str = DEFAULT_MUTEX_NAME,
        server_name: str = DEFAULT_SERVER_NAME,
        on_show: Callable[[], None] | None = None,
    ) -> None:
        self._server_name = server_name
        self._on_show = on_show
        self._server: QLocalServer | None = None
        self._sockets: set[QLocalSocket] = set()
        self._buffers: dict[QLocalSocket, bytearray] = {}
        lock_path = _lock_path(name)
        default_db_path().parent.mkdir(parents=True, exist_ok=True)
        self._lock = QLockFile(lock_path)
        self._lock.setStaleLockTime(0)
        acquired = self._lock.tryLock(0)
        if not acquired and self._lock.error() != QLockFile.LockError.LockFailedError:
            raise OSError(f"Unable to acquire the PC Stat instance lock: {lock_path}")
        self.already_running = not acquired
        self.activation_sent = False
        if self.already_running:
            self.activation_sent = self.send_command(SHOW_COMMAND)
        else:
            self.start_server()

    def start_server(self) -> bool:
        if self._server is not None and self._server.isListening():
            return True
        if QCoreApplication.instance() is None:
            return False

        server = QLocalServer()
        server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        if not server.listen(self._server_name):
            QLocalServer.removeServer(self._server_name)
            if not server.listen(self._server_name):
                return False
        server.newConnection.connect(self._accept_connections)
        self._server = server
        return True

    def send_command(self, command: str, timeout_ms: int = 1000) -> bool:
        payload = command.strip().encode("utf-8") + b"\n"
        if len(payload) > MAX_COMMAND_BYTES:
            raise ValueError("IPC command is too large")

        socket = QLocalSocket()
        socket.connectToServer(self._server_name)
        if not socket.waitForConnected(timeout_ms):
            return False
        if socket.write(payload) != len(payload):
            socket.abort()
            return False
        written = socket.waitForBytesWritten(timeout_ms) or socket.bytesToWrite() == 0
        socket.disconnectFromServer()
        return written

    def _accept_connections(self) -> None:
        if self._server is None:
            return
        while self._server.hasPendingConnections():
            socket = self._server.nextPendingConnection()
            if socket is None:
                continue
            self._sockets.add(socket)
            self._buffers[socket] = bytearray()
            socket.readyRead.connect(lambda current=socket: self._read_socket(current))
            socket.disconnected.connect(
                lambda current=socket: self._discard_socket(current)
            )
            if socket.bytesAvailable():
                self._read_socket(socket)

    def _read_socket(self, socket: QLocalSocket) -> None:
        buffer = self._buffers.get(socket)
        if buffer is None:
            return
        buffer.extend(bytes(socket.readAll()))
        if len(buffer) > MAX_COMMAND_BYTES:
            socket.abort()
            self._discard_socket(socket)
            return

        while b"\n" in buffer:
            raw_command, _, remainder = buffer.partition(b"\n")
            buffer[:] = remainder
            command = raw_command.decode("utf-8", errors="replace").strip()
            self._handle_command(command)

    def _handle_command(self, command: str) -> None:
        if command != SHOW_COMMAND:
            return
        if self._on_show is not None:
            self._on_show()
            return
        self._show_application_window()

    @staticmethod
    def _show_application_window() -> None:
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance()
        if app is None:
            return
        windows = [window for window in app.topLevelWidgets() if window.isWindow()]
        if not windows:
            return
        main_windows = [window for window in windows if window.inherits("QMainWindow")]
        candidates = main_windows or windows
        active_window = app.activeWindow()
        window = (
            active_window
            if active_window in candidates
            else next(
                (candidate for candidate in candidates if candidate.isVisible()),
                candidates[0],
            )
        )
        if window.isMinimized():
            window.showNormal()
        else:
            window.show()
        window.raise_()
        window.activateWindow()

    def _discard_socket(self, socket: QLocalSocket) -> None:
        self._buffers.pop(socket, None)
        self._sockets.discard(socket)
        socket.deleteLater()

    def close(self) -> None:
        for socket in tuple(self._sockets):
            socket.abort()
            self._discard_socket(socket)
        if self._server is not None:
            self._server.close()
            self._server.deleteLater()
            self._server = None
            QLocalServer.removeServer(self._server_name)
        if self._lock is not None:
            if not self.already_running:
                self._lock.unlock()
            self._lock = None

    def __enter__(self) -> "SingleInstance":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()
