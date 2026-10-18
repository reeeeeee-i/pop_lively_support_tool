"""統計ダイアログ (期間別の打鍵数・レベル別の成績・曲別のスコア推移) とセッションサマリー"""
from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from src.chart_widgets import JUDGE_COLORS, BarChartWidget, JudgeBarWidget, LineChartWidget
from src.score_manager import ScoreManager
from src.score_stats import (
    aggregate_periods,
    chart_history,
    format_session_summary,
    is_full_combo,
    level_stats,
    list_charts,
    summarize_session,
)

_UNITS = (("日別", "day", "日"), ("週別", "week", "週"), ("月別", "month", "か月"))
_METRICS = (("打鍵数", "notes"), ("プレー数", "plays"))
_DIFFICULTIES = (("すべて", ""), ("EASY (L)", "L"), ("NORMAL (N)", "N"), ("HYPER (H)", "H"), ("EX", "EX"))


class _SortableItem(QTableWidgetItem):
    """UserRole の数値で並べ替えるセル"""

    def __lt__(self, other):
        a, b = self.data(Qt.ItemDataRole.UserRole), other.data(Qt.ItemDataRole.UserRole)
        if a is not None and b is not None:
            return a < b
        return super().__lt__(other)


def _sortable(text: str, value: float) -> QTableWidgetItem:
    item = _SortableItem(text)
    item.setData(Qt.ItemDataRole.UserRole, value)
    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    return item


class _PeriodTab(QWidget):
    """期間別の打鍵数・プレー数"""

    def __init__(self, score_manager: ScoreManager, parent=None):
        super().__init__(parent)
        self._score_manager = score_manager
        layout = QVBoxLayout(self)

        controls = QHBoxLayout()
        self._cmb_unit = QComboBox()
        for label, _, _ in _UNITS:
            self._cmb_unit.addItem(label)
        self._cmb_metric = QComboBox()
        for label, _ in _METRICS:
            self._cmb_metric.addItem(label)
        self._spin_count = QSpinBox()
        self._spin_count.setRange(1, 3650)
        self._spin_count.setValue(30)
        self._chk_all = QCheckBox("全期間")
        self._lbl_unit = QLabel("日")
        for widget in (QLabel("単位:"), self._cmb_unit, QLabel("指標:"), self._cmb_metric,
                       QLabel("直近"), self._spin_count, self._lbl_unit, self._chk_all):
            controls.addWidget(widget)
        controls.addStretch()
        layout.addLayout(controls)

        self._chart = BarChartWidget()
        layout.addWidget(self._chart, 1)
        self._lbl_summary = QLabel()
        self._lbl_summary.setWordWrap(True)
        layout.addWidget(self._lbl_summary)

        self._cmb_unit.currentIndexChanged.connect(self._on_unit_changed)
        self._cmb_metric.currentIndexChanged.connect(self.refresh)
        self._spin_count.valueChanged.connect(self.refresh)
        self._chk_all.toggled.connect(self.refresh)
        self.refresh()

    def _on_unit_changed(self):
        self._lbl_unit.setText(_UNITS[self._cmb_unit.currentIndex()][2])
        self.refresh()

    def refresh(self, *_):
        unit_label, unit, _ = _UNITS[self._cmb_unit.currentIndex()]
        metric_label, metric = _METRICS[self._cmb_metric.currentIndex()]
        self._spin_count.setEnabled(not self._chk_all.isChecked())
        limit = None if self._chk_all.isChecked() else self._spin_count.value()
        stats = aggregate_periods(self._score_manager.records, unit, limit)
        values = [getattr(s, metric) for s in stats]
        suffix = "から" if unit != "day" else ""
        tips = [
            f"{s.label}{suffix}\n打鍵数: {s.notes:,}\nプレー数: {s.plays}" for s in stats
        ]
        self._chart.set_data(
            [s.label for s in stats], values, tips,
            "#ffb74d" if metric == "notes" else "#69f0ae",
        )

        active = [v for v in values if v > 0]
        if not active:
            self._lbl_summary.setText("この期間の記録はありません。")
            return
        peak = max(range(len(stats)), key=lambda i: values[i])
        self._lbl_summary.setText(
            f"{unit_label}の{metric_label}  合計: {sum(values):,}  /  "
            f"プレーした期間の平均: {sum(active) / len(active):,.0f}  /  "
            f"最大: {values[peak]:,} ({stats[peak].label})  /  "
            f"プレーした期間: {len(active)} / {len(stats)}"
        )


class _LevelTab(QWidget):
    """レベル別の成績"""

    _HEADERS = ["レベル", "プレー数", "プレー済み譜面", "FULL COMBO 譜面", "PERFECT 譜面", "ベスト平均", "最高スコア"]

    def __init__(self, score_manager: ScoreManager, parent=None):
        super().__init__(parent)
        self._score_manager = score_manager
        layout = QVBoxLayout(self)

        controls = QHBoxLayout()
        self._cmb_difficulty = QComboBox()
        for label, _ in _DIFFICULTIES:
            self._cmb_difficulty.addItem(label)
        controls.addWidget(QLabel("難易度区分:"))
        controls.addWidget(self._cmb_difficulty)
        controls.addStretch()
        layout.addLayout(controls)

        self._table = QTableWidget(0, len(self._HEADERS))
        self._table.setHorizontalHeaderLabels(self._HEADERS)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.verticalHeader().hide()
        self._table.setSortingEnabled(True)
        self._table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self._table, 1)

        note = QLabel(
            "「ベスト平均」は譜面ごとのベストスコアの平均です。\n"
            "FULL COMBO / PERFECT は BAD・GOOD の数で判定します（リタイアしたプレーも BAD が 0 なら含まれます）。"
        )
        note.setStyleSheet("color: gray;")
        layout.addWidget(note)

        self._cmb_difficulty.currentIndexChanged.connect(self.refresh)
        self.refresh()

    def refresh(self, *_):
        difficulty = _DIFFICULTIES[self._cmb_difficulty.currentIndex()][1]
        stats = level_stats(self._score_manager.records, difficulty)
        self._table.setSortingEnabled(False)
        self._table.setRowCount(len(stats))
        for row, s in enumerate(stats):
            cells = [
                _sortable(f"Lv{s.level}", s.level),
                _sortable(f"{s.plays:,}", s.plays),
                _sortable(f"{s.charts:,}", s.charts),
                _sortable(f"{s.full_combo_charts:,} ({s.full_combo_charts / s.charts:.0%})", s.full_combo_charts),
                _sortable(f"{s.perfect_charts:,} ({s.perfect_charts / s.charts:.0%})", s.perfect_charts),
                _sortable(f"{s.best_average:,.0f}", s.best_average),
                _sortable(f"{s.best_score:,}", s.best_score),
            ]
            for col, item in enumerate(cells):
                self._table.setItem(row, col, item)
        self._table.setSortingEnabled(True)
        self._table.sortByColumn(0, Qt.SortOrder.DescendingOrder)


class _TrendTab(QWidget):
    """曲別のスコア・判定内訳の推移"""

    _HEADERS = ["プレー日時", "score", "前回比", "cool", "great", "good", "bad", "combo", "オプション"]

    def __init__(self, score_manager: ScoreManager, parent=None):
        super().__init__(parent)
        self._score_manager = score_manager
        self._entries = []
        self._shown: list[int] = []

        splitter = QSplitter(Qt.Orientation.Horizontal)
        outer = QVBoxLayout(self)
        outer.addWidget(splitter)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        self._edit_search = QLineEdit()
        self._edit_search.setPlaceholderText("曲名で絞り込み")
        self._edit_search.setClearButtonEnabled(True)
        self._list = QListWidget()
        left_layout.addWidget(self._edit_search)
        left_layout.addWidget(self._list, 1)
        splitter.addWidget(left)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        self._lbl_title = QLabel("左の一覧から譜面を選んでください。")
        self._lbl_title.setStyleSheet("font-weight: bold;")
        self._lbl_title.setWordWrap(True)
        right_layout.addWidget(self._lbl_title)
        right_layout.addWidget(QLabel("スコアの推移 (黄色の点 = その時点でのベスト更新)"))
        self._line = LineChartWidget()
        right_layout.addWidget(self._line, 3)

        legend = QHBoxLayout()
        legend.addWidget(QLabel("判定内訳:"))
        for name, label in (("cool", "COOL"), ("great", "GREAT"), ("good", "GOOD"), ("bad", "BAD")):
            lbl = QLabel(f"■ {label}")
            lbl.setStyleSheet(f"color: {JUDGE_COLORS[name].name()}; font-weight: bold;")
            legend.addWidget(lbl)
        legend.addStretch()
        right_layout.addLayout(legend)
        self._judge = JudgeBarWidget()
        right_layout.addWidget(self._judge, 2)

        self._table = QTableWidget(0, len(self._HEADERS))
        self._table.setHorizontalHeaderLabels(self._HEADERS)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.verticalHeader().hide()
        self._table.horizontalHeader().setStretchLastSection(True)
        right_layout.addWidget(self._table, 3)
        splitter.addWidget(right)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([260, 700])

        self._edit_search.textChanged.connect(self._fill_list)
        self._list.currentRowChanged.connect(self._on_selected)
        self.reload()

    def reload(self):
        self._entries = list_charts(self._score_manager.records)
        self._fill_list()

    def _fill_list(self, *_):
        words = self._edit_search.text().lower().split()
        self._list.blockSignals(True)
        self._list.clear()
        self._shown = []
        for i, e in enumerate(self._entries):
            if not all(w in e.title.lower() for w in words):
                continue
            level = f"Lv{e.level} " if e.level is not None else ""
            item = QListWidgetItem(f"{e.title} [{level}{e.difficulty}]  {e.play_count}回")
            item.setToolTip(f"ベスト: {e.best_score:,}\n最終プレー: {e.last_played}")
            self._list.addItem(item)
            self._shown.append(i)
        self._list.blockSignals(False)
        self._on_selected(-1)

    def select_chart(self, music_id: str, difficulty: str) -> bool:
        """指定した譜面を選ぶ (絞り込みは解除する)。プレー履歴が無ければ False。"""
        self._edit_search.clear()
        for row, i in enumerate(self._shown):
            e = self._entries[i]
            if e.music_id == music_id and e.difficulty == difficulty:
                self._list.setCurrentRow(row)
                return True
        return False

    def _on_selected(self, row: int):
        if not 0 <= row < len(self._shown):
            self._lbl_title.setText("左の一覧から譜面を選んでください。")
            self._line.set_data([], [], [], [])
            self._judge.set_data([], [], [])
            self._table.setRowCount(0)
            return
        entry = self._entries[self._shown[row]]
        history = chart_history(self._score_manager.records, entry.music_id, entry.difficulty)
        level = f"Lv{entry.level} " if entry.level is not None else ""
        self._lbl_title.setText(
            f"{entry.title} [{level}{entry.difficulty}]  /  {entry.play_count} 回プレー  /  ベスト {entry.best_score:,}"
        )

        labels, scores, tips, highlight, judges = [], [], [], [], []
        best = None
        for n, r in enumerate(history, 1):
            improved = best is not None and r.score > best
            best = r.score if best is None else max(best, r.score)
            labels.append(str(n))
            scores.append(r.score)
            highlight.append(improved)
            judges.append((r.cool, r.great, r.good, r.bad))
            tips.append(
                f"{n} 回目 ({r.timestamp})\nscore: {r.score:,}\n"
                f"COOL {r.cool} / GREAT {r.great} / GOOD {r.good} / BAD {r.bad}\nCOMBO {r.combo}"
            )
        self._line.set_data(labels, scores, tips, highlight)
        self._judge.set_data(labels, judges, tips)

        self._table.setRowCount(len(history))
        for n, r in enumerate(reversed(history)):
            # 新しい順に表示。前回比は 1 つ古い記録との差
            index = len(history) - 1 - n
            prev_score = history[index - 1].score if index > 0 else None
            diff = "" if prev_score is None else f"{r.score - prev_score:+,}"
            values = [r.timestamp, f"{r.score:,}", diff, r.cool, r.great, r.good, r.bad, r.combo,
                      r.options.to_summary()]
            for col, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if 1 <= col <= 7:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                if is_full_combo(r) and col == 1:
                    item.setForeground(JUDGE_COLORS["cool"])
                self._table.setItem(n, col, item)
        self._table.resizeColumnsToContents()


class StatsDialog(QDialog):
    """統計ダイアログ"""

    TAB_TREND = 2

    def __init__(
        self, score_manager: ScoreManager, parent=None, initial_chart: tuple[str, str] | None = None
    ):
        super().__init__(parent)
        self.setWindowTitle("統計")
        self.setMinimumSize(900, 600)
        layout = QVBoxLayout(self)

        self._tabs = QTabWidget()
        self._period = _PeriodTab(score_manager)
        self._level = _LevelTab(score_manager)
        self._trend = _TrendTab(score_manager)
        self._tabs.addTab(self._period, "打鍵数・プレー数")
        self._tabs.addTab(self._level, "レベル別")
        self._tabs.addTab(self._trend, "曲別の推移")
        layout.addWidget(self._tabs)

        bottom = QHBoxLayout()
        bottom.addStretch()
        btn_close = QPushButton("閉じる")
        btn_close.clicked.connect(self.accept)
        bottom.addWidget(btn_close)
        layout.addLayout(bottom)

        if initial_chart is not None and self._trend.select_chart(*initial_chart):
            self._tabs.setCurrentIndex(self.TAB_TREND)


class SessionSummaryDialog(QDialog):
    """今回の起動中 (セッション) の成績のまとめ"""

    def __init__(self, score_manager: ScoreManager, session_start: datetime, parent=None):
        super().__init__(parent)
        self.setWindowTitle("セッションサマリー")
        self.setMinimumSize(520, 380)
        layout = QVBoxLayout(self)

        summary = summarize_session(score_manager.records, session_start)
        self._text = QPlainTextEdit(format_session_summary(summary))
        self._text.setReadOnly(True)
        layout.addWidget(self._text)

        note = QLabel("ツールを起動してから現在までに記録したスコアの集計です。")
        note.setStyleSheet("color: gray;")
        layout.addWidget(note)

        bottom = QHBoxLayout()
        btn_copy = QPushButton("クリップボードにコピー")
        btn_copy.clicked.connect(lambda: QApplication.clipboard().setText(self._text.toPlainText()))
        bottom.addWidget(btn_copy)
        bottom.addStretch()
        btn_close = QPushButton("閉じる")
        btn_close.clicked.connect(self.accept)
        bottom.addWidget(btn_close)
        layout.addLayout(bottom)
