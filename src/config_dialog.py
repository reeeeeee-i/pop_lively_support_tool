"""設定ダイアログ"""
from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QPushButton, QRadioButton, QButtonGroup,
    QCheckBox, QComboBox, QListWidget, QListWidgetItem, QSlider, QSpinBox, QTabWidget,
    QTextEdit, QVBoxLayout, QWidget,
)
from PySide6.QtCore import Qt

from src.config import CAPTURE_METHODS, Config, UPDATE_CHECK_MODES, LAST_SONG_DISPLAYS, FALLBACK_SECONDS_RANGE, JPEG_QUALITY_RANGE
from src.funcs import load_ui_text
from src.logger import LOG_MAX_SIZE_MB_RANGE
from src.music_list_fetch import DEFAULT_MUSIC_LIST_URL

# 1920x1080 のリザルト画面を保存したときのファイルサイズの目安 (KB)。実測の平均値
_PNG_SIZE_KB = 1630
# JPEG の品質 → サイズ (KB)。間の品質は線形補間する
_JPEG_SIZE_KB = (
    (10, 83), (20, 115), (30, 140), (40, 161), (50, 181), (60, 202),
    (70, 233), (80, 281), (85, 322), (90, 391), (95, 542), (100, 1030),
)


def _estimate_jpeg_size_kb(quality: int) -> float:
    """JPEG の品質から、ファイルサイズの目安 (KB) を返す。"""
    prev_q, prev_kb = _JPEG_SIZE_KB[0]
    for q, kb in _JPEG_SIZE_KB[1:]:
        if quality <= q:
            return prev_kb + (kb - prev_kb) * (quality - prev_q) / (q - prev_q)
        prev_q, prev_kb = q, kb
    return prev_kb


def _format_size(kb: float) -> str:
    return f"{kb / 1024:.1f} MB" if kb >= 1000 else f"{round(kb, -1):.0f} KB"


class ConfigDialog(QDialog):
    """設定ダイアログ"""

    def __init__(self, config: Config, parent=None):
        super().__init__(parent)
        self.config = config
        self.ui = load_ui_text(config)
        self.setWindowTitle(self.ui.window.settings_title)
        self.setMinimumWidth(500)
        self._init_ui()
        self._load_values()

    # ------------------------------------------------------------------
    # UI 構築
    # ------------------------------------------------------------------

    def _init_ui(self):
        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        layout.addWidget(tabs)

        tabs.addTab(self._build_feature_tab(), "キャプチャ設定")
        tabs.addTab(self._build_obs_tab(), "OBS WebSocket")

        bbox = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel
        )
        bbox.accepted.connect(self._apply)
        bbox.rejected.connect(self.reject)
        layout.addWidget(bbox)

    def _build_feature_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        # キャプチャ方式
        cap_group = QGroupBox(self.ui.feature.game_capture_group)
        cap_vbox = QVBoxLayout(cap_group)
        cap_vbox.addWidget(QLabel(self.ui.feature.capture_priority_help))
        self._cap_names = {
            "direct_window":        self.ui.feature.capture_method_direct,
            "direct_window_legacy": self.ui.feature.capture_method_direct_legacy,
            "obs_websocket":        self.ui.feature.capture_method_obs,
        }
        self._cap_list = QListWidget()
        self._cap_list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._btn_cap_up = QPushButton(self.ui.feature.capture_move_up)
        self._btn_cap_down = QPushButton(self.ui.feature.capture_move_down)
        self._btn_cap_up.clicked.connect(lambda: self._move_capture_item(-1))
        self._btn_cap_down.clicked.connect(lambda: self._move_capture_item(1))
        move_col = QVBoxLayout()
        move_col.addWidget(self._btn_cap_up)
        move_col.addWidget(self._btn_cap_down)
        move_col.addStretch()
        cap_row = QHBoxLayout()
        cap_row.addWidget(self._cap_list, 1)
        cap_row.addLayout(move_col)
        cap_vbox.addLayout(cap_row)

        self._spin_fallback = QSpinBox()
        self._spin_fallback.setRange(*FALLBACK_SECONDS_RANGE)
        self._spin_fallback.setSuffix(" 秒")
        self._spin_fallback.setToolTip(self.ui.feature.capture_fallback_seconds_tip)
        fb_row = QHBoxLayout()
        fb_row.addWidget(QLabel(self.ui.feature.capture_fallback_seconds))
        fb_row.addWidget(self._spin_fallback)
        fb_row.addStretch()
        cap_vbox.addLayout(fb_row)

        self._chk_all_monitors = QCheckBox(self.ui.feature.direct_capture_all_monitors)
        self._chk_all_monitors.setToolTip(self.ui.feature.direct_capture_all_monitors_tip)
        cap_vbox.addWidget(self._chk_all_monitors)
        layout.addWidget(cap_group)

        # その他
        other_group = QGroupBox(self.ui.feature.other_group)
        other_form = QFormLayout(other_group)
        self._chk_keep_on_top = QCheckBox(self.ui.feature.keep_on_top)
        other_form.addRow(self._chk_keep_on_top)
        self._cmb_last_song = QComboBox()
        last_song_names = {
            "title":       self.ui.feature.last_song_display_title,
            "genre":       self.ui.feature.last_song_display_genre,
            "genre_title": self.ui.feature.last_song_display_genre_title,
        }
        for key in LAST_SONG_DISPLAYS:
            self._cmb_last_song.addItem(last_song_names[key], key)
        last_song_row = QHBoxLayout()
        last_song_row.addWidget(self._cmb_last_song)
        last_song_row.addStretch()
        other_form.addRow(QLabel(self.ui.feature.last_song_display), last_song_row)
        self._chk_single_cpu = QCheckBox(self.ui.feature.lively_single_cpu)
        self._chk_single_cpu.setToolTip(self.ui.feature.lively_single_cpu_tip)
        other_form.addRow(self._chk_single_cpu)
        self._spin_log_size = QSpinBox()
        self._spin_log_size.setRange(*LOG_MAX_SIZE_MB_RANGE)
        self._spin_log_size.setSuffix(" MB")
        self._spin_log_size.setToolTip(self.ui.feature.log_max_size_tip)
        lbl_log_size = QLabel(self.ui.feature.log_max_size)
        lbl_log_size.setToolTip(self.ui.feature.log_max_size_tip)
        log_row = QHBoxLayout()
        log_row.addWidget(self._spin_log_size)
        log_row.addStretch()
        other_form.addRow(lbl_log_size, log_row)
        self._cmb_update_mode = QComboBox()
        update_mode_names = {
            "auto":   self.ui.feature.update_check_auto,
            "notify": self.ui.feature.update_check_notify,
            "off":    self.ui.feature.update_check_off,
        }
        for key in UPDATE_CHECK_MODES:
            self._cmb_update_mode.addItem(update_mode_names[key], key)
        self._cmb_update_mode.setToolTip(self.ui.feature.update_check_mode_tip)
        self._cmb_update_mode.currentIndexChanged.connect(self._update_skip_enabled)
        lbl_update_mode = QLabel(self.ui.feature.update_check_mode)
        lbl_update_mode.setToolTip(self.ui.feature.update_check_mode_tip)
        update_row = QHBoxLayout()
        update_row.addWidget(self._cmb_update_mode)
        update_row.addStretch()
        other_form.addRow(lbl_update_mode, update_row)
        self._chk_update_skip = QCheckBox(self.ui.feature.update_skip_until_next)
        self._chk_update_skip.setToolTip(self.ui.feature.update_skip_until_next_tip)
        other_form.addRow(self._chk_update_skip)
        self._edit_music_list_url = QLineEdit()
        self._edit_music_list_url.setToolTip(self.ui.feature.music_list_url_tip)
        lbl_music_url = QLabel(self.ui.feature.music_list_url)
        lbl_music_url.setToolTip(self.ui.feature.music_list_url_tip)
        other_form.addRow(lbl_music_url, self._edit_music_list_url)
        layout.addWidget(other_group)

        # スコア保存時の条件
        save_group = QGroupBox(self.ui.feature.score_save_group)
        save_vbox = QVBoxLayout(save_group)
        self._chk_skip_retire = QCheckBox(self.ui.feature.score_skip_retire)
        self._chk_skip_retire.setToolTip(self.ui.feature.score_skip_retire_tip)
        save_vbox.addWidget(self._chk_skip_retire)
        layout.addWidget(save_group)

        # 認識診断
        diag_group = QGroupBox(self.ui.feature.diagnostics_group)
        diag_vbox = QVBoxLayout(diag_group)
        self._chk_diagnostics = QCheckBox(self.ui.feature.diagnostics_enabled)
        self._chk_diagnostics.setToolTip(self.ui.feature.diagnostics_enabled_tip)
        diag_vbox.addWidget(self._chk_diagnostics)
        layout.addWidget(diag_group)

        # リザルトのスクリーンショット
        shot_group = QGroupBox(self.ui.feature.screenshot_group)
        shot_form = QFormLayout(shot_group)
        self._chk_shot_conds = {
            "all":       QCheckBox(self.ui.feature.screenshot_cond_all),
            "best":      QCheckBox(self.ui.feature.screenshot_cond_best),
            "fullcombo": QCheckBox(self.ui.feature.screenshot_cond_fullcombo),
            "perfect":   QCheckBox(self.ui.feature.screenshot_cond_perfect),
        }
        self._shot_conds_before_all: dict[str, bool] = {}
        cond_row = QHBoxLayout()
        for chk in self._chk_shot_conds.values():
            chk.setToolTip(self.ui.feature.screenshot_cond_tip)
            cond_row.addWidget(chk)
        cond_row.addStretch()
        self._chk_shot_conds["all"].toggled.connect(self._on_shot_all_toggled)
        self._chk_shot_conds["fullcombo"].toggled.connect(self._on_shot_fullcombo_toggled)
        shot_form.addRow(QLabel(self.ui.feature.screenshot_cond), cond_row)
        self._edit_shot_dir = QLineEdit()
        btn_shot_dir = QPushButton(self.ui.feature.screenshot_dir_browse)
        btn_shot_dir.clicked.connect(self._browse_shot_dir)
        dir_row = QHBoxLayout()
        dir_row.addWidget(self._edit_shot_dir)
        dir_row.addWidget(btn_shot_dir)
        shot_form.addRow(QLabel(self.ui.feature.screenshot_dir), dir_row)

        self._shot_fmt_grp = QButtonGroup(self)
        self._shot_fmt_png  = QRadioButton(self.ui.feature.screenshot_format_png)
        self._shot_fmt_jpeg = QRadioButton(self.ui.feature.screenshot_format_jpeg)
        self._shot_fmt_grp.addButton(self._shot_fmt_png, 0)
        self._shot_fmt_grp.addButton(self._shot_fmt_jpeg, 1)
        self._lbl_png_size = QLabel(
            self.ui.feature.screenshot_png_size.format(size=_format_size(_PNG_SIZE_KB))
        )
        fmt_row = QHBoxLayout()
        fmt_row.addWidget(self._shot_fmt_png)
        fmt_row.addWidget(self._lbl_png_size)
        fmt_row.addSpacing(16)
        fmt_row.addWidget(self._shot_fmt_jpeg)
        fmt_row.addStretch()
        shot_form.addRow(QLabel(self.ui.feature.screenshot_format), fmt_row)

        self._slider_shot_quality = QSlider(Qt.Orientation.Horizontal)
        self._slider_shot_quality.setRange(*JPEG_QUALITY_RANGE)
        self._slider_shot_quality.setPageStep(5)
        self._slider_shot_quality.setToolTip(self.ui.feature.screenshot_quality_tip)
        self._lbl_shot_quality = QLabel()
        self._lbl_shot_quality.setToolTip(self.ui.feature.screenshot_quality_tip)
        # 値が変わってもスライダーの幅が動かないよう、最大幅の表示に合わせておく
        self._lbl_shot_quality.setMinimumWidth(
            self._lbl_shot_quality.fontMetrics().horizontalAdvance(
                self.ui.feature.screenshot_quality_value.format(quality=100, size="000 KB")
            )
        )
        quality_row = QHBoxLayout()
        quality_row.addWidget(self._slider_shot_quality)
        quality_row.addWidget(self._lbl_shot_quality)
        self._lbl_shot_quality_title = QLabel(self.ui.feature.screenshot_quality)
        shot_form.addRow(self._lbl_shot_quality_title, quality_row)
        self._slider_shot_quality.valueChanged.connect(self._on_shot_quality_changed)
        self._shot_fmt_jpeg.toggled.connect(self._on_shot_format_toggled)
        layout.addWidget(shot_group)

        layout.addStretch()
        return tab

    def _add_capture_item(self, method: str, checked: bool) -> None:
        item = QListWidgetItem(self._cap_names[method])
        item.setData(Qt.ItemDataRole.UserRole, method)
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        self._cap_list.addItem(item)

    def _move_capture_item(self, delta: int) -> None:
        row = self._cap_list.currentRow()
        new_row = row + delta
        if row < 0 or not 0 <= new_row < self._cap_list.count():
            return
        item = self._cap_list.takeItem(row)
        self._cap_list.insertItem(new_row, item)
        self._cap_list.setCurrentRow(new_row)

    def _on_shot_all_toggled(self, checked: bool):
        """「毎回」を選んだら、他の条件もすべて選んだ状態でグレーアウトする。

        外したときは、選ぶ前のチェック状態に戻す。
        """
        others = {key: chk for key, chk in self._chk_shot_conds.items() if key != "all"}
        if checked:
            self._shot_conds_before_all = {key: chk.isChecked() for key, chk in others.items()}
            for chk in others.values():
                chk.setChecked(True)
        else:
            for key, chk in others.items():
                chk.setChecked(self._shot_conds_before_all.get(key, False))
        self._update_shot_conds_enabled()

    def _on_shot_fullcombo_toggled(self, checked: bool):
        """FULL COMBO を選んだら、PERFECT も自動的に選んでグレーアウトする。"""
        if checked:
            self._chk_shot_conds["perfect"].setChecked(True)
        self._update_shot_conds_enabled()

    def _update_skip_enabled(self):
        """「次の更新まで通知しない」は、更新内容を確認するモードのときだけ使える。"""
        self._chk_update_skip.setEnabled(self._cmb_update_mode.currentData() == "notify")

    def _update_shot_conds_enabled(self):
        conds = self._chk_shot_conds
        every = conds["all"].isChecked()
        conds["best"].setEnabled(not every)
        conds["fullcombo"].setEnabled(not every)
        # PERFECT は FULL COMBO に含まれるため、FULL COMBO 選択中は変更できない
        conds["perfect"].setEnabled(not every and not conds["fullcombo"].isChecked())

    def _on_shot_format_toggled(self, jpeg: bool):
        """圧縮率は JPEG のときだけ選べる。"""
        self._lbl_shot_quality_title.setEnabled(jpeg)
        self._slider_shot_quality.setEnabled(jpeg)
        self._lbl_shot_quality.setEnabled(jpeg)
        self._lbl_png_size.setEnabled(not jpeg)

    def _on_shot_quality_changed(self, quality: int):
        self._lbl_shot_quality.setText(self.ui.feature.screenshot_quality_value.format(
            quality=quality, size=_format_size(_estimate_jpeg_size_kb(quality)),
        ))

    def _browse_shot_dir(self):
        path = QFileDialog.getExistingDirectory(
            self, self.ui.feature.screenshot_dir_dialog, self._edit_shot_dir.text().strip()
        )
        if path:
            self._edit_shot_dir.setText(path)

    def _build_obs_tab(self) -> QWidget:
        tab = QWidget()
        form = QFormLayout(tab)
        ui = self.ui.obs_dialog

        self._edit_obs_host   = QLineEdit()
        self._spin_obs_port   = QSpinBox()
        self._spin_obs_port.setRange(1, 65535)
        self._edit_obs_pass   = QLineEdit()
        self._edit_obs_pass.setEchoMode(QLineEdit.EchoMode.Password)
        self._edit_obs_src    = QLineEdit()
        self._edit_obs_scene_col = QLineEdit()

        form.addRow(QLabel(ui.host),     self._edit_obs_host)
        form.addRow(QLabel(ui.port),     self._spin_obs_port)
        form.addRow(QLabel(ui.password), self._edit_obs_pass)
        form.addRow(QLabel(ui.source),   self._edit_obs_src)
        form.addRow(QLabel(ui.scene_col), self._edit_obs_scene_col)

        info = QTextEdit()
        info.setReadOnly(True)
        info.setPlainText(ui.help_text)
        info.setFixedHeight(120)
        form.addRow(QLabel(ui.triggers), info)

        return tab

    # ------------------------------------------------------------------
    # 値の読み書き
    # ------------------------------------------------------------------

    def _load_values(self):
        enabled = [m for m in self.config.capture_priority if m in CAPTURE_METHODS]
        for method in enabled:
            self._add_capture_item(method, True)
        for method in CAPTURE_METHODS:
            if method not in enabled:
                self._add_capture_item(method, False)
        self._cap_list.setCurrentRow(0)
        # 全項目が収まる高さに固定する (スクロールさせない)
        self._cap_list.setFixedHeight(
            self._cap_list.sizeHintForRow(0) * self._cap_list.count() + 2 * self._cap_list.frameWidth() + 4
        )
        self._spin_fallback.setValue(self.config.capture_fallback_seconds)

        self._chk_all_monitors.setChecked(self.config.direct_capture_all_monitors)
        self._chk_keep_on_top.setChecked(self.config.keep_on_top)
        self._chk_single_cpu.setChecked(self.config.lively_single_cpu)
        self._cmb_last_song.setCurrentIndex(max(0, self._cmb_last_song.findData(self.config.last_song_display)))
        self._spin_log_size.setValue(self.config.log_max_size_mb)
        self._edit_music_list_url.setText(self.config.music_list_url)
        idx = self._cmb_update_mode.findData(self.config.update_check_mode)
        self._cmb_update_mode.setCurrentIndex(max(idx, 0))
        self._chk_update_skip.setChecked(self.config.update_skip_until_next)
        self._update_skip_enabled()
        self._chk_skip_retire.setChecked(self.config.score_skip_retire)
        self._chk_diagnostics.setChecked(self.config.diagnostics_enabled)
        # 「毎回」は他の条件を上書きするので、他の条件を反映してから最後に設定する
        for key in ("best", "fullcombo", "perfect", "all"):
            self._chk_shot_conds[key].setChecked(key in self.config.result_screenshot_conditions)
        self._edit_shot_dir.setText(self.config.result_screenshot_dir)
        jpeg = self.config.result_screenshot_format == "jpeg"
        (self._shot_fmt_jpeg if jpeg else self._shot_fmt_png).setChecked(True)
        self._slider_shot_quality.setValue(self.config.result_screenshot_jpeg_quality)
        self._on_shot_quality_changed(self._slider_shot_quality.value())
        self._on_shot_format_toggled(jpeg)

        self._edit_obs_host.setText(self.config.websocket_host)
        self._spin_obs_port.setValue(self.config.websocket_port)
        self._edit_obs_pass.setText(self.config.websocket_password)
        self._edit_obs_src.setText(self.config.monitor_source_name)
        self._edit_obs_scene_col.setText(self.config.obs_scene_collection)

    def _apply(self):
        priority = []
        for row in range(self._cap_list.count()):
            item = self._cap_list.item(row)
            if item.checkState() == Qt.CheckState.Checked:
                priority.append(item.data(Qt.ItemDataRole.UserRole))
        # 1 つも選ばれていなければ、既定の直接取得にする
        self.config.capture_priority            = priority or ["direct_window"]
        self.config.capture_fallback_seconds    = self._spin_fallback.value()
        self.config.direct_capture_all_monitors = self._chk_all_monitors.isChecked()
        self.config.keep_on_top                 = self._chk_keep_on_top.isChecked()
        self.config.lively_single_cpu           = self._chk_single_cpu.isChecked()
        self.config.last_song_display           = self._cmb_last_song.currentData()
        self.config.log_max_size_mb             = self._spin_log_size.value()
        self.config.update_check_mode           = self._cmb_update_mode.currentData()
        self.config.update_skip_until_next      = self._chk_update_skip.isChecked()
        self.config.music_list_url              = self._edit_music_list_url.text().strip() or DEFAULT_MUSIC_LIST_URL
        self.config.score_skip_retire           = self._chk_skip_retire.isChecked()
        self.config.diagnostics_enabled         = self._chk_diagnostics.isChecked()
        if self._chk_shot_conds["all"].isChecked():
            # 「毎回」を外したときに戻せるよう、選ぶ前の条件を一緒に保存する
            self.config.result_screenshot_conditions = ["all"] + [
                key for key, on in self._shot_conds_before_all.items() if on
            ]
        else:
            self.config.result_screenshot_conditions = [
                key for key, chk in self._chk_shot_conds.items() if chk.isChecked()
            ]
        self.config.result_screenshot_dir       = (
            self._edit_shot_dir.text().strip() or "result_screenshots"
        )
        self.config.result_screenshot_format    = (
            "jpeg" if self._shot_fmt_jpeg.isChecked() else "png"
        )
        self.config.result_screenshot_jpeg_quality = self._slider_shot_quality.value()
        self.config.websocket_host              = self._edit_obs_host.text().strip()
        self.config.websocket_port              = self._spin_obs_port.value()
        self.config.websocket_password          = self._edit_obs_pass.text()
        self.config.monitor_source_name         = self._edit_obs_src.text().strip()
        self.config.obs_scene_collection        = self._edit_obs_scene_col.text().strip()
        self.accept()
