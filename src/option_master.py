"""pop'n music Lively オプションマスター

オプション項目ごとの選択肢 (ゲーム内の表示順) を定義する。
DB の option_masters テーブルに保存され、オプション値の正規化や修正画面の選択肢に使う。
"""
from __future__ import annotations

import difflib
import re
import unicodedata

# 項目キー (= PopnOptions の属性名 / scores テーブルの列名)。ゲーム内の並び順
OPTION_KEYS = [
    "hispeed", "popkun", "gauge_type", "guide_se", "random", "judge_plus",
    "hidden", "sudden", "ojama1", "ojama2", "ojama1_zutto", "ojama2_zutto", "auto",
]

# ゲーム内の項目名
OPTION_NAMES = {
    "hispeed": "ハイスピード",
    "popkun": "POP-KUN",
    "gauge_type": "GAUGE TYPE",
    "guide_se": "GUIDE SE",
    "random": "RANDOM",
    "judge_plus": "JUDGE+",
    "hidden": "HIDDEN",
    "sudden": "SUDDEN",
    "ojama1": "OJAMA1",
    "ojama2": "OJAMA2",
    "ojama1_zutto": "OJAMA1 ずっと",
    "ojama2_zutto": "OJAMA2 ずっと",
    "auto": "AUTO TYPE",
}

# CSV の列名・オプション要約 (PopnOptions.to_summary) での項目名
OPTION_LABELS = {
    "hispeed": "HI-SPEED",
    "popkun": "POP-KUN",
    "gauge_type": "GAUGE TYPE",
    "guide_se": "GUIDE SE",
    "random": "RANDOM",
    "judge_plus": "JUDGE+",
    "hidden": "HIDDEN",
    "sudden": "SUDDEN",
    "ojama1": "OJAMA1",
    "ojama2": "OJAMA2",
    "ojama1_zutto": "OJAMA1ずっと",
    "ojama2_zutto": "OJAMA2ずっと",
    "auto": "AUTO",
}

OPTION_DEFAULTS = {
    "hispeed": "1.0",
    "popkun": "NORMAL",
    "gauge_type": "NORMAL",
    "guide_se": "OFF",
    "random": "OFF",
    "judge_plus": "OFF",
    "hidden": "OFF",
    "sudden": "OFF",
    "ojama1": "OFF",
    "ojama2": "OFF",
    "ojama1_zutto": "OFF",
    "ojama2_zutto": "OFF",
    "auto": "OFF",
}

_HISPEED_RANGE = (10, 100)   # 1.0 ～ 10.0 (0.1 刻み)
_HIDDEN_RANGE = (-70, 220)   # 1 刻み
_SUDDEN_RANGE = (-200, 90)   # 1 刻み

_OJAMA = [
    "OFF",
    "ミニポップ君",
    "ファットポップ君",
    "しろポップ君",
    "バラバラポップ君",
    "ドキドキポップ君",
    "ナゾイロポップ君",
    "くるくるポップ君",
    "上下プレス",
    "左右プレス",
    "上下プレス&プレス",
    "左右プレス&プレス",
    "上下さかさま",
    "爆走(SPIRAL)",
    "爆走(CIRCLE)",
    "カエルポップ君",
    "色々爆走",
    "EXCITE",
    "GOODがBADに!!",
    "COOL or BAD!!",
    "縦分身",
    "横分身",
    "ふわふわ判定ライン",
    "超ふわふわ判定ライン",
    "ファット判定ライン",
    "にせポップ君の嵐",
    "ポップ君の竜巻",
    "地震でぐらぐら",
    "ダーク",
    "ラブリー",
    "ダンス",
    "ボンバー",
    "ミクロポップ君",
    "ズームポップ君",
    "クロス",
    "トリック",
    "スライド",
    "交互プレス",
]


def format_offset(n: int) -> str:
    """HIDDEN / SUDDEN の位置補正値の表記 (-70, ±0, +220)"""
    return "±0" if n == 0 else f"{n:+d}"


def _offsets(lo: int, hi: int) -> list[str]:
    return ["OFF"] + [format_offset(n) for n in range(lo, hi + 1)]


OPTION_MASTER: dict[str, list[str]] = {
    "hispeed": [f"{n / 10:.1f}" for n in range(_HISPEED_RANGE[0], _HISPEED_RANGE[1] + 1)],
    "popkun": ["NORMAL", "BEAT POP", "CHARA POP(YOU)", "CHARA POP(RIVAL)"],
    "gauge_type": ["NORMAL", "EASY", "HARD", "DANGER"],
    "guide_se": ["ON 大", "OFF", "ON 小"],
    "random": ["OFF", "MIRROR", "RANDOM", "S-RANDOM"],
    "judge_plus": ["OFF", "TIMING", "LOST", "PANIC"],
    "hidden": _offsets(*_HIDDEN_RANGE),
    "sudden": _offsets(*_SUDDEN_RANGE),
    "ojama1": _OJAMA,
    "ojama2": _OJAMA,
    "ojama1_zutto": ["OFF", "ON"],
    "ojama2_zutto": ["OFF", "ON"],
    "auto": ["OFF", "ON"],
}

# 画面から読んだ文字列との照合: これ未満の類似度は不一致とみなす
_MATCH_MIN_RATIO = 0.75

_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")
_OFFSET_RE = re.compile(r"([+\-±]?)(\d+)")


def _match_key(s: str) -> str:
    """表記揺れ (全角/半角・大文字/小文字・空白・マイナス記号) を吸収した照合キー"""
    s = unicodedata.normalize("NFKC", s or "").casefold()
    for ch in "−‐‑–—ー":
        s = s.replace(ch, "-")
    return "".join(s.split())


def normalize_option(key: str, text: str, values: list[str] | None = None) -> str | None:
    """読み取った文字列・手入力された文字列をマスターの値に正規化する。

    values は対象項目の選択肢 (省略時は OPTION_MASTER)。該当が無ければ None。
    """
    if values is None:
        values = OPTION_MASTER.get(key, [])
    by_key = {_match_key(v): v for v in values}
    k = _match_key(text)
    if not k:
        return None
    if k in by_key:
        return by_key[k]

    candidate = None
    if key == "hispeed":
        # "x3.5" "3.50" など
        m = _NUMBER_RE.search(k)
        if m:
            candidate = f"{float(m.group()):.1f}"
    elif key in ("hidden", "sudden"):
        # "+10" "-5" "0" など。符号なしは正の値として扱う
        m = _OFFSET_RE.search(k)
        if m:
            n = int(m.group(2))
            candidate = format_offset(-n if m.group(1) == "-" else n)
    else:
        close = difflib.get_close_matches(k, list(by_key), n=1, cutoff=_MATCH_MIN_RATIO)
        if close:
            return by_key[close[0]]
    return candidate if candidate in values else None
