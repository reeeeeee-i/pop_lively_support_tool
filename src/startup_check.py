"""起動時の更新確認 (アプリ本体と曲リスト)

曲リストは、署名を検証できた新しいものを確認なしで取り込む。
アプリ本体は、設定の更新チェック方式 (自動 / 通知) に従う。通知のときだけ「はい」「いいえ」で確認する。
どちらも結果がそろってから処理するので、起動時に出るダイアログは多くても 1 つ。
"""
from __future__ import annotations

from PySide6.QtCore import QObject, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QMessageBox

from src.app_version import get_app_version, is_frozen, is_newer
from src.data_actions import FetchThread, apply_music_list_quietly
from src.logger import get_logger
from src.music_list_fetch import MusicList
from src.update_dialog import CheckThread, UpdateController
from src.updater import ReleaseInfo

logger = get_logger(__name__)


def confirm_update(parent, release: ReleaseInfo, current: str) -> bool:
    """アプリ本体の更新を「はい」「いいえ」で確認する。更新するなら True。"""
    box = QMessageBox(parent)
    box.setWindowTitle("更新の確認")
    if release.notes:
        box.setDetailedText(release.notes)
    if not is_frozen():
        # ソース実行ではアプリ本体を自動更新できないため、リリースページへの案内だけにする
        box.setIcon(QMessageBox.Icon.Information)
        box.setText(
            f"新しいバージョン {release.tag} があります (現在 {current})。\n\n"
            "ソースから実行しているため、自動更新は使えません。リリースページから入手してください。"
        )
        btn_page = box.addButton("リリースページを開く", QMessageBox.ButtonRole.ActionRole)
        box.addButton("あとで", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is btn_page:
            QDesktopServices.openUrl(QUrl(release.page_url))
        return False
    size_mb = f"約 {release.size / 1024 / 1024:.0f} MB" if release.size else "サイズ不明"
    box.setIcon(QMessageBox.Icon.Question)
    box.setText(
        f"新しいバージョン {release.tag} があります (現在 {current})。\n"
        f"更新ファイルをダウンロード ({size_mb}) して、アプリを再起動します。\n"
        "開発者の署名を確認しました。\n\n設定・スコア・ログなどのデータは引き継がれます。更新しますか?"
    )
    box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
    box.setDefaultButton(QMessageBox.StandardButton.Yes)
    return box.exec() == QMessageBox.StandardButton.Yes


class StartupUpdateCheck(QObject):
    """アプリ本体と曲リストを並行して確認し、結果がそろってから処理する。

    on_data_changed: 曲リストの取り込みでスコアの紐づけが変わったときに呼ぶ (メイン画面の表示を合わせるため)。
    """

    def __init__(self, parent, config, score_manager, updater: UpdateController, on_data_changed=None):
        super().__init__(parent)
        self._parent = parent
        self._config = config
        self._score_manager = score_manager
        self._updater = updater
        self._on_data_changed = on_data_changed
        self._waiting: set[str] = set()
        self._release: ReleaseInfo | None = None
        self._music_list: MusicList | None = None
        self._threads: list = []

    def start(self) -> None:
        if self._waiting:
            return
        if self._config.update_check_mode != "off":
            self._waiting.add("app")
            thread = CheckThread(self)
            thread.finished_with.connect(self._on_release)
            self._run(thread)
        self._waiting.add("music")
        thread = FetchThread(self._config.music_list_url, self._config.music_list_serial, self)
        thread.finished_with.connect(self._on_music_list)
        self._run(thread)

    def _run(self, thread) -> None:
        self._threads.append(thread)
        thread.start()

    def _on_release(self, release: ReleaseInfo | None, error: str) -> None:
        if release is None:
            logger.info("起動時の更新の確認に失敗: %s", error)
        self._release = release
        self._done("app")

    def _on_music_list(self, music_list: MusicList | None, error: str) -> None:
        if music_list is None:
            logger.info("起動時の曲リストの確認に失敗: %s", error)
        self._music_list = music_list
        self._done("music")

    def _done(self, key: str) -> None:
        self._waiting.discard(key)
        if not self._waiting:
            self._threads.clear()
            self._finish()

    def _finish(self) -> None:
        config = self._config
        music_list = self._music_list
        if music_list is not None and (music_list.serial is None or music_list.serial <= config.music_list_serial):
            logger.info("曲リストは最新です (通し番号 %s)", config.music_list_serial)
            music_list = None

        # 曲リストを先に取り込む (アプリ本体の更新は、適用するとアプリが終了するため最後)
        if music_list is not None:
            relinked = apply_music_list_quietly(self._score_manager, config, music_list)
            if relinked is None:
                QMessageBox.warning(self._parent, "曲リストの更新", "曲リストを取り込めませんでした。詳しくはログを確認してください。")
            elif relinked and self._on_data_changed is not None:
                self._on_data_changed()

        release = self._release
        current = get_app_version()
        if release is None or not is_newer(release.tag, current):
            return
        if config.update_check_mode == "auto" and is_frozen():
            logger.info("新しいバージョン %s を自動で適用します", release.tag)
            self._updater.apply_release(release)
        elif self._should_notify(release) and confirm_update(self._parent, release, current):
            self._updater.apply_release(release)

    def _should_notify(self, release: ReleaseInfo) -> bool:
        """起動時に、この版を知らせるか (「通知済みの版は再通知しない」の設定を反映する)。"""
        config = self._config
        notified = config.update_notified_tag
        if config.update_skip_until_next and notified and not is_newer(release.tag, notified):
            logger.info("バージョン %s は通知済みのため、起動時の案内を省略します", release.tag)
            return False
        if notified != release.tag:
            config.update_notified_tag = release.tag
            config.save_config()
        return True
