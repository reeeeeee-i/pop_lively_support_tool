"""pop_lively_support_tool 設定クラス"""
from __future__ import annotations

import json
import os
import traceback

from src.music_list_fetch import DEFAULT_MUSIC_LIST_URL
from src.logger import (
    DEFAULT_LOG_MAX_SIZE_MB, LOG_MAX_SIZE_MB_RANGE, get_logger, set_log_max_size_mb,
)

logger = get_logger(__name__)

_CONFIG_FILE = "config.json"

# 設定ファイルに保存する項目 (= Config の属性名)。保存順
_KEYS = (
    "capture_priority",
    "capture_fallback_seconds",
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
    "last_song_display",
    "log_max_size_mb",
    "score_csv_path",
    "score_db_path",
    "score_history_columns",
    "score_skip_retire",
    "diagnostics_enabled",
    "music_list_url",
    "music_list_serial",
    "update_check_mode",
    "update_skip_until_next",
    "update_notified_tag",
    "result_screenshot_conditions",
    "result_screenshot_dir",
    "result_screenshot_format",
    "result_screenshot_jpeg_quality",
)
# 旧設定 result_screenshot_mode → result_screenshot_conditions
_LEGACY_SCREENSHOT_MODES = {"off": [], "all": ["all"], "best": ["best"]}
CAPTURE_METHODS = ("direct_window", "direct_window_legacy", "obs_websocket")
FALLBACK_SECONDS_RANGE = (1, 300)
SCREENSHOT_CONDITIONS =("all", "best", "fullcombo", "perfect")
SCREENSHOT_FORMATS = ("png", "jpeg")
UPDATE_CHECK_MODES = ("auto", "notify", "off")
LAST_SONG_DISPLAYS = ("title", "genre", "genre_title")
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
        self.capture_priority: list = ["direct_window"]
        """有効な取り込み方式を優先順に並べたリスト。
        'direct_window'=DXCAM直接取得 / 'direct_window_legacy'=旧直接取得 / 'obs_websocket'=OBS WebSocket経由"""
        self.capture_fallback_seconds: int = 10
        """フレームを取得できないまま、この秒数が経つと次の方式に切り替える"""
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
        self.last_song_display: str = "title"
        """メインウィンドウの「最後にプレイした曲」の表記。'title'=曲名 / 'genre'=ジャンル名 / 'genre_title'=ジャンル名(曲名)"""
        self.log_max_size_mb: int = DEFAULT_LOG_MAX_SIZE_MB
        """ログフォルダ全体の最大容量 (MB)。超えた分は古いログから削除する"""

        # スコア記録 CSV パス
        self.score_csv_path: str = "popn_score.csv"
        # スコア管理 SQLite DB パス
        self.score_db_path: str = "popn.db"
        # スコア履歴ビューの列設定 (並び順 / 非表示列 / 列幅)
        self.score_history_columns: dict = {}
        # スコア保存時の条件
        self.score_skip_retire: bool = False
        """リタイアしたプレーのスコアを保存しない"""

        self.music_list_serial: int = 0
        """これまでに取り込んだ曲リストの署名の通し番号。これより古い曲リストは取り込まない (巻き戻し防止)"""

        # 自動更新
        self.update_check_mode: str = "off"
        """起動時の更新チェック。'auto'=新しい版を自動で適用 / 'notify'=更新内容を確認して適用は任意 / 'off'=チェックしない
        (どれでも、メニューからはいつでも確認できる)"""
        self.update_skip_until_next: bool = False
        """'notify' のとき、一度知らせた版は、次の版が出るまで起動時に知らせない"""
        self.update_notified_tag: str = ""
        """起動時に最後に知らせた版のタグ (update_skip_until_next 用)"""

        # 曲リストの取得先
        self.music_list_url: str = DEFAULT_MUSIC_LIST_URL
        """「曲リストをURLから更新」で取得する popn_music_list.json の URL (https)"""

        # 認識診断
        self.diagnostics_enabled: bool = False
        """読み取りに失敗・不一致だった画面を diagnostics フォルダに保存する"""

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
        self.apply_log_settings()
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
            if "capture_priority" not in d and d.get("capture_method") in CAPTURE_METHODS:
                # 旧設定 capture_method (択一式) → capture_priority
                self.capture_priority = [d["capture_method"]]
            if not isinstance(self.capture_priority, list):
                self.capture_priority = []
            seen: list = []
            for m in self.capture_priority:
                if m in CAPTURE_METHODS and m not in seen:
                    seen.append(m)
            self.capture_priority = seen or ["direct_window"]
            try:
                fallback = int(self.capture_fallback_seconds)
            except (TypeError, ValueError):
                fallback = 10
            low, high = FALLBACK_SECONDS_RANGE
            self.capture_fallback_seconds = max(low, min(high, fallback))
            if "result_screenshot_conditions" not in d:
                self.result_screenshot_conditions = list(
                    _LEGACY_SCREENSHOT_MODES.get(d.get("result_screenshot_mode"), [])
                )
            elif not isinstance(self.result_screenshot_conditions, list):
                self.result_screenshot_conditions = []
            if "update_check_mode" not in d and d.get("check_update_on_startup") is True:
                # 旧設定 check_update_on_startup (起動時に確認) → 'notify'
                self.update_check_mode = "notify"
            if self.update_check_mode not in UPDATE_CHECK_MODES:
                self.update_check_mode = "off"
            self.update_skip_until_next = self.update_skip_until_next is True
            if not isinstance(self.update_notified_tag, str):
                self.update_notified_tag = ""
            if isinstance(self.music_list_serial, bool) or not isinstance(self.music_list_serial, int):
                self.music_list_serial = 0
            if not isinstance(self.music_list_url, str) or not self.music_list_url.strip():
                self.music_list_url = DEFAULT_MUSIC_LIST_URL
            if self.last_song_display not in LAST_SONG_DISPLAYS:
                self.last_song_display = "title"
            if self.result_screenshot_format not in SCREENSHOT_FORMATS:
                self.result_screenshot_format = "png"
            try:
                quality = int(self.result_screenshot_jpeg_quality)
            except (TypeError, ValueError):
                quality = 85
            low, high = JPEG_QUALITY_RANGE
            self.result_screenshot_jpeg_quality = max(low, min(high, quality))
            try:
                log_size = int(self.log_max_size_mb)
            except (TypeError, ValueError):
                log_size = DEFAULT_LOG_MAX_SIZE_MB
            low, high = LOG_MAX_SIZE_MB_RANGE
            self.log_max_size_mb = max(low, min(high, log_size))
            window = d.get("window", {})
            for key, attr in _WINDOW_KEYS.items():
                setattr(self, attr, window.get(key, getattr(self, attr)))

        except Exception:
            logger.error(traceback.format_exc())

    def apply_log_settings(self) -> None:
        """ログの最大容量をロガーに反映する。"""
        set_log_max_size_mb(self.log_max_size_mb)

    def save_config(self) -> None:
        try:
            d = {key: getattr(self, key) for key in _KEYS}
            d["window"] = {key: getattr(self, attr) for key, attr in _WINDOW_KEYS.items()}
            with open(self.config_file, "w", encoding="utf-8") as f:
                json.dump(d, f, ensure_ascii=False, indent=2)
        except Exception:
            logger.error(traceback.format_exc())
