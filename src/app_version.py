"""アプリのバージョンと、実行場所の判定

バージョンは pyproject.toml の version (YYMMDD、同日の再リリースは YYMMDD.N) を正とする。
ビルド (setup.py) が pyproject.toml を exe と同じフォルダにコピーするので、配布版でも同じ方法で読める。
"""
from __future__ import annotations

import os
import re
import sys
import tomllib

from src.logger import get_logger

logger = get_logger(__name__)

APP_NAME = "pop_lively_support_tool"
EXE_NAME = f"{APP_NAME}.exe"

_SOURCE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_VERSION_PATTERN = re.compile(r"^v?(\d{6})(?:\.(\d+))?$")


def is_frozen() -> bool:
    """exe (cx_Freeze でビルドしたもの) として実行中か"""
    return bool(getattr(sys, "frozen", False))


def app_dir() -> str:
    """アプリのフォルダ。配布版は exe のあるフォルダ、ソース実行時はリポジトリ直下。"""
    return os.path.dirname(os.path.abspath(sys.executable)) if is_frozen() else _SOURCE_ROOT


def get_app_version() -> str:
    """実行中のアプリのバージョン文字列 (読めなければ "0")"""
    try:
        with open(os.path.join(app_dir(), "pyproject.toml"), "rb") as f:
            return str(tomllib.load(f)["project"]["version"])
    except (OSError, KeyError, ValueError) as e:
        logger.warning("バージョンを読めませんでした: %s", e)
        return "0"


def parse_version(text: str) -> tuple[int, int] | None:
    """"261014.1" → (261014, 1)。"261004" → (261004, 0)。バージョンの形式でなければ None。"""
    match = _VERSION_PATTERN.match(text.strip())
    if match is None:
        return None
    return int(match.group(1)), int(match.group(2) or 0)


def is_newer(candidate: str, current: str) -> bool:
    """candidate が current より新しいバージョンか。どちらかが読めなければ False。"""
    a, b = parse_version(candidate), parse_version(current)
    return a is not None and b is not None and a > b
