"""pop'n music Lively プレー画面上部の曲名・難易度区分読み取り

読み取り方針:
    1. 画面上部中央の黒い曲名バーを動的に検出する。
       キャプチャ方式（タイトルバー込み/クライアント領域のみ）によって縦に数十 px ずれるため、
       固定座標ではなく「黒地に白文字だけの行」が続く範囲をバーとみなす。
    2. バー内の曲名を Windows 標準 OCR (Windows.Media.Ocr) で文字列にする。
       OCR 結果は誤字を含みうるので、曲テーブルとのあいまい照合 (src/db.py) を前提とする。
    3. バー右端の丸い難易度アイコンの色相から難易度区分を判定する。
"""
from __future__ import annotations

import asyncio
import colorsys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import numpy as np
from PIL import Image

from src.define import PosPlaySong
from src.logger import get_logger

logger = get_logger(__name__)

_OCR_TIMEOUT_SEC = 3.0
_OCR_SCALE = 2

# 難易度アイコンの色相範囲 (度)。EX は 0 度をまたぐので別扱い
_HUE_RANGES = (
    ("HYPER", 15, 75),     # 橙〜黄
    ("NORMAL", 75, 165),   # 緑
    ("EASY", 165, 290),    # 青
)


@dataclass
class PlaySongInfo:
    """プレー画面から読み取った曲情報。読めなかった項目は空文字。"""
    text: str = ""         # OCR で読んだ曲名（未照合）
    difficulty: str = ""   # EASY / NORMAL / HYPER / EX


# ----------------------------------------------------------------------
# 曲名バー検出
# ----------------------------------------------------------------------

def _runs(flags: np.ndarray) -> list[tuple[int, int]]:
    """flags が True の連続区間 [start, end) のリストを返す。"""
    padded = np.concatenate(([False], flags, [False]))
    edges = np.flatnonzero(padded[1:] != padded[:-1])
    return [(int(edges[i]), int(edges[i + 1])) for i in range(0, len(edges), 2)]


def locate_title_bar(arr: np.ndarray) -> tuple[int, int] | None:
    """曲名バーの (y0, y1) を返す。見つからなければ None。

    バーの行は「黒」と「白文字」でほぼ埋まる。直下のレーンは中間的な暗色、
    ウィンドウのタイトルバーはほぼ全面が明るいので、どちらも除外できる。
    """
    x0, x1 = PosPlaySong.TITLE_X
    band = arr[:PosPlaySong.SEARCH_BOTTOM, x0:x1]
    black = (band.max(axis=2) < 40).mean(axis=1)
    white = (band.min(axis=2) > 150).mean(axis=1)
    is_bar = (black + white > 0.7) & (white < 0.8)

    # 文字の輪郭（中間色）が多い行で途切れるため、数 px の隙間はつなげる
    merged: list[tuple[int, int]] = []
    for s, e in _runs(is_bar):
        if merged and s - merged[-1][1] <= 4:
            merged[-1] = (merged[-1][0], e)
        else:
            merged.append((s, e))
    if not merged:
        return None
    y0, y1 = max(merged, key=lambda r: r[1] - r[0])
    lo, hi = PosPlaySong.BAR_HEIGHT
    return (y0, y1) if lo <= y1 - y0 <= hi else None


# ----------------------------------------------------------------------
# OCR (Windows.Media.Ocr)
# ----------------------------------------------------------------------

class _WindowsOcr:
    """Windows 標準 OCR のラッパー。

    GUI スレッドの COM アパートメントと干渉しないよう、専用スレッドで実行する。
    winrt パッケージや日本語 OCR が使えない環境では常に空文字を返す。
    """

    def __init__(self):
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ocr")
        self._engine = None
        self._unavailable = False

    def _create_engine(self):
        from winrt.windows.globalization import Language
        from winrt.windows.media.ocr import OcrEngine

        engine = OcrEngine.try_create_from_language(Language("ja"))
        if engine is None:
            engine = OcrEngine.try_create_from_user_profile_languages()
        if engine is None:
            raise RuntimeError("OCR 言語パックがインストールされていません")
        return engine

    def _recognize(self, image: Image.Image) -> str:
        from winrt.windows.graphics.imaging import (
            BitmapAlphaMode,
            BitmapPixelFormat,
            SoftwareBitmap,
        )
        from winrt.windows.storage.streams import DataWriter

        if self._engine is None:
            self._engine = self._create_engine()

        rgba = image.convert("RGBA")
        writer = DataWriter()
        writer.write_bytes(rgba.tobytes())
        bitmap = SoftwareBitmap.create_copy_with_alpha_from_buffer(
            writer.detach_buffer(),
            BitmapPixelFormat.RGBA8,
            rgba.width,
            rgba.height,
            BitmapAlphaMode.PREMULTIPLIED,
        )

        async def run():
            return await self._engine.recognize_async(bitmap)

        return asyncio.run(run()).text

    def read(self, image: Image.Image) -> str:
        if self._unavailable:
            return ""
        try:
            return self._executor.submit(self._recognize, image).result(_OCR_TIMEOUT_SEC)
        except (ImportError, RuntimeError) as e:
            self._unavailable = True
            logger.warning("Windows OCR が利用できないため曲名認識を無効化します: %s", e)
        except Exception as e:
            logger.debug("OCR エラー: %s", e)
        return ""


_ocr = _WindowsOcr()


# ----------------------------------------------------------------------
# 難易度区分
# ----------------------------------------------------------------------

def _read_difficulty(arr: np.ndarray, bar: tuple[int, int]) -> str:
    """曲名バー右端の丸アイコンの色から難易度区分を返す。判定できなければ空文字。"""
    cy = (bar[0] + bar[1]) // 2
    half = PosPlaySong.DIFF_ICON_HALF
    cx = PosPlaySong.DIFF_ICON_X
    icon = arr[max(0, cy - half):cy + half, cx - half:cx + half].reshape(-1, 3) / 255.0

    hues = []
    for r, g, b in icon:
        h, s, v = colorsys.rgb_to_hsv(r, g, b)
        if s > 0.5 and v > 0.5:
            hues.append(h * 360.0)
    if len(hues) < len(icon) * 0.2:
        return ""

    # アイコン内には文字の縁取り等の別色も混じるので、最も多い色相帯を採用する
    hist, _ = np.histogram(hues, bins=24, range=(0, 360))
    hue = (int(np.argmax(hist)) + 0.5) * 15.0
    for name, lo, hi in _HUE_RANGES:
        if lo <= hue < hi:
            return name
    return "EX"   # 赤〜ピンク


# ----------------------------------------------------------------------
# 公開関数
# ----------------------------------------------------------------------

def crop_title(image: Image.Image) -> Image.Image | None:
    """曲名バーの文字領域を切り出す。バーが見つからなければ None。"""
    arr = np.asarray(image.convert("RGB"))
    bar = locate_title_bar(arr)
    if bar is None:
        return None
    x0, x1 = PosPlaySong.TITLE_X
    return image.crop((x0, bar[0], x1, bar[1]))


def read_play_song(image: Image.Image) -> PlaySongInfo:
    """プレー画面 (1920x1080) から曲名と難易度区分を読み取る。"""
    info = PlaySongInfo()
    arr = np.asarray(image.convert("RGB"))
    if arr.shape[0] < 1080 or arr.shape[1] < 1920:
        return info
    bar = locate_title_bar(arr)
    if bar is None:
        return info

    x0, x1 = PosPlaySong.TITLE_X
    crop = image.crop((x0, bar[0], x1, bar[1]))
    # 等倍では英字を読み誤りやすいので拡大してから OCR にかける
    crop = crop.resize(
        (crop.width * _OCR_SCALE, crop.height * _OCR_SCALE), Image.Resampling.LANCZOS
    )
    info.text = " ".join(_ocr.read(crop).split())
    info.difficulty = _read_difficulty(arr, bar)
    return info
