"""pop'n music Lively 打鍵カウンタ メインエントリポイント"""
from __future__ import annotations

import sys
import time
import traceback
from datetime import datetime

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QAction, QFont
from PySide6.QtWidgets import (
    QApplication,
    QGroupBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenuBar,
    QPushButton,
    QSizePolicy,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from src.config import Config
from src.classes import DetectMode, PopnJudge, PopnOptions, PopnScoreRecord
from src.screen_reader import ScreenReader
from src.obs_websocket_manager import OBSWebSocketManager
from src.score_manager import ScoreManager
from src.funcs import load_ui_text
from src.logger import get_logger

logger = get_logger(__name__)

_LOOP_INTERVAL_MS = 100   # メインループ間隔 (ms)

# 曲名読み取り: このフレーム数ごとに 1 回読む (OCR は 1 回数十 ms かかるため毎フレームは行わない)
_TITLE_SCAN_INTERVAL_FRAMES = 5
# 曲名読み取り: この回数読んでも曲を特定できなければ諦める
_TITLE_SCAN_MAX_TRIES = 20

# リザルト読み取り: 同じ値がこのフレーム数続いたら確定する（表示演出の途中を掴まないため）
_RESULT_STABLE_FRAMES = 3
# リザルト読み取り: このフレーム数待っても安定しなければ、その時点の値で記録する
_RESULT_TIMEOUT_FRAMES = 50


class MainWindow(QMainWindow):
    """pop'n music Lively 打鍵カウンタ メインウィンドウ"""

    def __init__(self):
        super().__init__()

        self.config  = Config()
        self.ui      = load_ui_text(self.config)
        self.screen_reader = ScreenReader()
        self.obs_manager   = OBSWebSocketManager()
        self.score_manager = ScoreManager(
            db_path=self.config.score_db_path,
            csv_path=self.config.score_csv_path,
        )

        # 打鍵カウント（現在の曲の判定内訳）
        self.song_cool  = 0
        self.song_great = 0
        self.song_good  = 0
        self.song_bad   = 0

        # 本日の打鍵数・日付管理
        self._today_date  = datetime.now().strftime("%Y-%m-%d")
        self._today_notes = self.score_manager.get_today_notes(self._today_date)

        # 起動時刻
        self._start_time = time.time()

        # 最後にプレイした曲
        self._last_played_song = self.score_manager.get_last_played_song() or self.ui.main_display.none_song

        # 画面状態
        self.current_mode = DetectMode.unknown
        self._title_scanned = False
        self._title_frames = 0

        # リザルト読み取り待ち状態
        self._result_pending = False
        self._result_frames = 0
        self._result_stable = 0
        self._result_values = None   # 直近に全項目を読めた値
        self._result_image = None    # 直近のリザルト画面フレーム

        self._setup_ui()
        self._setup_obs()

        # メインループ
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._main_loop)
        self._timer.start(_LOOP_INTERVAL_MS)

        # ウィンドウ位置・サイズ復元
        self.setGeometry(
            self.config.main_window_x,
            self.config.main_window_y,
            self.config.main_window_width,
            self.config.main_window_height,
        )
        if self.config.keep_on_top:
            self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)

    # ------------------------------------------------------------------
    # UI 構築
    # ------------------------------------------------------------------

    def _setup_ui(self):
        self.setWindowTitle(self.ui.window.main_title)
        self.setMinimumWidth(400)

        # メニューバー
        menubar: QMenuBar = self.menuBar()
        file_menu = menubar.addMenu(self.ui.menu.file)

        act_settings = QAction(self.ui.menu.settings, self)
        act_settings.triggered.connect(self._open_settings)
        file_menu.addAction(act_settings)

        act_obs = QAction(self.ui.menu.obs_settings, self)
        act_obs.triggered.connect(self._open_obs_settings)
        file_menu.addAction(act_obs)

        file_menu.addSeparator()

        act_reset = QAction(self.ui.menu.reset_count, self)
        act_reset.triggered.connect(self._reset_counts)
        file_menu.addAction(act_reset)

        file_menu.addSeparator()

        act_exit = QAction(self.ui.menu.exit, self)
        act_exit.triggered.connect(self.close)
        file_menu.addAction(act_exit)

        # スコアメニュー
        score_menu = menubar.addMenu(self.ui.menu.score)

        act_history = QAction(self.ui.menu.score_history, self)
        act_history.triggered.connect(self._open_score_history)
        score_menu.addAction(act_history)

        act_export_csv = QAction(self.ui.menu.export_csv, self)
        act_export_csv.triggered.connect(self._export_csv)
        score_menu.addAction(act_export_csv)

        act_open_csv = QAction(self.ui.menu.open_csv, self)
        act_open_csv.triggered.connect(self.score_manager.open_csv)
        score_menu.addAction(act_open_csv)

        # 中央ウィジェット
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setSpacing(10)

        # 情報表示グループ
        info_group = QGroupBox(self.ui.main_display.group)
        info_form  = QFormLayout(info_group)
        info_form.setSpacing(10)
        info_form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)

        font_lbl = QFont()
        font_lbl.setPointSize(11)
        font_lbl.setBold(True)

        font_val = QFont()
        font_val.setPointSize(13)
        font_val.setBold(True)

        font_notes = QFont()
        font_notes.setPointSize(22)
        font_notes.setBold(True)

        font_time = QFont()
        font_time.setPointSize(16)
        font_time.setBold(True)

        def make_row_label(text: str) -> QLabel:
            lbl = QLabel(text)
            lbl.setFont(font_lbl)
            lbl.setStyleSheet("color: #aaaaaa;")
            return lbl

        self.lbl_mode = QLabel(self.ui.status.waiting_game)
        self.lbl_mode.setFont(font_val)
        self.lbl_mode.setStyleSheet("color: #aaaaaa; font-weight: bold;")

        self.lbl_uptime = QLabel("00:00:00")
        self.lbl_uptime.setFont(font_time)
        self.lbl_uptime.setStyleSheet("color: #80d8ff; font-weight: bold;")

        self.lbl_today_notes = QLabel(f"{self._today_notes:,}")
        self.lbl_today_notes.setFont(font_notes)
        self.lbl_today_notes.setStyleSheet("color: #ffb74d; font-weight: bold;")

        self.lbl_last_song = QLabel(self._last_played_song)
        self.lbl_last_song.setFont(font_val)
        self.lbl_last_song.setStyleSheet("color: #ffffff; font-weight: bold;")
        self.lbl_last_song.setWordWrap(True)

        info_form.addRow(make_row_label(self.ui.main_display.current_mode), self.lbl_mode)
        info_form.addRow(make_row_label(self.ui.main_display.uptime),       self.lbl_uptime)
        info_form.addRow(make_row_label(self.ui.main_display.today_notes),  self.lbl_today_notes)
        info_form.addRow(make_row_label(self.ui.main_display.last_song),    self.lbl_last_song)

        layout.addWidget(info_group)

        # リセットボタン
        self.btn_reset = QPushButton(self.ui.main_display.reset_notes)
        self.btn_reset.clicked.connect(self._reset_counts)
        layout.addWidget(self.btn_reset)

        layout.addStretch()

        # ステータスバー
        self._statusbar = QStatusBar()
        self.setStatusBar(self._statusbar)

        self._lbl_game = QLabel(self.ui.status.waiting_game)
        self._lbl_obs  = QLabel(self.ui.status.obs_disconnected)
        self._lbl_mode = QLabel("")

        self._statusbar.addWidget(self._lbl_game, 1)
        self._statusbar.addPermanentWidget(self._lbl_mode)
        self._statusbar.addPermanentWidget(self._lbl_obs)

    # ------------------------------------------------------------------
    # セットアップ
    # ------------------------------------------------------------------

    def _setup_obs(self):
        self.obs_manager.set_config(self.config)
        self.obs_manager.connection_changed.connect(self._on_obs_connection_changed)
        if self.obs_manager.uses_obs_websocket():
            self.obs_manager.connect()
        else:
            self.obs_manager.disconnect_obs()

    def _on_obs_connection_changed(self, connected: bool, message: str):
        if connected:
            self._lbl_obs.setText(self.ui.status.obs_connected)
            self._lbl_obs.setStyleSheet("color: #188038; font-weight: bold;")
        else:
            self._lbl_obs.setText(self.ui.status.obs_disconnected)
            self._lbl_obs.setStyleSheet("color: #d93025;")
        status_text, _ = self.obs_manager.get_status()
        self._lbl_game.setText(status_text)

    # ------------------------------------------------------------------
    # メインループ
    # ------------------------------------------------------------------

    def _main_loop(self):
        try:
            self._update_uptime()
            self._check_date_rollover()

            image = self.obs_manager.read_frame()

            if image is None:
                status_text, _ = self.obs_manager.get_status()
                self._lbl_game.setText(status_text)
                self.lbl_mode.setText(self.ui.status.waiting_game)
                self.lbl_mode.setStyleSheet("color: #aaaaaa; font-weight: bold;")
                self._lbl_mode.setText("")
                return

            mode = self.screen_reader.detect_mode(image)
            self._handle_mode(mode, image)

        except Exception:
            logger.error(traceback.format_exc())

    def _handle_mode(self, mode: DetectMode, image):
        # モード変化検出
        if mode != self.current_mode:
            self._on_mode_changed(self.current_mode, mode)

        self.current_mode = mode

        # ステータス表示
        mode_labels = {
            DetectMode.play:             self.ui.status.playing,
            DetectMode.result:           self.ui.status.result,
            DetectMode.select:           self.ui.status.select,
            DetectMode.option:           self.ui.status.option,
            DetectMode.title:            self.ui.status.title,
            DetectMode.ticket:           self.ui.status.ticket,
            DetectMode.character_select: self.ui.status.character_select,
            DetectMode.exit:             self.ui.status.exit,
            DetectMode.loading:          self.ui.status.loading,
            DetectMode.unknown:          self.ui.status.waiting_game,
        }
        mode_colors = {
            DetectMode.play:             "#00e676",  # プレー中（緑）
            DetectMode.result:           "#ffd600",  # リザルト（黄）
            DetectMode.select:           "#40c4ff",  # 選曲中（水色）
            DetectMode.option:           "#ff80ab",  # オプション（ピンク）
            DetectMode.title:            "#b388ff",  # タイトル（紫）
            DetectMode.ticket:           "#b388ff",  # チケット（紫）
            DetectMode.character_select: "#b388ff",  # キャラセレクト（紫）
            DetectMode.exit:             "#ff5252",  # 終了画面（赤）
            DetectMode.loading:          "#ffab40",  # ロード中（オレンジ）
            DetectMode.unknown:          "#aaaaaa",  # 待機中（グレー）
        }
        mode_text = mode_labels.get(mode, self.ui.status.waiting_game)
        mode_color = mode_colors.get(mode, "#ffffff")

        self.lbl_mode.setText(mode_text)
        self.lbl_mode.setStyleSheet(f"color: {mode_color}; font-weight: bold;")
        self._lbl_mode.setText(mode_text)

        # ゲーム検出表示
        status_text, _ = self.obs_manager.get_status()
        self._lbl_game.setText(status_text)

        # オプション画面時はオプション状態をスキャン
        if mode == DetectMode.option:
            self.screen_reader.read_options(image)

        # プレー画面の場合は判定を読み取る
        if mode == DetectMode.play:
            self._process_play(image)

        # リザルト画面の場合は数値が安定するまで読み取りを続ける
        if mode == DetectMode.result and self._result_pending:
            self._process_result(image)

    def _on_mode_changed(self, prev: DetectMode, curr: DetectMode):
        logger.info("モード変更: %s → %s", prev.name, curr.name)

        if curr == DetectMode.title:
            self._trigger_obs("title_start")
        if prev == DetectMode.title and curr != DetectMode.title:
            self._trigger_obs("title_end")

        if curr == DetectMode.ticket:
            self._trigger_obs("ticket_start")
        if prev == DetectMode.ticket and curr != DetectMode.ticket:
            self._trigger_obs("ticket_end")

        if curr == DetectMode.character_select:
            self._trigger_obs("character_select_start")
        if prev == DetectMode.character_select and curr != DetectMode.character_select:
            self._trigger_obs("character_select_end")

        if curr == DetectMode.select:
            self._trigger_obs("select_start")
        if prev == DetectMode.select and curr != DetectMode.select:
            self._trigger_obs("select_end")

        if curr == DetectMode.option:
            self._trigger_obs("option_start")
        if prev == DetectMode.option and curr != DetectMode.option:
            self._trigger_obs("option_end")

        if curr == DetectMode.play:
            self._title_scanned = False
            self._title_frames = 0
            self.score_manager.reset_current_song()
            self.screen_reader.reset_judge()
            self.song_cool = self.song_great = self.song_good = self.song_bad = 0
            self._trigger_obs("play_start")
        if prev == DetectMode.play and curr != DetectMode.play:
            self._trigger_obs("play_end")

        if curr == DetectMode.result:
            self._trigger_obs("result_start")
            # スコアの記録は数値が安定してから行う (_process_result)
            self._result_pending = True
            self._result_frames = 0
            self._result_stable = 0
            self._result_values = None
            self._result_image = None

        if prev == DetectMode.result and curr != DetectMode.result:
            # 安定を待っている間にリザルト画面を抜けた場合は、最後に読めた値で記録する
            if self._result_pending and self._result_image is not None:
                self._save_result(self._result_image, self._result_values)
            self._result_pending = False
            self._trigger_obs("result_end")

        if curr == DetectMode.loading:
            self._trigger_obs("loading_start")
        if prev == DetectMode.loading and curr != DetectMode.loading:
            self._trigger_obs("loading_end")

        if curr == DetectMode.exit:
            self._trigger_obs("exit_start")
        if prev == DetectMode.exit and curr != DetectMode.exit:
            self._trigger_obs("exit_end")

    def _process_play(self, image):
        # プレー開始直後に曲名・難易度区分を認識
        if not self._title_scanned:
            self._scan_play_song(image)

        judge: PopnJudge = self.screen_reader.detect_judge(image)
        if judge.notes > 0:
            self._check_date_rollover()
            self._today_notes += judge.notes
            self.song_cool    += judge.cool
            self.song_great   += judge.great
            self.song_good    += judge.good
            self.song_bad     += judge.bad
            self._update_display()

    def _scan_play_song(self, image):
        """プレー画面上部の曲名バーから曲を特定する。特定できるまで一定間隔で読み直す。"""
        self._title_frames += 1
        if (self._title_frames - 1) % _TITLE_SCAN_INTERVAL_FRAMES != 0:
            return

        song = self.screen_reader.read_play_song(image)
        if song.text and self.score_manager.identify_song(song.text, song.difficulty):
            self._title_scanned = True
            title = self.score_manager.current_song_title
            diff = PopnScoreRecord(difficulty=song.difficulty).difficulty_code
            self._last_played_song = f"{title} [{diff}]" if diff else title
            self.lbl_last_song.setText(self._last_played_song)
        elif self._title_frames >= _TITLE_SCAN_INTERVAL_FRAMES * _TITLE_SCAN_MAX_TRIES:
            self._title_scanned = True
            logger.warning("曲を特定できませんでした (読み取り結果: '%s' / %s)", song.text, song.difficulty)
            self.screen_reader.save_unread_title(image)

    def _process_result(self, image):
        """リザルト画面の数値を読み、数フレーム連続で同じ値になったら記録する。"""
        self._result_frames += 1
        values = self.screen_reader.read_result_values(image)

        if values is not None and values.is_complete:
            same = self._result_values is not None and values.key() == self._result_values.key()
            self._result_stable = self._result_stable + 1 if same else 1
            self._result_values = values
            self._result_image = image
            if self._result_stable >= _RESULT_STABLE_FRAMES:
                self._save_result(image, values)
                return
        else:
            self._result_stable = 0
            if self._result_values is None:
                self._result_image = image

        if self._result_frames >= _RESULT_TIMEOUT_FRAMES:
            if self._result_values is not None:
                self._save_result(self._result_image, self._result_values)
            else:
                self._save_result(image, values)

    def _save_result(self, image, values):
        """リザルト画面の読み取り結果をスコア履歴に記録する。"""
        self._result_pending = False
        try:
            current_judge = PopnJudge(
                cool=self.song_cool,
                great=self.song_great,
                good=self.song_good,
                bad=self.song_bad,
            )
            record = self.screen_reader.read_result(
                image,
                live_judge=current_judge,
                options=self.score_manager.current_options,
                title=self.score_manager.current_song_title,
                level=self.score_manager.current_level,
                difficulty=self.score_manager.current_difficulty,
                values=values,
            )
            saved = self.score_manager.add_record(record)
            if saved:
                chart_info = f"[Lv{record.level} {record.difficulty_code}] " if record.level else f"[{record.difficulty_code}] "
                msg = f"スコア保存: {chart_info}{record.title} | {record.score}点 ({record.options.to_summary()})"
                self._statusbar.showMessage(msg, 6000)

            # 最後にプレイした曲の表示を更新
            song_title = record.title if record.title != "Unknown" else self.score_manager.current_song_title
            if song_title and song_title != "Unknown":
                diff_str = f" [{record.difficulty_code}]" if record.difficulty_code else ""
                self._last_played_song = f"{song_title}{diff_str}"
                self.lbl_last_song.setText(self._last_played_song)
        except Exception as e:
            logger.error("スコア保存処理エラー: %s", e)

    def _update_display(self):
        self.lbl_today_notes.setText(f"{self._today_notes:,}")

    def _update_uptime(self):
        elapsed = int(time.time() - self._start_time)
        hours = elapsed // 3600
        minutes = (elapsed % 3600) // 60
        seconds = elapsed % 60
        self.lbl_uptime.setText(f"{hours:02d}:{minutes:02d}:{seconds:02d}")

    def _check_date_rollover(self):
        now_date = datetime.now().strftime("%Y-%m-%d")
        if now_date != self._today_date:
            self._today_date = now_date
            self._today_notes = self.score_manager.get_today_notes(now_date)
            self._update_display()

    def _reset_counts(self):
        self._today_notes = 0
        self.song_cool = self.song_great = self.song_good = self.song_bad = 0
        self._update_display()

    # ------------------------------------------------------------------
    # OBS トリガー
    # ------------------------------------------------------------------

    def _trigger_obs(self, event: str):
        """OBS 自動制御トリガーを実行する。"""
        try:
            for setting in self.config.obs_control_settings:
                if setting.get("trigger") != event:
                    continue
                action = setting.get("action", "")
                if action == "start_recording":
                    self.obs_manager.start_recording()
                elif action == "stop_recording":
                    self.obs_manager.stop_recording()
                elif action == "start_streaming":
                    self.obs_manager.start_streaming()
                elif action == "stop_streaming":
                    self.obs_manager.stop_streaming()
                elif action == "switch_scene":
                    scene = setting.get("scene", "")
                    if scene:
                        self.obs_manager.change_scene(scene)
                elif action in ("show_source", "hide_source"):
                    scene  = setting.get("scene", "")
                    source = setting.get("source", "")
                    if scene and source:
                        enabled = (action == "show_source")
                        self.obs_manager.set_source_visible(scene, source, enabled)
                logger.info("OBS トリガー実行: event=%s action=%s", event, action)
        except Exception:
            logger.error(traceback.format_exc())

    # ------------------------------------------------------------------
    # メニューアクション
    # ------------------------------------------------------------------

    def _open_settings(self):
        from src.config_dialog import ConfigDialog
        dlg = ConfigDialog(self.config, self)
        if dlg.exec():
            self.config.save_config()
            # キャプチャ方式の変更を反映
            self.obs_manager.set_config(self.config)
            if self.obs_manager.uses_obs_websocket():
                self.obs_manager.connect()
            else:
                self.obs_manager.disconnect_obs()
            # 最前面フラグの更新
            flags = self.windowFlags()
            if self.config.keep_on_top:
                self.setWindowFlags(flags | Qt.WindowType.WindowStaysOnTopHint)
            else:
                self.setWindowFlags(flags & ~Qt.WindowType.WindowStaysOnTopHint)
            self.show()

    def _open_obs_settings(self):
        from src.obs_dialog import OBSControlDialog
        dlg = OBSControlDialog(self.config, self.obs_manager, self)
        if dlg.exec():
            # 接続設定が変わっている可能性があるので再接続
            self.obs_manager.set_config(self.config)
            if self.obs_manager.uses_obs_websocket():
                self.obs_manager.connect()
            else:
                self.obs_manager.disconnect_obs()

    def _open_score_history(self):
        from src.score_dialog import ScoreHistoryDialog
        dlg = ScoreHistoryDialog(self.score_manager, self)
        dlg.exec()

    def _export_csv(self):
        from PySide6.QtWidgets import QFileDialog, QMessageBox
        path, _ = QFileDialog.getSaveFileName(
            self,
            "CSVエクスポート先の選択",
            self.config.score_csv_path,
            "CSV Files (*.csv);;All Files (*)",
        )
        if not path:
            return
        try:
            self.score_manager.export_csv(path)
            QMessageBox.information(self, "完了", f"CSVファイルを出力しました:\n{path}")
        except Exception as e:
            QMessageBox.critical(self, "エラー", f"CSV出力に失敗しました:\n{e}")

    # ------------------------------------------------------------------
    # 終了処理
    # ------------------------------------------------------------------

    def closeEvent(self, event):
        self._timer.stop()
        # ウィンドウ位置・サイズを保存
        geo = self.geometry()
        self.config.main_window_x      = geo.x()
        self.config.main_window_y      = geo.y()
        self.config.main_window_width  = geo.width()
        self.config.main_window_height = geo.height()
        self.config.save_config()
        self.obs_manager.disconnect_obs()
        super().closeEvent(event)


# -----------------------------------------------------------------------

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setApplicationName("popn_daken_counter")
    app.setApplicationDisplayName("pop'n music Lively 打鍵カウンタ")

    window = MainWindow()
    window.show()
    sys.exit(app.exec())
