"""モニターの HDR (Advanced Color) 有効状態の取得

HDR が有効なモニターでは、DXGI Desktop Duplication (dxcam) で取り込んだ画面の
明るい部分が白飛びし、色の濃淡で読み取る表示 (プレー画面の判定内訳バーなど) を読めなくなる。
"""
from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

_QDC_ONLY_ACTIVE_PATHS = 0x00000002
_DISPLAYCONFIG_DEVICE_INFO_GET_SOURCE_NAME = 1
_DISPLAYCONFIG_DEVICE_INFO_GET_ADVANCED_COLOR_INFO = 9
_ADVANCED_COLOR_ENABLED = 0x2
_CCHDEVICENAME = 32


class _LUID(ctypes.Structure):
    _fields_ = [("LowPart", wintypes.DWORD), ("HighPart", wintypes.LONG)]


class _PATH_SOURCE_INFO(ctypes.Structure):
    _fields_ = [
        ("adapterId", _LUID),
        ("id", ctypes.c_uint32),
        ("modeInfoIdx", ctypes.c_uint32),
        ("statusFlags", ctypes.c_uint32),
    ]


class _RATIONAL(ctypes.Structure):
    _fields_ = [("Numerator", ctypes.c_uint32), ("Denominator", ctypes.c_uint32)]


class _PATH_TARGET_INFO(ctypes.Structure):
    _fields_ = [
        ("adapterId", _LUID),
        ("id", ctypes.c_uint32),
        ("modeInfoIdx", ctypes.c_uint32),
        ("outputTechnology", ctypes.c_uint32),
        ("rotation", ctypes.c_uint32),
        ("scaling", ctypes.c_uint32),
        ("refreshRate", _RATIONAL),
        ("scanLineOrdering", ctypes.c_uint32),
        ("targetAvailable", wintypes.BOOL),
        ("statusFlags", ctypes.c_uint32),
    ]


class _PATH_INFO(ctypes.Structure):
    _fields_ = [
        ("sourceInfo", _PATH_SOURCE_INFO),
        ("targetInfo", _PATH_TARGET_INFO),
        ("flags", ctypes.c_uint32),
    ]


class _MODE_INFO(ctypes.Structure):
    # 中身は使わないのでサイズだけ合わせる (DISPLAYCONFIG_MODE_INFO は 64 バイト)
    _fields_ = [("data", ctypes.c_byte * 64)]


class _DEVICE_INFO_HEADER(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.c_uint32),
        ("size", ctypes.c_uint32),
        ("adapterId", _LUID),
        ("id", ctypes.c_uint32),
    ]


class _SOURCE_DEVICE_NAME(ctypes.Structure):
    _fields_ = [
        ("header", _DEVICE_INFO_HEADER),
        ("viewGdiDeviceName", wintypes.WCHAR * _CCHDEVICENAME),
    ]


class _ADVANCED_COLOR_INFO(ctypes.Structure):
    _fields_ = [
        ("header", _DEVICE_INFO_HEADER),
        ("value", ctypes.c_uint32),
        ("colorEncoding", ctypes.c_uint32),
        ("bitsPerColorChannel", ctypes.c_uint32),
    ]


class _MONITORINFOEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
        ("szDevice", wintypes.WCHAR * _CCHDEVICENAME),
    ]


def _user32():
    # ctypes.windll.user32 は他モジュールが argtypes を設定しているので、別のインスタンスを使う
    return ctypes.WinDLL("user32")


def _monitor_device_name(hmonitor: int) -> str:
    user32 = _user32()
    info = _MONITORINFOEXW()
    info.cbSize = ctypes.sizeof(_MONITORINFOEXW)
    if not user32.GetMonitorInfoW(wintypes.HANDLE(hmonitor), ctypes.byref(info)):
        return ""
    return info.szDevice


def is_hdr_monitor(hmonitor: int) -> bool:
    """指定モニターで HDR が有効かどうか。判定できなければ False。"""
    if not sys.platform.startswith("win") or not hmonitor:
        return False
    try:
        device_name = _monitor_device_name(hmonitor)
        if not device_name:
            return False

        user32 = _user32()
        path_count = ctypes.c_uint32()
        mode_count = ctypes.c_uint32()
        if user32.GetDisplayConfigBufferSizes(
            _QDC_ONLY_ACTIVE_PATHS, ctypes.byref(path_count), ctypes.byref(mode_count)
        ):
            return False
        paths = (_PATH_INFO * path_count.value)()
        modes = (_MODE_INFO * mode_count.value)()
        if user32.QueryDisplayConfig(
            _QDC_ONLY_ACTIVE_PATHS, ctypes.byref(path_count), paths, ctypes.byref(mode_count), modes, None
        ):
            return False

        for path in paths[:path_count.value]:
            source = _SOURCE_DEVICE_NAME()
            source.header.type = _DISPLAYCONFIG_DEVICE_INFO_GET_SOURCE_NAME
            source.header.size = ctypes.sizeof(_SOURCE_DEVICE_NAME)
            source.header.adapterId = path.sourceInfo.adapterId
            source.header.id = path.sourceInfo.id
            if user32.DisplayConfigGetDeviceInfo(ctypes.byref(source)):
                continue
            if source.viewGdiDeviceName != device_name:
                continue

            color = _ADVANCED_COLOR_INFO()
            color.header.type = _DISPLAYCONFIG_DEVICE_INFO_GET_ADVANCED_COLOR_INFO
            color.header.size = ctypes.sizeof(_ADVANCED_COLOR_INFO)
            color.header.adapterId = path.targetInfo.adapterId
            color.header.id = path.targetInfo.id
            if user32.DisplayConfigGetDeviceInfo(ctypes.byref(color)):
                return False
            return bool(color.value & _ADVANCED_COLOR_ENABLED)
    except Exception:
        pass
    return False
