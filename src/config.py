"""pop'n music Lively 打鍵カウンタ 設定クラス"""
from __future__ import annotations

import json
import os
import traceback

from src.logger import get_logger

logger = get_logger(__name__)

_CONFIG_FILE = "config.json"


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

        # データ配信ポート（IIDX ツールと競合しないよう別ポート）
        self.websocket_data_port: int = 8768

        # スコア記録 CSV パス
        self.score_csv_path: str = "popn_score.csv"
        # スコア管理 SQLite DB パス
        self.score_db_path: str = "popn.db"

        self.load_config()
        self.save_config()

    # ------------------------------------------------------------------

    def load_config(self) -> None:
        if not os.path.exists(self.config_file):
            return
        try:
            with open(self.config_file, "r", encoding="utf-8") as f:
                d = json.load(f)

            self.capture_method            = d.get("capture_method", "direct_window")
            self.direct_capture_exe        = d.get("direct_capture_exe", "popnLively.exe")
            self.direct_capture_title      = d.get("direct_capture_title", "pop'n music Lively")
            self.direct_capture_all_monitors = d.get("direct_capture_all_monitors", False)
            self.websocket_host            = d.get("websocket_host", "localhost")
            self.websocket_port            = d.get("websocket_port", 4444)
            self.websocket_password        = d.get("websocket_password", "")
            self.monitor_source_name       = d.get("monitor_source_name", "")
            self.obs_control_settings      = d.get("obs_control_settings", [])
            self.obs_scene_collection      = d.get("obs_scene_collection", "")
            self.language                  = d.get("language", "ja")
            self.keep_on_top               = d.get("keep_on_top", False)
            self.websocket_data_port       = d.get("websocket_data_port", 8768)
            self.score_csv_path            = d.get("score_csv_path", "popn_score.csv")
            self.score_db_path             = d.get("score_db_path", "popn.db")

            w = d.get("window", {})
            self.main_window_x      = w.get("x",      100)
            self.main_window_y      = w.get("y",      100)
            self.main_window_width  = w.get("width",  480)
            self.main_window_height = w.get("height", 340)

        except Exception:
            logger.error(traceback.format_exc())

    def save_config(self) -> None:
        try:
            d = {
                "capture_method":             self.capture_method,
                "direct_capture_exe":         self.direct_capture_exe,
                "direct_capture_title":       self.direct_capture_title,
                "direct_capture_all_monitors": self.direct_capture_all_monitors,
                "websocket_host":             self.websocket_host,
                "websocket_port":             self.websocket_port,
                "websocket_password":         self.websocket_password,
                "monitor_source_name":        self.monitor_source_name,
                "obs_control_settings":       self.obs_control_settings,
                "obs_scene_collection":       self.obs_scene_collection,
                "language":                   self.language,
                "keep_on_top":                self.keep_on_top,
                "websocket_data_port":        self.websocket_data_port,
                "score_csv_path":             self.score_csv_path,
                "score_db_path":              self.score_db_path,
                "window": {
                    "x":      self.main_window_x,
                    "y":      self.main_window_y,
                    "width":  self.main_window_width,
                    "height": self.main_window_height,
                },
            }
            with open(self.config_file, "w", encoding="utf-8") as f:
                json.dump(d, f, ensure_ascii=False, indent=2)
        except Exception:
            logger.error(traceback.format_exc())
