"""pop'n music Lively リザルト画面のスコアパネル数字読み取り

読み取り方針:
    1. スコアパネル（青枠の中に黒い角丸ボックスが縦に4つ並ぶ）を動的に検出する。
       キャプチャ方式（タイトルバー込み/クライアント領域のみ等）によってパネル位置が
       縦に十数 px ずれるため、固定座標ではなく青い区切り行を手がかりに位置を求める。
           SCORE / COOL・GREAT・GOOD・BAD / COMBO / BEST SCORE（前回ベスト・差分）
    2. 各行の右側（数字表示域）を列方向の射影で1文字ずつに分割する。
    3. 各文字を 24x24 に正規化し、テンプレート (src/digit_templates.py) と照合する。
    4. SCORE は「前回ベスト + 差分」と突き合わせて検算する。
"""
from __future__ import annotations

import base64
from dataclasses import dataclass, field

import numpy as np
from PIL import Image

from src.logger import get_logger

logger = get_logger(__name__)

try:
    from src.digit_templates import TEMPLATES as _RAW_TEMPLATES
except Exception:  # テンプレート未生成時 (tools/build_digit_templates.py 実行前)
    _RAW_TEMPLATES = {}

GLYPH_SIZE = 24          # 正規化後の文字サイズ (正方形)
_BRIGHT_TH = 128         # 黒背景上の文字とみなす輝度 (max(R,G,B))
_MATCH_MAX_DIST = 0.16   # これを超える距離は「読めなかった」とみなす
_UNSURE_DIST = 0.12      # これを超える距離は採用するが、不確かとして記録する
_MAX_SCORE = 100000
_CROSS_FONT_PENALTY = 0.03  # 他フォントのテンプレートと照合する際に距離へ加算する値

# パネル探索範囲 (1920x1080 座標)
_SEARCH_Y = (480, 1070)
_BAND_X = (760, 1160)    # 区切り行判定に使う中央帯
_BOX_SEARCH_X = (600, 1320)

_JUDGE_NAMES = ("cool", "great", "good", "bad")
# フォントごとの標準的な数字の縦横比 (幅 / 高さ) と、正規化後の標準字幅
_FONT_ASPECT = {"score": 36 / 43, "judge": 25 / 33, "combo": 30 / 34, "best": 20 / 27}
_NOMINAL_W = 20
_SMALL_FONTS = ("judge", "combo", "best")
# 判定ボックス内の各行の中心位置 (ボックス高さに対する比率)。行の実測に失敗した場合に使う
_JUDGE_ROW_CENTERS = (0.185, 0.406, 0.622, 0.844)
_JUDGE_ROW_HALF = 0.105
# SCORE ボックスの高さ (判定ボックス高さに対する比率)
_SCORE_BOX_RATIO = 0.37


@dataclass
class PanelBoxes:
    """スコアパネル内の各黒ボックスの位置 (1920x1080 座標)。"""
    x0: int
    x1: int
    score: tuple[int, int]
    judge: tuple[int, int]
    combo: tuple[int, int]
    best: tuple[int, int]
    judge_rows: list[tuple[int, int]] = field(default_factory=list)  # COOL/GREAT/GOOD/BAD

    def row(self, name: str) -> tuple[int, int]:
        """行名から (y0, y1) を返す。"""
        if name == "score":
            return self.score
        if name == "combo":
            return self.combo
        if name in _JUDGE_NAMES:
            return self.judge_rows[_JUDGE_NAMES.index(name)]
        mid = (self.best[0] + self.best[1]) // 2
        if name == "best":
            return self.best[0], mid
        if name == "diff":
            return mid, self.best[1]
        raise KeyError(name)

    def digit_x(self, name: str) -> tuple[int, int]:
        """行名から数字表示域の (x0, x1) を返す。ラベル文字を避けた右側。"""
        w = self.x1 - self.x0
        ratio = 0.42 if name == "score" else 0.55
        return self.x0 + int(w * ratio), self.x1 - 3


@dataclass
class ResultValues:
    """リザルト画面から読み取った値。読めなかった項目は None。"""
    score: int | None = None
    cool: int | None = None
    great: int | None = None
    good: int | None = None
    bad: int | None = None
    combo: int | None = None
    best: int | None = None
    diff: int | None = None
    score_verified: bool = False   # SCORE が「前回ベスト + 差分」と一致したか
    notes: list[str] = field(default_factory=list)

    @property
    def is_complete(self) -> bool:
        """記録に必要な全項目が読めているか"""
        return None not in (self.score, self.cool, self.great, self.good, self.bad, self.combo)

    def key(self) -> tuple:
        """フレーム間の一致判定用キー"""
        return (self.score, self.cool, self.great, self.good, self.bad, self.combo)


# ----------------------------------------------------------------------
# テンプレート
# ----------------------------------------------------------------------

def _load_templates() -> dict[str, list[tuple[str, np.ndarray]]]:
    out: dict[str, list[tuple[str, np.ndarray]]] = {}
    for group, items in _RAW_TEMPLATES.items():
        loaded = []
        for label, b64 in items:
            buf = np.frombuffer(base64.b64decode(b64), dtype=np.uint8)
            loaded.append((label, buf.reshape(GLYPH_SIZE, GLYPH_SIZE).astype(np.float32) / 255.0))
        out[group] = loaded
    return out


def _candidate_groups(font: str) -> tuple[str, ...]:
    """照合対象のテンプレート群。SCORE の大きい数字は形が独特なので専用テンプレートのみ。"""
    return ("score",) if font == "score" else _SMALL_FONTS


def _build_weights(templates: dict[str, list[tuple[str, np.ndarray]]]) -> dict[str, np.ndarray]:
    """フォントごとの画素重みを作る。

    太字の数字は輪郭がほぼ同じ塊で、3/5/6/8/9 は内側の小さな切れ込みでしか区別できない。
    テンプレート間でばらつきの大きい画素（＝数字の区別に効く画素）ほど重くする。
    """
    weights = {}
    for font in _FONT_ASPECT:
        stack = [t for g in _candidate_groups(font) for _, t in templates.get(g, [])]
        if len(stack) >= 2:
            weights[font] = np.var(np.array(stack), axis=0) + 0.01
        else:
            weights[font] = np.ones((GLYPH_SIZE, GLYPH_SIZE), dtype=np.float32)
    return weights


def set_templates(raw: dict[str, list[tuple[str, str]]]) -> None:
    """テンプレートを差し替える (テンプレート生成ツール・検証用)。"""
    global _RAW_TEMPLATES, _TEMPLATES, _WEIGHTS
    _RAW_TEMPLATES = raw
    _TEMPLATES = _load_templates()
    _WEIGHTS = _build_weights(_TEMPLATES)


_TEMPLATES = _load_templates()
_WEIGHTS = _build_weights(_TEMPLATES)


# ----------------------------------------------------------------------
# パネル検出
# ----------------------------------------------------------------------

def _runs(values: np.ndarray, threshold: float) -> list[tuple[int, int]]:
    """values > threshold が連続する区間 [start, end) のリストを返す。"""
    flags = np.concatenate(([False], values > threshold, [False]))
    edges = np.flatnonzero(flags[1:] != flags[:-1])
    return [(int(edges[i]), int(edges[i + 1])) for i in range(0, len(edges), 2)]


def locate_panel(arr: np.ndarray) -> PanelBoxes | None:
    """スコアパネルの黒ボックス4つ (SCORE / 判定 / COMBO / BEST SCORE) を検出する。

    ボックス間は青一色の行で区切られているため、中央帯で青が過半を占める行を区切りとする。
    """
    if arr.shape[0] < 1080 or arr.shape[1] < 1920:
        return None

    ys, ye = _SEARCH_Y
    band = arr[ys:ye, _BAND_X[0]:_BAND_X[1]].astype(np.int16)
    r, g, b = band[..., 0], band[..., 1], band[..., 2]
    blue_frac = ((b > 200) & (r < 110) & (g < 130)).mean(axis=1)
    boxes = [(s + ys, e + ys) for s, e in _runs(1.0 - blue_frac, 0.5)]

    for i in range(1, len(boxes) - 2):
        score, judge, combo, best = boxes[i - 1], boxes[i], boxes[i + 1], boxes[i + 2]
        jh = judge[1] - judge[0]
        if not 140 <= jh <= 200:
            continue
        # 判定ボックスの高さを基準に、他ボックスの高さと間隔の比率を確認する
        if (score[1] - score[0]) / jh < 0.28:
            continue
        if (score[1] - score[0]) / jh > 0.48:
            # 「NEW RECORD!」の帯が SCORE ボックス上の区切りを隠している場合。
            # 上端が分からないので判定ボックスとの比率から求める
            score = (score[1] - int(round(jh * _SCORE_BOX_RATIO)), score[1])
        if not 0.22 <= (combo[1] - combo[0]) / jh <= 0.40:
            continue
        if not 0.36 <= (best[1] - best[0]) / jh <= 0.58:
            continue
        if max(judge[0] - score[1], combo[0] - judge[1], best[0] - combo[1]) > 20:
            continue

        # 判定ボックスの行で黒が過半を占める列 → ボックスの左右端
        xs, xe = _BOX_SEARCH_X
        black = arr[judge[0]:judge[1], xs:xe].max(axis=2) < 45
        cols = np.flatnonzero(black.mean(axis=0) > 0.5)
        if len(cols) == 0:
            continue
        x0, x1 = int(cols[0]) + xs, int(cols[-1]) + xs + 1
        if not 450 <= x1 - x0 <= 650:
            continue
        panel = PanelBoxes(x0=x0, x1=x1, score=score, judge=judge, combo=combo, best=best)
        panel.judge_rows = _locate_judge_rows(arr, panel)
        return panel

    return None


def _locate_judge_rows(arr: np.ndarray, panel: PanelBoxes) -> list[tuple[int, int]]:
    """判定ボックス内の COOL/GREAT/GOOD/BAD 各行の (y0, y1) を求める。

    4行は等分配置ではない（上下の余白が異なる）ため、数字の行方向射影から実測する。
    """
    y0, y1 = panel.judge
    x0, x1 = panel.digit_x("cool")
    mask = arr[y0:y1, x0:x1].max(axis=2) > _BRIGHT_TH
    # 右端に接する塊はボックスの角丸なので除外
    for s, e in _runs(mask.sum(axis=0), 0):
        if e >= mask.shape[1]:
            mask[:, s:e] = False
    rows = [(s, e) for s, e in _runs(mask.sum(axis=1), 0) if e - s >= 12]
    if len(rows) == 4:
        return [(max(y0, y0 + s - 2), min(y1, y0 + e + 2)) for s, e in rows]

    h = y1 - y0
    return [
        (int(round(y0 + h * (c - _JUDGE_ROW_HALF))), int(round(y0 + h * (c + _JUDGE_ROW_HALF))))
        for c in _JUDGE_ROW_CENTERS
    ]


# ----------------------------------------------------------------------
# 文字の切り出し・照合
# ----------------------------------------------------------------------

def _row_mask(arr: np.ndarray, name: str) -> tuple[np.ndarray, np.ndarray]:
    """数字部分のマスクを (分割用 bool, 形状用 float 0..1) の組で返す。

    SCORE の大きい数字は緑の影どうしが隣とつながるため、本体のオレンジ色だけで分割する。
    形状用には数字内部の白いハイライトも含め、他フォントと同じ塗りつぶし形状にする。
    それ以外は黒背景に対して明るいピクセルを文字とみなす。
    """
    if name == "score":
        a = arr.astype(np.int16)
        r, g, b = a[..., 0], a[..., 1], a[..., 2]
        orange = (r > 200) & (g > 70) & (g < 200) & (b < 110)
        light = (r > 200) & (g > 150) & (r >= g)   # 白〜淡いオレンジのハイライト
        return orange, (orange | light).astype(np.float32)
    level = arr.max(axis=2)
    # 形状用は輝度の濃淡を残す（拡大キャプチャのぼけ方の違いに二値化より強い）
    soft = np.clip((level.astype(np.float32) - 48.0) / 160.0, 0.0, 1.0)
    return level > _BRIGHT_TH, soft


def _font_of(name: str) -> str:
    """行名からフォント種別を返す。"""
    if name in _JUDGE_NAMES:
        return "judge"
    if name in ("best", "diff"):
        return "best"
    return name


def _normalize_glyph(mask: np.ndarray, font: str) -> np.ndarray:
    """文字マスクを GLYPH_SIZE 四方に正規化する。

    高さを GLYPH_SIZE に揃え、幅はフォントごとの標準字幅が _NOMINAL_W になるよう伸縮する。
    これによりフォントが違っても同じ数字がほぼ同じ形になり、「1」のような細い字は細いまま残る。
    """
    h, w = mask.shape
    new_w = int(round(w / (h * _FONT_ASPECT[font]) * _NOMINAL_W))
    new_w = max(1, min(GLYPH_SIZE, new_w))
    img = Image.fromarray((np.asarray(mask, dtype=np.float32) * 255).astype(np.uint8)).resize(
        (new_w, GLYPH_SIZE), Image.Resampling.BILINEAR
    )
    canvas = np.zeros((GLYPH_SIZE, GLYPH_SIZE), dtype=np.float32)
    off = (GLYPH_SIZE - new_w) // 2
    canvas[:, off:off + new_w] = np.asarray(img, dtype=np.float32) / 255.0
    return canvas


def extract_glyphs(arr: np.ndarray, panel: PanelBoxes, name: str) -> list[np.ndarray]:
    """1行分の数字を左から順に切り出し、文字画像 (float 2D, 0..1) のリストで返す。"""
    y0, y1 = panel.row(name)
    x0, x1 = panel.digit_x(name)
    mask, shape = _row_mask(arr[y0:y1, x0:x1], name)
    width = mask.shape[1]
    # ボックス上下端の枠線（ぼけた青）が横一線に入ることがあるので除外する
    mask[mask.mean(axis=1) > 0.6] = False

    # 列方向の射影で分割。右端に接する塊はボックスの角丸（枠の青）なので捨てる
    col_runs = [
        (s, e) for s, e in _runs(mask.sum(axis=0), 1)
        if e < width and e - s >= 3
    ]
    if not col_runs:
        return []

    # 文字の上下端: 残った列だけで行方向に射影し、最も長い連続区間を採用
    keep = np.zeros(width, dtype=bool)
    for s, e in col_runs:
        keep[s:e] = True
    row_runs = _runs(mask[:, keep].sum(axis=1), 0)
    if not row_runs:
        return []
    top, bottom = max(row_runs, key=lambda r: r[1] - r[0])
    height = bottom - top
    if height < 12:
        return []

    # 隣の文字とつながってしまった塊は等分割する (数字は等幅)
    max_w = height * 1.15
    pieces: list[tuple[int, int]] = []
    for s, e in col_runs:
        n = int(np.ceil((e - s) / max_w)) if e - s > max_w else 1
        step = (e - s) / n
        pieces.extend((int(round(s + step * k)), int(round(s + step * (k + 1)))) for k in range(n))

    glyphs = []
    for s, e in pieces:
        sub = mask[top:bottom, s:e]
        rows = np.flatnonzero(sub.any(axis=1))
        cols = np.flatnonzero(sub.any(axis=0))
        if len(rows) == 0 or len(cols) == 0:
            continue
        glyphs.append(shape[top:bottom, s:e][rows[0]:rows[-1] + 1, cols[0]:cols[-1] + 1])
    return glyphs


def classify_glyph(glyph: np.ndarray, font: str, with_sign: bool = False) -> tuple[str, float, bool]:
    """文字画像をテンプレートと照合し (ラベル, 距離, 同一フォントで一致したか) を返す。

    距離は 0 に近いほど一致。同じフォントのテンプレートを優先し、そのフォントで
    未収録の数字は他の小フォントのテンプレートで補う（距離にペナルティを加算）。
    """
    norm = _normalize_glyph(glyph, font)
    weight = _WEIGHTS[font]
    groups = _candidate_groups(font) + (("sign",) if with_sign else ())
    best_label, best_dist, best_own = "?", 1.0, False
    for group in groups:
        own = group in (font, "sign")
        for label, tmpl in _TEMPLATES.get(group, []):
            dist = float((weight * np.abs(norm - tmpl)).sum() / weight.sum())
            if not own:
                dist += _CROSS_FONT_PENALTY
            if dist < best_dist:
                best_label, best_dist, best_own = label, dist, own
    return best_label, best_dist, best_own


def _read_row(
    arr: np.ndarray, panel: PanelBoxes, name: str, notes: list[str]
) -> tuple[int | None, float]:
    """1行分の数値を読み取り (値, 最も一致の悪かった文字の距離) を返す。読めなければ値は None。"""
    glyphs = extract_glyphs(arr, panel, name)
    if not glyphs:
        notes.append(f"{name}: 数字が見つからない")
        return None, 1.0

    font = _font_of(name)
    full_h = max(g.shape[0] for g in glyphs)

    sign = 1
    text = ""
    worst = 0.0
    for i, glyph in enumerate(glyphs):
        # 差分行の先頭は符号。「-」は数字より明らかに背が低い
        is_sign_pos = name == "diff" and i == 0
        if is_sign_pos and glyph.shape[0] < full_h * 0.5:
            sign = -1
            continue
        label, dist, own = classify_glyph(glyph, font, with_sign=is_sign_pos)
        if label == "+":
            continue

        if not label.isdigit() or dist > _MATCH_MAX_DIST:
            notes.append(f"{name}: {i + 1}文字目が不明 ({label}, dist={dist:.3f})")
            return None, 1.0
        if not own:
            notes.append(f"{name}: {i + 1}文字目 '{label}' は他フォントのテンプレートで推定 (dist={dist:.3f})")
        elif dist > _UNSURE_DIST:
            notes.append(f"{name}: {i + 1}文字目 '{label}' は一致度が低い (dist={dist:.3f})")
        text += label
        worst = max(worst, dist)

    if not text or len(text) > 6:
        notes.append(f"{name}: 桁数異常 '{text}'")
        return None, 1.0
    return sign * int(text), worst


def read_result_values(image: Image.Image) -> ResultValues | None:
    """リザルト画面 (1920x1080) からスコアパネルの数値を読み取る。

    パネル自体が見つからない場合は None を返す。
    """
    arr = np.asarray(image.convert("RGB"))
    panel = locate_panel(arr)
    if panel is None:
        return None

    v = ResultValues()
    dists = {}
    for name in ("cool", "great", "good", "bad", "combo", "best", "diff"):
        value, dists[name] = _read_row(arr, panel, name, v.notes)
        setattr(v, name, value)
    big_score, big_dist = _read_row(arr, panel, "score", v.notes)
    if big_score is not None and not 0 <= big_score <= _MAX_SCORE:
        big_score = None

    # SCORE = 前回ベスト + 差分 で検算する
    sum_score = None
    if v.best is not None and v.diff is not None and v.best >= 0:
        sum_score = v.best + v.diff
        if not 0 <= sum_score <= _MAX_SCORE:
            sum_score = None

    if big_score is not None and sum_score is not None:
        v.score_verified = big_score == sum_score
        if v.score_verified:
            v.score = big_score
        else:
            # 食い違った場合はテンプレートとの一致度が高い方を採用する
            sum_dist = max(dists["best"], dists["diff"])
            v.score = big_score if big_dist <= sum_dist else sum_score
            v.notes.append(
                f"score: 表示 {big_score} と ベスト+差分 {sum_score} が不一致 → {v.score} を採用"
            )
    else:
        v.score = big_score if big_score is not None else sum_score
    return v
