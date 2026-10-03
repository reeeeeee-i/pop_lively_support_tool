"""OBS WebSocket 接続管理クラス。
既存の inf_daken_counter_obsw を参考に pop'n music Lively 向けに移植・簡略化。
infnotebook 依存・load_ui_text 依存を完全に除去している。
"""
from __future__ import annotations

import functools
import logging
import os
import threading
import time
import traceback
from html import escape
from typing import Any, Dict, List, Optional

from PySide6.QtCore import QObject, Signal

from src.config import Config
from src.direct_window_capture import DirectWindowCapture
from src.dxcam_window_capture import DxcamWindowCapture
from src.logger import get_logger

logger = get_logger(__name__)

# obsws_python ライブラリのトレースバックを抑制
logging.getLogger("obsws_python").setLevel(logging.CRITICAL)

try:
    from obsws_python import ReqClient
    OBSWS_AVAILABLE = True
except ImportError:
    ReqClient = None  # type: ignore[assignment,misc]
    OBSWS_AVAILABLE = False
    logger.warning("obsws_python not installed. OBS WebSocket 機能は使用できません。")


def _require_connection(func):
    """OBS 接続が必要なメソッド用デコレータ"""
    @functools.wraps(func)
    def wrapper(self, *args, **kwargs):
        if not self.is_connected or not self.client:
            logger.warning("OBS 未接続 (%s)", func.__name__)
            return None
        try:
            return func(self, *args, **kwargs)
        except Exception as e:
            logger.error("OBS コマンド失敗 (%s): %s", func.__name__, e)
            return None
    return wrapper


class OBSWebSocketManager(QObject):
    """OBS WebSocket 接続管理・ゲーム画面キャプチャを統合するクラス。

    直接キャプチャモード (DXCAM / 旧方式) と OBS WebSocket 経由の
    両方に対応する。画面取得は read_frame() で行う。
    """

    connection_changed = Signal(bool, str)   # (is_connected, message)

    def __init__(self):
        super().__init__()

        self.config: Optional[Config] = None
        self.client: Optional[ReqClient] = None  # type: ignore[type-arg]
        self.is_connected = False

        # 再接続設定
        self.auto_reconnect       = True
        self.reconnect_interval   = 5.0   # 秒
        self.max_reconnect_attempts = 0   # 0 = 無限

        # 監視スレッド
        self.monitor_thread: Optional[threading.Thread] = None
        self.monitor_running = False
        self.stop_event = threading.Event()

        # キャプチャ
        self.picw = 1920
        self.pich = 1080
        self.direct_capture: Optional[Any] = None
        self._next_direct_capture_probe_at = 0.0
        self._scene_collection_applied = False

    # ------------------------------------------------------------------
    # 設定
    # ------------------------------------------------------------------

    def set_config(self, config: Config) -> None:
        self.config = config
        capture_cls = self._direct_capture_class()
        if self.direct_capture is None or not isinstance(self.direct_capture, capture_cls):
            if self.direct_capture and hasattr(self.direct_capture, "close"):
                self.direct_capture.close()
            self.direct_capture = capture_cls(config)
        else:
            self.direct_capture.set_config(config)
        self._next_direct_capture_probe_at = 0.0

    def _direct_capture_class(self):
        if (
            self.config and
            getattr(self.config, "capture_method", "direct_window") == "direct_window_legacy"
        ):
            return DirectWindowCapture
        return DxcamWindowCapture

    # ------------------------------------------------------------------
    # 状態判定
    # ------------------------------------------------------------------

    def is_direct_capture(self) -> bool:
        return bool(
            self.config and
            getattr(self.config, "capture_method", "direct_window")
            in ("direct_window", "direct_window_legacy")
        )

    def is_obs_control_enabled(self) -> bool:
        if not self.config:
            return False
        return bool(
            getattr(self.config, "obs_control_settings", []) or
            getattr(self.config, "obs_scene_collection", "")
        )

    def uses_obs_websocket(self) -> bool:
        if not self.config:
            return False
        if not self.is_direct_capture():
            return True
        return bool(
            getattr(self.config, "obs_control_settings", []) or
            getattr(self.config, "obs_scene_collection", "") or
            str(getattr(self.config, "websocket_password", "")).strip() or
            str(getattr(self.config, "monitor_source_name", "")).strip()
        )

    def is_capture_ready(self) -> bool:
        if not self.config:
            return False
        if self.is_direct_capture():
            return True
        return self.is_connected and self.is_monitor_source_configured()

    def is_monitor_source_configured(self) -> bool:
        if not self.config:
            return False
        if self.is_direct_capture():
            return True
        return bool(
            self.config.monitor_source_name and
            self.config.monitor_source_name.strip()
        )

    # ------------------------------------------------------------------
    # 接続
    # ------------------------------------------------------------------

    def connect(self, force: bool = False) -> bool:
        if not force and not self.uses_obs_websocket():
            self.stop_monitor()
            if self.client:
                try:
                    self.client.disconnect()
                except Exception:
                    pass
                self.client = None
            self.is_connected = False
            self._emit_status("直接取得モード", False)
            return False

        if not OBSWS_AVAILABLE:
            self._emit_status("obsws_python がインストールされていません", False)
            return False

        if not self.config:
            self._emit_status("設定が未完了です", False)
            return False

        try:
            if self.client:
                try:
                    self.client.disconnect()
                except Exception:
                    pass
                self.client = None

            logger.info(
                "OBS WebSocket 接続中: %s:%s",
                self.config.websocket_host, self.config.websocket_port,
            )
            self.client = ReqClient(
                host=self.config.websocket_host,
                port=self.config.websocket_port,
                password=self.config.websocket_password,
                timeout=5,
            )
            self.client.get_version()
            self.is_connected = True
            self._emit_status(
                f"OBS 接続済み ({self.config.websocket_host}:{self.config.websocket_port})",
                True,
            )
            self._apply_scene_collection()
            self.start_monitor()
            return True

        except Exception as e:
            self.is_connected = False
            if self.client:
                try:
                    self.client.disconnect()
                except Exception:
                    pass
                self.client = None
            self._emit_status(f"OBS 接続失敗: {e}", False)
            logger.error("OBS WebSocket 接続失敗: %s", e)
            if self.auto_reconnect:
                self.start_monitor()
            return False

    def disconnect_obs(self) -> None:
        logger.info("OBS WebSocket 切断")
        self.stop_monitor()
        if self.client:
            try:
                self.client.disconnect()
            except Exception:
                pass
            self.client = None
        self.is_connected = False
        self._scene_collection_applied = False

    # ------------------------------------------------------------------
    # 監視スレッド
    # ------------------------------------------------------------------

    def start_monitor(self) -> None:
        if self.monitor_running:
            return
        self.monitor_running = True
        self.stop_event.clear()
        self.monitor_thread = threading.Thread(
            target=self._monitor_loop,
            daemon=True,
            name="OBSMonitorThread",
        )
        self.monitor_thread.start()

    def stop_monitor(self) -> None:
        if not self.monitor_running:
            return
        self.monitor_running = False
        self.stop_event.set()
        if self.monitor_thread:
            self.monitor_thread.join(timeout=2.0)
            self.monitor_thread = None

    def _monitor_loop(self) -> None:
        check_interval = 2.0
        consecutive_failures = 0

        while self.monitor_running and not self.stop_event.is_set():
            try:
                if not self.config:
                    time.sleep(check_interval)
                    continue

                if not self.uses_obs_websocket():
                    time.sleep(check_interval)
                    continue

                if self.is_connected and self.client:
                    try:
                        self.client.get_version()
                        consecutive_failures = 0
                    except Exception as e:
                        logger.warning("OBS 接続が切れました: %s", e)
                        self.is_connected = False
                        self.client = None
                        self._emit_status("OBS 接続切断", False)
                        consecutive_failures += 1
                else:
                    if self.auto_reconnect:
                        if (
                            self.max_reconnect_attempts > 0 and
                            consecutive_failures >= self.max_reconnect_attempts
                        ):
                            time.sleep(check_interval)
                            continue
                        self._emit_status(
                            f"OBS 再接続中... ({consecutive_failures + 1}回目)", False
                        )
                        try:
                            self.client = ReqClient(
                                host=self.config.websocket_host,
                                port=self.config.websocket_port,
                                password=self.config.websocket_password,
                                timeout=5,
                            )
                            self.client.get_version()
                            self.is_connected = True
                            self._emit_status(
                                f"OBS 再接続成功 ({self.config.websocket_host}:{self.config.websocket_port})",
                                True,
                            )
                            consecutive_failures = 0
                            self._apply_scene_collection()
                        except Exception:
                            self.is_connected = False
                            self.client = None
                            consecutive_failures += 1
                            time.sleep(self.reconnect_interval)
                            continue

            except Exception:
                logger.error(traceback.format_exc())
            time.sleep(check_interval)

    def _emit_status(self, message: str, is_connected: bool) -> None:
        self.is_connected = is_connected
        try:
            self.connection_changed.emit(is_connected, message)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # フレーム取得
    # ------------------------------------------------------------------

    def read_frame(self):
        """PIL Image を返す（失敗時は None）。

        直接キャプチャ: DxcamWindowCapture / DirectWindowCapture を使用。
        OBS WebSocket: OBS のスクリーンショット API 経由で取得。
        """
        from PIL import Image

        if self.is_direct_capture():
            if self.direct_capture is None and self.config:
                self.direct_capture = self._direct_capture_class()(self.config)
            if self.direct_capture is None:
                return None
            return self.direct_capture.read_frame()

        # OBS WebSocket 経由
        if not self.is_connected or not self.client:
            return None
        if not self.config or not self.config.monitor_source_name.strip():
            return None
        try:
            os.makedirs("out", exist_ok=True)
            dst = os.path.abspath("out/capture.png")
            self.client.save_source_screenshot(
                self.config.monitor_source_name,
                "png", dst,
                self.picw, self.pich, 100,
            )
            return Image.open(dst).convert("RGB")
        except Exception as e:
            logger.debug("OBS スクリーンショット取得失敗: %s", e)
            return None

    # ------------------------------------------------------------------
    # OBS 制御
    # ------------------------------------------------------------------

    @_require_connection
    def change_scene(self, name: str):
        self.client.set_current_program_scene(name)
        return True

    @_require_connection
    def start_recording(self):
        self.client.start_record()
        return True

    @_require_connection
    def stop_recording(self):
        self.client.stop_record()
        return True

    @_require_connection
    def start_streaming(self):
        self.client.start_stream()
        return True

    @_require_connection
    def stop_streaming(self):
        self.client.stop_stream()
        return True

    @_require_connection
    def set_source_visible(self, scene: str, source: str, visible: bool):
        """指定シーンのソースの表示・非表示を切り替える"""
        try:
            items = self.client.get_scene_item_list(scene).scene_items
            for item in items:
                if item.get("sourceName") == source:
                    self.client.set_scene_item_enabled(
                        scene, item["sceneItemId"], enabled=visible
                    )
                    return True
        except Exception as e:
            logger.error("set_source_visible エラー: %s", e)
        return None

    @_require_connection
    def get_scene_list(self) -> List[Dict]:
        res = self.client.get_scene_list()
        return res.scenes

    @_require_connection
    def get_scene_collection_list(self) -> List[str]:
        res = self.client.get_scene_collection_list()
        return res.scene_collections

    @_require_connection
    def get_source_list(self, scene: str) -> List[str]:
        """指定シーンのソース名一覧を返す"""
        ret = []
        try:
            all_items = self.client.get_scene_item_list(scene).scene_items
        except Exception:
            return ret
        for item in all_items:
            if item.get("isGroup"):
                try:
                    grp = self.client.get_group_scene_item_list(
                        item["sourceName"]
                    ).scene_items
                    for y in grp:
                        ret.append(y["sourceName"])
                except Exception:
                    pass
            ret.append(item["sourceName"])
        ret.reverse()
        return ret

    def _apply_scene_collection(self) -> None:
        if self._scene_collection_applied:
            return
        if not self.config or not self.config.obs_scene_collection:
            return
        try:
            self.client.set_current_scene_collection(self.config.obs_scene_collection)
            self._scene_collection_applied = True
        except Exception as e:
            logger.error("シーンコレクション切り替えエラー: %s", e)

    def get_status(self) -> tuple[str, bool]:
        if not self.config:
            return "設定未完了", False
        if self.is_direct_capture():
            self._probe_direct_capture_if_needed()
            status, ready = self._direct_capture_status()
            if self.is_connected:
                obs_status = (
                    f'<span style="color:#188038;">接続中</span> '
                    f'({self.config.websocket_host}:{self.config.websocket_port})'
                )
            elif self.uses_obs_websocket():
                obs_status = '<span style="color:#d93025;">未接続</span>'
            else:
                obs_status = '-'
            return f"{status} / OBS: {obs_status}", ready
        if not OBSWS_AVAILABLE:
            return "obsws_python がインストールされていません", False
        if not self.is_connected:
            return "OBS WebSocket: 未接続", False
        if not self.is_monitor_source_configured():
            return "OBS WebSocket: ソース未設定", False
        return (
            f"OBS WebSocket: 接続中 "
            f"({self.config.websocket_host}:{self.config.websocket_port})",
            True,
        )

    def _direct_capture_status(self) -> tuple[str, bool]:
        error = self.direct_capture.last_error if self.direct_capture else ""
        if error:
            if self.direct_capture and self.direct_capture.is_waiting_for_target():
                return f'直接取得: <span style="color:#5f6368;">ゲーム起動待ち</span> ({escape(error)})', False
            return f'直接取得: <span style="color:#d93025;">{escape(error)}</span>', False
        if not self.direct_capture or not self.direct_capture.has_successful_frame:
            return '直接取得: <span style="color:#5f6368;">未確認</span>', False
        return '直接取得: <span style="color:#188038;">OK</span>', True

    def _probe_direct_capture_if_needed(self) -> None:
        if not self.direct_capture:
            return
        if self.direct_capture.has_successful_frame:
            return
        now = time.monotonic()
        if (
            self.direct_capture.last_error and
            not self.direct_capture.is_waiting_for_target()
        ):
            return
        if now < self._next_direct_capture_probe_at:
            return
        self._next_direct_capture_probe_at = now + 3.0
        self.direct_capture.clear_pending_error()
        self.read_frame()
