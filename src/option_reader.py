"""pop'n music Lively オプション選択画面の設定一覧読み取り

読み取り方針:
    1. 画面右下のこげ茶色のパネルに、現在の設定値が 11 行で一覧表示される。
       上から ハイスピード / ポップ君 / ゲージタイプ / GUIDE SE / RANDOM / JUDGE+ /
       HIDDEN / SUDDEN / OJAMA1 / OJAMA2 / AUTO。シンプル設定では上 4 行だけが並ぶ。
    2. 各行の下には色付きの下線が引かれている。キャプチャ方式によって縦位置・縦倍率が
       変わるため、固定座標ではなく下線を手がかりに各行の位置を求める。
    3. 各行の文字 (白。オジャマの「ずっと」は黄) を二値化し、
       Windows 標準 OCR (src/song_reader.py) で文字列にする。
    4. OCR 結果をオプションマスター (src/option_master.py) の値に正規化する。
       OJAMA 行の先頭に黄色の「ずっと」があれば「OJAMA ずっと」を ON とする。

設定を開いていない OptionSelect 画面では、中央下の黒枠に並ぶオプションアイコンから読む:
    - ハイスピードは bpm 行の「150 × 2.9 = 435」を OCR で読む。
    - ポップ君 / ゲージ / RANDOM / JUDGE+ / AUTO / GUIDE SE はアイコンの絵柄を
      テンプレート (src/option_templates.py) と照合する。
    - HIDDEN / SUDDEN はアイコン内の数字を 1 文字ずつテンプレートと照合する。
    - アイコンから分からない項目 (設定中の OJAMA の種類、GUIDE SE の大/小) は読まない。
"""
from __future__ import annotations

import base64
import difflib
import re
from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from src.define import PosOptionIcons, PosOptionList
from src.logger import get_logger
from src.option_master import OPTION_MASTER, _match_key, normalize_option
from src.song_reader import _ocr, _runs

logger = get_logger(__name__)

try:
    from src.option_templates import GLYPHS as _RAW_GLYPHS, ICONS as _RAW_ICONS
except Exception:  # テンプレート未生成時 (tools/build_option_templates.py 実行前)
    _RAW_GLYPHS, _RAW_ICONS = [], {}

# 一覧の行 (上から順) に対応する項目キー
LIST_KEYS = (
    "hispeed", "popkun", "gauge_type", "guide_se", "random", "judge_plus",
    "hidden", "sudden", "ojama1", "ojama2", "auto",
)
_ZUTTO_KEYS = {"ojama1": "ojama1_zutto", "ojama2": "ojama2_zutto"}

_PANEL_RGB = (48, 28, 16)   # パネルの地色
_PANEL_TOL = 16
_OCR_SCALES = (4, 3)        # OCR にかける際の拡大率。先頭で読めなければ次を試す
_OCR_PAD = 12               # OCR にかける行画像の余白 (px)
_MIN_LINES = 8              # これ未満しか下線が見つからなければ一覧なしとみなす (フル設定)
# 文字の縦範囲: 下線から上へ (上端, 下端)。フル設定の行間隔に対する比率
_TEXT_BAND = (0.90, 0.08)
_SIMPLE_TEXT_BAND = (1.16, 0.19)   # シンプル設定は下線との間が広い
_SIMPLE_ROWS = 4            # シンプル設定の一覧の行数 (ハイスピード～GUIDE SE)
_LINE_MERGE_GAP = 10         # この間隔 (px) 未満で並ぶ下線の断片は同じ線とみなす
_MIN_PANEL_RATIO = 0.4      # 行の領域に占めるパネル地色の割合 (全行の中央値) の下限
_WHITE_TH = 140             # 白文字とみなす min(R,G,B)
_INK_RANGE = (50, 180)      # 濃淡画像にする際の min(R,G,B) の範囲 (地色～文字色)
_ZUTTO_MIN_PX = 60          # 「ずっと」とみなす黄色文字の画素数
_OCR_CACHE_MAX = 512
_GUARD = "OFF"              # 行末に付け足すガード語 (_guard_mask)
_GUARD_GAP = 30             # 行の文字とガード語の間隔 (px)
_NUMERIC_KEYS = ("hispeed", "hidden", "sudden")
_NUMERIC_FIX = str.maketrans({
    "士": "±", "土": "±", "十": "+", "一": "-", "ワ": "7", "フ": "7", "コ": "7",
    "O": "0", "o": "0", "〇": "0", "I": "1", "l": "1", "|": "1", "S": "5", "B": "8",
})
_LOOSE_MIN_RATIO = 0.6
_LOOSE_MARGIN = 0.1


@dataclass
class ListRow:
    """一覧の 1 行分の文字領域 (1920x1080 座標)。"""
    x0: int
    x1: int
    y0: int
    y1: int


# ----------------------------------------------------------------------
# 一覧の位置検出
# ----------------------------------------------------------------------

def _panel_mask(arr: np.ndarray) -> np.ndarray:
    diff = np.abs(arr.astype(np.int16) - np.array(_PANEL_RGB, dtype=np.int16))
    return diff.max(axis=2) <= _PANEL_TOL


def _find_underlines(arr: np.ndarray) -> list[tuple[int, int, int, int]]:
    """各行の下線 (y0, y1, x0, x1) を上から順に返す。座標は arr 内の相対値。

    下線は「パネルの地色に左右を挟まれた、地色でも文字でもない横線」として探す。
    """
    panel = _panel_mask(arr)
    line = ~panel & (arr.max(axis=2) > 70) & (arr.min(axis=2) < 200)
    lo, hi = PosOptionList.LINE_LENGTH

    found: dict[int, tuple[int, int]] = {}
    for y in range(arr.shape[0]):
        for s, e in _runs(line[y]):
            if not lo <= e - s <= hi:
                continue
            # 両端のすぐ外側がパネルの地色であること
            if panel[y, max(0, s - 8):s].any() and panel[y, e:e + 8].any():
                found[y] = (s, e)
                break

    # 文字や縮小時のにじみで途切れた線は 1 本にまとめる
    lines: list[tuple[int, int, int, int]] = []
    for y in sorted(found):
        if lines and y - lines[-1][1] < _LINE_MERGE_GAP:
            lines[-1] = (lines[-1][0], y + 1, *lines[-1][2:])
        else:
            lines.append((y, y + 1, *found[y]))
    return lines


def locate_rows(arr: np.ndarray) -> list[ListRow] | None:
    """設定一覧の各行の文字領域を返す。一覧が表示されていなければ None。"""
    ax0, ay0, ax1, ay1 = PosOptionList.SEARCH_AREA
    lines = _find_underlines(arr[ay0:ay1, ax0:ax1])
    if len(lines) < _SIMPLE_ROWS:
        return None

    # 下線は等間隔に並び、下の行ほど右にずれる。見つかった線から行番号を割り当てて直線で近似する
    ys = np.array([(l[0] + l[1]) / 2 for l in lines])
    pitch = float(np.median(np.diff(ys)))
    lo, hi = PosOptionList.PITCH
    simple_lo, simple_hi = PosOptionList.SIMPLE_PITCH
    if simple_lo <= pitch <= simple_hi and len(lines) == _SIMPLE_ROWS:
        # シンプル設定: 上 4 項目だけが広い間隔で並ぶ。文字の大きさはフル設定と同じ
        count = _SIMPLE_ROWS
        text_pitch = pitch * PosOptionList.SIMPLE_TEXT_RATIO
        band = _SIMPLE_TEXT_BAND
    elif lo <= pitch <= hi and len(lines) >= _MIN_LINES:
        count = len(LIST_KEYS)
        text_pitch = pitch
        band = _TEXT_BAND
    else:
        return None
    idx = np.round((ys - ys[0]) / pitch).astype(int)
    if len(set(idx)) != len(idx) or idx[-1] >= count:
        return None
    # 途中や上側の線を取りこぼしても、一番下の線を最終行として番号を振る
    idx += count - 1 - idx[-1]

    fy = np.polyfit(idx, ys, 1)
    # 左端はアイコンとつながって長く検出された線を除いて近似する
    length = float(np.median([l[3] - l[2] for l in lines]))
    ok = [i for i, l in enumerate(lines) if abs(l[3] - l[2] - length) <= 10]
    if len(ok) < _SIMPLE_ROWS:
        return None
    fx = np.polyfit(idx[ok], [lines[i][2] for i in ok], 1)

    rows = []
    for i in range(count):
        y = float(np.polyval(fy, i))
        x = float(np.polyval(fx, i))
        rows.append(ListRow(
            x0=ax0 + int(x) - 2,
            x1=min(arr.shape[1], ax0 + int(x + length) + PosOptionList.TEXT_OVERHANG),
            y0=ay0 + int(y - text_pitch * band[0]),
            y1=ay0 + int(y - text_pitch * band[1]),
        ))
    if rows[0].y0 < 0 or rows[-1].y1 > arr.shape[0]:
        return None
    # 全行がパネルの上に乗っていること (下線に似た別の模様を拾っていないかの確認)
    ratios = [float(_panel_mask(arr[r.y0:r.y1, r.x0:r.x1]).mean()) for r in rows]
    if np.median(ratios) < _MIN_PANEL_RATIO or min(ratios) < _MIN_PANEL_RATIO / 3:
        return None
    return rows


# ----------------------------------------------------------------------
# 行の読み取り
# ----------------------------------------------------------------------

_ocr_cache: dict[tuple, str | None] = {}
_guard_cache: dict[int, np.ndarray] = {}


def _guard_mask(height: int) -> np.ndarray:
    """行末に付け足すガード語の二値マスク。

    Windows OCR は「2.7」のような数字だけの短い行を文字列として検出できない。
    後ろに既知の単語を並べると行として認識されるので、読み取り後に取り除く。
    """
    mask = _guard_cache.get(height)
    if mask is None:
        try:
            font = ImageFont.truetype("arialbd.ttf", int(height * 0.95))
        except OSError:
            font = ImageFont.load_default(int(height * 0.95))
        width = int(font.getlength(_GUARD)) + 4
        image = Image.new("L", (width, height), 0)
        ImageDraw.Draw(image).text((2, height // 2), _GUARD, 255, font=font, anchor="lm")
        mask = _guard_cache[height] = np.asarray(image) > 128
    return mask


def _ocr_row(key: str, ink: np.ndarray, mask: np.ndarray) -> str | None:
    """1 行分の文字を OCR にかけ、マスターの値に正規化して返す。読めなければ None。

    ink は文字の濃さ (0.0～1.0)、mask はその二値版。同じ絵柄は読み直さない。
    """
    cols = np.flatnonzero(mask.any(axis=0))
    if len(cols) == 0:
        return None
    ink = ink[:, cols[0]:cols[-1] + 1]
    mask = mask[:, cols[0]:cols[-1] + 1]
    cache_key = (key, mask.shape, np.packbits(mask).tobytes())
    if cache_key in _ocr_cache:
        return _ocr_cache[cache_key]

    gap = np.zeros((ink.shape[0], _GUARD_GAP), dtype=ink.dtype)
    ink = np.hstack([ink, gap, _guard_mask(ink.shape[0]).astype(ink.dtype)])
    ink = np.pad(ink, _OCR_PAD)
    image = Image.fromarray((255 - ink * 255).astype(np.uint8)).convert("RGB")

    value = None
    for scale in _OCR_SCALES:
        scaled = image.resize((image.width * scale, image.height * scale), Image.Resampling.BICUBIC)
        text = "".join(_ocr.read(scaled).split())
        pos = text.upper().rfind(_GUARD)
        if pos < 0:
            continue
        text = text[:pos] + text[pos + len(_GUARD):]
        value = _normalize(key, text)
        if value is not None:
            break
        logger.debug("オプション一覧: %s を読めませんでした ('%s')", key, text)

    if len(_ocr_cache) >= _OCR_CACHE_MAX:
        _ocr_cache.clear()
    _ocr_cache[cache_key] = value
    return value


def _read_row(arr: np.ndarray, key: str, row: ListRow) -> tuple[str | None, bool]:
    """1 行分の (マスターの値, 黄色の「ずっと」があるか) を返す。"""
    crop = arr[row.y0:row.y1, row.x0:row.x1].astype(np.int16)
    r, g, b = crop[:, :, 0], crop[:, :, 1], crop[:, :, 2]
    level = crop.min(axis=2)
    white = level > _WHITE_TH
    yellow = (r > 170) & (g > 150) & (b < 130)
    # 二値化すると細い線がつぶれるので、OCR には輪郭のぼかしを残した濃淡画像を渡す
    ink = np.clip((level - _INK_RANGE[0]) / (_INK_RANGE[1] - _INK_RANGE[0]), 0.0, 1.0)

    zutto = int(yellow.sum()) >= _ZUTTO_MIN_PX
    if zutto:
        # 「ずっと」より右の白文字だけを読む
        last = int(np.flatnonzero(yellow.any(axis=0))[-1])
        white[:, :last + 1] = False
        ink[:, :last + 1] = 0.0
    return _ocr_row(key, ink, white), zutto


def _closest(text: str, values: list[str]) -> str | None:
    """OCR の誤字が多い日本語名向けの緩い照合。2 位と差がつかない場合は不一致とする。"""
    key = _match_key(text)
    scored = sorted(
        ((difflib.SequenceMatcher(None, key, _match_key(v)).ratio(), v) for v in values),
        reverse=True,
    )
    if len(scored) < 2 or scored[0][0] < _LOOSE_MIN_RATIO or scored[0][0] - scored[1][0] < _LOOSE_MARGIN:
        return None
    return scored[0][1]


def _normalize(key: str, text: str) -> str | None:
    if key in _NUMERIC_KEYS:
        if "OFF" in text.upper():
            return normalize_option(key, "OFF")
        # 数字・記号は似た形の文字に化けやすい
        text = text.translate(_NUMERIC_FIX)
        if key == "hispeed" and text.isdigit() and len(text) >= 2:
            text = f"{text[:-1]}.{text[-1]}"   # 小数点の取りこぼし
    value = normalize_option(key, text)
    if value is None and text and key in _ZUTTO_KEYS:
        value = _closest(text, OPTION_MASTER[key])
    return value


def read_option_list(image: Image.Image) -> dict[str, str] | None:
    """オプション選択画面 (1920x1080) の設定一覧を読み取る。

    戻り値は {項目キー: マスターの値}。読めなかった項目や、シンプル設定で
    表示されない項目は含めない。一覧が表示されていなければ None。
    """
    arr = np.asarray(image.convert("RGB"))
    if arr.shape[0] < 1080 or arr.shape[1] < 1920:
        return None
    rows = locate_rows(arr)
    if rows is None:
        return None

    values: dict[str, str] = {}
    for key, row in zip(LIST_KEYS, rows):
        value, zutto = _read_row(arr, key, row)
        if value is None:
            continue
        values[key] = value
        if key in _ZUTTO_KEYS:
            values[_ZUTTO_KEYS[key]] = "ON" if zutto else "OFF"
    return values


# ----------------------------------------------------------------------
# オプションアイコン (OptionSelect 画面)
# ----------------------------------------------------------------------

ICON_SIZE = 24             # 正規化後のアイコン画像の一辺
GLYPH_SIZE = (16, 36)      # 正規化後の HIDDEN / SUDDEN の 1 文字分 (幅, 高さ)
_ICON_MAX_DIST = 0.09      # アイコン照合: これを超える距離は不一致とみなす
_ICON_MIN_MARGIN = 0.008   # アイコン照合: 1 位と 2 位 (別の値) の距離の差の下限
_SHIFTS = (-3, 0, 3)       # アイコン位置の探索幅 (px)
_GLYPH_SHIFTS = range(-3, 4)   # 数字は 1 px のずれでも距離が大きく変わるので細かく探す
_GLYPH_MAX_DIST = 0.06     # 数字照合: これを超える距離は不一致とみなす (ずれた位置での誤読を防ぐ)
_BLANK_INK = 0.03          # 文字なしとみなす濃さの平均
_BLACK_TH = 45             # 黒枠とみなす max(R,G,B)
_HISPEED_LABEL_ROWS = 10   # ハイスピードのアイコンは数字で絵柄が変わるので、上部のラベルだけ照合する
_HISPEED_RE = re.compile(r"[x×*]?(\d{1,2}\.\d)=")
_BPM_FIX = str.maketrans({"ー": "=", "一": "=", "ニ": "=", "二": "=", "o": "0", "l": "1"})
UNREADABLE = "?"           # テンプレートのラベル: アイコンからは値を決められない

# アイコンの並び (上段, 下段)
_FULL_ICONS = (
    ("hispeed", "popkun", "gauge_type", "guide_se", "random"),
    ("judge_plus", "hidden", "sudden", "ojama1", "ojama2", "auto"),
)
_SIMPLE_ICONS = ("hispeed", "popkun", "gauge_type", "guide_se")


@dataclass
class IconBox:
    """オプションアイコンの黒枠の位置 (1920x1080 座標)。"""
    x0: int
    x1: int
    y0: int
    y1: int
    simple: bool               # シンプル設定 (アイコン 4 個が 1 段)
    bar: tuple[int, int]       # 上にある bpm 行の (y0, y1)

    @property
    def scale(self) -> float:
        """基準の高さに対する縦倍率 (キャプチャ方式で変わる)"""
        return (self.y1 - self.y0) / PosOptionIcons.BOX_HEIGHT

    def centers(self) -> dict[str, tuple[int, int]]:
        """各アイコンの中心座標"""
        w, h = self.x1 - self.x0, self.y1 - self.y0
        if self.simple:
            rows = ((_SIMPLE_ICONS, PosOptionIcons.SIMPLE_X, PosOptionIcons.SIMPLE_ROW_Y),)
        else:
            rows = zip(_FULL_ICONS, PosOptionIcons.ROW_X, PosOptionIcons.ROW_Y)
        out = {}
        for keys, xs, ry in rows:
            for key, rx in zip(keys, xs):
                out[key] = (self.x0 + round(w * rx), self.y0 + round(h * ry))
        return out


def locate_icon_box(arr: np.ndarray) -> IconBox | None:
    """オプションアイコンの黒枠を探す。見つからなければ None。

    枠内でアイコンのない行 (上下の余白と段の間) はほぼ真っ黒になる。
    フル設定は 上余白 / 段間 / 下余白、シンプル設定は広い上下の余白が見つかる。
    """
    x0, x1 = PosOptionIcons.BAND_X
    sy0, sy1 = PosOptionIcons.SEARCH_Y
    black = (arr[sy0:sy1, x0:x1].max(axis=2) < _BLACK_TH).mean(axis=1) > 0.55
    runs = [(s + sy0, e + sy0) for s, e in _runs(black) if e - s >= 6]

    lo, hi = PosOptionIcons.BOX_HEIGHT_RANGE
    for i, (top, top_end) in enumerate(runs):
        for bottom_start, bottom in runs[i + 1:]:
            h = bottom - top
            if not lo <= h <= hi:
                continue
            middle = [r for r in runs if top_end < r[0] and r[1] < bottom_start]
            mid_y = (top + bottom) / 2
            if len(middle) == 1 and abs(sum(middle[0]) / 2 - mid_y) < h * 0.08:
                simple = False
            elif not middle and top_end - top > h * 0.2 and bottom - bottom_start > h * 0.2:
                simple = True
            else:
                continue
            bars = [r for r in runs if top - h * 0.5 < r[0] and r[1] < top - h * 0.1]
            if not bars:
                continue
            # 枠の左右端: 上余白の行で、中央から連続する黒の範囲
            row = arr[(top + top_end) // 2].max(axis=1) < _BLACK_TH
            center = arr.shape[1] // 2
            edges = [(s, e) for s, e in _runs(row) if s <= center < e]
            wlo, whi = PosOptionIcons.BOX_WIDTH_RANGE
            if not edges or not wlo <= edges[0][1] - edges[0][0] <= whi:
                continue
            return IconBox(edges[0][0], edges[0][1], top, bottom, simple, (bars[0][0], bars[-1][1]))
    return None


def icon_tile(arr: np.ndarray, box: IconBox, center: tuple[int, int]) -> np.ndarray:
    """アイコン 1 個を ICON_SIZE 四方の RGB (0.0～1.0) に正規化して返す。"""
    cx, cy = center
    half_w = PosOptionIcons.ICON_HALF
    half_h = int(half_w * box.scale)
    crop = Image.fromarray(arr[cy - half_h:cy + half_h, cx - half_w:cx + half_w])
    crop = crop.resize((ICON_SIZE, ICON_SIZE), Image.Resampling.BILINEAR)
    return np.asarray(crop, dtype=np.float32) / 255.0


def value_glyphs(arr: np.ndarray, box: IconBox, center: tuple[int, int]) -> list[np.ndarray]:
    """HIDDEN / SUDDEN のアイコン内の値を、右の文字から順に 1 文字ずつ切り出す。

    文字は白、等幅で右詰め。各要素は GLYPH_SIZE の濃淡画像 (0.0～1.0)。
    """
    cx, cy = center
    y0 = cy + int(PosOptionIcons.VALUE_Y[0] * box.scale)
    y1 = cy + int(PosOptionIcons.VALUE_Y[1] * box.scale)
    half = PosOptionIcons.VALUE_GLYPH_HALF
    out = []
    for gx in PosOptionIcons.VALUE_GLYPH_X:
        level = arr[y0:y1, cx + gx - half:cx + gx + half].min(axis=2).astype(np.float32)
        ink = np.clip((level - 150.0) / 70.0, 0.0, 1.0)
        image = Image.fromarray((ink * 255).astype(np.uint8)).resize(GLYPH_SIZE, Image.Resampling.BILINEAR)
        out.append(np.asarray(image, dtype=np.float32) / 255.0)
    return out


def _decode(b64: str, shape: tuple[int, ...]) -> np.ndarray:
    buf = np.frombuffer(base64.b64decode(b64), dtype=np.uint8)
    return buf.reshape(shape).astype(np.float32) / 255.0


def _load_templates(raw_icons, raw_glyphs):
    icons = {
        key: [(label, _decode(b64, (ICON_SIZE, ICON_SIZE, 3))) for label, b64 in items]
        for key, items in raw_icons.items()
    }
    glyphs = [(label, _decode(b64, (GLYPH_SIZE[1], GLYPH_SIZE[0]))) for label, b64 in raw_glyphs]
    return icons, glyphs


_icons, _glyphs = _load_templates(_RAW_ICONS, _RAW_GLYPHS)


def set_templates(raw_icons, raw_glyphs) -> None:
    """テンプレートを差し替える (tools/build_option_templates.py 用)"""
    global _icons, _glyphs
    _icons, _glyphs = _load_templates(raw_icons, raw_glyphs)


def _shifted(center: tuple[int, int], shifts=None):
    """枠の検出誤差を吸収するため、中心を数 px ずらした候補を返す。"""
    shifts = _SHIFTS if shifts is None else shifts
    for dy in shifts:
        for dx in shifts:
            yield center[0] + dx, center[1] + dy


def _match_icon(key: str, arr: np.ndarray, box: IconBox, center: tuple[int, int]) -> tuple[str | None, float]:
    """アイコンをテンプレートと照合し、(ラベル, 距離) を返す。該当なしはラベル None。"""
    templates = _icons.get(key, [])
    if not templates:
        return None, 1.0
    rows = slice(0, _HISPEED_LABEL_ROWS) if key == "hispeed" else slice(None)
    dists: dict[str, float] = {}
    for c in _shifted(center):
        tile = icon_tile(arr, box, c)
        for label, template in templates:
            dist = float(np.abs(tile[rows] - template[rows]).mean())
            if dist < dists.get(label, 1.0):
                dists[label] = dist
    ranked = sorted(dists.items(), key=lambda kv: kv[1])
    best, best_dist = ranked[0]
    if best_dist > _ICON_MAX_DIST:
        return None, best_dist
    # 2 位の値と差がつかない場合は決めない
    if len(ranked) > 1 and ranked[1][1] - best_dist < _ICON_MIN_MARGIN:
        return None, best_dist
    return best, best_dist


def _read_glyphs(glyphs: list[np.ndarray]) -> tuple[str | None, float]:
    """右から順に並んだ文字画像を ("+26" 等, 平均距離) にする。読めなければ値は None。"""
    digits, total = "", 0.0
    for glyph in glyphs:
        if float(glyph.mean()) < _BLANK_INK:
            break
        best, best_dist = None, 1.0
        for label, template in _glyphs:
            dist = float(np.abs(glyph - template).mean())
            if dist < best_dist:
                best, best_dist = label, dist
        if best is None or best_dist > _GLYPH_MAX_DIST:
            break
        total += best_dist
        if not best.isdigit():
            # 符号まで読めたら完了 (符号だけ・符号なしは不正)
            return (best + digits, total / (len(digits) + 1)) if digits else (None, 1.0)
        digits = best + digits
    return None, 1.0


def _read_icon_value(arr: np.ndarray, box: IconBox, center: tuple[int, int]) -> str | None:
    """HIDDEN / SUDDEN のアイコン内の値 ("+26" "-139" "±0") を読む。読めなければ None。"""
    best, best_dist = None, 1.0
    for c in _shifted(center, _GLYPH_SHIFTS):
        value, dist = _read_glyphs(value_glyphs(arr, box, c))
        if value is not None and dist < best_dist:
            best, best_dist = value, dist
    return best


def _read_bpm_hispeed(arr: np.ndarray, box: IconBox) -> str | None:
    """bpm 行の「150 × 2.9 = 435」からハイスピードの値を読む。"""
    w = box.x1 - box.x0
    x0, x1 = (box.x0 + round(w * r) for r in PosOptionIcons.BPM_X)
    level = arr[box.bar[0]:box.bar[1], x0:x1].max(axis=2).astype(np.float32)
    mask = level > 130
    if not mask.any():
        return None
    cache_key = ("bpm", mask.shape, np.packbits(mask).tobytes())
    if cache_key in _ocr_cache:
        return _ocr_cache[cache_key]

    ink = np.pad(np.clip((level - 60.0) / 140.0, 0.0, 1.0), _OCR_PAD)
    image = Image.fromarray((255 - ink * 255).astype(np.uint8)).convert("RGB")
    value = None
    for scale in _OCR_SCALES:
        scaled = image.resize((image.width * scale, image.height * scale), Image.Resampling.BICUBIC)
        text = "".join(_ocr.read(scaled).split()).casefold().translate(_BPM_FIX)
        m = _HISPEED_RE.search(text)
        if m:
            value = normalize_option("hispeed", m.group(1))
            if value is not None:
                break
    if len(_ocr_cache) >= _OCR_CACHE_MAX:
        _ocr_cache.clear()
    _ocr_cache[cache_key] = value
    return value


_last_icons: tuple[tuple, dict[str, str]] | None = None   # 直近に読んだ (枠内の絵柄, 結果)


def has_option_icons(arr: np.ndarray, box: IconBox | None = None) -> bool:
    """オプションアイコンの黒枠が表示されているか (画面判定用)。"""
    if box is None:
        if arr.shape[0] < 1080 or arr.shape[1] < 1920:
            return False
        box = locate_icon_box(arr)
        if box is None:
            return False
    return _match_icon("hispeed", arr, box, box.centers()["hispeed"])[0] is not None


def read_option_icons(image: Image.Image) -> dict[str, str] | None:
    """OptionSelect 画面 (1920x1080) のオプションアイコンから設定を読み取る。

    戻り値は {項目キー: マスターの値}。アイコンから分からない項目は含めない。
    アイコンが表示されていなければ None。
    """
    arr = np.asarray(image.convert("RGB"))
    if arr.shape[0] < 1080 or arr.shape[1] < 1920:
        return None
    box = locate_icon_box(arr)
    if box is None:
        return None
    # 枠内の絵柄が前回と同じなら読み直さない (枠の外は背景が動くので見ない)
    global _last_icons
    signature = (
        box,
        arr[box.bar[0]:box.bar[1], box.x0:box.x1].tobytes(),
        arr[box.y0:box.y1, box.x0:box.x1].tobytes(),
    )
    if _last_icons is not None and _last_icons[0] == signature:
        return dict(_last_icons[1])

    centers = box.centers()
    # 先頭は必ずハイスピードのアイコン (似た黒枠を拾っていないかの確認)
    if not has_option_icons(arr, box):
        return None

    values: dict[str, str] = {}
    hispeed = _read_bpm_hispeed(arr, box)
    if hispeed is not None:
        values["hispeed"] = hispeed
    for key, center in centers.items():
        if key == "hispeed":
            continue
        # HIDDEN / SUDDEN は数値を先に読む。読めなければ絵柄で OFF かどうかだけ判別する
        label = _read_icon_value(arr, box, center) if key in ("hidden", "sudden") else None
        dist = 0.0
        if label is None:
            label, dist = _match_icon(key, arr, box, center)
        if label is None:
            logger.debug("オプションアイコン: %s を読めませんでした (距離 %.3f)", key, dist)
            continue
        if label == UNREADABLE:
            continue
        value = normalize_option(key, label)
        if value is None:
            continue
        values[key] = value
        if key in _ZUTTO_KEYS and value == "OFF":
            values[_ZUTTO_KEYS[key]] = "OFF"
    _last_icons = (signature, dict(values))
    return values
