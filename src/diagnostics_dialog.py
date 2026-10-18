"""認識診断ダイアログ: 保存された診断データを見て、正解値を確定する"""
from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from src.diagnostics import KIND_JUDGE, KIND_LABELS, KIND_RESULT, KIND_TITLE, DiagnosticStore
from src.score_dialog import MusicSelectDialog
from src.score_manager import ScoreManager

# 種類ごとの、正解値を入力する項目 (キー, 表示名)
_JUDGE_FIELDS = (("cool", "COOL"), ("great", "GREAT"), ("good", "GOOD"), ("bad", "BAD"))
_RESULT_FIELDS = (("score", "SCORE"), *_JUDGE_FIELDS, ("combo", "COMBO"))
_FIELDS = {KIND_JUDGE: _JUDGE_FIELDS, KIND_RESULT: _RESULT_FIELDS}


class DiagnosticsDialog(QDialog):
    """保存された認識診断データの一覧と、正解値の入力"""

    def __init__(self, store: DiagnosticStore, score_manager: ScoreManager, parent=None):
        super().__init__(parent)
        self.store = store
        self.score_manager = score_manager
        self._entries: list[dict] = []
        self._current: dict | None = None
        self._spins: dict[str, QSpinBox] = {}
        self._music: dict | None = None

        self.setWindowTitle("認識診断")
        self.setMinimumSize(1000, 600)
        layout = QVBoxLayout(self)

        help_label = QLabel(
            "診断モードで保存した、読み取りに失敗・不一致だった画面です。画像を見て正解値を入力し「正解を確定」を押すと、"
            "tools の build_*_templates.py のサンプルとして使えます。曲名は、確定すると読み替えとして学習します。"
        )
        help_label.setWordWrap(True)
        layout.addWidget(help_label)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(splitter, 1)

        self._list = QListWidget()
        self._list.currentRowChanged.connect(self._on_selected)
        splitter.addWidget(self._list)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        self._preview = QLabel("左の一覧からデータを選んでください。")
        self._preview.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setWidget(self._preview)
        right_layout.addWidget(area, 1)
        self._lbl_info = QLabel()
        self._lbl_info.setWordWrap(True)
        right_layout.addWidget(self._lbl_info)
        self._form = QFormLayout()
        right_layout.addLayout(self._form)

        buttons = QHBoxLayout()
        self._btn_music = QPushButton("曲を選択...")
        self._btn_music.clicked.connect(self._choose_music)
        self._btn_confirm = QPushButton("正解を確定")
        self._btn_confirm.clicked.connect(self._confirm)
        self._btn_unconfirm = QPushButton("確定を取り消す")
        self._btn_unconfirm.clicked.connect(self._unconfirm)
        self._btn_delete = QPushButton("削除")
        self._btn_delete.clicked.connect(self._delete)
        for widget in (self._btn_music, self._btn_confirm, self._btn_unconfirm, self._btn_delete):
            buttons.addWidget(widget)
        buttons.addStretch()
        right_layout.addLayout(buttons)
        splitter.addWidget(right)
        splitter.setSizes([320, 680])

        bottom = QHBoxLayout()
        btn_folder = QPushButton("診断データのフォルダを開く")
        btn_folder.clicked.connect(self._open_folder)
        bottom.addWidget(btn_folder)
        bottom.addStretch()
        btn_close = QPushButton("閉じる")
        btn_close.clicked.connect(self.accept)
        bottom.addWidget(btn_close)
        layout.addLayout(bottom)

        self._reload()

    # ------------------------------------------------------------------

    def _reload(self, select_id: str | None = None):
        self._entries = list(reversed(self.store.entries()))   # 新しい順
        self._list.blockSignals(True)
        self._list.clear()
        for e in self._entries:
            mark = "確定" if e.get("truth") is not None else "未確定"
            item = QListWidgetItem(f"[{mark}] {e['created']}  {KIND_LABELS.get(e['kind'], e['kind'])}")
            item.setToolTip(e.get("note", ""))
            self._list.addItem(item)
        self._list.blockSignals(False)
        row = next((i for i, e in enumerate(self._entries) if e["id"] == select_id), 0 if self._entries else -1)
        self._list.setCurrentRow(row)
        self._on_selected(row)

    def _clear_form(self):
        while self._form.rowCount():
            self._form.removeRow(0)
        self._spins = {}

    def _on_selected(self, row: int):
        self._clear_form()
        self._music = None
        if not 0 <= row < len(self._entries):
            self._current = None
            self._preview.setText("診断データはありません。")
            self._preview.setPixmap(QPixmap())
            self._lbl_info.setText("")
            for button in (self._btn_music, self._btn_confirm, self._btn_unconfirm, self._btn_delete):
                button.setEnabled(False)
            return
        entry = self._current = self._entries[row]
        pixmap = QPixmap(self.store.image_path(entry))
        if pixmap.isNull():
            self._preview.setText("画像を読み込めませんでした。")
        else:
            self._preview.setPixmap(pixmap.scaledToWidth(640, Qt.TransformationMode.SmoothTransformation))
        self._lbl_info.setText(self._describe(entry))

        kind = entry["kind"]
        truth = entry.get("truth") or {}
        initial = {**(entry.get("read") or {}), **(entry.get("suggested") or {}), **truth}
        for key, label in _FIELDS.get(kind, ()):
            spin = QSpinBox()
            spin.setRange(0, 999999)
            spin.setValue(int(initial.get(key) or 0))
            self._spins[key] = spin
            self._form.addRow(label, spin)
        if kind == KIND_TITLE:
            self._music = truth if truth.get("music_id") else None
            self._form.addRow("正解の曲", QLabel(truth.get("title", "(未選択)")))

        self._btn_music.setVisible(kind == KIND_TITLE)
        self._btn_music.setEnabled(True)
        self._btn_confirm.setEnabled(True)
        self._btn_unconfirm.setEnabled(entry.get("truth") is not None)
        self._btn_delete.setEnabled(True)

    @staticmethod
    def _describe(entry: dict) -> str:
        read = entry.get("read") or {}
        parts = [entry.get("note", "")]
        if entry["kind"] == KIND_TITLE:
            parts.append(f"OCR で読んだ曲名: 「{read.get('text', '')}」 / 難易度区分: {read.get('difficulty', '')}")
        else:
            shown = ", ".join(f"{k}={v}" for k, v in read.items() if v is not None and k != "notes")
            parts.append(f"読み取った値: {shown}")
            if entry.get("suggested"):
                parts.append("入力欄の初期値は、リザルト画面の値 (正解の見当) です。画像と見比べて確認してください。")
        return "\n".join(p for p in parts if p)

    # ------------------------------------------------------------------

    def _choose_music(self):
        dlg = MusicSelectDialog(self.score_manager, "", self)
        if dlg.exec() and dlg.selected:
            self._music = dlg.selected
            label = self._form.itemAt(self._form.rowCount() - 1, QFormLayout.ItemRole.FieldRole).widget()
            label.setText(dlg.selected["title"])

    def _confirm(self):
        if self._current is None:
            return
        entry = self._current
        if entry["kind"] == KIND_TITLE:
            if not self._music:
                QMessageBox.information(self, "認識診断", "「曲を選択...」で正解の曲を選んでください。")
                return
            truth = {"music_id": self._music["music_id"], "title": self._music["title"]}
            text = (entry.get("read") or {}).get("text", "")
            if text:
                self.score_manager.db.add_alias(text, truth["music_id"])
        else:
            truth = {key: spin.value() for key, spin in self._spins.items()}
        self.store.set_truth(entry["id"], truth)
        self._reload(entry["id"])

    def _unconfirm(self):
        if self._current is not None:
            self.store.set_truth(self._current["id"], None)
            self._reload(self._current["id"])

    def _delete(self):
        if self._current is None:
            return
        answer = QMessageBox.question(
            self, "認識診断", "この診断データ (画像を含む) を削除します。よろしいですか?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.store.delete(self._current["id"])
            self._reload()

    def _open_folder(self):
        folder = os.path.abspath(self.store.folder)
        os.makedirs(folder, exist_ok=True)
        os.startfile(folder)
