"""設定ダイアログ"""
from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QPushButton, QRadioButton, QButtonGroup,
    QCheckBox, QSpinBox, QTabWidget, QTextEdit, QVBoxLayout, QWidget,
)

from src.config import Config
from src.funcs import load_ui_text


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
        self._cap_grp = QButtonGroup(self)
        self._cap_direct = QRadioButton(self.ui.feature.capture_method_direct)
        self._cap_legacy = QRadioButton(self.ui.feature.capture_method_direct_legacy)
        self._cap_obs    = QRadioButton(self.ui.feature.capture_method_obs)
        self._cap_grp.addButton(self._cap_direct, 0)
        self._cap_grp.addButton(self._cap_legacy, 1)
        self._cap_grp.addButton(self._cap_obs, 2)
        cap_vbox.addWidget(self._cap_direct)
        cap_vbox.addWidget(self._cap_legacy)
        cap_vbox.addWidget(self._cap_obs)

        self._chk_all_monitors = QCheckBox(self.ui.feature.direct_capture_all_monitors)
        self._chk_all_monitors.setToolTip(self.ui.feature.direct_capture_all_monitors_tip)
        cap_vbox.addWidget(self._chk_all_monitors)
        layout.addWidget(cap_group)

        # その他
        other_group = QGroupBox(self.ui.feature.other_group)
        other_form = QFormLayout(other_group)
        self._chk_keep_on_top = QCheckBox(self.ui.feature.keep_on_top)
        other_form.addRow(self._chk_keep_on_top)
        self._chk_single_cpu = QCheckBox(self.ui.feature.lively_single_cpu)
        self._chk_single_cpu.setToolTip(self.ui.feature.lively_single_cpu_tip)
        other_form.addRow(self._chk_single_cpu)
        layout.addWidget(other_group)

        # リザルトのスクリーンショット
        shot_group = QGroupBox(self.ui.feature.screenshot_group)
        shot_form = QFormLayout(shot_group)
        self._cmb_shot_mode = QComboBox()
        self._cmb_shot_mode.addItem(self.ui.feature.screenshot_mode_off, "off")
        self._cmb_shot_mode.addItem(self.ui.feature.screenshot_mode_all, "all")
        self._cmb_shot_mode.addItem(self.ui.feature.screenshot_mode_best, "best")
        self._cmb_shot_mode.setToolTip(self.ui.feature.screenshot_mode_tip)
        shot_form.addRow(QLabel(self.ui.feature.screenshot_mode), self._cmb_shot_mode)
        self._edit_shot_dir = QLineEdit()
        btn_shot_dir = QPushButton(self.ui.feature.screenshot_dir_browse)
        btn_shot_dir.clicked.connect(self._browse_shot_dir)
        dir_row = QHBoxLayout()
        dir_row.addWidget(self._edit_shot_dir)
        dir_row.addWidget(btn_shot_dir)
        shot_form.addRow(QLabel(self.ui.feature.screenshot_dir), dir_row)
        layout.addWidget(shot_group)

        layout.addStretch()
        return tab

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
        method = self.config.capture_method
        if method == "direct_window":
            self._cap_direct.setChecked(True)
        elif method == "direct_window_legacy":
            self._cap_legacy.setChecked(True)
        else:
            self._cap_obs.setChecked(True)

        self._chk_all_monitors.setChecked(self.config.direct_capture_all_monitors)
        self._chk_keep_on_top.setChecked(self.config.keep_on_top)
        self._chk_single_cpu.setChecked(self.config.lively_single_cpu)
        self._cmb_shot_mode.setCurrentIndex(
            max(0, self._cmb_shot_mode.findData(self.config.result_screenshot_mode))
        )
        self._edit_shot_dir.setText(self.config.result_screenshot_dir)

        self._edit_obs_host.setText(self.config.websocket_host)
        self._spin_obs_port.setValue(self.config.websocket_port)
        self._edit_obs_pass.setText(self.config.websocket_password)
        self._edit_obs_src.setText(self.config.monitor_source_name)
        self._edit_obs_scene_col.setText(self.config.obs_scene_collection)

    def _apply(self):
        bid = self._cap_grp.checkedId()
        self.config.capture_method = [
            "direct_window", "direct_window_legacy", "obs_websocket"
        ][bid]
        self.config.direct_capture_all_monitors = self._chk_all_monitors.isChecked()
        self.config.keep_on_top                 = self._chk_keep_on_top.isChecked()
        self.config.lively_single_cpu           = self._chk_single_cpu.isChecked()
        self.config.result_screenshot_mode      = self._cmb_shot_mode.currentData()
        self.config.result_screenshot_dir       = (
            self._edit_shot_dir.text().strip() or "result_screenshots"
        )
        self.config.websocket_host              = self._edit_obs_host.text().strip()
        self.config.websocket_port              = self._spin_obs_port.value()
        self.config.websocket_password          = self._edit_obs_pass.text()
        self.config.monitor_source_name         = self._edit_obs_src.text().strip()
        self.config.obs_scene_collection        = self._edit_obs_scene_col.text().strip()
        self.accept()
