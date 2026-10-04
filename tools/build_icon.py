"""アプリのアイコン (src/icon.ico) を生成する。

ポップ君風の丸い粒を、目を付けずに描く。大きく描いてから縮小し、
16～256px を 1 つの .ico にまとめる。確認用に src/icon.png も書き出す。

    python tools/build_icon.py [red|blue|green|yellow|white]
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

ROOT = Path(__file__).resolve().parent.parent

MASTER = 1024                                   # 描画サイズ (縮小前)
ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)

OUTLINE = (58, 30, 62)                          # 輪郭線
# 色名: (上側の色, 下側の色)
COLORS = {
    "red":    ((255, 112, 128), (226, 30, 66)),
    "blue":   ((104, 178, 255), (32, 96, 224)),
    "green":  ((126, 226, 122), (30, 160, 72)),
    "yellow": ((255, 236, 120), (246, 176, 20)),
    "white":  ((255, 255, 255), (206, 212, 228)),
}

# 粒の形 (MASTER に対する比率)。横長のスーパー楕円
CENTER = (0.5, 0.47)
HALF_W, HALF_H = 0.47, 0.30
ROUNDNESS = 2.5                                 # 2 で楕円、大きいほど角ばる
OUTLINE_WIDTH = 0.05


def _shape(cx: float, cy: float, half_w: float, half_h: float) -> np.ndarray:
    """スーパー楕円の内側を 1.0、外側を 0.0 とするマスク (縁は 1px ぼかす)。"""
    y, x = np.mgrid[0:MASTER, 0:MASTER].astype(np.float64) + 0.5
    a, b = half_w * MASTER, half_h * MASTER
    d = (np.abs((x - cx * MASTER) / a) ** ROUNDNESS + np.abs((y - cy * MASTER) / b) ** ROUNDNESS) ** (1 / ROUNDNESS)
    return np.clip((1.0 - d) * min(a, b) + 0.5, 0.0, 1.0)


def _blur(mask: np.ndarray, radius: float) -> np.ndarray:
    im = Image.fromarray((mask * 255).astype(np.uint8))
    return np.asarray(im.filter(ImageFilter.GaussianBlur(radius * MASTER))) / 255.0


def _over(dst: np.ndarray, color, alpha: np.ndarray) -> np.ndarray:
    """dst (RGBA, 0.0～1.0) の上に単色を alpha で重ねる。"""
    src_a = alpha[..., None]
    rgb = np.broadcast_to(np.asarray(color, dtype=np.float64) / 255.0, dst[..., :3].shape)
    out_a = src_a + dst[..., 3:] * (1 - src_a)
    out_rgb = (rgb * src_a + dst[..., :3] * dst[..., 3:] * (1 - src_a)) / np.maximum(out_a, 1e-6)
    return np.concatenate([out_rgb, out_a], axis=-1)


def render(color: str = "red") -> Image.Image:
    top, bottom = COLORS[color]
    cx, cy = CENTER
    canvas = np.zeros((MASTER, MASTER, 4))

    # 足元の影
    shadow = _blur(_shape(cx, cy + HALF_H + 0.035, HALF_W * 0.8, 0.05), 0.02)
    canvas = _over(canvas, (0, 0, 0), shadow * 0.28)

    # 輪郭
    canvas = _over(canvas, OUTLINE, _shape(cx, cy, HALF_W, HALF_H))

    # 本体 (上から下へのグラデーション)
    body = _shape(cx, cy, HALF_W - OUTLINE_WIDTH, HALF_H - OUTLINE_WIDTH)
    y = np.mgrid[0:MASTER, 0:MASTER][0] / MASTER
    t = np.clip((y - (cy - HALF_H)) / (2 * HALF_H), 0.0, 1.0)[..., None]
    grad = np.asarray(top) * (1 - t) + np.asarray(bottom) * t
    canvas = np.concatenate([
        canvas[..., :3] * (1 - body[..., None]) + grad / 255.0 * body[..., None],
        canvas[..., 3:],
    ], axis=-1)

    # 下側の陰 (本体から、上にずらした本体を引いた三日月)
    shade = body * (1 - _blur(_shape(cx, cy - 0.05, HALF_W - OUTLINE_WIDTH, HALF_H - OUTLINE_WIDTH), 0.02))
    canvas = _over(canvas, OUTLINE, shade * 0.3)

    # 上側のつや
    gloss = _shape(cx - 0.02, cy - 0.12, 0.3, 0.09) * (1 - _shape(cx + 0.01, cy - 0.065, 0.36, 0.105))
    canvas = _over(canvas, (255, 255, 255), _blur(gloss, 0.004) * body * 0.8)
    dot = _shape(cx + 0.28, cy - 0.08, 0.035, 0.028)
    canvas = _over(canvas, (255, 255, 255), dot * body * 0.8)

    return Image.fromarray((np.clip(canvas, 0, 1) * 255).round().astype(np.uint8), "RGBA")


def main() -> None:
    color = sys.argv[1] if len(sys.argv) > 1 else "red"
    if color not in COLORS:
        sys.exit(f"色は {' / '.join(COLORS)} から選んでください")
    master = render(color)
    frames = [master.resize((s, s), Image.Resampling.LANCZOS) for s in ICO_SIZES]
    frames[-1].save(ROOT / "src" / "icon.ico", format="ICO", append_images=frames[:-1],
                    sizes=[(s, s) for s in ICO_SIZES])
    frames[-1].save(ROOT / "src" / "icon.png")
    print(f"src/icon.ico を書き出しました ({color}, {', '.join(str(s) for s in ICO_SIZES)}px)")


if __name__ == "__main__":
    main()
