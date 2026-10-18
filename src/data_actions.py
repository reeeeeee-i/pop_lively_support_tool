"""データの管理メニュー (曲リストの更新・バックアップ・復元・インポート・エクスポート) の操作"""
from __future__ import annotations

import os
from datetime import datetime

from PySide6.QtCore import QEventLoop, QThread, Qt, Signal
from PySide6.QtWidgets import QFileDialog, QMessageBox, QProgressDialog

from src.logger import get_logger
from src.music_list_fetch import MusicList, MusicListFetchError, fetch_music_list, load_local_music_list
from src.score_manager import ScoreManager

logger = get_logger(__name__)

_DB_FILTER = "SQLite Database (*.db);;All Files (*)"
_JSON_FILTER = "JSON Files (*.json);;All Files (*)"  # 曲リスト用
_CSV_FILTER = "CSV Files (*.csv);;All Files (*)"


def _error(parent, title: str, e: Exception) -> None:
    logger.error("%s: %s", title, e)
    QMessageBox.critical(parent, title, f"{title}に失敗しました:\n{e}")


def _apply_music_list(parent, score_manager: ScoreManager, config, music_list: MusicList, title: str) -> bool:
    """検証済みの曲リストを曲テーブルに反映して、結果を知らせる。データが変わったら True。"""
    try:
        added, relinked = score_manager.apply_music_list(music_list.items)
    except Exception as e:
        _error(parent, "曲リストの更新", e)
        return False
    if music_list.serial is not None and music_list.serial > config.music_list_serial:
        config.music_list_serial = music_list.serial
        config.save_config()
    message = f"曲リストを更新しました ({len(music_list.items)} 曲)。\n\n追加された曲: {added} 曲"
    if added == 0:
        message += "\n(新しい曲はありませんでした)"
    if relinked:
        message += f"\n曲を特定できたスコア (これまで Unknown だったもの): {relinked} 件"
    if music_list.signed is not None:
        message += f"\n\n署名を確認しました (鍵 {music_list.signed.key_id} / 通し番号 {music_list.serial})"
    QMessageBox.information(parent, title, message)
    return relinked > 0


def update_music_list(parent, score_manager: ScoreManager, config) -> bool:
    """曲リスト JSON (popn_music_list.json の形式) を選び、曲テーブルを更新する。データが変わったら True。

    署名 (<ファイル>.sig) があれば検証し、不正なら取り込まない。署名が無いファイルは、確認のうえで取り込む。
    """
    start = score_manager.music_json_path if os.path.exists(score_manager.music_json_path) else ""
    path, _ = QFileDialog.getOpenFileName(parent, "曲リストの選択", start, _JSON_FILTER)
    if not path:
        return False
    try:
        music_list = load_local_music_list(path)
    except MusicListFetchError as e:
        QMessageBox.critical(parent, "曲リストの更新", f"曲リストを取り込めませんでした。\n\n{e}")
        return False
    if music_list.signed is None:
        answer = QMessageBox.warning(
            parent, "曲リストの更新",
            "この曲リストには署名 (.sig) がありません。作成者を確認できないため、内容が改ざんされていないかは分かりません。\n"
            "信頼できる入手元のファイルだけを取り込んでください。\n\n取り込みますか?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return False
    elif music_list.serial < config.music_list_serial:
        QMessageBox.critical(
            parent, "曲リストの更新",
            f"この曲リストは、取り込み済みのもの (通し番号 {config.music_list_serial}) より古い"
            f" (通し番号 {music_list.serial}) ため、取り込みません。",
        )
        return False
    return _apply_music_list(parent, score_manager, config, music_list, "曲リストの更新")


class _FetchThread(QThread):
    """曲リストの取得 (ネットワーク待ちで画面が固まらないよう別スレッドで行う)"""

    finished_with = Signal(object, str)   # (MusicList or None, エラーメッセージ)

    def __init__(self, url: str, last_serial: int, parent=None):
        super().__init__(parent)
        self._url = url
        self._last_serial = last_serial

    def run(self):
        try:
            self.finished_with.emit(fetch_music_list(self._url, self._last_serial), "")
        except MusicListFetchError as e:
            self.finished_with.emit(None, str(e))
        except Exception as e:   # 想定外のエラーも画面に出す
            self.finished_with.emit(None, f"{type(e).__name__}: {e}")


def update_music_list_from_url(parent, score_manager: ScoreManager, config) -> bool:
    """URL から曲リストを取得し、署名を検証してから曲テーブルを更新する。データが変わったら True。

    取得先へ接続するのは、確認に「はい」と答えたときだけ。署名が不正・無い曲リストは取り込まない。
    """
    url = config.music_list_url
    answer = QMessageBox.question(
        parent, "曲リストをURLから更新",
        f"次の URL から曲リストを取得します。\n\n{url}\n\n"
        "取得した曲リストは、開発者の署名を検証できたものだけを取り込みます。よろしいですか?",
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.Yes,
    )
    if answer != QMessageBox.StandardButton.Yes:
        return False

    progress = QProgressDialog("曲リストを取得しています...", None, 0, 0, parent)
    progress.setWindowTitle("曲リストをURLから更新")
    progress.setWindowModality(Qt.WindowModality.WindowModal)
    progress.setMinimumDuration(0)
    thread = _FetchThread(url, config.music_list_serial, parent)
    result: dict = {}
    loop = QEventLoop()

    def on_done(music_list, error):
        result["music_list"], result["error"] = music_list, error
        loop.quit()

    thread.finished_with.connect(on_done)
    thread.start()
    progress.show()
    loop.exec()
    progress.close()
    thread.wait()

    if result["music_list"] is None:
        QMessageBox.critical(parent, "曲リストをURLから更新", f"曲リストを取り込めませんでした。\n\n{result['error']}")
        return False
    return _apply_music_list(parent, score_manager, config, result["music_list"], "曲リストをURLから更新")


def create_backup(parent, score_manager: ScoreManager) -> None:
    """データベース全体 (スコア・曲テーブル・曲名の読み替え) をバックアップする。"""
    default = os.path.join(os.path.dirname(os.path.abspath(score_manager.db_path)), f"popn_backup_{datetime.now():%Y%m%d_%H%M%S}.db")
    path, _ = QFileDialog.getSaveFileName(parent, "バックアップの保存先", default, _DB_FILTER)
    if not path:
        return
    try:
        score_manager.backup(path)
    except Exception as e:
        _error(parent, "バックアップ", e)
        return
    QMessageBox.information(parent, "バックアップ", f"バックアップを作成しました:\n{path}")


def restore_backup(parent, score_manager: ScoreManager) -> bool:
    """バックアップでデータベースの中身を置き換える。復元したら True。"""
    path, _ = QFileDialog.getOpenFileName(parent, "バックアップの選択", "", _DB_FILTER)
    if not path:
        return False
    answer = QMessageBox.warning(
        parent, "バックアップから復元",
        "現在のスコア・曲テーブル・曲名の読み替えを、バックアップの内容で置き換えます。\n"
        "置き換える前の状態は、バックアップフォルダに自動で保存します。\n\n復元しますか?",
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No,
    )
    if answer != QMessageBox.StandardButton.Yes:
        return False
    try:
        safety_dir = os.path.join(os.path.dirname(os.path.abspath(score_manager.db_path)), "backup")
        os.makedirs(safety_dir, exist_ok=True)
        safety = os.path.join(safety_dir, f"popn_before_restore_{datetime.now():%Y%m%d_%H%M%S}.db")
        score_manager.backup(safety)
        score_manager.restore(path)
    except Exception as e:
        _error(parent, "復元", e)
        return False
    QMessageBox.information(
        parent, "バックアップから復元",
        f"復元しました ({len(score_manager.records)} 件のスコア)。\n復元前の状態: {safety}",
    )
    return True


def import_csv(parent, score_manager: ScoreManager) -> bool:
    """CSV からスコアを取り込む。取り込めたら True。"""
    path, _ = QFileDialog.getOpenFileName(parent, "インポートする CSV の選択", "", _CSV_FILTER)
    if not path:
        return False
    try:
        count = score_manager.import_csv(path)
    except Exception as e:
        _error(parent, "CSV インポート", e)
        return False
    QMessageBox.information(
        parent, "CSV インポート",
        f"{count} 件のスコアを取り込みました。\n(プレー日時とスコアが同じ記録は取り込み済みとして飛ばします)",
    )
    return count > 0
