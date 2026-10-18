"""自動更新の画面操作 (確認・ダウンロード・適用)"""
from __future__ import annotations

import os
import traceback
from typing import Callable

from PySide6.QtCore import QObject, QThread, QUrl, Qt, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QMessageBox, QProgressDialog

from src import updater
from src.app_version import get_app_version, is_frozen, is_newer
from src.logger import get_logger
from src.updater import ReleaseInfo, UpdateError

logger = get_logger(__name__)


class _CheckThread(QThread):
    """最新リリースの確認 (ネットワーク待ちで画面が固まらないよう別スレッドで行う)"""

    finished_with = Signal(object, str)   # (ReleaseInfo or None, エラーメッセージ)

    def run(self):
        try:
            self.finished_with.emit(updater.fetch_latest_release(), "")
        except UpdateError as e:
            self.finished_with.emit(None, str(e))
        except Exception as e:
            self.finished_with.emit(None, f"{type(e).__name__}: {e}")


class _DownloadThread(QThread):
    """更新ファイルのダウンロードと展開"""

    progress = Signal(int, int, str)   # (済, 全体, 段階の名前)
    finished_with = Signal(str, str)   # (展開先のフォルダ or "", エラーメッセージ)

    def __init__(self, release: ReleaseInfo, stage: str, parent=None):
        super().__init__(parent)
        self._release = release
        self._stage = stage
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        try:
            zip_path = os.path.join(self._stage, "update.zip")   # 添付ファイル名は使わず、固定の名前にする
            updater.download(
                self._release.asset_url, zip_path, self._release.size, self._release.sha256,
                progress=lambda done, total: self.progress.emit(done, total, "ダウンロード中"),
                cancelled=lambda: self._cancelled,
            )
            extracted = os.path.join(self._stage, "extracted")
            updater.extract(zip_path, extracted, lambda done, total: self.progress.emit(done, total, "展開中"))
            os.remove(zip_path)
            self.finished_with.emit(updater.find_app_root(extracted), "")
        except UpdateError as e:
            self.finished_with.emit("", str(e))
        except Exception as e:
            logger.error(traceback.format_exc())
            self.finished_with.emit("", f"{type(e).__name__}: {e}")


class UpdateController(QObject):
    """更新の確認から適用までを進める。適用するときは、アプリを終了するため quit_app を呼ぶ。"""

    def __init__(self, parent, quit_app: Callable[[], None], config=None):
        super().__init__(parent)
        self._parent = parent
        self._config = config
        self._startup = False
        self._quit_app = quit_app
        self._check_thread: _CheckThread | None = None
        self._download_thread: _DownloadThread | None = None
        self._silent = False
        self._busy = False

    # ------------------------------------------------------------------
    # 確認
    # ------------------------------------------------------------------

    def check(self, silent: bool = False, startup: bool = False) -> None:
        """最新バージョンを確認する。silent=True (起動時の自動確認) は、新しい版があるときだけ知らせる。
        startup=True は起動時の確認で、設定の更新チェック方式 (自動適用 / 通知のみ) に従う。"""
        if self._busy:
            return
        self._busy = True
        self._silent = silent
        self._startup = startup
        self._check_thread = _CheckThread(self)
        self._check_thread.finished_with.connect(self._on_checked)
        self._check_thread.start()

    def _on_checked(self, release: ReleaseInfo | None, error: str):
        self._busy = False
        current = get_app_version()
        if release is None:
            logger.info("更新の確認に失敗: %s", error)
            if not self._silent:
                QMessageBox.warning(self._parent, "更新の確認", error)
            return
        if not is_newer(release.tag, current):
            if not self._silent:
                QMessageBox.information(
                    self._parent, "更新の確認", f"最新バージョンです (バージョン {current})。"
                )
            return
        if self._startup and self._config is not None:
            if self._config.update_check_mode == "auto" and is_frozen():
                logger.info("新しいバージョン %s を自動で適用します", release.tag)
                self._download(release)
                return
            notified = self._config.update_notified_tag
            if self._config.update_skip_until_next and notified and not is_newer(release.tag, notified):
                logger.info("バージョン %s は通知済みのため、起動時の案内を省略します", release.tag)
                return
            if notified != release.tag:
                self._config.update_notified_tag = release.tag
                self._config.save_config()
        self._offer_update(release, current)

    # ------------------------------------------------------------------
    # 更新の案内・ダウンロード
    # ------------------------------------------------------------------

    def _offer_update(self, release: ReleaseInfo, current: str) -> None:
        box = QMessageBox(self._parent)
        box.setWindowTitle("更新の確認")
        box.setIcon(QMessageBox.Icon.Information)
        size_mb = f"約 {release.size / 1024 / 1024:.0f} MB" if release.size else "サイズ不明"
        if is_frozen():
            box.setText(
                f"新しいバージョン {release.tag} があります (現在 {current})。\n"
                f"更新ファイルをダウンロード ({size_mb}) して、アプリを再起動します。\n"
                f"開発者の署名を確認しました (鍵 {release.key_id})。\n\n"
                "設定・スコア・ログなどのデータは引き継がれます。更新しますか?"
            )
            btn_update = box.addButton("更新して再起動", QMessageBox.ButtonRole.AcceptRole)
        else:
            box.setText(
                f"新しいバージョン {release.tag} があります (現在 {current})。\n\n"
                "ソースから実行しているため、自動更新は使えません。リリースページから入手してください。"
            )
            btn_update = None
        btn_page = box.addButton("リリースページを開く", QMessageBox.ButtonRole.ActionRole)
        box.addButton("あとで", QMessageBox.ButtonRole.RejectRole)
        if release.notes:
            box.setDetailedText(release.notes)
        box.exec()
        clicked = box.clickedButton()
        if clicked is btn_page:
            QDesktopServices.openUrl(QUrl(release.page_url))
        elif btn_update is not None and clicked is btn_update:
            self._download(release)

    def _download(self, release: ReleaseInfo) -> None:
        try:
            stage = updater.prepare_staging()
        except UpdateError as e:
            QMessageBox.warning(self._parent, "更新", str(e))
            return

        progress = QProgressDialog("更新ファイルを準備しています...", "キャンセル", 0, 100, self._parent)
        progress.setWindowTitle("更新")
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.setAutoClose(False)
        progress.setAutoReset(False)

        thread = self._download_thread = _DownloadThread(release, stage, self)

        def on_progress(done: int, total: int, phase: str):
            progress.setLabelText(f"{phase} ({done / 1024 / 1024:.0f} / {total / 1024 / 1024:.0f} MB)"
                                  if phase == "ダウンロード中" else f"{phase} ({done} / {total})")
            progress.setMaximum(max(total, 1))
            progress.setValue(done)

        def on_finished(root: str, error: str):
            progress.close()
            if error:
                if error != "キャンセルしました":
                    QMessageBox.critical(self._parent, "更新", f"更新できませんでした。\n\n{error}")
                self._cleanup(stage)
                return
            self._apply(root, stage)

        thread.progress.connect(on_progress)
        thread.finished_with.connect(on_finished)
        progress.canceled.connect(thread.cancel)
        thread.start()
        progress.show()

    # ------------------------------------------------------------------
    # 適用
    # ------------------------------------------------------------------

    def _apply(self, source: str, stage: str) -> None:
        try:
            updater.launch_update_script(os.getpid(), source, updater.app_dir(), stage)
        except Exception as e:
            logger.error(traceback.format_exc())
            QMessageBox.critical(self._parent, "更新", f"更新を開始できませんでした。\n\n{e}")
            self._cleanup(stage)
            return
        QMessageBox.information(
            self._parent, "更新", "更新を適用するため、アプリを終了します。\n終了後、自動で更新して再起動します。"
        )
        self._quit_app()

    @staticmethod
    def _cleanup(stage: str) -> None:
        import shutil
        shutil.rmtree(stage, ignore_errors=True)
