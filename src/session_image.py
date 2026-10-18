"""セッションサマリーを 1 枚の画像 (カード) にする。リザルト画像を下に並べることもできる"""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QLinearGradient, QPainter, QPen

from src.score_stats import SessionSummary

IMAGE_WIDTH = 1200
IMAGE_HEIGHT = 675   # 16:9 (X のタイムラインで切り取られにくい比率)

_FONT_FAMILY = "Yu Gothic UI"
_BEST_UPDATE_ROWS = 5

MAX_RESULT_IMAGES = 8
_RESULT_COLUMNS = 2   # リザルト画像は 2 (横) x 4 (縦)
_RESULT_GAP = 16
_RESULT_ASPECT = 16 / 9
_MARGIN = 50

_TEXT = QColor("#ffffff")
_SUB_TEXT = QColor("#9aa4b5")
_TILE = QColor(255, 255, 255, 22)


def _font(size: int, bold: bool = False) -> QFont:
    font = QFont(_FONT_FAMILY)
    font.setPixelSize(size)
    font.setBold(bold)
    return font


def _fill_background(painter: QPainter, image: QImage):
    background = QLinearGradient(0, 0, image.width(), image.height())
    background.setColorAt(0, QColor("#1b1f3a"))
    background.setColorAt(1, QColor("#3a1c4d"))
    painter.fillRect(image.rect(), background)


def _draw_tile(painter: QPainter, rect: QRectF, label: str, value: str, color: str, value_px: int):
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(_TILE)
    painter.drawRoundedRect(rect, 14, 14)
    painter.setFont(_font(22))
    painter.setPen(_SUB_TEXT)
    painter.drawText(rect.adjusted(20, 12, -20, 0), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, label)
    painter.setFont(_font(value_px, True))
    painter.setPen(QColor(color))
    painter.drawText(rect.adjusted(20, 0, -20, -10), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom, value)


def _result_cell_size() -> tuple[float, float]:
    width = (IMAGE_WIDTH - _MARGIN * 2 - _RESULT_GAP * (_RESULT_COLUMNS - 1)) / _RESULT_COLUMNS
    return width, width / _RESULT_ASPECT


def load_result_images(paths: list[str]) -> list[QImage]:
    """リザルト画像を読み込む (読めないファイルは除く)。"""
    images = []
    for path in paths:
        image = QImage(path)
        if not image.isNull():
            images.append(image)
    return images


def render_session_image(s: SessionSummary) -> QImage:
    """セッションサマリーのカード画像 (1200x675) を作る。"""
    height = IMAGE_HEIGHT
    image = QImage(IMAGE_WIDTH, height, QImage.Format.Format_ARGB32)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

    _fill_background(painter, image)

    # 見出し
    margin = _MARGIN
    painter.setFont(_font(40, True))
    painter.setPen(_TEXT)
    painter.drawText(QRectF(margin, 28, 800, 56), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                     "SESSION SUMMARY")
    elapsed = max(0, int((s.end - s.start).total_seconds()))
    hours, rest = divmod(elapsed, 3600)
    painter.setFont(_font(24))
    painter.setPen(_SUB_TEXT)
    painter.drawText(
        QRectF(margin, 28, IMAGE_WIDTH - margin * 2, 56),
        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
        f"{s.start:%Y-%m-%d %H:%M} ～ {s.end:%H:%M} ({hours}時間{rest // 60:02d}分)",
    )
    painter.setPen(QPen(QColor(255, 255, 255, 60), 2))
    painter.drawLine(margin, 96, IMAGE_WIDTH - margin, 96)

    # 主要な数値 (大きいタイル)
    gap = 20
    tile_width = (IMAGE_WIDTH - margin * 2 - gap * 3) / 4
    level = f"Lv{s.max_level}" if s.max_level is not None else "-"
    big = [
        ("プレー数", f"{s.plays}", "#00e676"),
        ("打鍵数", f"{s.notes:,}", "#ffb74d"),
        ("平均スコア", f"{s.average_score:,.0f}" if s.plays else "-", "#40c4ff"),
        ("最高レベル", level, "#ff80ab"),
    ]
    for i, (label, value, color) in enumerate(big):
        _draw_tile(painter, QRectF(margin + i * (tile_width + gap), 120, tile_width, 130), label, value, color, 56)

    small = [
        ("FULL COMBO", f"{s.full_combos}", "#ffd600"),
        ("PERFECT", f"{s.perfects}", "#ffd600"),
        ("初プレー譜面", f"{s.first_plays}", "#b388ff"),
        ("自己ベスト更新", f"{len(s.best_updates)}", "#ffd600"),
    ]
    for i, (label, value, color) in enumerate(small):
        _draw_tile(painter, QRectF(margin + i * (tile_width + gap), 270, tile_width, 84), label, value, color, 40)

    # 自己ベスト更新の一覧
    painter.setFont(_font(26, True))
    painter.setPen(_TEXT)
    painter.drawText(QRectF(margin, 374, 600, 38), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                     "自己ベスト更新")
    updates = s.best_updates[-_BEST_UPDATE_ROWS:][::-1]   # 新しいものから
    row_height = 40
    if not updates:
        painter.setFont(_font(24))
        painter.setPen(_SUB_TEXT)
        painter.drawText(QRectF(margin, 418, 600, row_height), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                         "今回の更新はありませんでした")
    for i, u in enumerate(updates):
        y = 418 + i * row_height
        lv = f"Lv{u.level} " if u.level is not None else ""
        painter.setFont(_font(24))
        painter.setPen(_TEXT)
        painter.drawText(
            QRectF(margin, y, 760, row_height), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            painter.fontMetrics().elidedText(f"{u.title} [{lv}{u.difficulty}]", Qt.TextElideMode.ElideRight, 740),
        )
        painter.setPen(QColor("#ffd600"))
        painter.drawText(
            QRectF(820, y, IMAGE_WIDTH - margin - 820, row_height),
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            f"{u.score:,} ({u.score - u.prev_best:+,})",
        )
    if len(s.best_updates) > len(updates):
        painter.setFont(_font(20))
        painter.setPen(_SUB_TEXT)
        painter.drawText(
            QRectF(margin, 418 + _BEST_UPDATE_ROWS * row_height, 600, 30),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            f"ほか {len(s.best_updates) - len(updates)} 件",
        )

    # フッター
    painter.setFont(_font(20))
    painter.setPen(_SUB_TEXT)
    painter.drawText(
        QRectF(margin, height - 44, IMAGE_WIDTH - margin * 2, 30),
        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
        "pop'n music Lively サポートツール",
    )
    painter.end()
    return image


def render_results_image(results: list[QImage], date_label: str) -> QImage:
    """リザルト画像だけを 2 (横) x 4 (縦) で並べた画像 (幅 1200) を作る。最大 MAX_RESULT_IMAGES 枚。"""
    results = results[:MAX_RESULT_IMAGES]
    rows = max(1, -(-len(results) // _RESULT_COLUMNS))
    cell_width, cell_height = _result_cell_size()
    top = 110
    height = int(top + rows * cell_height + (rows - 1) * _RESULT_GAP + 70)
    image = QImage(IMAGE_WIDTH, height, QImage.Format.Format_ARGB32)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    _fill_background(painter, image)

    painter.setFont(_font(40, True))
    painter.setPen(_TEXT)
    painter.drawText(QRectF(_MARGIN, 28, 800, 56), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "RESULTS")
    painter.setFont(_font(24))
    painter.setPen(_SUB_TEXT)
    painter.drawText(
        QRectF(_MARGIN, 28, IMAGE_WIDTH - _MARGIN * 2, 56),
        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, date_label,
    )
    painter.setPen(QPen(QColor(255, 255, 255, 60), 2))
    painter.drawLine(_MARGIN, 96, IMAGE_WIDTH - _MARGIN, 96)

    for i, result in enumerate(results):
        row, col = divmod(i, _RESULT_COLUMNS)
        cell = QRectF(
            _MARGIN + col * (cell_width + _RESULT_GAP), top + row * (cell_height + _RESULT_GAP),
            cell_width, cell_height,
        )
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 90))
        painter.drawRoundedRect(cell, 8, 8)
        # セルの比率に合わなくても、縦横比を保って収める
        scaled = result.scaled(
            int(cell.width()), int(cell.height()),
            Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation,
        )
        painter.drawImage(
            int(cell.x() + (cell.width() - scaled.width()) / 2),
            int(cell.y() + (cell.height() - scaled.height()) / 2),
            scaled,
        )

    painter.setFont(_font(20))
    painter.setPen(_SUB_TEXT)
    painter.drawText(
        QRectF(_MARGIN, height - 44, IMAGE_WIDTH - _MARGIN * 2, 30),
        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, "pop'n music Lively サポートツール",
    )
    painter.end()
    return image
