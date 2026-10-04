"""pop_lively_support_tool メインエントリポイント"""
from __future__ import annotations

import os
import re
import sys
import time
import traceback
from datetime import datetime

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QAction, QFont, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QGroupBox,
    QFormLayout,
    QLabel,
    QMainWindow,
    QMenuBar,
    QPushButton,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from src.config import Config
from src.classes import DetectMode, PopnJudge, PopnOptions, format_song
from src.cpu_affinity import LivelyCpuAffinity
from src.screen_reader import ScreenReader
from src.option_reader import GUIDE_SE_ON
from src.obs_websocket_manager import OBSWebSocketManager
from src.score_manager import ScoreManager
from src.funcs import load_ui_text
from src.logger import get_logger

logger = get_logger(__name__)

_LOOP_INTERVAL_MS = 100   # メインループ間隔 (ms)
_CPU_AFFINITY_INTERVAL_MS = 1000   # Lively の CPU 割り当て監視間隔 (ms)

# 曲名読み取り: このフレーム数ごとに 1 回読む (OCR は 1 回数十 ms かかるため毎フレームは行わない)
_TITLE_SCAN_INTERVAL_FRAMES = 5
# 曲名読み取り: この回数読んでも曲を特定できなければ諦める
_TITLE_SCAN_MAX_TRIES = 20

# オプション読み取り: このフレーム数ごとに 1 回読む
_OPTION_SCAN_INTERVAL_FRAMES = 3
# オプション読み取り: 同じ値がこの回数続いたら反映する（画面の開閉演出の途中を掴まないため）
_OPTION_STABLE_READS = 2
# GUIDE SE の ON の値。アイコンからは大/小が分からないので、先頭 (ゲームの初期値) を既定とする
_GUIDE_SE_ON_VALUES = ("ON 大", "ON 小")

# リザルト読み取り: 同じ値がこのフレーム数続いたら確定する（表示演出の途中を掴まないため）
_RESULT_STABLE_FRAMES = 3
# リザルト読み取り: このフレーム数待っても安定しなければ、その時点の値で記録する
_RESULT_TIMEOUT_FRAMES = 50

# 現在のモード表示の文字色
_MODE_COLORS = {
    DetectMode.play:             "#00e676",  # プレー中（緑）
    DetectMode.result:           "#ffd600",  # リザルト（黄）
    DetectMode.select:           "#40c4ff",  # 選曲中（水色）
    DetectMode.option:           "#ff80ab",  # オプション（ピンク）
    DetectMode.title:            "#b388ff",  # タイトル（紫）
    DetectMode.status:           "#b388ff",  # ステータス（紫）
    DetectMode.ticket:           "#b388ff",  # チケット（紫）
    DetectMode.character_select: "#b388ff",  # キャラセレクト（紫）
    DetectMode.exit:             "#ff5252",  # 終了画面（赤）
    DetectMode.loading:          "#ffab40",  # ロード中（オレンジ）
    DetectMode.unknown:          "#aaaaaa",  # 待機中（グレー）
}

# OBS トリガー (<モード名>_start / <モード名>_end) を出す画面。
# 1 回の画面遷移で出る開始・終了トリガーの順序は、この並び順で決まる
_TRIGGER_MODES = (
    DetectMode.title,
    DetectMode.status,
    DetectMode.ticket,
    DetectMode.character_select,
    DetectMode.select,
    DetectMode.option,
    DetectMode.play,
    DetectMode.result,
    DetectMode.loading,
    DetectMode.exit,
)


def _bold_font(point_size: int) -> QFont:
    font = QFont()
    font.setPointSize(point_size)
    font.setBold(True)
    return font


class MainWindow(QMainWindow):
    """pop_lively_support_tool メインウィンドウ"""

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

        # 打鍵カウント（現在の曲の判定内訳）。プレー画面下部の累計値を読んだもので、
        # リザルト画面を読めた時点でその値に置き換える
        self._song_judge = PopnJudge()

        # 本日の打鍵数・日付管理
        # _today_notes は確定分（リザルトで記録した曲 + 途中でやめた曲の暫定値）。
        # 表示はこれにプレー中の曲の暫定値を加えたもの (_update_display)
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

        # オプション読み取り状態
        self._option_values = None   # 直近に読めたオプション一覧
        self._option_stable = 0
        self._option_frames = 0

        # リザルト読み取り待ち状態
        self._result_pending = False
        self._result_frames = 0
        self._result_stable = 0
        self._result_values = None   # 直近に全項目を読めた値
        self._result_image = None    # 直近のリザルト画面フレーム
        self._result_retire = False  # リザルト画面で「Retire」の表示を検出したか

        self._setup_ui()
        self._setup_obs()

        # メインループ
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._main_loop)
        self._timer.start(_LOOP_INTERVAL_MS)

        # Lively の CPU 割り当て監視
        self.cpu_affinity = LivelyCpuAffinity()
        self._affinity_timer = QTimer(self)
        self._affinity_timer.timeout.connect(self._update_cpu_affinity)
        self._affinity_timer.start(_CPU_AFFINITY_INTERVAL_MS)

        # ウィンドウ位置・サイズ復元
        self.setGeometry(
            self.config.main_window_x,
            self.config.main_window_y,
            self.config.main_window_width,
            self.config.main_window_height,
        )
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, self.config.keep_on_top)

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

        font_lbl = _bold_font(11)
        font_val = _bold_font(13)
        font_notes = _bold_font(22)
        font_time = _bold_font(16)

        def make_row_label(text: str) -> QLabel:
            lbl = QLabel(text)
            lbl.setFont(font_lbl)
            lbl.setStyleSheet("color: #aaaaaa;")
            return lbl

        status = self.ui.status
        self._mode_labels = {
            DetectMode.play:             status.playing,
            DetectMode.result:           status.result,
            DetectMode.select:           status.select,
            DetectMode.option:           status.option,
            DetectMode.title:            status.title,
            DetectMode.status:           status.status,
            DetectMode.ticket:           status.ticket,
            DetectMode.character_select: status.character_select,
            DetectMode.exit:             status.exit,
            DetectMode.loading:          status.loading,
            DetectMode.unknown:          status.waiting_game,
        }

        self.lbl_mode = QLabel()
        self.lbl_mode.setFont(font_val)

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

        self._show_mode(DetectMode.unknown, in_statusbar=False)

    # ------------------------------------------------------------------
    # セットアップ
    # ------------------------------------------------------------------

    def _setup_obs(self):
        self.obs_manager.connection_changed.connect(self._on_obs_connection_changed)
        self._apply_obs_config()

    def _apply_obs_config(self):
        """設定 (キャプチャ方式・接続先) を OBS マネージャへ反映し、必要なら接続し直す。"""
        self.obs_manager.set_config(self.config)
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
                self._lbl_game.setText(self.obs_manager.get_status()[0])
                self._show_mode(DetectMode.unknown, in_statusbar=False)
                return

            mode = self.screen_reader.detect_mode(image)
            self._handle_mode(mode, image)

        except Exception:
            logger.error(traceback.format_exc())

    def _show_mode(self, mode: DetectMode, in_statusbar: bool = True):
        """現在のモード表示を更新する。"""
        text = self._mode_labels[mode]
        self.lbl_mode.setText(text)
        self.lbl_mode.setStyleSheet(f"color: {_MODE_COLORS[mode]}; font-weight: bold;")
        self._lbl_mode.setText(text if in_statusbar else "")

    def _handle_mode(self, mode: DetectMode, image):
        if mode != self.current_mode:
            self._on_mode_changed(self.current_mode, mode)
        self.current_mode = mode

        self._show_mode(mode)
        self._lbl_game.setText(self.obs_manager.get_status()[0])

        if mode == DetectMode.option:
            self._process_option(image)
        elif mode == DetectMode.play:
            self._process_play(image)
        elif mode == DetectMode.result and self._result_pending:
            # 数値が安定するまで読み取りを続ける
            self._process_result(image)

    def _on_mode_changed(self, prev: DetectMode, curr: DetectMode):
        logger.info("モード変更: %s → %s", prev.name, curr.name)
        for mode in _TRIGGER_MODES:
            if curr == mode:
                self._enter_mode(mode)
                self._trigger_obs(f"{mode.name}_start")
            if prev == mode:
                self._leave_mode(mode)
                self._trigger_obs(f"{mode.name}_end")

    def _enter_mode(self, mode: DetectMode):
        if mode == DetectMode.option:
            self._option_values = None
            self._option_stable = 0
            self._option_frames = 0
        elif mode == DetectMode.play:
            self._title_scanned = False
            self._title_frames = 0
            self.score_manager.reset_current_song()
            # 判定内訳はここではリセットしない。プレー画面の検出が一瞬途切れただけの場合に
            # 数え直しにならないよう、累計値が 0 に戻ったことを見て曲の切り替わりを判断する
        elif mode == DetectMode.result:
            # スコアの記録は数値が安定してから行う (_process_result)
            self._result_pending = True
            self._result_frames = 0
            self._result_stable = 0
            self._result_values = None
            self._result_image = None
            self._result_retire = False

    def _leave_mode(self, mode: DetectMode):
        if mode == DetectMode.result:
            # 安定を待っている間にリザルト画面を抜けた場合は、最後に読めた値で記録する
            if self._result_pending and self._result_image is not None:
                self._save_result(self._result_image, self._result_values)
            self._result_pending = False

    def _process_option(self, image):
        """オプション選択画面の設定一覧を読み、続けて同じ値になったら反映する。"""
        self._option_frames += 1
        if (self._option_frames - 1) % _OPTION_SCAN_INTERVAL_FRAMES != 0:
            return

        values = self.screen_reader.read_options(image)
        if not values:
            self._option_values = None
            self._option_stable = 0
            return

        self._option_stable = self._option_stable + 1 if values == self._option_values else 1
        self._option_values = values
        if self._option_stable != _OPTION_STABLE_READS:
            return

        # 読めなかった項目は現在の値を引き継ぐ
        current = self.score_manager.current_options.to_dict()
        if values.get("guide_se") == GUIDE_SE_ON:
            # アイコンからは ON の大/小が分からない。直前が ON ならその値、OFF なら初期値の「ON 大」とする
            guide_se = current.get("guide_se")
            values = {**values, "guide_se": guide_se if guide_se in _GUIDE_SE_ON_VALUES else _GUIDE_SE_ON_VALUES[0]}
        if any(current.get(k) != v for k, v in values.items()):
            self.score_manager.set_current_options(PopnOptions.from_dict({**current, **values}))

    def _process_play(self, image):
        # プレー開始直後に曲名・難易度区分を認識
        if not self._title_scanned:
            self._scan_play_song(image)

        judge, restarted = self.screen_reader.detect_judge(image)
        if restarted:
            # 累計値が 0 に戻った = 次の曲が始まった。リザルトに到達しなかった曲
            # （リタイア・リトライ）の分が残っていれば確定分へ繰り入れる
            self._today_notes += self._song_judge.notes
        changed = restarted or judge.notes != self._song_judge.notes
        self._song_judge = judge
        if changed:
            self._check_date_rollover()
            self._update_display()

    def _scan_play_song(self, image):
        """プレー画面上部の曲名バーから曲を特定する。特定できるまで一定間隔で読み直す。"""
        self._title_frames += 1
        if (self._title_frames - 1) % _TITLE_SCAN_INTERVAL_FRAMES != 0:
            return

        song = self.screen_reader.read_play_song(image)
        if song.text and self.score_manager.identify_song(song.text, song.difficulty):
            self._title_scanned = True
            self._set_last_played_song(self.score_manager.current_song_title, song.difficulty)
        elif self._title_frames >= _TITLE_SCAN_INTERVAL_FRAMES * _TITLE_SCAN_MAX_TRIES:
            self._title_scanned = True
            logger.warning("曲を特定できませんでした (読み取り結果: '%s' / %s)", song.text, song.difficulty)
            self.screen_reader.save_unread_title(image)

    def _process_result(self, image):
        """リザルト画面の数値を読み、数フレーム連続で同じ値になったら記録する。"""
        self._result_frames += 1
        values = self.screen_reader.read_result_values(image)
        # 「Retire」の表示が数値より遅れて出ても拾えるよう、一度でも検出したら覚えておく
        if values is not None and values.retire:
            self._result_retire = True

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
            record = self.screen_reader.read_result(
                image,
                live_judge=self._song_judge,
                options=self.score_manager.current_options,
                title=self.score_manager.current_song_title,
                level=self.score_manager.current_level,
                difficulty=self.score_manager.current_difficulty,
                values=values,
            )
            if self.config.score_skip_retire and self._result_retire:
                # 記録はしないが、打鍵数は本日の打鍵数に反映する
                logger.info("リタイアのためスコアを保存しません: %s - SCORE:%d", record.title, record.score)
                self._check_date_rollover()
                self._today_notes += record.cool + record.great + record.good
                self._reset_song_judge()
                self._update_display()
                self._statusbar.showMessage(self.ui.status.retire_skipped, 6000)
                saved = False
            else:
                saved = self.score_manager.add_record(record)
            if saved:
                # プレー中の暫定値を捨て、リザルト画面の値を本日の打鍵数に反映する
                self._check_date_rollover()
                self._today_notes += record.cool + record.great + record.good
                self._reset_song_judge()
                self._update_display()
                chart_info = f"[Lv{record.level} {record.difficulty_code}] " if record.level else f"[{record.difficulty_code}] "
                msg = f"スコア保存: {chart_info}{record.title} | {record.score}点 ({record.options.to_summary()})"
                self._statusbar.showMessage(msg, 6000)
                self._save_result_screenshot(image, record)

            # 最後にプレイした曲の表示を更新
            song_title = record.title if record.title != "Unknown" else self.score_manager.current_song_title
            if song_title and song_title != "Unknown":
                self._set_last_played_song(song_title, record.difficulty)
        except Exception as e:
            logger.error("スコア保存処理エラー: %s", e)

    def _save_result_screenshot(self, image, record):
        """設定に応じて、記録したリザルト画面のスクリーンショットを保存する。"""
        conds = self.config.result_screenshot_conditions
        # リタイアしたプレーは BAD が 0 でも FULL COMBO / PERFECT として扱わない
        full_combo = not self._result_retire and record.total_notes > 0 and record.bad == 0
        if not (
            "all" in conds
            or ("fullcombo" in conds and full_combo)
            or ("perfect" in conds and full_combo and record.good == 0)
            or ("best" in conds and self.score_manager.is_personal_best(record))
        ):
            return
        try:
            folder = self.config.result_screenshot_dir
            os.makedirs(folder, exist_ok=True)
            played_at = datetime.strptime(record.timestamp, "%Y-%m-%d %H:%M:%S")
            # ファイル名に使えない文字を置き換える
            title = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", record.title).strip(" .") or "Unknown"
            jpeg = self.config.result_screenshot_format == "jpeg"
            ext = "jpg" if jpeg else "png"
            name = f"{played_at:%Y%m%d_%H%M%S}_{title}_{record.difficulty_code}_{record.score}.{ext}"
            path = os.path.join(folder, name)
            if jpeg:
                # JPEG はアルファチャンネルを持てないため RGB に変換する
                image.convert("RGB").save(
                    path, "JPEG", quality=self.config.result_screenshot_jpeg_quality
                )
            else:
                image.save(path)
            logger.info("リザルトのスクリーンショットを保存: %s", path)
        except Exception as e:
            logger.error("スクリーンショット保存エラー: %s", e)

    def _set_last_played_song(self, title: str, difficulty: str):
        self._last_played_song = format_song(title, difficulty)
        self.lbl_last_song.setText(self._last_played_song)

    def _reset_song_judge(self):
        """現在の曲の判定内訳（プレー中の暫定値）を捨てる。"""
        self.screen_reader.reset_judge()
        self._song_judge = PopnJudge()

    def _update_display(self):
        self.lbl_today_notes.setText(f"{self._today_notes + self._song_judge.notes:,}")

    def _update_uptime(self):
        minutes, seconds = divmod(int(time.time() - self._start_time), 60)
        hours, minutes = divmod(minutes, 60)
        self.lbl_uptime.setText(f"{hours:02d}:{minutes:02d}:{seconds:02d}")

    def _check_date_rollover(self):
        now_date = datetime.now().strftime("%Y-%m-%d")
        if now_date != self._today_date:
            self._today_date = now_date
            self._today_notes = self.score_manager.get_today_notes(now_date)
            self._update_display()

    def _update_cpu_affinity(self):
        """Lively の起動を見つけたら CPU 割り当てを 1 コアに絞る（設定で有効な場合のみ）。"""
        try:
            cpu = self.cpu_affinity.update(
                self.config.lively_single_cpu, self.config.direct_capture_exe
            )
            if cpu is not None:
                self._statusbar.showMessage(f"Lively の CPU 割り当てを CPU{cpu} のみに変更しました", 6000)
        except Exception:
            logger.error(traceback.format_exc())

    def _reset_counts(self):
        self._today_notes = 0
        self._reset_song_judge()
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
            self._apply_obs_config()
            # 最前面フラグの更新 (フラグを変えるとウィンドウが隠れるので表示し直す)
            self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, self.config.keep_on_top)
            self.show()

    def _open_obs_settings(self):
        from src.obs_dialog import OBSControlDialog
        dlg = OBSControlDialog(self.config, self.obs_manager, self)
        if dlg.exec():
            # 接続設定が変わっている可能性があるので再接続
            self._apply_obs_config()

    def _open_score_history(self):
        from src.score_dialog import ScoreHistoryDialog
        dlg = ScoreHistoryDialog(self.score_manager, self, config=self.config)
        dlg.exec()

    def _export_csv(self):
        from src.score_dialog import export_csv_with_dialog
        export_csv_with_dialog(self, self.score_manager)

    # ------------------------------------------------------------------
    # 終了処理
    # ------------------------------------------------------------------

    def closeEvent(self, event):
        self._timer.stop()
        self._affinity_timer.stop()
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
    app.setApplicationName("pop_lively_support_tool")
    app.setApplicationDisplayName("pop'n music Lively サポートツール")
    app.setWindowIcon(QIcon("src/icon.ico"))

    window = MainWindow()
    window.show()
    sys.exit(app.exec())
