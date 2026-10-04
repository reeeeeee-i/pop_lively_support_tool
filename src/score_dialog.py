"""スコア履歴ダイアログ"""
from __future__ import annotations

import re
import unicodedata
from typing import Callable, NamedTuple

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from src.classes import DIFFICULTY_LEVEL_COLUMNS, PopnOptions, PopnScoreRecord
from src.config import Config
from src.option_master import OPTION_KEYS as _OPTION_KEYS
from src.score_manager import ScoreManager


_VER_PREFIX = "pop'n music"

# スコア履歴の ver 列に表示する略称 (ナンバリング作品は数字のみにする)
_VER_SHORT_NAMES = {
    "Sunny Park": "SP",
    "ラピストリア": "LT",
    "éclale": "ec",
    "うさぎと猫と少年の夢": "うさ",
    "peace": "pe",
    "解明リドルズ": "解",
    "UniLab": "UL",
    "Jam&Fizz": "JF",
    "High☆Cheers!!": "HC",
}


def _short_ver(ver: str) -> str:
    """ver の略称。"pop'n music 20 fantasia" → "20"、"pop'n music Sunny Park" → "SP"。"""
    if not ver.startswith(_VER_PREFIX):
        return ver
    name = ver[len(_VER_PREFIX):].strip()
    if not name:
        # 初代は "pop'n music" のみ
        return "1"
    number = re.match(r"\d+", name)
    if number:
        return number.group()
    return _VER_SHORT_NAMES.get(name, name)


class _Column(NamedTuple):
    key: str
    """設定保存用の識別子"""
    label: str
    value: Callable[[PopnScoreRecord], object]
    width: int
    numeric: bool = False


# 既定の列順。並び順・表示/非表示・幅はユーザーが変更でき、config に保存される
_COLUMNS: list[_Column] = [
    _Column("level",      "レベル",       lambda r: r.level if r.level else "", 50, True),
    _Column("ver",        "ver",          lambda r: _short_ver(r.ver), 50),
    _Column("genre",      "ジャンル",     lambda r: r.genre, 160),
    _Column("difficulty", "難易度",       lambda r: r.difficulty_code, 50),
    _Column("title",      "曲名",         lambda r: r.title, 220),
    _Column("artist",     "アーティスト", lambda r: r.artist, 180),
    _Column("score",      "score",        lambda r: r.score, 65, True),
    _Column("cool",       "cool",         lambda r: r.cool, 50, True),
    _Column("great",      "great",        lambda r: r.great, 50, True),
    _Column("good",       "good",         lambda r: r.good, 50, True),
    _Column("bad",        "bad",          lambda r: r.bad, 50, True),
    _Column("combo",      "combo",        lambda r: r.combo, 55, True),
    _Column("hispeed",    "ハイスピード", lambda r: r.options.hispeed, 80),
    _Column("popkun",     "ポップ君",     lambda r: r.options.popkun, 80),
    _Column("gauge_type", "ゲージタイプ", lambda r: r.options.gauge_type, 90),
    _Column("guide_se",   "ガイドSE",     lambda r: r.options.guide_se, 70),
    _Column("random",     "RANDOM",       lambda r: r.options.random, 80),
    _Column("judge_plus", "JUDGE+",       lambda r: r.options.judge_plus, 70),
    _Column("hidden",     "HIDDEN",       lambda r: r.options.hidden, 70),
    _Column("sudden",     "SUDDEN",       lambda r: r.options.sudden, 70),
    _Column("ojama1",     "オジャマ1",    lambda r: r.options.ojama1, 90),
    _Column("ojama2",     "オジャマ2",    lambda r: r.options.ojama2, 90),
    _Column("ojama1_zutto", "オジャマ1ずっと", lambda r: r.options.ojama1_zutto, 100),
    _Column("ojama2_zutto", "オジャマ2ずっと", lambda r: r.options.ojama2_zutto, 100),
    _Column("auto",       "AUTO",         lambda r: r.options.auto, 60),
    _Column("played_at",  "プレー日時",   lambda r: r.timestamp, 140),
    _Column("modified",   "修正済",       lambda r: "○" if r.modified else "", 55),
]


_COLUMN_LABELS = {c.key: c.label for c in _COLUMNS}

# 詳細画面で修正できる項目 (列キー = PopnScoreRecord / PopnOptions の属性名)
_JUDGE_KEYS = ["score", "cool", "great", "good", "bad", "combo"]
_SCORE_MAX = 100000
_DIFFICULTY_CODES = list(DIFFICULTY_LEVEL_COLUMNS)

_MUSIC_COLUMNS = [
    ("title", "曲名", 240),
    ("genre", "ジャンル", 170),
    ("artist", "アーティスト", 180),
    ("ver", "ver", 150),
    ("easy", "L", 36),
    ("normal", "N", 36),
    ("hyper", "H", 36),
    ("ex", "EX", 36),
]


_HIRAGANA_TO_KATAKANA = {c: c + 0x60 for c in range(ord("ぁ"), ord("ゖ") + 1)}
_WAVE_DASHES = {ord(c): "~" for c in "〜∼˜"}


def _search_key(s: str) -> str:
    """検索用のキー。全角/半角・大文字/小文字・ひらがな/カタカナ・アクセント記号・波ダッシュの違いを吸収する。"""
    s = unicodedata.normalize("NFKC", s).casefold()
    # アクセント記号を外す ("é" → "e")。濁点・半濁点は残す
    s = "".join(c for c in unicodedata.normalize("NFD", s) if not "\u0300" <= c <= "\u036f")
    s = unicodedata.normalize("NFC", s)
    return s.translate(_HIRAGANA_TO_KATAKANA).translate(_WAVE_DASHES)


class _MusicItem(QTableWidgetItem):
    """曲の選択テーブルのセル。列見出しクリックでのソート順を sort_key で決める。"""

    def __init__(self, value, index: int):
        super().__init__("" if value is None else str(value))
        self.index = index
        """曲リスト (MusicSelectDialog._musics) の添字"""
        if isinstance(value, str):
            # 文字列中の数字は数値として比べる ("pop'n music 6" < "pop'n music 15")
            parts = re.split(r"(\d+)", _search_key(value))
            self.sort_key = [int(p) if i % 2 else p for i, p in enumerate(parts)]
        else:
            # レベル。譜面の無い曲は None
            self.sort_key = value
            self.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

    def __lt__(self, other):
        a, b = self.sort_key, other.sort_key
        if a is None or b is None:
            # 譜面の無い曲は昇順・降順のどちらでも末尾に並べる
            descending = (
                self.tableWidget().horizontalHeader().sortIndicatorOrder()
                == Qt.SortOrder.DescendingOrder
            )
            return (a is None and b is not None) if descending else (b is None and a is not None)
        return a < b


class MusicSelectDialog(QDialog):
    """曲テーブルから 1 曲を選ぶダイアログ"""

    def __init__(self, score_manager: ScoreManager, current_music_id: str = "", parent=None):
        super().__init__(parent)
        self.selected: dict | None = None
        self._musics = score_manager.db.list_musics()
        # 絞り込みは曲名・ジャンル・アーティスト・ver の部分一致
        self._keys = [
            _search_key("\n".join(m[k] or "" for k in ("title", "genre", "artist", "ver")))
            for m in self._musics
        ]

        self.setWindowTitle("曲の選択")
        self.setMinimumSize(960, 500)
        layout = QVBoxLayout(self)

        self._edit_search = QLineEdit()
        self._edit_search.setPlaceholderText("曲名・ジャンル・アーティスト・ver で絞り込み (空白区切りで AND)")
        self._edit_search.setClearButtonEnabled(True)
        self._edit_search.textChanged.connect(self._filter)
        layout.addWidget(self._edit_search)

        self._table = QTableWidget(len(self._musics), len(_MUSIC_COLUMNS))
        self._table.setHorizontalHeaderLabels([label for _, label, _ in _MUSIC_COLUMNS])
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._table.verticalHeader().hide()
        for col_idx, (_, _, width) in enumerate(_MUSIC_COLUMNS):
            self._table.setColumnWidth(col_idx, width)
        for row_idx, m in enumerate(self._musics):
            for col_idx, (key, _, _) in enumerate(_MUSIC_COLUMNS):
                self._table.setItem(row_idx, col_idx, _MusicItem(m[key], row_idx))
            if m["music_id"] == current_music_id:
                self._table.selectRow(row_idx)
        # 列見出しのクリックでソートを切り替える (初期状態は曲名の昇順)
        self._table.setToolTip("列見出しをクリックすると、その列で並べ替えます。")
        self._table.setSortingEnabled(True)
        self._table.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        # 行の表示/非表示は行位置に紐づくので、並べ替えのたびに絞り込みをやり直す
        self._table.horizontalHeader().sortIndicatorChanged.connect(
            lambda *_: self._filter(self._edit_search.text())
        )
        self._table.cellDoubleClicked.connect(lambda *_: self._accept_selection())
        layout.addWidget(self._table)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("選択")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("キャンセル")
        buttons.accepted.connect(self._accept_selection)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._table.scrollToItem(self._table.currentItem(), QTableWidget.ScrollHint.PositionAtCenter)
        self._edit_search.setFocus()

    def _filter(self, text: str):
        words = _search_key(text).split()
        first_visible = -1
        for row_idx in range(self._table.rowCount()):
            key = self._keys[self._table.item(row_idx, 0).index]
            match = all(w in key for w in words)
            self._table.setRowHidden(row_idx, not match)
            if match and first_visible < 0:
                first_visible = row_idx
        # 選択中の曲が絞り込みで隠れたら先頭の候補を選び、そのまま Enter で決定できるようにする
        row = self._table.currentRow()
        if first_visible >= 0 and (row < 0 or self._table.isRowHidden(row)):
            self._table.selectRow(first_visible)
        if self._table.currentItem() is not None:
            self._table.scrollToItem(self._table.currentItem())

    def _accept_selection(self):
        row = self._table.currentRow()
        if row < 0 or self._table.isRowHidden(row):
            QMessageBox.information(self, "曲の選択", "曲を選択してください。")
            return
        self.selected = self._musics[self._table.item(row, 0).index]
        self.accept()


def export_csv_with_dialog(parent, score_manager: ScoreManager) -> None:
    """出力先を選ばせてスコア履歴を CSV に出力し、結果をメッセージで知らせる。"""
    path, _ = QFileDialog.getSaveFileName(
        parent,
        "CSVエクスポート先の選択",
        score_manager.csv_path,
        "CSV Files (*.csv);;All Files (*)",
    )
    if not path:
        return
    try:
        score_manager.export_csv(path)
        QMessageBox.information(parent, "完了", f"CSVファイルを出力しました:\n{path}")
    except Exception as e:
        QMessageBox.critical(parent, "エラー", f"CSV出力に失敗しました:\n{e}")


def _confirm_and_delete(
    parent, score_manager: ScoreManager, records: list[PopnScoreRecord]
) -> bool:
    """確認のうえスコア記録を削除する。削除した場合のみ True を返す。"""
    if not records:
        return False
    if len(records) == 1:
        r = records[0]
        target = f"{r.title} [{r.difficulty_code}]  SCORE: {r.score}\n{r.timestamp}"
    else:
        target = f"選択中の {len(records)} 件"
    answer = QMessageBox.question(
        parent,
        "スコア記録の削除",
        f"次のスコア記録を削除します。元に戻せません。\n\n{target}\n\n削除しますか?",
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.No,
    )
    if answer != QMessageBox.StandardButton.Yes:
        return False
    try:
        score_manager.delete_records(records)
    except Exception as e:
        QMessageBox.critical(parent, "エラー", f"スコア記録の削除に失敗しました:\n{e}")
        return False
    return True


class ScoreDetailDialog(QDialog):
    """スコア記録 1 件の詳細表示・修正ダイアログ"""

    def __init__(self, record: PopnScoreRecord, score_manager: ScoreManager, parent=None):
        super().__init__(parent)
        self.record = record
        self.score_manager = score_manager
        self._music_id = record.music_id
        self._levels: dict = {}

        self.setWindowTitle("スコア記録の詳細 / 修正")
        self.setMinimumWidth(520)
        self._init_ui()

    def _init_ui(self):
        r = self.record
        layout = QVBoxLayout(self)

        # 曲情報: ver / 難易度 / レベル、ジャンル / 曲名 / アーティスト の 2 段
        self._cmb_difficulty = QComboBox()
        self._cmb_difficulty.addItems(_DIFFICULTY_CODES)
        if r.difficulty_code not in _DIFFICULTY_CODES:
            self._cmb_difficulty.addItem(r.difficulty_code)
        self._cmb_difficulty.setCurrentText(r.difficulty_code)
        self._cmb_difficulty.currentTextChanged.connect(self._update_level)
        self._lbl_level = QLabel()
        self._song_labels = {key: QLabel() for key in ("ver", "genre", "title", "artist")}
        music = self.score_manager.db.get_music(r.music_id)
        self._set_music(music or {"music_id": r.music_id, "title": r.title, "genre": r.genre,
                                  "artist": r.artist, "ver": r.ver})

        song_box = QGroupBox("曲情報")
        box_layout = QVBoxLayout(song_box)
        grid = QGridLayout()
        box_layout.addLayout(grid)
        btn_change = QPushButton("曲を変更...")
        btn_change.clicked.connect(self._change_music)
        box_layout.addWidget(btn_change, 0, Qt.AlignmentFlag.AlignRight)
        labels = self._song_labels
        song_rows = [
            [("ver", labels["ver"]), ("difficulty", self._cmb_difficulty), ("level", self._lbl_level)],
            [("genre", labels["genre"]), ("title", labels["title"]), ("artist", labels["artist"])],
        ]
        for row_idx, row in enumerate(song_rows):
            for col_idx, (key, widget) in enumerate(row):
                caption = QLabel(_COLUMN_LABELS[key])
                caption.setStyleSheet("color: gray;")
                grid.addWidget(caption, row_idx * 2, col_idx)
                if isinstance(widget, QLabel):
                    widget.setStyleSheet("font-weight: bold;")
                    widget.setWordWrap(True)
                    widget.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
                    grid.addWidget(widget, row_idx * 2 + 1, col_idx)
                else:
                    grid.addWidget(widget, row_idx * 2 + 1, col_idx, Qt.AlignmentFlag.AlignLeft)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 2)
        grid.setColumnStretch(2, 1)
        grid.setHorizontalSpacing(16)
        layout.addWidget(song_box)

        form = QFormLayout()

        self._spins: dict[str, QSpinBox] = {}
        for key in _JUDGE_KEYS:
            spin = QSpinBox()
            spin.setRange(0, _SCORE_MAX if key == "score" else 999999)
            spin.setValue(int(getattr(r, key)))
            self._spins[key] = spin
            form.addRow(_COLUMN_LABELS[key], spin)

        # オプションの候補はオプションマスターの値。選択肢が多いので直接入力でも選べる
        self._option_combos: dict[str, QComboBox] = {}
        for key in _OPTION_KEYS:
            current = getattr(r.options, key)
            values = self.score_manager.db.get_option_values(key)
            if current not in values:
                # マスターに無い値で記録済みのものは、そのまま残せるようにする
                values.append(current)
            combo = QComboBox()
            combo.setEditable(True)
            combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
            combo.addItems(values)
            combo.setCurrentText(current)
            self._option_combos[key] = combo
            form.addRow(_COLUMN_LABELS[key], combo)

        form.addRow(_COLUMN_LABELS["played_at"], QLabel(r.timestamp))
        form.addRow(_COLUMN_LABELS["modified"], QLabel("○" if r.modified else "―"))
        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("保存")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("キャンセル")
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)

        # 最下部: 左に削除、右に保存 / キャンセル
        bottom_hbox = QHBoxLayout()
        btn_delete = QPushButton("削除")
        btn_delete.setAutoDefault(False)
        btn_delete.clicked.connect(self._delete)
        bottom_hbox.addWidget(btn_delete)
        bottom_hbox.addStretch()
        bottom_hbox.addWidget(buttons)
        layout.addLayout(bottom_hbox)

    def _delete(self):
        if _confirm_and_delete(self, self.score_manager, [self.record]):
            self.accept()

    def _set_music(self, music: dict):
        self._music_id = music["music_id"]
        self._levels = {code: music.get(col) for code, col in DIFFICULTY_LEVEL_COLUMNS.items()}
        for key, label in self._song_labels.items():
            label.setText(music[key])
        self._update_level(self._cmb_difficulty.currentText())

    def _change_music(self):
        dlg = MusicSelectDialog(self.score_manager, self._music_id, self)
        if dlg.exec() and dlg.selected:
            self._set_music(dlg.selected)

    def _update_level(self, difficulty: str):
        level = self._levels.get(difficulty)
        self._lbl_level.setText(str(level) if level is not None else "")

    def _values(self) -> dict:
        values = {"music_id": self._music_id, "difficulty": self._cmb_difficulty.currentText()}
        values.update({k: spin.value() for k, spin in self._spins.items()})
        values.update({k: combo.currentText().strip() for k, combo in self._option_combos.items()})
        return values

    def _save(self):
        r = self.record
        values = self._values()
        original = {"music_id": r.music_id, "difficulty": r.difficulty_code}
        original.update({k: getattr(r, k) for k in _JUDGE_KEYS})
        original.update({k: getattr(r.options, k) for k in _OPTION_KEYS})
        # 直接入力された値はオプションマスターの表記に揃える ("x3.5" → "3.5" など)
        for key in _OPTION_KEYS:
            if values[key] == original[key]:
                continue
            value = self.score_manager.db.normalize_option(key, values[key])
            if value is None:
                QMessageBox.warning(
                    self, "入力エラー",
                    f"{_COLUMN_LABELS[key]} の値「{values[key]}」は選択肢にありません。",
                )
                self._option_combos[key].setFocus()
                return
            values[key] = value
        if values == original:
            # 変更が無ければ修正済フラグを立てない
            self.reject()
            return

        options = PopnOptions(**{k: values[k] for k in _OPTION_KEYS}, extra=r.options.extra)
        updated = PopnScoreRecord(
            title=self._song_labels["title"].text(),
            level=self._lbl_level.text(),
            difficulty=values["difficulty"],
            **{k: values[k] for k in _JUDGE_KEYS},
            options=options,
            timestamp=r.timestamp,
            music_id=self._music_id,
            record_id=r.record_id,
        )
        try:
            self.score_manager.update_record(updated)
        except Exception as e:
            QMessageBox.critical(self, "エラー", f"スコア記録の修正に失敗しました:\n{e}")
            return
        self.accept()


class ScoreHistoryDialog(QDialog):
    """スコア履歴一覧ダイアログ"""

    def __init__(self, score_manager: ScoreManager, parent=None, config: Config | None = None):
        super().__init__(parent)
        self.score_manager = score_manager
        self.config = config
        self._row_texts: list[list[str]] = []
        """行ごとの検索用文字列 (列順は _COLUMNS)"""

        self.setWindowTitle("スコア履歴 / CSV出力")
        self.setMinimumSize(950, 500)

        self._init_ui()
        self._apply_column_settings(config.score_history_columns if config else {})
        self._load_records()

    def _init_ui(self):
        layout = QVBoxLayout(self)

        # 概要情報
        top_hbox = QHBoxLayout()
        self._lbl_count = QLabel("記録件数: 0 件")
        self._lbl_count.setStyleSheet("font-weight: bold;")
        top_hbox.addWidget(self._lbl_count)
        top_hbox.addStretch()

        btn_columns = QPushButton("表示列")
        btn_columns.setToolTip(
            "列の表示/非表示を切り替えます。\n"
            "列見出しのドラッグで並び替え、境界のドラッグで幅を変更できます。"
        )
        self._columns_menu = QMenu(self)
        self._columns_menu.aboutToShow.connect(self._build_columns_menu)
        btn_columns.setMenu(self._columns_menu)
        top_hbox.addWidget(btn_columns)

        btn_export_csv = QPushButton("CSVエクスポート...")
        btn_export_csv.clicked.connect(lambda: export_csv_with_dialog(self, self.score_manager))
        top_hbox.addWidget(btn_export_csv)

        btn_open_csv = QPushButton("CSVファイルを外部アプリで開く")
        btn_open_csv.clicked.connect(self._open_csv)
        top_hbox.addWidget(btn_open_csv)

        btn_reload = QPushButton("再読み込み")
        btn_reload.clicked.connect(self._reload)
        top_hbox.addWidget(btn_reload)

        # 検索 (表示中の列の部分一致)
        self._edit_search = QLineEdit()
        self._edit_search.setPlaceholderText("検索 (空白区切りで AND)")
        self._edit_search.setToolTip("表示中の列から部分一致で絞り込みます。 (Ctrl+F)")
        self._edit_search.setClearButtonEnabled(True)
        self._edit_search.setFixedWidth(220)
        self._edit_search.textChanged.connect(self._filter)
        top_hbox.addWidget(self._edit_search)
        shortcut = QShortcut(QKeySequence.StandardKey.Find, self)
        shortcut.activated.connect(self._edit_search.setFocus)
        shortcut.activated.connect(self._edit_search.selectAll)
        layout.addLayout(top_hbox)

        # テーブル
        self._table = QTableWidget()
        self._table.setColumnCount(len(_COLUMNS))
        self._table.setHorizontalHeaderLabels([c.label for c in _COLUMNS])
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setHorizontalScrollMode(QTableWidget.ScrollMode.ScrollPerPixel)
        self._table.setToolTip("行をダブルクリックすると詳細を表示し、内容を修正できます。")
        self._table.cellDoubleClicked.connect(self._open_detail)
        self._table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._show_row_menu)
        hdr = self._table.horizontalHeader()
        hdr.setSectionsMovable(True)
        hdr.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        hdr.setStretchLastSection(False)
        hdr.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        hdr.customContextMenuRequested.connect(
            lambda pos: self._columns_menu.exec(hdr.mapToGlobal(pos))
        )
        layout.addWidget(self._table)

        # 下部ボタン
        bottom_hbox = QHBoxLayout()
        bottom_hbox.addStretch()
        btn_close = QPushButton("閉じる")
        btn_close.clicked.connect(self.accept)
        bottom_hbox.addWidget(btn_close)
        layout.addLayout(bottom_hbox)

    # ------------------------------------------------------------------
    # 列設定 (並び順 / 表示・非表示 / 幅)
    # ------------------------------------------------------------------

    def _build_columns_menu(self):
        menu = self._columns_menu
        menu.clear()
        hdr = self._table.horizontalHeader()
        # 現在の表示順に並べる
        for visual in range(hdr.count()):
            logical = hdr.logicalIndex(visual)
            action = menu.addAction(_COLUMNS[logical].label)
            action.setCheckable(True)
            action.setChecked(not hdr.isSectionHidden(logical))
            action.toggled.connect(
                lambda checked, i=logical: self._set_column_hidden(i, not checked)
            )
        menu.addSeparator()
        menu.addAction("すべての列を表示", self._show_all_columns)
        menu.addAction("列幅を内容に合わせる", self._table.resizeColumnsToContents)
        menu.addAction("列を初期状態に戻す", lambda: self._apply_column_settings({}))

    def _set_column_hidden(self, index: int, hidden: bool):
        self._table.setColumnHidden(index, hidden)
        self._filter()

    def _show_all_columns(self):
        for i in range(len(_COLUMNS)):
            self._table.setColumnHidden(i, False)
        self._filter()

    def _apply_column_settings(self, settings: dict):
        """保存済みの列設定を反映する。設定に無い列は既定の位置・幅で表示する。"""
        if not isinstance(settings, dict):
            settings = {}
        keys = [c.key for c in _COLUMNS]
        saved_order = [k for k in settings.get("order", []) if k in keys]
        order = saved_order + [k for k in keys if k not in saved_order]
        hidden = set(settings.get("hidden", []))
        widths = settings.get("widths", {})

        hdr = self._table.horizontalHeader()
        for visual, key in enumerate(order):
            hdr.moveSection(hdr.visualIndex(keys.index(key)), visual)
        for i, col in enumerate(_COLUMNS):
            # 非表示列の幅は 0 になるため、幅を設定してから隠す
            self._table.setColumnHidden(i, False)
            width = widths.get(col.key)
            self._table.setColumnWidth(i, width if isinstance(width, int) and width > 0 else col.width)
            self._table.setColumnHidden(i, col.key in hidden)
        self._filter()

    def _column_settings(self) -> dict:
        hdr = self._table.horizontalHeader()
        hidden = [c.key for i, c in enumerate(_COLUMNS) if hdr.isSectionHidden(i)]
        widths = {}
        for i, col in enumerate(_COLUMNS):
            if hdr.isSectionHidden(i):
                # 非表示中は幅を取得できないので、再表示時用に直前の値を引き継ぐ
                prev = self.config.score_history_columns.get("widths", {}) if self.config else {}
                widths[col.key] = prev.get(col.key, col.width)
            else:
                widths[col.key] = hdr.sectionSize(i)
        return {
            "order": [_COLUMNS[hdr.logicalIndex(v)].key for v in range(hdr.count())],
            "hidden": hidden,
            "widths": widths,
        }

    def done(self, result):
        if self.config is not None:
            self.config.score_history_columns = self._column_settings()
            self.config.save_config()
        super().done(result)

    # ------------------------------------------------------------------

    def _load_records(self):
        # 新しい順に表示 (行番号 = self._rows の添字)
        records = self._rows = list(reversed(self.score_manager.records))
        self._table.setRowCount(len(records))

        self._row_texts = []
        for row_idx, r in enumerate(records):
            texts = [str(col.value(r)) for col in _COLUMNS]
            # ver は略称で表示するが、正式名称でも検索できるようにする
            self._row_texts.append([
                _search_key(f"{t}\n{r.ver}" if col.key == "ver" else t)
                for col, t in zip(_COLUMNS, texts)
            ])
            for col_idx, (col, text) in enumerate(zip(_COLUMNS, texts)):
                item = QTableWidgetItem(text)
                if col.key == "ver":
                    item.setToolTip(r.ver)
                if col.numeric:
                    item.setTextAlignment(
                        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                    )
                self._table.setItem(row_idx, col_idx, item)
        self._filter()

    def _filter(self, _text: str = ""):
        """表示中の列に検索語を全て含む行だけを表示する"""
        words = _search_key(self._edit_search.text()).split()
        hdr = self._table.horizontalHeader()
        visible = [i for i in range(len(_COLUMNS)) if not hdr.isSectionHidden(i)]
        shown = 0
        for row_idx, texts in enumerate(self._row_texts):
            key = "\n".join(texts[i] for i in visible)
            match = all(w in key for w in words)
            self._table.setRowHidden(row_idx, not match)
            shown += match
        total = len(self._row_texts)
        count = f"{total} 件中 {shown} 件を表示" if words else f"{total} 件"
        self._lbl_count.setText(
            f"記録件数: {count} (DB: {self.score_manager.db_path} / CSV: {self.score_manager.csv_path})"
        )

    def keyPressEvent(self, event):
        # 検索欄での Enter が既定ボタンを押してしまわないようにする
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self._edit_search.hasFocus():
            return
        super().keyPressEvent(event)

    def _open_detail(self, row: int, _column: int = 0):
        if not 0 <= row < len(self._rows):
            return
        dlg = ScoreDetailDialog(self._rows[row], self.score_manager, self)
        if dlg.exec():
            self._load_records()
            self._table.selectRow(row)

    def _show_row_menu(self, pos):
        item = self._table.itemAt(pos)
        if item is None:
            return
        row = item.row()
        # 選択外の行を右クリックしたら、その行だけを選択し直す
        if not item.isSelected():
            self._table.selectRow(row)
        menu = QMenu(self)
        act_edit = menu.addAction("編集...")
        act_delete = menu.addAction("削除")
        chosen = menu.exec(self._table.viewport().mapToGlobal(pos))
        if chosen is act_edit:
            self._open_detail(row)
        elif chosen is act_delete:
            self._delete_selected()

    def _delete_selected(self):
        rows = sorted(
            i.row() for i in self._table.selectionModel().selectedRows()
            if not self._table.isRowHidden(i.row())
        )
        if _confirm_and_delete(self, self.score_manager, [self._rows[r] for r in rows]):
            self._load_records()

    def _open_csv(self):
        if not self.score_manager.open_csv():
            QMessageBox.warning(self, "エラー", "CSVファイルを開けませんでした。")

    def _reload(self):
        self.score_manager.load_from_db()
        self._load_records()
