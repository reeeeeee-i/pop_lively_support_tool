"""pop'n music Lively オプション選択画面・リザルト画面の曲バナーによる曲の特定

読み取り方針:
    1. オプション選択画面 (設定を開いていない状態) とリザルト画面の中央上に、選んだ曲のバナーが
       大きく表示される (縦位置はリザルトのほうが 30px ほど下)。
       公式サイトの楽曲一覧にある同じバナー画像から作った特徴量 (popn_music_list.json の banner 列) と照合する。
    2. バナーは黒い縁取りに囲まれている。キャプチャ方式によって縦位置・縦倍率が変わるので、
       縁取りを手がかりにバナーの位置を動的に検出する。
    3. バナーを小さな RGB サムネイルにして、明るさの違いに強い相関で最も近い曲を選ぶ。
       2 位との差が小さいときは曲を決めない (別の曲に誤認するより、曲名 OCR に任せる)。

特徴量の作り方 (banner_feature) は tools / generate_music_list.py も使うので、変えたら曲リストを作り直すこと。
"""
from __future__ import annotations

import base64

import numpy as np
from PIL import Image

from src.define import PosBanner

FEATURE_W = 16
FEATURE_H = 4
_INSET = 0.025          # 縁取りの内側の余白 (バナーの幅・高さに対する比率)
_BLACK_TH = 50          # 縁取りとみなす明るさ (RGB の最大値)

MIN_SCORE = 0.80        # 最も近い曲の相関がこれ未満なら特定しない
MIN_MARGIN = 0.04       # 2 位との相関の差がこれ未満なら特定しない
# 公式サイトのバナーと、ゲーム内のバナーの文字などが違う曲は相関が低くなる。
# その場合は、2 位との差が十分大きいときだけ採用する
LOW_SCORE = 0.60
LOW_SCORE_MARGIN = 0.15


def _runs(flags: np.ndarray) -> list[tuple[int, int]]:
    padded = np.concatenate(([False], flags, [False]))
    edges = np.flatnonzero(padded[1:] != padded[:-1])
    return [(int(edges[i]), int(edges[i + 1])) for i in range(0, len(edges), 2)]


# ----------------------------------------------------------------------
# 特徴量
# ----------------------------------------------------------------------

def banner_feature(image: Image.Image) -> np.ndarray:
    """バナー画像 (縁取りを含まない) から特徴量を作る。正規化済みの float32 ベクトルを返す。

    サムネイルを RGB 平均値で引いて長さ 1 にするので、内積がそのまま相関になる。
    透過部分 (公式サイトの画像は角が透過) は黒として扱う。
    """
    rgba = image.convert("RGBA")
    base = Image.new("RGBA", rgba.size, (0, 0, 0, 255))
    base.alpha_composite(rgba)
    w, h = base.size
    mx, my = round(w * _INSET), round(h * _INSET)
    crop = base.convert("RGB").crop((mx, my, w - mx, h - my))
    thumb = crop.resize((FEATURE_W, FEATURE_H), Image.Resampling.BOX)
    v = np.asarray(thumb, dtype=np.float32).ravel()
    return _normalize(v)


def _normalize(v: np.ndarray) -> np.ndarray:
    v = v - v.mean()
    n = float(np.linalg.norm(v))
    return v / n if n > 1e-6 else v * 0.0


def encode_feature(v: np.ndarray) -> str:
    """特徴量を曲リストに書き込む文字列にする (0～255 に量子化した base64)。"""
    q = np.clip(np.round((v + 0.5) * 255), 0, 255).astype(np.uint8)
    return base64.b64encode(q.tobytes()).decode("ascii")


def decode_feature(s: str) -> np.ndarray | None:
    try:
        q = np.frombuffer(base64.b64decode(s), dtype=np.uint8)
    except ValueError:
        return None
    if q.size != FEATURE_W * FEATURE_H * 3:
        return None
    return _normalize(q.astype(np.float32) / 255 - 0.5)


# ----------------------------------------------------------------------
# 画面からの切り出し
# ----------------------------------------------------------------------

def locate_banner(arr: np.ndarray) -> tuple[int, int, int, int] | None:
    """バナー (縁取りの内側) の (x0, y0, x1, y1) を返す。見つからなければ None。

    黒い縁取りの上辺・下辺は、バナーの幅いっぱいに続く黒い横線になる。
    リザルト画面では上辺がランクの演出などで途切れることがあるので、上辺・下辺のどちらかが
    幅いっぱいに続いていれば、もう一方は途切れていてもよい。
    """
    bx0, bx1 = PosBanner.SEARCH_X
    by0, by1 = PosBanner.SEARCH_Y
    black = arr[by0:by1, bx0:bx1].max(axis=2) < _BLACK_TH
    lo, hi = PosBanner.WIDTH
    lines = []
    for y in range(black.shape[0]):
        runs = [r for r in _runs(black[y]) if PosBanner.LINE_MIN <= r[1] - r[0] <= hi + 20]
        if runs:
            lines.append((y, max(runs, key=lambda r: r[1] - r[0])))
    if not lines:
        return None

    # 連続する行をまとめて「線」にする
    groups: list[list[tuple[int, tuple[int, int]]]] = []
    for item in lines:
        if groups and item[0] - groups[-1][-1][0] <= 1:
            groups[-1].append(item)
        else:
            groups.append([item])

    h_lo, h_hi = PosBanner.HEIGHT
    for i, top in enumerate(groups):
        for bottom in groups[i + 1:]:
            y0, y1 = top[-1][0] + 1, bottom[0][0]
            if not h_lo <= y1 - y0 <= h_hi:
                continue
            full = [g[1] for g in top + bottom if lo <= g[1][1] - g[1][0]]
            if not full:
                continue
            xs0 = int(np.median([r[0] for r in full]))
            xs1 = int(np.median([r[1] for r in full]))
            thickness = len(top)   # 左右の縁取りも上辺と同じ太さとみなす
            return bx0 + xs0 + thickness, by0 + y0, bx0 + xs1 - thickness, by0 + y1
    return None


def read_banner(image: Image.Image) -> np.ndarray | None:
    """オプション選択画面・リザルト画面 (1920x1080) からバナーの特徴量を作る。バナーが見つからなければ None。"""
    arr = np.asarray(image.convert("RGB"))
    if arr.shape[0] < 1080 or arr.shape[1] < 1920:
        return None
    box = locate_banner(arr)
    if box is None:
        return None
    x0, y0, x1, y1 = box
    return banner_feature(Image.fromarray(arr[y0:y1, x0:x1]))


# ----------------------------------------------------------------------
# 照合
# ----------------------------------------------------------------------

class BannerIndex:
    """曲ごとのバナー特徴量を持ち、画面から読んだ特徴量に最も近い曲を返す。"""

    def __init__(self, items: list[tuple[str, np.ndarray]] | None = None):
        self._ids: list[str] = []
        self._matrix = np.zeros((0, FEATURE_W * FEATURE_H * 3), dtype=np.float32)
        if items:
            self._ids = [i for i, _ in items]
            self._matrix = np.stack([v for _, v in items]).astype(np.float32)

    def __len__(self) -> int:
        return len(self._ids)

    def match(self, feature: np.ndarray) -> tuple[str, float, float] | None:
        """(music_id, 相関, 2 位との差) を返す。基準に満たなければ None。

        同じバナーを使う別の曲 (ウラ譜面・別バージョンなど) があると 2 位との差が 0 になり、
        特定できない (曲名 OCR に任せる)。
        """
        if len(self) < 2:
            return None
        sims = self._matrix @ feature
        first, second = (int(i) for i in np.argsort(-sims)[:2])
        score = float(sims[first])
        margin = score - float(sims[second])
        if score < LOW_SCORE or (score < MIN_SCORE and margin < LOW_SCORE_MARGIN) or margin < MIN_MARGIN:
            return None
        return self._ids[first], score, margin
