"""pop_lively_support_tool 設定クラス"""
from __future__ import annotations

import json
import os
import traceback

from src.logger import get_logger

logger = get_logger(__name__)

_CONFIG_FILE = "config.json"

# 設定ファイルに保存する項目 (= Config の属性名)。保存順
_KEYS = (
    "capture_method",
    "direct_capture_exe",
    "direct_capture_title",
    "direct_capture_all_monitors",
    "websocket_host",
    "websocket_port",
    "websocket_password",
    "monitor_source_name",
    "obs_control_settings",
    "obs_scene_collection",
    "language",
    "keep_on_top",
    "lively_single_cpu",
    "score_csv_path",
    "score_db_path",
    "score_history_columns",
    "score_skip_retire",
    "result_screenshot_conditions",
    "result_screenshot_dir",
    "result_screenshot_format",
    "result_screenshot_jpeg_quality",
)
# 旧設定 result_screenshot_mode → result_screenshot_conditions
_LEGACY_SCREENSHOT_MODES = {"off": [], "all": ["all"], "best": ["best"]}
SCREENSHOT_CONDITIONS = ("all", "best", "fullcombo", "perfect")
SCREENSHOT_FORMATS = ("png", "jpeg")
JPEG_QUALITY_RANGE = (10, 100)
# 設定ファイルの "window" 以下のキー → Config の属性名
_WINDOW_KEYS = {
    "x": "main_window_x",
    "y": "main_window_y",
    "width": "main_window_width",
    "height": "main_window_height",
}


class Config:
    def __init__(self, config_file: str = _CONFIG_FILE):
        self.config_file = config_file

        # キャプチャ設定
        self.capture_method: str = "direct_window"
        """'direct_window'=DXCAM直接取得 / 'direct_window_legacy'=旧直接取得 / 'obs_websocket'=OBS WebSocket経由"""
        self.direct_capture_exe: str = "popnLively.exe"
        """直接取得対象のプロセス名"""
        self.direct_capture_title: str = "pop'n music Lively"
        """直接取得対象のウィンドウタイトル"""
        self.direct_capture_all_monitors: bool = False
        """旧直接取得用。DXCAM直接取得では使用しない。"""

        # OBS WebSocket 設定
        self.websocket_host: str = "localhost"
        self.websocket_port: int = 4444
        self.websocket_password: str = ""
        self.monitor_source_name: str = ""
        """OBS でゲーム画面を映しているソース名"""
        self.obs_control_settings: list = []
        """OBS 自動制御設定リスト"""
        self.obs_scene_collection: str = ""
        """起動時に切り替えるシーンコレクション名（空=未設定）"""

        # アプリ設定
        self.language: str = "ja"
        self.keep_on_top: bool = False
        self.main_window_x: int = 100
        self.main_window_y: int = 100
        self.main_window_width: int = 480
        self.main_window_height: int = 340
        self.lively_single_cpu: bool = False
        """Lively の CPU 割り当てを 1 コアに絞る（ロード時間短縮）"""

        # スコア記録 CSV パス
        self.score_csv_path: str = "popn_score.csv"
        # スコア管理 SQLite DB パス
        self.score_db_path: str = "popn.db"
        # スコア履歴ビューの列設定 (並び順 / 非表示列 / 列幅)
        self.score_history_columns: dict = {}
        # スコア保存時の条件
        self.score_skip_retire: bool = False
        """リタイアしたプレーのスコアを保存しない"""

        # リザルト画面のスクリーンショット
        self.result_screenshot_conditions: list = []
        """保存条件 (いずれかを満たせば保存。空=無効)。
        'all'=毎回 / 'best'=自己ベスト更新時 / 'fullcombo'=FULL COMBO 時 / 'perfect'=PERFECT 時"""
        self.result_screenshot_dir: str = "result_screenshots"
        """スクリーンショットの保存先フォルダ"""
        self.result_screenshot_format: str = "png"
        """保存形式。'png' / 'jpeg'"""
        self.result_screenshot_jpeg_quality: int = 85
        """JPEG の品質 (10～100)。小さいほど圧縮率が高く、ファイルが小さくなる"""

        self.load_config()
        self.save_config()

    # ------------------------------------------------------------------

    def load_config(self) -> None:
        """設定ファイルを読み込む。ファイルに無い項目は既定値のまま。"""
        if not os.path.exists(self.config_file):
            return
        try:
            with open(self.config_file, "r", encoding="utf-8") as f:
                d = json.load(f)

            for key in _KEYS:
                setattr(self, key, d.get(key, getattr(self, key)))
            if "result_screenshot_conditions" not in d:
                self.result_screenshot_conditions = list(
                    _LEGACY_SCREENSHOT_MODES.get(d.get("result_screenshot_mode"), [])
                )
            elif not isinstance(self.result_screenshot_conditions, list):
                self.result_screenshot_conditions = []
            if self.result_screenshot_format not in SCREENSHOT_FORMATS:
                self.result_screenshot_format = "png"
            try:
                quality = int(self.result_screenshot_jpeg_quality)
            except (TypeError, ValueError):
                quality = 85
            low, high = JPEG_QUALITY_RANGE
            self.result_screenshot_jpeg_quality = max(low, min(high, quality))
            window = d.get("window", {})
            for key, attr in _WINDOW_KEYS.items():
                setattr(self, attr, window.get(key, getattr(self, attr)))

        except Exception:
            logger.error(traceback.format_exc())

    def save_config(self) -> None:
        try:
            d = {key: getattr(self, key) for key in _KEYS}
            d["window"] = {key: getattr(self, attr) for key, attr in _WINDOW_KEYS.items()}
            with open(self.config_file, "w", encoding="utf-8") as f:
                json.dump(d, f, ensure_ascii=False, indent=2)
        except Exception:
            logger.error(traceback.format_exc())
