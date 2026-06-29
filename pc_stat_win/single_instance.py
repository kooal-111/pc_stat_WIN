from __future__ import annotations

import ctypes
from ctypes import wintypes


ERROR_ALREADY_EXISTS = 183


class SingleInstance:
    """Named Windows mutex guard for one running tracker instance."""

    def __init__(self, name: str = r"Local\PCStatWin.SingleInstance") -> None:
        self._kernel32 = ctypes.windll.kernel32
        self._kernel32.CreateMutexW.argtypes = (wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR)
        self._kernel32.CreateMutexW.restype = wintypes.HANDLE
        self._kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        self._kernel32.CloseHandle.restype = wintypes.BOOL
        self._handle = self._kernel32.CreateMutexW(None, False, name)
        self.already_running = False
        if self._handle:
            self.already_running = self._kernel32.GetLastError() == ERROR_ALREADY_EXISTS

    def close(self) -> None:
        if self._handle:
            self._kernel32.CloseHandle(wintypes.HANDLE(self._handle))
            self._handle = None

    def __enter__(self) -> "SingleInstance":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()
