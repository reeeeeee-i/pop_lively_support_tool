"""統計ダイアログ (期間別の打鍵数・レベル別の成績・曲別のスコア推移) とセッションサマリー"""
from __future__ import annotations

import os
from datetime import date, datetime, time, timedelta
from urllib.parse import quote

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QImage, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
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
from src.config import Config
from src.session_image import (
    MAX_RESULT_IMAGES, load_result_images, render_results_image, render_session_image,
)
from src.score_stats import (
    aggregate_periods,
    chart_history,
    format_session_summary,
    format_share_text,
    is_full_combo,
    level_stats,
    list_charts,
    records_with_screenshots,
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


# リザルト画像の対象期間 (表示名, 識別子)。日付をまたいだセッションでも前日分を選べる
_RESULT_RANGES = (
    ("今回のセッション", "session"),
    ("本日", "today"),
    ("昨日から", "yesterday"),
    ("直近 7 日", "week"),
)


class SessionSummaryDialog(QDialog):
    """今回の起動中 (セッション) の成績のまとめ。

    サマリーの画像と、本日のリザルトを並べた画像 (別の画像) を作り、
    クリップボードへのコピー・保存・X への投稿ができる。
    """

    _X_INTENT_URL = "https://x.com/intent/post?text={text}"

    def __init__(
        self, score_manager: ScoreManager, session_start: datetime, parent=None,
        config: Config | None = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("セッションサマリー")
        self.setMinimumSize(800, 680)
        layout = QVBoxLayout(self)

        self._summary = summarize_session(score_manager.records, session_start)
        self._image = render_session_image(self._summary)
        self._results_images: list[QImage] = []
        self._shot_folder = config.result_screenshot_dir if config else "result_screenshots"
        self._session_start = session_start
        # 保存済みのリザルト画像 (ファイルが残っているもの)。表示する範囲は _fill_results_list で絞る
        self._all_shot_records = [
            r for r in records_with_screenshots(score_manager.records, datetime(2000, 1, 1))
            if os.path.isfile(self._shot_path(r))
        ]
        self._shot_records: list = []

        self._tabs = QTabWidget()
        self._tabs.addTab(self._make_preview_tab(self._image), "サマリー画像")
        self._tabs.addTab(self._make_results_tab(), "リザルト画像")
        self._text = QPlainTextEdit(format_session_summary(self._summary))
        self._text.setReadOnly(True)
        self._tabs.addTab(self._text, "テキスト")
        layout.addWidget(self._tabs, 1)

        note = QLabel("ツールを起動してから現在までに記録したスコアの集計です。")
        note.setStyleSheet("color: gray;")
        layout.addWidget(note)
        self._lbl_message = QLabel("")
        self._lbl_message.setWordWrap(True)
        layout.addWidget(self._lbl_message)

        bottom = QHBoxLayout()
        btn_copy_text = QPushButton("テキストをコピー")
        btn_copy_text.clicked.connect(lambda: QApplication.clipboard().setText(self._text.toPlainText()))
        btn_save = QPushButton("サマリー画像を保存...")
        btn_save.clicked.connect(
            lambda: self._save_image(self._image, f"session_{self._summary.start:%Y%m%d_%H%M}.png")
        )
        btn_copy_image = QPushButton("サマリー画像をコピー")
        btn_copy_image.clicked.connect(lambda: self._copy_image(self._image, "サマリー画像"))
        btn_post = QPushButton("X にポスト")
        btn_post.setToolTip(
            "サマリー画像をクリップボードにコピーし、投稿画面をブラウザで開きます。\n"
            "投稿画面の入力欄で Ctrl+V を押すと画像を貼り付けられます。\n"
            "リザルト画像も付ける場合は、「リザルト画像」タブでコピーしてから、もう一度貼り付けてください。"
        )
        btn_post.clicked.connect(self._post_to_x)
        for widget in (btn_copy_text, btn_save, btn_copy_image, btn_post):
            bottom.addWidget(widget)
        bottom.addStretch()
        btn_close = QPushButton("閉じる")
        btn_close.clicked.connect(self.accept)
        bottom.addWidget(btn_close)
        layout.addLayout(bottom)

    # ------------------------------------------------------------------
    # タブの組み立て
    # ------------------------------------------------------------------

    @staticmethod
    def _preview_area(label: QLabel) -> QScrollArea:
        label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setWidget(label)
        return area

    @staticmethod
    def _set_preview(label: QLabel, image: QImage | None):
        if image is None:
            label.clear()
            return
        label.setPixmap(QPixmap.fromImage(image).scaledToWidth(
            680, Qt.TransformationMode.SmoothTransformation
        ))

    def _make_preview_tab(self, image: QImage) -> QScrollArea:
        label = QLabel()
        self._set_preview(label, image)
        return self._preview_area(label)

    def _make_results_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        layout.addWidget(QLabel(
            f"保存したリザルトから使うものを選び、2 (横) x 4 (縦) で並べた画像を作ります。"
            f"{MAX_RESULT_IMAGES} 枚を超える場合は、複数の画像に分けて生成します。"
        ))
        range_row = QHBoxLayout()
        self._cmb_range = QComboBox()
        for label, _ in _RESULT_RANGES:
            self._cmb_range.addItem(label)
        range_row.addWidget(QLabel("対象の期間:"))
        range_row.addWidget(self._cmb_range)
        range_row.addStretch()
        layout.addLayout(range_row)
        self._list = QListWidget()
        self._list.setMaximumHeight(150)
        layout.addWidget(self._list)

        select_row = QHBoxLayout()
        btn_all = QPushButton("すべて選択")
        btn_all.clicked.connect(lambda: self._set_all_checked(True))
        btn_none = QPushButton("すべて解除")
        btn_none.clicked.connect(lambda: self._set_all_checked(False))
        self._lbl_results = QLabel()
        select_row.addWidget(btn_all)
        select_row.addWidget(btn_none)
        select_row.addWidget(self._lbl_results)
        select_row.addStretch()
        layout.addLayout(select_row)

        controls = QHBoxLayout()
        self._btn_generate = QPushButton("リザルト画像を生成")
        self._btn_generate.clicked.connect(self._generate_results_images)
        self._cmb_page = QComboBox()
        self._cmb_page.currentIndexChanged.connect(self._show_results_page)
        self._btn_copy_results = QPushButton("表示中の画像をコピー")
        self._btn_copy_results.clicked.connect(
            lambda: self._copy_image(self._current_results_image(), "リザルト画像")
        )
        self._btn_save_results = QPushButton("表示中の画像を保存...")
        self._btn_save_results.clicked.connect(
            lambda: self._save_image(
                self._current_results_image(), f"results_{date.today():%Y%m%d}_{self._cmb_page.currentIndex() + 1}.png"
            )
        )
        self._btn_save_all = QPushButton("すべて保存...")
        self._btn_save_all.clicked.connect(self._save_all_results)
        for widget in (self._btn_generate, self._cmb_page, self._btn_copy_results,
                       self._btn_save_results, self._btn_save_all):
            controls.addWidget(widget)
        controls.addStretch()
        layout.addLayout(controls)

        self._results_preview = QLabel()
        layout.addWidget(self._preview_area(self._results_preview), 1)

        self._select_buttons = (btn_all, btn_none, self._btn_generate)
        self._list.itemChanged.connect(self._on_item_changed)
        self._cmb_range.currentIndexChanged.connect(self._fill_results_list)
        self._fill_results_list()
        return tab

    # ------------------------------------------------------------------
    # リザルト画像
    # ------------------------------------------------------------------

    def _range_start(self) -> datetime:
        """リザルト画像の対象期間の開始日時"""
        key = _RESULT_RANGES[self._cmb_range.currentIndex()][1]
        if key == "session":
            return self._session_start
        midnight = datetime.combine(date.today(), time())
        return midnight - timedelta(days={"today": 0, "yesterday": 1, "week": 6}[key])

    def _fill_results_list(self, *_):
        """対象期間のリザルトを一覧に並べ直す (既定ではすべてチェックする)。"""
        since = self._range_start().strftime("%Y-%m-%d %H:%M:%S")
        self._shot_records = [r for r in self._all_shot_records if r.timestamp >= since]
        self._list.blockSignals(True)
        self._list.clear()
        for r in reversed(self._shot_records):   # 新しいものを上に
            level = f"Lv{r.level} " if r.level else ""
            item = QListWidgetItem(
                f"{r.timestamp[5:16]}  {r.title} [{level}{r.difficulty_code}]  {r.score:,}"
            )
            item.setData(Qt.ItemDataRole.UserRole, r.record_id)
            item.setCheckState(Qt.CheckState.Checked)
            self._list.addItem(item)
        self._list.blockSignals(False)
        for widget in (self._list, *self._select_buttons):
            widget.setEnabled(bool(self._shot_records))
        self._set_results_images([])
        if not self._shot_records:
            self._lbl_results.setText(
                "この期間に保存したリザルト画像がありません（設定でスクリーンショットの保存条件を選ぶと保存されます）。"
            )

    def _shot_path(self, record) -> str:
        return os.path.abspath(os.path.join(self._shot_folder, record.screenshot_file))

    def _checked_records(self) -> list:
        """チェックされたリザルトの記録 (古い順)"""
        ids = {
            self._list.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self._list.count())
            if self._list.item(i).checkState() == Qt.CheckState.Checked
        }
        return [r for r in self._shot_records if r.record_id in ids]

    def _set_all_checked(self, checked: bool):
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        self._list.blockSignals(True)
        for i in range(self._list.count()):
            self._list.item(i).setCheckState(state)
        self._list.blockSignals(False)
        self._on_item_changed()

    def _on_item_changed(self, _item: QListWidgetItem | None = None):
        # 選び直したら、生成済みの画像は古くなる
        self._set_results_images([])

    def _set_results_images(self, images: list[QImage]):
        self._results_images = images
        self._cmb_page.blockSignals(True)
        self._cmb_page.clear()
        for i in range(len(images)):
            self._cmb_page.addItem(f"{i + 1} / {len(images)} 枚目")
        self._cmb_page.blockSignals(False)
        has_images = bool(images)
        for widget in (self._cmb_page, self._btn_copy_results, self._btn_save_results):
            widget.setEnabled(has_images)
        self._btn_save_all.setEnabled(has_images)
        self._show_results_page()
        if not images and self._shot_records:
            count = len(self._checked_records())
            pages = -(-count // MAX_RESULT_IMAGES)
            self._lbl_results.setText(f"{count} 枚を選択中 (画像 {pages} 枚)" if count else "リザルトを選んでください。")

    def _current_results_image(self) -> QImage | None:
        index = self._cmb_page.currentIndex()
        return self._results_images[index] if 0 <= index < len(self._results_images) else None

    def _show_results_page(self, *_):
        self._set_preview(self._results_preview, self._current_results_image())

    def _generate_results_images(self):
        records = self._checked_records()
        if not records:
            self._lbl_results.setText("リザルトを 1 枚以上選んでください。")
            return
        paths = [self._shot_path(r) for r in records]
        images = []
        # 1 枚の画像に並べられる枚数ごとに分けて生成する (古い順)
        for start in range(0, len(paths), MAX_RESULT_IMAGES):
            chunk = records[start:start + MAX_RESULT_IMAGES]
            results = load_result_images(paths[start:start + MAX_RESULT_IMAGES])
            if results:
                images.append(render_results_image(results, self._date_label(chunk)))
        if not images:
            self._lbl_results.setText("リザルトの画像ファイルを読み込めませんでした。")
            return
        self._set_results_images(images)
        self._lbl_results.setText(f"{len(records)} 枚のリザルトから {len(images)} 枚の画像を生成しました。")

    @staticmethod
    def _date_label(records: list) -> str:
        """画像の見出しに出す日付。日付をまたぐ場合は期間で表す。"""
        first, last = records[0].timestamp[:10], records[-1].timestamp[:10]
        return first if first == last else f"{first} ～ {last[5:]}"

    def _save_all_results(self):
        if not self._results_images:
            return
        folder = QFileDialog.getExistingDirectory(self, "画像の保存先フォルダ")
        if not folder:
            return
        failed = []
        for i, image in enumerate(self._results_images, 1):
            path = os.path.join(folder, f"results_{date.today():%Y%m%d}_{i}.png")
            if not image.save(path, "PNG"):
                failed.append(path)
        if failed:
            QMessageBox.critical(self, "エラー", "保存できなかった画像があります:\n" + "\n".join(failed))
        else:
            self._lbl_message.setText(f"{len(self._results_images)} 枚の画像を保存しました: {folder}")

    # ------------------------------------------------------------------
    # コピー・保存・投稿
    # ------------------------------------------------------------------

    def _copy_image(self, image: QImage | None, name: str):
        if image is None:
            return
        QApplication.clipboard().setImage(image)
        self._lbl_message.setText(f"{name}をクリップボードにコピーしました。")

    def _save_image(self, image: QImage | None, default_name: str):
        if image is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, "画像の保存先", default_name, "PNG Files (*.png)")
        if not path:
            return
        if image.save(path, "PNG"):
            self._lbl_message.setText(f"画像を保存しました: {path}")
        else:
            QMessageBox.critical(self, "エラー", f"画像を保存できませんでした:\n{path}")

    def _post_to_x(self):
        # X の投稿画面 (Web Intent) では画像を指定できないため、画像はクリップボード経由で貼り付けてもらう
        QApplication.clipboard().setImage(self._image)
        url = QUrl(self._X_INTENT_URL.format(text=quote(format_share_text(self._summary), safe="")))
        if QDesktopServices.openUrl(url):
            self._lbl_message.setText(
                "投稿画面をブラウザで開きました。サマリー画像はクリップボードにコピー済みです。"
                "入力欄で Ctrl+V を押して貼り付けてください。"
                "リザルト画像も付ける場合は、「リザルト画像」タブでコピーしてから、もう一度貼り付けてください。"
            )
        else:
            self._lbl_message.setText("ブラウザを開けませんでした。画像を保存して投稿してください。")
