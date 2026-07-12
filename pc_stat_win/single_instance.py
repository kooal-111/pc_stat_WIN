from __future__ import annotations

import ctypes
from ctypes import wintypes
from collections.abc import Callable

from PySide6.QtCore import QCoreApplication
from PySide6.QtNetwork import QLocalServer, QLocalSocket


ERROR_ALREADY_EXISTS = 183
DEFAULT_MUTEX_NAME = r"Local\PCStatWin.SingleInstance"
DEFAULT_SERVER_NAME = "PCStatWin.SingleInstance.IPC"
SHOW_COMMAND = "show"
MAX_COMMAND_BYTES = 1024


class SingleInstance:
    """Named Windows mutex guard with local IPC for the running instance."""

    def __init__(
        self,
        name: str = DEFAULT_MUTEX_NAME,
        server_name: str = DEFAULT_SERVER_NAME,
        on_show: Callable[[], None] | None = None,
    ) -> None:
        self._kernel32 = ctypes.windll.kernel32
        self._kernel32.CreateMutexW.argtypes = (wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR)
        self._kernel32.CreateMutexW.restype = wintypes.HANDLE
        self._kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        self._kernel32.CloseHandle.restype = wintypes.BOOL
        self._server_name = server_name
        self._on_show = on_show
        self._server: QLocalServer | None = None
        self._sockets: set[QLocalSocket] = set()
        self._buffers: dict[QLocalSocket, bytearray] = {}
        self._handle = self._kernel32.CreateMutexW(None, False, name)
        self.already_running = False
        self.activation_sent = False
        if self._handle:
            self.already_running = self._kernel32.GetLastError() == ERROR_ALREADY_EXISTS
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
        if self._handle:
            self._kernel32.CloseHandle(wintypes.HANDLE(self._handle))
            self._handle = None

    def __enter__(self) -> "SingleInstance":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()
