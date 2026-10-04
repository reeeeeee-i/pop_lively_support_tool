"""Lively の CPU 割り当てを 1 コアに絞る（ロード時間短縮）

popnLively はフルスクリーン時、CPU 割り当てを 1 つだけにするとロード時間が短くなる。
Lively の起動を見つけたら、使用率が最小の CPU だけを割り当て、優先度を「高」にする。
"""
from __future__ import annotations

import ctypes
import random
from ctypes import wintypes

from src.logger import get_logger

logger = get_logger(__name__)

_TH32CS_SNAPPROCESS = 0x00000002
_PROCESS_SET_INFORMATION = 0x0200
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_HIGH_PRIORITY_CLASS = 0x00000080
_INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
_SYSTEM_PROCESSOR_PERFORMANCE_INFORMATION = 8


class _PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", wintypes.WCHAR * 260),
    ]


class _PROCESSOR_PERFORMANCE_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("IdleTime", ctypes.c_longlong),
        ("KernelTime", ctypes.c_longlong),   # IdleTime を含む
        ("UserTime", ctypes.c_longlong),
        ("DpcTime", ctypes.c_longlong),
        ("InterruptTime", ctypes.c_longlong),
        ("InterruptCount", wintypes.ULONG),
    ]


# ctypes.windll のインスタンスは共有されるので、argtypes を他モジュールと取り合わないよう専用に持つ
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_ntdll = ctypes.WinDLL("ntdll")

_kernel32.CreateToolhelp32Snapshot.argtypes = (wintypes.DWORD, wintypes.DWORD)
_kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
_kernel32.Process32FirstW.argtypes = (wintypes.HANDLE, ctypes.POINTER(_PROCESSENTRY32W))
_kernel32.Process32FirstW.restype = wintypes.BOOL
_kernel32.Process32NextW.argtypes = (wintypes.HANDLE, ctypes.POINTER(_PROCESSENTRY32W))
_kernel32.Process32NextW.restype = wintypes.BOOL
_kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
_kernel32.OpenProcess.restype = wintypes.HANDLE
_kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
_kernel32.CloseHandle.restype = wintypes.BOOL
_kernel32.GetProcessAffinityMask.argtypes = (
    wintypes.HANDLE, ctypes.POINTER(ctypes.c_size_t), ctypes.POINTER(ctypes.c_size_t),
)
_kernel32.GetProcessAffinityMask.restype = wintypes.BOOL
_kernel32.SetProcessAffinityMask.argtypes = (wintypes.HANDLE, ctypes.c_size_t)
_kernel32.SetProcessAffinityMask.restype = wintypes.BOOL
_kernel32.GetPriorityClass.argtypes = (wintypes.HANDLE,)
_kernel32.GetPriorityClass.restype = wintypes.DWORD
_kernel32.SetPriorityClass.argtypes = (wintypes.HANDLE, wintypes.DWORD)
_kernel32.SetPriorityClass.restype = wintypes.BOOL
_ntdll.NtQuerySystemInformation.argtypes = (
    wintypes.ULONG, ctypes.c_void_p, wintypes.ULONG, ctypes.POINTER(wintypes.ULONG),
)
_ntdll.NtQuerySystemInformation.restype = wintypes.LONG


def _find_pid(exe_name: str) -> int | None:
    """exe 名（大文字小文字を区別しない）が一致するプロセスの ID を返す。"""
    snapshot = _kernel32.CreateToolhelp32Snapshot(_TH32CS_SNAPPROCESS, 0)
    if not snapshot or snapshot == _INVALID_HANDLE_VALUE:
        return None
    try:
        target = exe_name.lower()
        entry = _PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(_PROCESSENTRY32W)
        ok = _kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        while ok:
            if entry.szExeFile.lower() == target:
                return entry.th32ProcessID
            ok = _kernel32.Process32NextW(snapshot, ctypes.byref(entry))
        return None
    finally:
        _kernel32.CloseHandle(snapshot)


def _read_cpu_times() -> list[tuple[int, int]] | None:
    """CPU ごとの (アイドル時間, 総時間) の累積値を返す。取得できなければ None。"""
    buffer = (_PROCESSOR_PERFORMANCE_INFORMATION * 64)()
    returned = wintypes.ULONG(0)
    status = _ntdll.NtQuerySystemInformation(
        _SYSTEM_PROCESSOR_PERFORMANCE_INFORMATION,
        buffer, ctypes.sizeof(buffer), ctypes.byref(returned),
    )
    if status != 0:
        return None
    count = returned.value // ctypes.sizeof(_PROCESSOR_PERFORMANCE_INFORMATION)
    return [(buffer[i].IdleTime, buffer[i].KernelTime + buffer[i].UserTime) for i in range(count)]


def _cpu_usage(prev: list[tuple[int, int]], curr: list[tuple[int, int]]) -> list[int]:
    """2 回の計測の差分から CPU ごとの使用率 (%) を求める。"""
    usage = []
    for (idle0, total0), (idle1, total1) in zip(prev, curr):
        total = total1 - total0
        usage.append(round(100 * (1 - (idle1 - idle0) / total)) if total > 0 else 100)
    return usage


class LivelyCpuAffinity:
    """Lively の起動を監視し、CPU 割り当てを使用率最小の 1 コアに変更する。"""

    def __init__(self):
        self._pid: int | None = None          # 割り当て変更済みのプロセス
        self._original: tuple[int, int] | None = None   # 変更前の (割り当てマスク, 優先度)
        self._prev_times: list[tuple[int, int]] | None = None
        self._failed_pid: int | None = None   # 失敗ログを出したプロセス

    def update(self, enabled: bool, exe_name: str) -> int | None:
        """定期的に呼ぶ。割り当てを変更したときだけ、選んだ CPU 番号を返す。"""
        if not enabled:
            self.restore()
            self._prev_times = None
            return None

        # 使用率は前回呼び出しからの差分で求めるので、毎回計測しておく
        times = _read_cpu_times()
        prev, self._prev_times = self._prev_times, times

        pid = _find_pid(exe_name)
        if pid is None:
            self._pid = None
            self._original = None
            return None
        if pid == self._pid:
            return None
        if times is not None and prev is None:
            return None   # 使用率の計測がまだ 1 回目。次回に回す

        usage = _cpu_usage(prev, times) if times is not None and prev is not None else None
        return self._apply(pid, usage)

    def restore(self) -> None:
        """変更した CPU 割り当て・優先度を元に戻す。"""
        if self._pid is not None and self._original is not None:
            handle = _kernel32.OpenProcess(_PROCESS_SET_INFORMATION, False, self._pid)
            if handle:
                try:
                    mask, priority = self._original
                    _kernel32.SetProcessAffinityMask(handle, mask)
                    if priority:
                        _kernel32.SetPriorityClass(handle, priority)
                    logger.info("Lively の CPU 割り当てを元に戻しました (pid=%d)", self._pid)
                finally:
                    _kernel32.CloseHandle(handle)
        self._pid = None
        self._original = None

    def _apply(self, pid: int, usage: list[int] | None) -> int | None:
        handle = _kernel32.OpenProcess(
            _PROCESS_SET_INFORMATION | _PROCESS_QUERY_LIMITED_INFORMATION, False, pid
        )
        if not handle:
            self._log_failure(pid, "OpenProcess")
            return None
        try:
            process_mask = ctypes.c_size_t(0)
            system_mask = ctypes.c_size_t(0)
            if not _kernel32.GetProcessAffinityMask(
                handle, ctypes.byref(process_mask), ctypes.byref(system_mask)
            ):
                self._log_failure(pid, "GetProcessAffinityMask")
                return None

            cpus = [i for i in range(system_mask.value.bit_length()) if system_mask.value >> i & 1]
            if not cpus:
                return None
            measured = [i for i in cpus if usage is not None and i < len(usage)]
            if measured:
                # 使用率最小の CPU が複数あれば、偏らないようランダムに選ぶ
                lowest = min(usage[i] for i in measured)
                cpu = random.choice([i for i in measured if usage[i] == lowest])
            else:
                lowest = None
                cpu = cpus[0]

            priority = _kernel32.GetPriorityClass(handle)
            if not _kernel32.SetProcessAffinityMask(handle, 1 << cpu):
                self._log_failure(pid, "SetProcessAffinityMask")
                return None
            _kernel32.SetPriorityClass(handle, _HIGH_PRIORITY_CLASS)

            self._pid = pid
            self._original = (process_mask.value, priority)
            logger.info(
                "Lively の CPU 割り当てを CPU%d のみに変更しました (pid=%d, 使用率=%s)",
                cpu, pid, "取得失敗" if lowest is None else f"{lowest}%",
            )
            return cpu
        finally:
            _kernel32.CloseHandle(handle)

    def _log_failure(self, pid: int, func: str) -> None:
        # 起動中は毎回リトライするので、同じプロセスについてのログは 1 回だけにする
        if pid != self._failed_pid:
            self._failed_pid = pid
            logger.warning(
                "Lively の CPU 割り当てを変更できませんでした (pid=%d, %s, error=%d)。"
                "Lively を管理者権限で起動している場合は、本ツールも管理者権限で起動してください。",
                pid, func, ctypes.get_last_error(),
            )
