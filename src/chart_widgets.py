"""統計ダイアログ用の簡易グラフウィジェット (QPainter 描画。追加ライブラリ不要)"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPalette, QPen, QPolygonF
from PySide6.QtWidgets import QToolTip, QWidget

_MARGIN_LEFT = 62
_MARGIN_RIGHT = 14
_MARGIN_TOP = 14
_MARGIN_BOTTOM = 30
_GRID_LINES = 4

# 判定ごとの色 (ゲーム画面の判定表示に合わせる)
JUDGE_COLORS = {
    "cool":  QColor("#e040fb"),
    "great": QColor("#ff9800"),
    "good":  QColor("#f44336"),
    "bad":   QColor("#26c6da"),
}


def nice_ceiling(value: float) -> float:
    """グラフの上端: value 以上のキリのいい数 (1・2・5 × 10^n)"""
    if value <= 0:
        return 1.0
    magnitude = 10 ** (len(str(int(value))) - 1) if value >= 1 else 1
    for step in (1, 2, 5, 10):
        if value <= step * magnitude:
            return float(step * magnitude)
    return float(10 * magnitude)


class _ChartBase(QWidget):
    """軸・目盛り線・ツールチップを共通で持つグラフの土台"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(180)
        self.setMouseTracking(True)
        self._labels: list[str] = []
        self._tips: list[str] = []
        self._empty_text = "データがありません"

    # 派生クラスが実装する
    def _count(self) -> int:
        return len(self._labels)

    def _x_of(self, index: int, plot: QRectF) -> float:
        raise NotImplementedError

    def _plot_rect(self) -> QRectF:
        return QRectF(
            _MARGIN_LEFT, _MARGIN_TOP,
            max(10, self.width() - _MARGIN_LEFT - _MARGIN_RIGHT),
            max(10, self.height() - _MARGIN_TOP - _MARGIN_BOTTOM),
        )

    def _text_color(self) -> QColor:
        return self.palette().color(QPalette.ColorRole.WindowText)

    def _grid_color(self) -> QColor:
        color = QColor(self._text_color())
        color.setAlpha(50)
        return color

    def _draw_axes(self, painter: QPainter, plot: QRectF, y_min: float, y_max: float, fmt) -> None:
        painter.setFont(self.font())
        for i in range(_GRID_LINES + 1):
            ratio = i / _GRID_LINES
            y = plot.bottom() - plot.height() * ratio
            painter.setPen(QPen(self._grid_color(), 1))
            painter.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
            painter.setPen(self._text_color())
            painter.drawText(
                QRectF(0, y - 9, _MARGIN_LEFT - 6, 18),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                fmt(y_min + (y_max - y_min) * ratio),
            )

    def _draw_x_labels(self, painter: QPainter, plot: QRectF) -> None:
        count = self._count()
        if count == 0:
            return
        painter.setPen(self._text_color())
        label_width = max(painter.fontMetrics().horizontalAdvance(t) for t in self._labels) + 10
        step = max(1, int(label_width // max(1.0, self._slot_width(plot))) + 1)
        for i in range(0, count, step):
            x = self._x_of(i, plot)
            painter.drawText(
                QRectF(x - label_width / 2, plot.bottom() + 4, label_width, 20),
                Qt.AlignmentFlag.AlignCenter, self._labels[i],
            )

    def _slot_width(self, plot: QRectF) -> float:
        return plot.width() / max(1, self._count())

    def _draw_empty(self, painter: QPainter) -> None:
        painter.setPen(self._text_color())
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self._empty_text)

    def mouseMoveEvent(self, event):
        index = self._index_at(event.position().x())
        if index is not None and index < len(self._tips):
            QToolTip.showText(event.globalPosition().toPoint(), self._tips[index], self)
        else:
            QToolTip.hideText()

    def _index_at(self, x: float) -> int | None:
        count = self._count()
        if count == 0:
            return None
        plot = self._plot_rect()
        best = min(range(count), key=lambda i: abs(self._x_of(i, plot) - x))
        return best if abs(self._x_of(best, plot) - x) <= max(self._slot_width(plot), 12) else None


class BarChartWidget(_ChartBase):
    """棒グラフ (期間別の打鍵数・プレー数)"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._values: list[float] = []
        self._color = QColor("#ffb74d")

    def set_data(self, labels: list[str], values: list[float], tips: list[str], color: str = "#ffb74d"):
        self._labels, self._values, self._tips = labels, values, tips
        self._color = QColor(color)
        self.update()

    def _x_of(self, index: int, plot: QRectF) -> float:
        return plot.left() + self._slot_width(plot) * (index + 0.5)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self._values or max(self._values) <= 0:
            self._draw_empty(painter)
            return
        plot = self._plot_rect()
        y_max = nice_ceiling(max(self._values))
        self._draw_axes(painter, plot, 0, y_max, lambda v: f"{v:,.0f}")
        slot = self._slot_width(plot)
        bar_width = max(1.0, min(slot * 0.7, 40.0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self._color)
        for i, value in enumerate(self._values):
            if value <= 0:
                continue
            height = plot.height() * value / y_max
            x = self._x_of(i, plot)
            painter.drawRect(QRectF(x - bar_width / 2, plot.bottom() - height, bar_width, height))
        self._draw_x_labels(painter, plot)


class LineChartWidget(_ChartBase):
    """折れ線グラフ (曲別のスコア推移)。ベスト更新の点は強調する。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._values: list[float] = []
        self._highlight: list[bool] = []

    def set_data(self, labels: list[str], values: list[float], tips: list[str], highlight: list[bool]):
        self._labels, self._values, self._tips, self._highlight = labels, values, tips, highlight
        self.update()

    def _x_of(self, index: int, plot: QRectF) -> float:
        count = self._count()
        if count <= 1:
            return plot.center().x()
        return plot.left() + plot.width() * 0.03 + plot.width() * 0.94 * index / (count - 1)

    def _slot_width(self, plot: QRectF) -> float:
        return plot.width() / max(1, self._count() - 1) if self._count() > 1 else plot.width()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self._values:
            self._draw_empty(painter)
            return
        plot = self._plot_rect()
        low, high = min(self._values), max(self._values)
        span = max(high - low, 1000.0)
        y_min = max(0.0, low - span * 0.15)
        y_max = high + span * 0.15
        self._draw_axes(painter, plot, y_min, y_max, lambda v: f"{v:,.0f}")

        points = [
            QPointF(self._x_of(i, plot), plot.bottom() - plot.height() * (v - y_min) / (y_max - y_min))
            for i, v in enumerate(self._values)
        ]
        line_color = QColor("#40c4ff")
        painter.setPen(QPen(line_color, 2))
        painter.drawPolyline(QPolygonF(points))
        for i, point in enumerate(points):
            strong = self._highlight[i] if i < len(self._highlight) else False
            painter.setPen(QPen(line_color, 1))
            painter.setBrush(QColor("#ffd600") if strong else line_color)
            radius = 5 if strong else 3
            painter.drawEllipse(point, radius, radius)
        self._draw_x_labels(painter, plot)


class JudgeBarWidget(_ChartBase):
    """判定内訳の積み上げ棒グラフ (1 プレーにつき 1 本。下から COOL / GREAT / GOOD / BAD)"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: list[tuple[int, int, int, int]] = []

    def set_data(self, labels: list[str], rows: list[tuple[int, int, int, int]], tips: list[str]):
        self._labels, self._rows, self._tips = labels, rows, tips
        self.update()

    def _x_of(self, index: int, plot: QRectF) -> float:
        return plot.left() + self._slot_width(plot) * (index + 0.5)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self._rows:
            self._draw_empty(painter)
            return
        plot = self._plot_rect()
        y_max = nice_ceiling(max(sum(row) for row in self._rows) or 1)
        self._draw_axes(painter, plot, 0, y_max, lambda v: f"{v:,.0f}")
        slot = self._slot_width(plot)
        bar_width = max(1.0, min(slot * 0.7, 40.0))
        painter.setPen(Qt.PenStyle.NoPen)
        for i, row in enumerate(self._rows):
            bottom = plot.bottom()
            x = self._x_of(i, plot)
            for name, count in zip(("cool", "great", "good", "bad"), row):
                height = plot.height() * count / y_max
                if height <= 0:
                    continue
                painter.setBrush(JUDGE_COLORS[name])
                painter.drawRect(QRectF(x - bar_width / 2, bottom - height, bar_width, height))
                bottom -= height
        self._draw_x_labels(painter, plot)
