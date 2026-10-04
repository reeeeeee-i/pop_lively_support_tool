"""プレー画面の判定内訳バーの数字テンプレート (src/judge_templates.py) を生成する。

正解値が分かっているプレー画面のスクリーンショット (ゲーム画面全体) から数字を切り出し、
数字ごとに平均した画像をテンプレートとして書き出す。4 判定とも同じフォントなので共通で使う。

読み取りを誤る数字が見つかった場合は、その画面のスクリーンショットと正解値を
SAMPLES に追加して再実行する。

    python tools/build_judge_templates.py
"""
from __future__ import annotations

import base64
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src import judge_reader as jr  # noqa: E402

# (画像パス, 各判定の累計値)
SAMPLES = [
    ("scratch/client_screens/play_1.png", {"bad": 10, "good": 10, "great": 3, "cool": 3}),
    ("screenshots/play/vlcsnap-2026-10-04-08h58m59s412.png", {"bad": 3, "good": 2, "great": 2, "cool": 6}),
    ("screenshots/play/vlcsnap-2026-10-04-08h59m06s606.png", {"bad": 6, "good": 3, "great": 4, "cool": 9}),
    ("screenshots/play/vlcsnap-2026-10-04-08h59m14s532.png", {"bad": 35, "good": 7, "great": 34, "cool": 67}),
    ("screenshots/play/vlcsnap-2026-10-04-08h59m18s926.png", {"bad": 50, "good": 16, "great": 63, "cool": 117}),
    ("screenshots/play/vlcsnap-2026-10-04-08h59m23s741.png", {"bad": 50, "good": 16, "great": 71, "cool": 156}),
    ("screenshots/play/vlcsnap-2026-10-04-08h59m34s337.png", {"bad": 67, "good": 16, "great": 72, "cool": 201}),
    ("screenshots/play/vlcsnap-2026-10-04-09h07m01s119.png", {"bad": 35, "good": 8, "great": 42, "cool": 87}),
]


def load_image(path: str) -> Image.Image:
    """サンプル画像を読み込み、アプリ内と同じ 1920x1080 の RGB にそろえる。"""
    image = Image.open(ROOT / path).convert("RGB")
    if image.size != (1920, 1080):
        image = image.resize((1920, 1080), Image.Resampling.LANCZOS)
    return image


def collect(samples=SAMPLES) -> dict[str, list[np.ndarray]]:
    """サンプル画像から数字ごとの正規化済み文字画像を集める。"""
    collected: dict[str, list[np.ndarray]] = {}
    for path, values in samples:
        arr = np.asarray(load_image(path))
        for name, value in values.items():
            text = str(value) if value else ""
            digits = jr.extract_digits(arr, name)
            if digits is None or len(digits) != len(text):
                raise SystemExit(f"{path} {name}: 切り出し {digits and len(digits)} 文字 != 正解 '{text}'")
            for ch, variants in zip(text, digits):
                collected.setdefault(ch, []).append(variants[len(variants) // 2])
    return collected


def build(samples=SAMPLES) -> list[tuple[str, str]]:
    means = {label: np.mean(imgs, axis=0) for label, imgs in collect(samples).items()}
    return [
        (label, base64.b64encode((img * 255).round().astype(np.uint8).tobytes()).decode())
        for label, img in sorted(means.items())
    ]


def main() -> None:
    templates = build()
    lines = [
        '"""プレー画面の判定内訳バーの数字テンプレート (自動生成: tools/build_judge_templates.py)',
        "",
        f"各テンプレートは 幅{jr.GLYPH_W} x 高さ{jr.GLYPH_H} のグレースケール画像を base64 化したもの。",
        '"""',
        "",
        "TEMPLATES = [",
    ]
    lines.extend(f'    ("{label}", "{b64}"),' for label, b64 in templates)
    lines.append("]")
    (ROOT / "src" / "judge_templates.py").write_text("\n".join(lines) + "\n", encoding="utf-8")
    jr.set_templates(templates)
    have = "".join(label for label, _ in templates)
    missing = "".join(d for d in "0123456789" if d not in have)
    print(f"収録 {have}" + (f" / 未収録 {missing}" if missing else ""))

    # 生成したテンプレートでサンプル自身を読み直して確認
    for path, values in SAMPLES:
        counts = jr.read_judge_counts(load_image(path))
        print("OK" if counts == values else "NG", path, counts)


if __name__ == "__main__":
    main()
