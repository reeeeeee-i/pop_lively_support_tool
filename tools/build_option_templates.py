"""オプションアイコンのテンプレート (src/option_templates.py) を生成する。

設定値が分かっている OptionSelect 画面のスクリーンショット (ゲーム画面全体) から
各アイコンと HIDDEN / SUDDEN の数字を切り出し、テンプレートとして書き出す。

読めない・読み誤るアイコンが見つかった場合は、その画面のスクリーンショットと設定値を
SAMPLES に追加して再実行する。

    python tools/build_option_templates.py
"""
from __future__ import annotations

import base64
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src import option_reader as opr  # noqa: E402

VARIOUS = "screenshots/various/スクリーンショット "

# アイコンからは値を決められない場合のラベル
#   GUIDE SE: 「ON 大」と「ON 小」は同じ絵柄
#   OJAMA:    設定中は番号だけが表示され、オジャマの種類は分からない
UNREADABLE = opr.UNREADABLE

# (画像パス, 各アイコンの設定値)。hidden / sudden はアイコン内の表示どおりに書く
SAMPLES = [
    # シンプル設定 (アイコン 4 個)
    (VARIOUS + "2026-09-28 020119.png",
     {"popkun": "NORMAL", "gauge_type": "NORMAL", "guide_se": UNREADABLE}),
    (VARIOUS + "2026-09-30 072909.png",
     {"popkun": "NORMAL", "gauge_type": "NORMAL", "guide_se": UNREADABLE, "random": "OFF",
      "judge_plus": "OFF", "hidden": "+32", "sudden": "-138",
      "ojama1": UNREADABLE, "ojama2": UNREADABLE, "auto": "ON"}),
    (VARIOUS + "2026-10-04 072937.png",
     {"popkun": "BEAT POP", "gauge_type": "HARD", "guide_se": UNREADABLE, "random": "RANDOM",
      "judge_plus": "TIMING", "hidden": "±0", "sudden": "-139",
      "ojama1": UNREADABLE, "ojama2": UNREADABLE, "auto": "OFF"}),
    (VARIOUS + "2026-10-04 074205.png",
     {"popkun": "CHARA POP(YOU)", "gauge_type": "DANGER", "guide_se": UNREADABLE, "random": "S-RANDOM",
      "judge_plus": "LOST", "hidden": "+26", "sudden": "-139",
      "ojama1": UNREADABLE, "ojama2": UNREADABLE, "auto": "OFF"}),
    (VARIOUS + "2026-10-04 074703.png",
     {"popkun": "CHARA POP(RIVAL)", "gauge_type": "EASY", "guide_se": "OFF", "random": "MIRROR",
      "judge_plus": "PANIC", "hidden": "+26", "sudden": "-139",
      "ojama1": UNREADABLE, "ojama2": UNREADABLE, "auto": "OFF"}),
    (VARIOUS + "2026-10-04 081013.png",
     {"popkun": "CHARA POP(RIVAL)", "gauge_type": "EASY", "guide_se": "OFF", "random": "MIRROR",
      "judge_plus": "OFF", "hidden": "+37", "sudden": "-145",
      "ojama1": "OFF", "ojama2": "OFF", "auto": "OFF"}),
    (VARIOUS + "2026-10-04 081121.png",
     {"popkun": "CHARA POP(RIVAL)", "gauge_type": "EASY", "guide_se": UNREADABLE, "random": "MIRROR",
      "judge_plus": "OFF", "hidden": "OFF", "sudden": "OFF",
      "ojama1": "OFF", "ojama2": "OFF", "auto": "OFF"}),
]

_SAME_DIST = 0.02   # これ未満の距離のテンプレートが既にあれば追加しない


def load_image(path: str) -> Image.Image:
    """サンプル画像を読み込み、アプリ内と同じ 1920x1080 の RGB にそろえる。"""
    image = Image.open(ROOT / path).convert("RGB")
    if image.size != (1920, 1080):
        image = image.resize((1920, 1080), Image.Resampling.LANCZOS)
    return image


def _add(items: list[tuple[str, np.ndarray]], label: str, data: np.ndarray) -> None:
    for known, template in items:
        if known == label and float(np.abs(template - data).mean()) < _SAME_DIST:
            return
    items.append((label, data))


def collect(samples=SAMPLES):
    """サンプル画像から (アイコン, 数字) のテンプレート候補を集める。"""
    icons: dict[str, list[tuple[str, np.ndarray]]] = {}
    glyphs: list[tuple[str, np.ndarray]] = []
    for path, values in samples:
        arr = np.asarray(load_image(path))
        box = opr.locate_icon_box(arr)
        if box is None:
            print(f"黒枠を検出できません: {path}")
            continue
        centers = box.centers()
        _add(icons.setdefault("hispeed", []), "HI-SPEED", opr.icon_tile(arr, box, centers["hispeed"]))
        for key, value in values.items():
            tile = opr.icon_tile(arr, box, centers[key])
            if key in ("hidden", "sudden") and value != "OFF":
                # 右の文字から順に切り出される
                for ch, glyph in zip(reversed(value), opr.value_glyphs(arr, box, centers[key])):
                    _add(glyphs, ch, glyph)
                # 数値表示のアイコンを「OFF」と取り違えないよう、絵柄も登録しておく
                _add(icons.setdefault(key, []), UNREADABLE, tile)
            else:
                _add(icons.setdefault(key, []), value, tile)
    return icons, glyphs


def _encode(data: np.ndarray) -> str:
    return base64.b64encode((data * 255).round().astype(np.uint8).tobytes()).decode()


def build(samples=SAMPLES):
    icons, glyphs = collect(samples)
    raw_icons = {key: [(label, _encode(t)) for label, t in items] for key, items in icons.items()}
    raw_glyphs = [(label, _encode(t)) for label, t in sorted(glyphs, key=lambda g: g[0])]
    return raw_icons, raw_glyphs


def main() -> None:
    raw_icons, raw_glyphs = build()
    lines = [
        '"""オプションアイコンのテンプレート (自動生成: tools/build_option_templates.py)',
        "",
        f"ICONS: {opr.ICON_SIZE}x{opr.ICON_SIZE} の RGB 画像、"
        f"GLYPHS: {opr.GLYPH_SIZE[0]}x{opr.GLYPH_SIZE[1]} のグレースケール画像を base64 化したもの。",
        '"""',
        "",
        "ICONS = {",
    ]
    for key, items in raw_icons.items():
        lines.append(f'    "{key}": [')
        for label, b64 in items:
            lines.append(f'        ("{label}", "{b64}"),')
        lines.append("    ],")
    lines += ["}", "", "GLYPHS = ["]
    for label, b64 in raw_glyphs:
        lines.append(f'    ("{label}", "{b64}"),')
    lines.append("]")
    (ROOT / "src" / "option_templates.py").write_text("\n".join(lines) + "\n", encoding="utf-8")
    opr.set_templates(raw_icons, raw_glyphs)

    for key, items in raw_icons.items():
        print(f"{key}: " + " / ".join(label for label, _ in items))
    have = "".join(sorted({label for label, _ in raw_glyphs if label.isdigit()}))
    missing = "".join(d for d in "0123456789" if d not in have)
    print(f"数字: 収録 {have}" + (f" / 未収録 {missing}" if missing else ""))

    # 生成したテンプレートでサンプル自身を読み直して確認
    for path, values in SAMPLES:
        got = opr.read_option_icons(load_image(path)) or {}
        expected = {k: v for k, v in values.items() if v != UNREADABLE}
        ok = all(got.get(k) == v for k, v in expected.items())
        print("OK" if ok else "NG", path, got)


if __name__ == "__main__":
    main()
