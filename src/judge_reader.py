"""pop'n music Lively プレー画面下部の判定内訳バー読み取り

読み取り方針:
    プレー画面下部のバーに「BAD 0035 GOOD 0007 GREAT 0034 COOL 0067」が並ぶ。
    数字は 4 桁固定・等幅で、先頭の 0 埋めは暗く、有効な桁だけが明るく表示される。
    1. 判定ごとに、明るい桁だけを取り出した濃淡マスクを作る。
    2. 桁の位置は固定なので、右端から連続して光っている桁をそれぞれ切り出す。
    3. 各桁をテンプレート (src/judge_templates.py) と照合する。
    累計値そのものを読むため、フレームを取りこぼしても打鍵数はずれない。
"""
from __future__ import annotations

import base64

import numpy as np
from PIL import Image

try:
    from src.judge_templates import TEMPLATES as _RAW_TEMPLATES
except Exception:  # テンプレート未生成時 (tools/build_judge_templates.py 実行前)
    _RAW_TEMPLATES = []

JUDGE_NAMES = ("cool", "great", "good", "bad")

GLYPH_W, GLYPH_H = 16, 24    # 正規化後の文字サイズ
_MATCH_MAX_DIST = 0.15       # これを超える距離は「読めなかった」とみなす

# 1920x1080 座標
_SEARCH_Y = (1026, 1068)     # 数字の縦位置の探索範囲 (キャプチャ方式によって数 px ずれる)
_DIGIT_HEIGHT = (18, 30)     # 数字とみなす高さの範囲
_DIGITS = 4
_PITCH = 20.3                # 桁の間隔
_CELL_W = 20                 # 1 桁の切り出し幅
_SHIFTS = (-2, -1, 0, 1, 2)  # 照合時に試す横ずれ
_LIT_MIN_PX = 20             # 桁が光っているとみなす明るいピクセル数
_PILL_MIN_RATIO = 0.5        # 数字表示域のうち、バーの色とみなせるピクセルの最低割合

# 判定ごとの 1 の位の左端 x
_LAST_DIGIT_X = {"bad": 751, "good": 927, "great": 1111, "cool": 1285}


# 明るい桁とみなす輝度の下限 (最も明るい部分を 255 にそろえた後の値)。暗い 0 埋めより少し上
_BRIGHT_FLOOR = {"bad": 208.0, "good": 188.0, "great": 192.0, "cool": 188.0}
_BRIGHT_RANGE = 40.0
_MIN_PEAK_RATIO = 0.6        # 明るい桁があるとみなす最大輝度 (背景から 255 までの比率)


def _soft_mask(rgb: np.ndarray, name: str) -> np.ndarray:
    """明るい桁だけが 1 に近づく濃淡マスク (float 0..1) を返す。暗い 0 埋めと背景は 0。

    BAD (シアン) は背景が青いので B、それ以外 (赤・橙・マゼンタ) は R で見分ける。
    録画などで全体が暗くなっていても読めるよう、最も明るい部分を 255 にそろえてから判定する。
    """
    level = rgb[..., 2 if name == "bad" else 0].astype(np.float32)
    base = float(np.median(level))
    peak = float(np.percentile(level, 99.5))
    if peak < base + (255.0 - base) * _MIN_PEAK_RATIO:
        return np.zeros(level.shape, dtype=np.float32)
    level = base + (level - base) * (255.0 - base) / (peak - base)
    return np.clip((level - _BRIGHT_FLOOR[name]) / _BRIGHT_RANGE, 0.0, 1.0)


def _is_pill(rgb: np.ndarray, name: str) -> np.ndarray:
    """バー (背景・暗い桁・明るい桁のいずれか) の色とみなせるピクセル。"""
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    if name == "bad":
        return (b > 140) & (r < 100)
    if name == "good":
        return (r > 100) & (g < 70) & (b < 60)
    if name == "great":
        return (r > 90) & (g > 60) & (g < 150) & (b < 60)
    return (r > 100) & (g < 50) & (b > 100)


def _load_templates() -> list[tuple[str, np.ndarray]]:
    out = []
    for label, b64 in _RAW_TEMPLATES:
        buf = np.frombuffer(base64.b64decode(b64), dtype=np.uint8)
        out.append((label, buf.reshape(GLYPH_H, GLYPH_W).astype(np.float32) / 255.0))
    return out


def set_templates(raw: list[tuple[str, str]]) -> None:
    """テンプレートを差し替える (テンプレート生成ツール・検証用)。"""
    global _RAW_TEMPLATES, _TEMPLATES
    _RAW_TEMPLATES = raw
    _TEMPLATES = _load_templates()


_TEMPLATES = _load_templates()


def _normalize(cell: np.ndarray) -> np.ndarray:
    img = Image.fromarray((cell * 255).astype(np.uint8)).resize((GLYPH_W, GLYPH_H), Image.Resampling.BILINEAR)
    return np.asarray(img, dtype=np.float32) / 255.0


def extract_digits(arr: np.ndarray, name: str) -> list[list[np.ndarray]] | None:
    """1 判定分の光っている桁を左から順に切り出す。

    各桁は横ずれ (_SHIFTS) ごとの正規化済み画像のリスト。
    バーが表示されていない、または桁の並びが不自然な場合は None。値が 0 の場合は空リスト。
    """
    last_x = _LAST_DIGIT_X[name]
    x0 = int(round(last_x - _PITCH * (_DIGITS - 1))) + min(_SHIFTS)
    x1 = last_x + _CELL_W + max(_SHIFTS)
    region = arr[_SEARCH_Y[0]:_SEARCH_Y[1], x0:x1].astype(np.int16)
    if _is_pill(region, name).mean() < _PILL_MIN_RATIO:
        return None

    soft = _soft_mask(region, name)
    lit = soft > 0.5
    # 探索範囲の上端にはゲージの枠が入り込むことがあるので、最も長い連続区間を数字の行とする
    flags = np.concatenate(([False], lit.any(axis=1), [False]))
    edges = np.flatnonzero(flags[1:] != flags[:-1])
    if len(edges) == 0:
        return []
    top, bottom = max(zip(edges[::2], edges[1::2]), key=lambda r: r[1] - r[0])
    if not _DIGIT_HEIGHT[0] <= bottom - top <= _DIGIT_HEIGHT[1]:
        return None

    digits: list[list[np.ndarray]] = []
    for k in range(_DIGITS):
        cx = int(round(last_x - _PITCH * (_DIGITS - 1 - k))) - x0
        if lit[top:bottom, cx:cx + _CELL_W].sum() < _LIT_MIN_PX:
            if digits:
                return None   # 光っている桁は右端まで連続しているはず
            continue
        digits.append([_normalize(soft[top:bottom, cx + dx:cx + dx + _CELL_W]) for dx in _SHIFTS])
    return digits


def classify_digit(variants: list[np.ndarray]) -> tuple[str, float]:
    """桁画像 (横ずれごとの候補) をテンプレートと照合し (数字, 距離) を返す。距離は 0 に近いほど一致。"""
    best_label, best_dist = "?", 1.0
    for glyph in variants:
        for label, tmpl in _TEMPLATES:
            dist = float(np.abs(glyph - tmpl).mean())
            if dist < best_dist:
                best_label, best_dist = label, dist
    return best_label, best_dist


def read_judge_counts(image: Image.Image) -> dict[str, int | None]:
    """プレー画面 (1920x1080) から各判定の累計値を読む。読めなかった判定は None。"""
    arr = np.asarray(image.convert("RGB"))
    counts: dict[str, int | None] = dict.fromkeys(JUDGE_NAMES)
    if arr.shape[0] < 1080 or arr.shape[1] < 1920:
        return counts

    for name in JUDGE_NAMES:
        digits = extract_digits(arr, name)
        if digits is None:
            continue
        text = ""
        for variants in digits:
            label, dist = classify_digit(variants)
            if dist > _MATCH_MAX_DIST:
                text = ""
                break
            text += label
        else:
            counts[name] = int(text) if text else 0
    return counts
