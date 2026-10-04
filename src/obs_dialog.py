"""OBS 制御設定ダイアログ (pop_lively_support_tool版)
既存の inf_daken_counter_obsw の obs_dialog.py をベースに移植・簡略化。
"""
from __future__ import annotations

import traceback

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from src.config import Config
from src.logger import get_logger

logger = get_logger(__name__)


# pop'n に存在するトリガー定義
_TIMINGS = [
    ("title_start",             "タイトル画面表示"),
    ("title_end",               "タイトル画面終了"),
    ("ticket_start",            "チケット画面表示"),
    ("ticket_end",              "チケット画面終了"),
    ("character_select_start",  "キャラセレクト表示"),
    ("character_select_end",    "キャラセレクト終了"),
    ("select_start",            "選曲画面表示"),
    ("select_end",              "選曲画面終了"),
    ("option_start",            "オプション画面表示"),
    ("option_end",              "オプション画面終了"),
    ("play_start",              "プレー開始"),
    ("play_end",                "プレー終了"),
    ("result_start",            "リザルト表示"),
    ("result_end",              "リザルト終了"),
    ("exit_start",              "終了画面表示"),
    ("exit_end",                "終了画面終了"),
]

# 利用可能なアクション定義
_ACTIONS = [
    ("switch_scene",    "シーン切り替え"),
    ("start_recording", "録画開始"),
    ("stop_recording",  "録画停止"),
    ("start_streaming", "配信開始"),
    ("stop_streaming",  "配信停止"),
    ("show_source",     "ソース表示"),
    ("hide_source",     "ソース非表示"),
]

# アクション行の背景色
_ACTION_COLORS = {
    "switch_scene":    QColor("#e3f2fd"),   # 薄青
    "start_recording": QColor("#e8f5e9"),   # 薄緑
    "stop_recording":  QColor("#ffebee"),   # 薄赤
    "start_streaming": QColor("#e8f5e9"),
    "stop_streaming":  QColor("#ffebee"),
    "show_source":     QColor("#e8f5e9"),
    "hide_source":     QColor("#ffebee"),
}

# ソースが必要なアクション
_ACTIONS_NEED_SOURCE = {"show_source", "hide_source"}
# シーン切り替え専用
_ACTIONS_SWITCH_ONLY = {"switch_scene"}
# ソース不要のアクション
_ACTIONS_NO_SCENE = {"start_recording", "stop_recording", "start_streaming", "stop_streaming"}


class OBSControlDialog(QDialog):
    """OBS 制御設定ダイアログ"""

    def __init__(self, config: Config, obs_manager, parent=None):
        super().__init__(parent)
        self.config      = config
        self.obs_manager = obs_manager

        self.setWindowTitle("OBS 制御設定")
        self.setMinimumSize(860, 680)

        self._init_ui()
        self._load_settings()
        if not self.obs_manager.is_connected:
            self.obs_manager.connect(force=True)
        self._update_scene_list()

    # ------------------------------------------------------------------
    # UI 構築
    # ------------------------------------------------------------------

    def _init_ui(self):
        root = QVBoxLayout(self)

        # ── OBS 接続設定 ──────────────────────────────────────────────
        conn_group = QGroupBox("OBS WebSocket 接続設定")
        conn_form  = QFormLayout(conn_group)

        self._edit_host = QLineEdit()
        self._spin_port = QSpinBox()
        self._spin_port.setRange(1, 65535)
        self._edit_pass = QLineEdit()
        self._edit_pass.setEchoMode(QLineEdit.EchoMode.Password)

        conn_form.addRow(QLabel("ホスト:"),    self._edit_host)
        conn_form.addRow(QLabel("ポート:"),    self._spin_port)
        conn_form.addRow(QLabel("パスワード:"), self._edit_pass)

        root.addWidget(conn_group)

        # ── シーンコレクション ──────────────────────────────────────────
        sc_group  = QGroupBox("起動時シーンコレクション")
        sc_form   = QFormLayout(sc_group)
        self._combo_scene_col = QComboBox()
        self._combo_scene_col.currentIndexChanged.connect(self._on_scene_collection_changed)
        sc_form.addRow(QLabel("コレクション名 (空=変更なし):"), self._combo_scene_col)
        root.addWidget(sc_group)

        # ── 監視対象ソース (OBS経由キャプチャ時) ─────────────────────────
        src_group  = QGroupBox("OBS WebSocket 経由キャプチャ用ソース")
        src_hbox   = QHBoxLayout(src_group)
        self._lbl_monitor = QLabel("(未設定)")
        self._lbl_monitor.setStyleSheet("font-weight: bold; color: #1565c0;")
        btn_clear_mon = QPushButton("クリア")
        btn_clear_mon.clicked.connect(self._clear_monitor_source)
        src_hbox.addWidget(QLabel("現在のソース:"))
        src_hbox.addWidget(self._lbl_monitor, 1)
        src_hbox.addWidget(btn_clear_mon)
        root.addWidget(src_group)

        # ── 新規ルール追加 ─────────────────────────────────────────────
        add_group = QGroupBox("制御ルールの追加")
        add_form  = QFormLayout(add_group)

        self._combo_action = QComboBox()
        for action_id, action_name in _ACTIONS:
            self._combo_action.addItem(action_name, action_id)
        self._combo_action.currentIndexChanged.connect(self._on_action_changed)
        add_form.addRow(QLabel("アクション:"), self._combo_action)

        self._combo_timing = QComboBox()
        self._combo_timing.addItem("", None)
        for timing_id, timing_name in _TIMINGS:
            self._combo_timing.addItem(timing_name, timing_id)
        add_form.addRow(QLabel("タイミング:"), self._combo_timing)

        self._combo_target_scene = QComboBox()
        self._combo_target_scene.currentIndexChanged.connect(self._on_target_scene_changed)
        self._lbl_target_scene = QLabel("シーン:")
        add_form.addRow(self._lbl_target_scene, self._combo_target_scene)

        self._combo_source = QComboBox()
        self._lbl_source = QLabel("ソース:")
        add_form.addRow(self._lbl_source, self._combo_source)

        # 「ゲームキャプチャソースとして設定」ボタン（OBS経由取得用）
        self._btn_set_monitor = QPushButton("↑ このソースをゲームキャプチャソースとして設定")
        self._btn_set_monitor.clicked.connect(self._set_as_monitor_source)
        add_form.addRow("", self._btn_set_monitor)

        self._combo_switch_scene = QComboBox()
        self._lbl_switch_scene = QLabel("切り替え先シーン:")
        add_form.addRow(self._lbl_switch_scene, self._combo_switch_scene)

        btn_add_hbox = QHBoxLayout()
        btn_add_hbox.addStretch()
        btn_add = QPushButton("追加")
        btn_add.clicked.connect(self._add_setting)
        btn_add_hbox.addWidget(btn_add)
        add_form.addRow("", btn_add_hbox)

        root.addWidget(add_group)

        # ── 登録済みルール一覧 ─────────────────────────────────────────
        list_group  = QGroupBox("登録済み制御ルール")
        list_vbox   = QVBoxLayout(list_group)

        self._table = QTableWidget()
        self._table.setColumnCount(4)
        self._table.setHorizontalHeaderLabels(["タイミング", "アクション", "シーン", "ソース"])
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        hdr = self._table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self._table.setColumnWidth(0, 170)
        self._table.setColumnWidth(1, 150)
        list_vbox.addWidget(self._table)

        del_hbox = QHBoxLayout()
        del_hbox.addStretch()
        btn_del_sel = QPushButton("選択行を削除")
        btn_del_sel.clicked.connect(self._delete_selected)
        btn_del_all = QPushButton("すべて削除")
        btn_del_all.clicked.connect(self._delete_all)
        del_hbox.addWidget(btn_del_sel)
        del_hbox.addWidget(btn_del_all)
        list_vbox.addLayout(del_hbox)

        root.addWidget(list_group)

        # ── 下部ボタン ─────────────────────────────────────────────────
        bottom_hbox = QHBoxLayout()
        btn_refresh = QPushButton("シーン一覧を更新")
        btn_refresh.clicked.connect(self._update_scene_list)
        btn_reconnect = QPushButton("OBS に再接続")
        btn_reconnect.clicked.connect(self._reconnect_obs)
        bottom_hbox.addWidget(btn_refresh)
        bottom_hbox.addWidget(btn_reconnect)
        bottom_hbox.addStretch()
        btn_ok = QPushButton("OK")
        btn_ok.clicked.connect(self._accept)
        btn_cancel = QPushButton("キャンセル")
        btn_cancel.clicked.connect(self.reject)
        bottom_hbox.addWidget(btn_ok)
        bottom_hbox.addWidget(btn_cancel)
        root.addLayout(bottom_hbox)

        # 初期有効・無効状態
        self._on_action_changed()

    # ------------------------------------------------------------------
    # 設定読み込み
    # ------------------------------------------------------------------

    def _load_settings(self):
        """config から値を読み込んで各ウィジェットに反映"""
        self._edit_host.setText(self.config.websocket_host)
        self._spin_port.setValue(self.config.websocket_port)
        self._edit_pass.setText(self.config.websocket_password)

        # シーンコレクション（OBS 未接続でも保存値は表示する）
        self._combo_scene_col.blockSignals(True)
        self._combo_scene_col.clear()
        self._combo_scene_col.addItem("(変更しない)", None)
        saved = self.config.obs_scene_collection
        if saved:
            self._combo_scene_col.addItem(saved, saved)
            self._combo_scene_col.setCurrentIndex(1)
        self._combo_scene_col.blockSignals(False)

        # 監視対象ソース
        mon = self.config.monitor_source_name
        self._lbl_monitor.setText(mon if mon else "(未設定)")

        # 制御ルール一覧
        timing_dict = {tid: tn for tid, tn in _TIMINGS}
        action_dict = {aid: an for aid, an in _ACTIONS}

        for setting in self.config.obs_control_settings:
            action_id = setting.get("action", "")
            timing_id = setting.get("trigger") or setting.get("timing", "")
            scene     = setting.get("scene", "")
            source    = setting.get("source", "")
            timing_name = timing_dict.get(timing_id, timing_id)
            action_name = action_dict.get(action_id, action_id)
            self._add_table_row(timing_name, action_name, scene, source, setting)

    # ------------------------------------------------------------------
    # OBS シーン取得
    # ------------------------------------------------------------------

    def _update_scene_list(self):
        """OBS からシーン・シーンコレクション一覧を取得してコンボボックスを更新"""
        if not self.obs_manager.is_connected:
            self.obs_manager.connect(force=True)
        if not self.obs_manager.is_connected:
            return

        try:
            scenes_data = self.obs_manager.get_scene_list()
            if scenes_data is None:
                return

            self._combo_target_scene.clear()
            self._combo_switch_scene.clear()
            for scene_dict in scenes_data:
                name = scene_dict.get("sceneName", "")
                if name:
                    self._combo_target_scene.addItem(name)
                    self._combo_switch_scene.addItem(name)

            logger.info("シーンリスト更新: %d 件", len(scenes_data))
        except Exception:
            logger.error(traceback.format_exc())

        self._update_scene_collection_list()

    def _update_scene_collection_list(self):
        """OBS からシーンコレクション一覧を取得"""
        if not self.obs_manager.is_connected:
            return
        try:
            collections = self.obs_manager.get_scene_collection_list()
            if not collections:
                return

            self._combo_scene_col.blockSignals(True)
            current_data = self._combo_scene_col.currentData()
            self._combo_scene_col.clear()
            self._combo_scene_col.addItem("(変更しない)", None)
            for name in collections:
                self._combo_scene_col.addItem(name, name)

            # 現在選択中の値を復元
            saved = current_data or self.config.obs_scene_collection
            if saved:
                idx = self._combo_scene_col.findData(saved)
                self._combo_scene_col.setCurrentIndex(idx if idx >= 0 else 0)

            self._combo_scene_col.blockSignals(False)
            logger.info("シーンコレクションリスト更新: %d 件", len(collections))
        except Exception:
            logger.error(traceback.format_exc())

    def _on_scene_collection_changed(self):
        """コンボ変更時に OBS 側も切り替える"""
        name = self._combo_scene_col.currentData()
        if not name or not self.obs_manager.is_connected:
            return
        try:
            self.obs_manager.get_scene_collection_list  # 接続チェック
            self.obs_manager.client.set_current_scene_collection(name)
            # シーン一覧も更新
            self._update_scene_list()
        except Exception as e:
            logger.error("シーンコレクション切り替えエラー: %s", e)
            QMessageBox.warning(self, "エラー", f"シーンコレクションの切り替えに失敗しました:\n{e}")

    def _on_target_scene_changed(self):
        """対象シーン変更時にソース一覧を更新"""
        scene_name = self._combo_target_scene.currentText()
        if not scene_name or not self.obs_manager.is_connected:
            return
        try:
            sources = self.obs_manager.get_source_list(scene_name)
            if sources is None:
                return
            self._combo_source.clear()
            for src in sources:
                self._combo_source.addItem(src)
        except Exception:
            logger.error(traceback.format_exc())

    # ------------------------------------------------------------------
    # フォーム有効・無効切り替え
    # ------------------------------------------------------------------

    def _on_action_changed(self):
        action_id = self._combo_action.currentData()

        needs_source  = action_id in _ACTIONS_NEED_SOURCE
        needs_switch  = action_id in _ACTIONS_SWITCH_ONLY
        no_scene      = action_id in _ACTIONS_NO_SCENE

        self._combo_target_scene.setEnabled(not no_scene and not needs_switch)
        self._lbl_target_scene.setEnabled(not no_scene and not needs_switch)
        self._combo_source.setEnabled(needs_source)
        self._lbl_source.setEnabled(needs_source)
        self._btn_set_monitor.setEnabled(needs_source)
        self._combo_switch_scene.setEnabled(needs_switch)
        self._lbl_switch_scene.setEnabled(needs_switch)

    # ------------------------------------------------------------------
    # ルール追加
    # ------------------------------------------------------------------

    def _add_setting(self):
        action_id   = self._combo_action.currentData()
        timing_id   = self._combo_timing.currentData()
        action_name = self._combo_action.currentText()
        timing_name = self._combo_timing.currentText()

        if not action_id:
            QMessageBox.warning(self, "エラー", "アクションを選択してください。")
            return
        if not timing_id:
            QMessageBox.warning(self, "エラー", "タイミングを選択してください。")
            return

        setting: dict = {"trigger": timing_id, "action": action_id}
        scene_text = source_text = ""

        if action_id in _ACTIONS_NEED_SOURCE:
            scene  = self._combo_target_scene.currentText()
            source = self._combo_source.currentText()
            if not scene or not source:
                QMessageBox.warning(self, "エラー", "シーンとソースを選択してください。")
                return
            setting["scene"]  = scene
            setting["source"] = source
            scene_text  = scene
            source_text = source

        elif action_id in _ACTIONS_SWITCH_ONLY:
            scene = self._combo_switch_scene.currentText()
            if not scene:
                QMessageBox.warning(self, "エラー", "切り替え先シーンを選択してください。")
                return
            setting["scene"] = scene
            scene_text = scene

        self.config.obs_control_settings.append(setting)
        self._add_table_row(timing_name, action_name, scene_text, source_text, setting)
        logger.info("OBS 制御ルール追加: %s", setting)

        # タイミングだけリセット
        self._combo_timing.setCurrentIndex(0)

    def _add_table_row(self, timing: str, action: str, scene: str, source: str, setting: dict):
        row = self._table.rowCount()
        self._table.insertRow(row)

        items = [
            QTableWidgetItem(timing),
            QTableWidgetItem(action),
            QTableWidgetItem(scene),
            QTableWidgetItem(source),
        ]
        color = _ACTION_COLORS.get(setting.get("action", ""))
        for col, item in enumerate(items):
            if color:
                item.setBackground(color)
            self._table.setItem(row, col, item)

        # 設定データをセルに保持
        items[0].setData(Qt.ItemDataRole.UserRole, setting)

    # ------------------------------------------------------------------
    # ルール削除
    # ------------------------------------------------------------------

    def _delete_selected(self):
        rows = sorted(
            {item.row() for item in self._table.selectedItems()},
            reverse=True,
        )
        if not rows:
            QMessageBox.information(self, "情報", "削除する行を選択してください。")
            return
        for row in rows:
            item = self._table.item(row, 0)
            if item:
                setting = item.data(Qt.ItemDataRole.UserRole)
                if setting and setting in self.config.obs_control_settings:
                    self.config.obs_control_settings.remove(setting)
            self._table.removeRow(row)

    def _delete_all(self):
        reply = QMessageBox.question(
            self, "確認", "すべての制御ルールを削除しますか?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.config.obs_control_settings.clear()
            self._table.setRowCount(0)

    # ------------------------------------------------------------------
    # 監視ソース設定
    # ------------------------------------------------------------------

    def _set_as_monitor_source(self):
        """選択中のソースをゲームキャプチャ用ソースとして設定"""
        source = self._combo_source.currentText()
        if not source:
            QMessageBox.warning(self, "エラー", "ソースを選択してください。")
            return
        self.config.monitor_source_name = source
        self._lbl_monitor.setText(source)
        QMessageBox.information(
            self, "設定完了",
            f"OBS 経由キャプチャのソースを「{source}」に設定しました。"
        )

    def _clear_monitor_source(self):
        reply = QMessageBox.question(
            self, "確認", "ゲームキャプチャソースの設定をクリアしますか?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.config.monitor_source_name = ""
            self._lbl_monitor.setText("(未設定)")

    # ------------------------------------------------------------------
    # 再接続
    # ------------------------------------------------------------------

    def _reconnect_obs(self):
        try:
            # 接続情報を先に設定に反映
            self.config.websocket_host     = self._edit_host.text().strip()
            self.config.websocket_port     = self._spin_port.value()
            self.config.websocket_password = self._edit_pass.text()
            self.obs_manager.set_config(self.config)

            self.obs_manager.disconnect_obs()
            ok = self.obs_manager.connect(force=True)
            if ok:
                self._update_scene_list()
                QMessageBox.information(self, "成功", "OBS に接続しました。")
            else:
                QMessageBox.warning(self, "失敗", "OBS に接続できませんでした。\nホスト・ポート・パスワードを確認してください。")
        except Exception as e:
            logger.error(traceback.format_exc())
            QMessageBox.warning(self, "エラー", f"再接続に失敗しました:\n{e}")

    # ------------------------------------------------------------------
    # OK
    # ------------------------------------------------------------------

    def _accept(self):
        self.config.websocket_host         = self._edit_host.text().strip()
        self.config.websocket_port         = self._spin_port.value()
        self.config.websocket_password     = self._edit_pass.text()
        selected_col = self._combo_scene_col.currentData()
        self.config.obs_scene_collection   = selected_col if selected_col else ""
        self.config.save_config()
        logger.info("OBS 制御設定を保存しました")
        self.accept()
