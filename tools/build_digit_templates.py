"""リザルト画面の数字テンプレート (src/digit_templates.py) を生成する。

正解値が分かっているリザルト画面のスクリーンショット (ゲーム画面全体) から数字を切り出し、
(フォント種別, 数字) ごとに平均した画像をテンプレートとして書き出す。

読み取りを誤る数字が見つかった場合は、その画面のスクリーンショットと正解値を
SAMPLES に追加して再実行する。

    python tools/build_digit_templates.py
"""
from __future__ import annotations

import base64
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src import result_reader as rr  # noqa: E402

# (画像パス, 各行に表示されている文字列)
SAMPLES = [
    ("scratch/true_1080p/result_1.png",
     {"score": "8609", "cool": "24", "great": "26", "good": "54", "bad": "330",
      "combo": "14", "best": "0", "diff": "+8609"}),
    ("scratch/client_screens/result_1.png",
     {"score": "8609", "cool": "24", "great": "26", "good": "54", "bad": "330",
      "combo": "14", "best": "0", "diff": "+8609"}),
    ("scratch/test_screens/res1.png",
     {"score": "8609", "cool": "24", "great": "26", "good": "54", "bad": "330",
      "combo": "14", "best": "0", "diff": "+8609"}),
    ("scratch/test_screens/new_res_1080.png",
     {"score": "25054", "cool": "126", "great": "39", "good": "17", "bad": "267",
      "combo": "74", "best": "0", "diff": "+25054"}),
    # 配信の切り抜き (動画圧縮でぼけている)
    ("screenshots/result/2.png",
     {"score": "98923", "cool": "1585", "great": "59", "good": "0", "bad": "0",
      "combo": "1644", "best": "98722", "diff": "+201"}),
    ("screenshots/result/3.png",
     {"score": "99343", "cool": "1072", "great": "24", "good": "0", "bad": "0",
      "combo": "1096", "best": "0", "diff": "+99343"}),
    # BEST SCORE 欄が手元カメラで隠れているため best / diff は対象外
    ("screenshots/result/4.png",
     {"score": "93876", "cool": "1283", "great": "293", "good": "9", "bad": "4",
      "combo": "675"}),
]


def load_image(path: str) -> Image.Image:
    """サンプル画像を読み込み、アプリ内と同じ 1920x1080 の RGB にそろえる。"""
    image = Image.open(ROOT / path).convert("RGB")
    if image.size != (1920, 1080):
        image = image.resize((1920, 1080), Image.Resampling.LANCZOS)
    return image


def collect(samples=SAMPLES) -> dict[tuple[str, str], list[np.ndarray]]:
    """サンプル画像から (グループ, ラベル) ごとの正規化済み文字画像を集める。"""
    collected: dict[tuple[str, str], list[np.ndarray]] = {}
    for path, rows in samples:
        arr = np.asarray(load_image(path))
        panel = rr.locate_panel(arr)
        if panel is None:
            raise SystemExit(f"パネルを検出できません: {path}")
        for name, text in rows.items():
            glyphs = rr.extract_glyphs(arr, panel, name)
            if len(glyphs) != len(text):
                raise SystemExit(f"{path} {name}: 切り出し {len(glyphs)} 文字 != 正解 '{text}'")
            for ch, glyph in zip(text, glyphs):
                font = rr._font_of(name)
                group = font if ch.isdigit() else "sign"
                collected.setdefault((group, ch), []).append(rr._normalize_glyph(glyph, font))
    return collected


def build(samples=SAMPLES) -> dict[str, list[tuple[str, str]]]:
    templates: dict[str, list[tuple[str, str]]] = {}
    for (group, label), imgs in sorted(collect(samples).items()):
        mean = (np.mean(imgs, axis=0) * 255).round().astype(np.uint8)
        templates.setdefault(group, []).append((label, base64.b64encode(mean.tobytes()).decode()))
    return templates


def main() -> None:
    templates = build()
    lines = [
        '"""リザルト画面の数字テンプレート (自動生成: tools/build_digit_templates.py)',
        "",
        f"各テンプレートは {rr.GLYPH_SIZE}x{rr.GLYPH_SIZE} のグレースケール画像を base64 化したもの。",
        '"""',
        "",
        "TEMPLATES = {",
    ]
    for group, items in templates.items():
        lines.append(f'    "{group}": [')
        for label, b64 in items:
            lines.append(f'        ("{label}", "{b64}"),')
        lines.append("    ],")
    lines.append("}")
    (ROOT / "src" / "digit_templates.py").write_text("\n".join(lines) + "\n", encoding="utf-8")
    rr.set_templates(templates)
    for group, items in templates.items():
        have = "".join(label for label, _ in items)
        missing = "".join(d for d in "0123456789" if d not in have) if group != "sign" else ""
        print(f"{group}: 収録 {have}" + (f" / 未収録 {missing}" if missing else ""))

    # 生成したテンプレートでサンプル自身を読み直して確認
    for path, rows in SAMPLES:
        v = rr.read_result_values(load_image(path))
        expected = tuple(int(rows[k]) for k in ("score", "cool", "great", "good", "bad", "combo"))
        print("OK" if v and v.key() == expected else "NG", path, v.key() if v else None)


if __name__ == "__main__":
    main()
