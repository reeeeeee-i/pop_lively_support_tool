"""スコア履歴ダイアログ"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from src.classes import PopnScoreRecord
from src.score_manager import ScoreManager


class ScoreHistoryDialog(QDialog):
    """スコア履歴一覧ダイアログ"""

    def __init__(self, score_manager: ScoreManager, parent=None):
        super().__init__(parent)
        self.score_manager = score_manager

        self.setWindowTitle("スコア履歴 / CSV出力")
        self.setMinimumSize(950, 500)

        self._init_ui()
        self._load_records()

    def _init_ui(self):
        layout = QVBoxLayout(self)

        # 概要情報
        top_hbox = QHBoxLayout()
        self._lbl_count = QLabel("記録件数: 0 件")
        self._lbl_count.setStyleSheet("font-weight: bold;")
        top_hbox.addWidget(self._lbl_count)
        top_hbox.addStretch()

        btn_export_csv = QPushButton("CSVエクスポート...")
        btn_export_csv.clicked.connect(self._export_csv)
        top_hbox.addWidget(btn_export_csv)

        btn_open_csv = QPushButton("CSVファイルを外部アプリで開く")
        btn_open_csv.clicked.connect(self._open_csv)
        top_hbox.addWidget(btn_open_csv)

        btn_reload = QPushButton("再読み込み")
        btn_reload.clicked.connect(self._reload)
        top_hbox.addWidget(btn_reload)
        layout.addLayout(top_hbox)

        # テーブル
        self._table = QTableWidget()
        self._table.setColumnCount(11)
        self._table.setHorizontalHeaderLabels([
            "レベル",
            "曲名",
            "難易度",
            "SCORE",
            "COOL",
            "GREAT",
            "GOOD",
            "BAD",
            "COMBO",
            "使用オプション",
            "プレー日時",
        ])
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        hdr = self._table.horizontalHeader()
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)  # 曲名
        hdr.setSectionResizeMode(9, QHeaderView.ResizeMode.Stretch)  # 使用オプション
        for i in [0, 2, 3, 4, 5, 6, 7, 8, 10]:
            hdr.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self._table)

        # 下部ボタン
        bottom_hbox = QHBoxLayout()
        bottom_hbox.addStretch()
        btn_close = QPushButton("閉じる")
        btn_close.clicked.connect(self.accept)
        bottom_hbox.addWidget(btn_close)
        layout.addLayout(bottom_hbox)

    def _load_records(self):
        records = self.score_manager.records
        self._table.setRowCount(len(records))
        self._lbl_count.setText(
            f"記録件数: {len(records)} 件 (DB: {self.score_manager.db_path} / CSV: {self.score_manager.csv_path})"
        )

        # 新しい順に表示
        for row_idx, r in enumerate(reversed(records)):
            self._table.setItem(row_idx, 0, QTableWidgetItem(str(r.level) if r.level else ""))
            self._table.setItem(row_idx, 1, QTableWidgetItem(r.title))
            self._table.setItem(row_idx, 2, QTableWidgetItem(r.difficulty_code))
            self._table.setItem(row_idx, 3, QTableWidgetItem(str(r.score)))
            self._table.setItem(row_idx, 4, QTableWidgetItem(str(r.cool)))
            self._table.setItem(row_idx, 5, QTableWidgetItem(str(r.great)))
            self._table.setItem(row_idx, 6, QTableWidgetItem(str(r.good)))
            self._table.setItem(row_idx, 7, QTableWidgetItem(str(r.bad)))
            self._table.setItem(row_idx, 8, QTableWidgetItem(str(r.combo)))
            self._table.setItem(row_idx, 9, QTableWidgetItem(r.options.to_summary()))
            self._table.setItem(row_idx, 10, QTableWidgetItem(r.timestamp))

    def _export_csv(self):
        path, _ = QFileDialog.getSaveFileName(
            self,
            "CSVエクスポート先の選択",
            self.score_manager.csv_path,
            "CSV Files (*.csv);;All Files (*)",
        )
        if not path:
            return
        try:
            self.score_manager.export_csv(path)
            QMessageBox.information(self, "完了", f"CSVファイルを出力しました:\n{path}")
        except Exception as e:
            QMessageBox.critical(self, "エラー", f"CSV出力に失敗しました:\n{e}")

    def _open_csv(self):
        if not self.score_manager.open_csv():
            QMessageBox.warning(self, "エラー", "CSVファイルを開けませんでした。")

    def _reload(self):
        self.score_manager.load_from_db()
        self._load_records()
