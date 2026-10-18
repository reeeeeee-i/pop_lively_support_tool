"""pop'n music Lively スコア管理・SQLite/CSVマネージャー"""
from __future__ import annotations

import os
import time
from datetime import datetime

from src.classes import DIFFICULTY_LEVEL_COLUMNS, PopnOptions, PopnScoreRecord, difficulty_code
from src.db import PopnDatabase
from src.logger import get_logger
from src.score_stats import ScoreComparison, compare_with_best, describe_chart, summarize_chart

logger = get_logger(__name__)


class ScoreManager:
    """スコア記録（SQLite）、CSV出力、オプション管理クラス"""

    def __init__(
        self,
        db_path: str = "popn.db",
        csv_path: str = "popn_score.csv",
        music_json_path: str = "popn_music_list.json",
    ):
        self.db_path = db_path
        self.csv_path = csv_path
        self.music_json_path = music_json_path

        self.db = PopnDatabase(self.db_path)
        self.records: list[PopnScoreRecord] = []
        self.current_options: PopnOptions = PopnOptions()
        self.current_music_id: str = ""
        self.current_song_title: str = "Unknown"
        self.current_genre: str = ""
        self.current_level: int | str = ""
        self.current_difficulty: str = ""
        self.current_ocr_text: str = ""
        """プレー画面から OCR で読んだ曲名 (未照合)"""
        self.last_unidentified_record: PopnScoreRecord | None = None
        """直近に保存したスコアが曲を特定できていないもの (特定できていれば None)"""
        self._last_saved_time: float = 0.0
        self.last_comparison: ScoreComparison | None = None
        """直近に保存したスコアと、それまでのベストとの比較 (曲を特定できていなければ None)"""

        # 曲リスト JSON を曲テーブルに反映 (music_id で上書き更新)。
        # 未登録曲の自動登録で曲テーブルが空でなくなっていても、JSON の曲が欠けないよう毎回行う
        if os.path.exists(self.music_json_path):
            self.db.import_music_list_json(self.music_json_path)
        else:
            logger.warning("曲リスト JSON が見つかりません: %s", os.path.abspath(self.music_json_path))

        # スコア履歴読み込み
        self.load_from_db()

        # 既存 CSV があり、DB にスコアがまだない場合は移行
        if len(self.records) == 0 and os.path.exists(self.csv_path):
            logger.info("既存の CSV ファイルからスコア履歴を移行します: %s", self.csv_path)
            try:
                imported_count = self.db.import_csv(self.csv_path)
            except Exception:
                imported_count = 0   # 詳細は db 側でログ済み。起動は続ける
            if imported_count > 0:
                self.load_from_db()

    # ------------------------------------------------------------------
    # オプション・曲名・難易度管理
    # ------------------------------------------------------------------

    def set_current_options(self, options: PopnOptions) -> None:
        self.current_options = self.db.normalize_options(options)
        logger.info("使用オプション更新: %s", options.to_summary())

    def set_current_song_title(self, title: str) -> None:
        if title and title != "Unknown":
            self.current_song_title = title
            logger.info("現在のプレー曲名設定: %s", title)

    def set_current_chart(self, level: int | str = "", difficulty: str = "") -> None:
        self.current_level = level
        self.current_difficulty = difficulty
        logger.info("現在の譜面設定: レベル %s / 難易度 %s", level, difficulty)

    def identify_song(self, text: str, difficulty: str = "") -> bool:
        """プレー画面から読んだ曲名 (OCR 文字列) と難易度区分から曲を特定し、現在の曲として設定する。

        曲テーブルに該当曲が見つからなければ何も変更せず False を返す。
        """
        self.current_ocr_text = text
        music = self.db.match_music(text, difficulty)
        if music is None:
            return False
        self.current_music_id = music["music_id"]
        self.set_current_song_title(music["title"])
        self.current_genre = music.get("genre") or ""
        self.set_current_chart(music["level"], difficulty)
        return True

    def identify_banner(self, feature) -> str:
        """オプション画面から読んだバナーの特徴量から曲を特定し、music_id を返す。特定できなければ空文字。"""
        found = self.db.match_banner(feature)
        if found is None:
            return ""
        logger.info("バナー照合: %s (相関 %.3f / 2 位との差 %.3f)", found["music_id"], found["score"], found["margin"])
        return found["music_id"]

    def identify_music(self, music_id: str, difficulty: str = "") -> bool:
        """music_id (バナー照合で特定した曲) と難易度区分から、現在の曲を設定する。曲が見つからなければ False。"""
        music = self.db.music_with_level(music_id, difficulty)
        if music is None:
            return False
        self.current_music_id = music["music_id"]
        self.set_current_song_title(music["title"])
        self.current_genre = music.get("genre") or ""
        self.set_current_chart(music["level"], difficulty)
        return True

    def reset_current_song(self) -> None:
        """次の曲に前曲の情報が誤適用されないよう曲名・レベル・難易度を初期化"""
        self.current_music_id = ""
        self.current_song_title = "Unknown"
        self.current_genre = ""
        self.current_level = ""
        self.current_difficulty = ""
        self.current_ocr_text = ""

    def assign_song(self, music: dict, difficulty: str = "") -> bool:
        """曲を手動で選んだ結果を反映する (曲を特定できなかったときの救済)。

        現在のプレー曲にし、OCR で読んだ曲名を読み替えとして学習する。直近のスコアが曲を特定できないまま
        記録されていれば、その曲に付け替える。付け替えたら True。
        """
        difficulty = difficulty or self.current_difficulty
        level = music.get(DIFFICULTY_LEVEL_COLUMNS.get(difficulty_code(difficulty), ""), "") or ""
        self.current_music_id = music["music_id"]
        self.set_current_song_title(music["title"])
        self.current_genre = music.get("genre") or ""
        self.set_current_chart(level, difficulty)
        if self.current_ocr_text:
            self.db.add_alias(self.current_ocr_text, music["music_id"])

        record = self.last_unidentified_record
        if record is None or record.record_id is None:
            return False
        self.db.set_music(record.record_id, music["music_id"], difficulty_code(difficulty))
        self.last_unidentified_record = None
        self.load_from_db()
        return True

    def learn_alias(self, ocr_text: str, music_id: str) -> int:
        """OCR で読んだ曲名を曲の読み替えとして学習し、同じ読み取りで Unknown だったスコアも直す。直した件数を返す。"""
        if not self.db.add_alias(ocr_text, music_id):
            return 0
        relinked = self.db.relink_unknown_scores()
        if relinked:
            self.load_from_db()
        return relinked

    def safety_backup(self, label: str, keep: int = 5) -> str:
        """データを書き換える操作の前に、データベースを backup フォルダへ自動で保存する。古いものは keep 件だけ残す。"""
        folder = os.path.join(os.path.dirname(os.path.abspath(self.db_path)), "backup")
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, f"popn_before_{label}_{datetime.now():%Y%m%d_%H%M%S}.db")
        self.db.backup_to(path)
        old = sorted(f for f in os.listdir(folder) if f.startswith(f"popn_before_{label}_") and f.endswith(".db"))
        for name in old[:-keep]:
            try:
                os.remove(os.path.join(folder, name))
            except OSError:
                pass
        return path

    def apply_music_list(self, items: list[dict]) -> tuple[int, int]:
        """検証済みの曲の配列で曲テーブルを更新する。(追加された曲数, 曲を特定できたスコア数) を返す。"""
        import json
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "popn_music_list.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(items, f, ensure_ascii=False)
            return self.update_music_list(path)

    def update_music_list(self, json_path: str) -> tuple[int, int]:
        """曲リスト JSON で曲テーブルを更新する。(追加された曲数, 曲を特定できたスコア数) を返す。

        同じ曲 (曲名・ジャンル・ver・アーティストが同じ) は更新し、新曲は追加する。
        そのうえで、Unknown で記録されていたスコアを照合し直す。
        """
        self.safety_backup("musiclist")   # 万一のときに戻せるよう、更新の前にデータベースを保存する
        before = self.db.get_music_count()
        if self.db.import_music_list_json(json_path, update_json=False) == 0:
            raise ValueError("曲を読み込めませんでした (popn_music_list.json の形式を確認してください)")
        added = self.db.get_music_count() - before
        relinked = self.db.relink_unknown_scores()
        if relinked:
            self.load_from_db()
        return added, relinked

    def get_today_notes(self, date_str: str | None = None) -> int:
        """指定日（デフォルトは本日）の記録から総打鍵数を計算する"""
        return self.db.get_today_notes(date_str or datetime.now().strftime("%Y-%m-%d"))

    def describe_current_chart(self) -> str:
        """現在のプレー曲のこれまでの成績 (ベスト・前回・プレー回数)。曲を特定できていなければ空文字。"""
        if not self.current_music_id:
            return ""
        code = difficulty_code(self.current_difficulty)
        return describe_chart(summarize_chart(self.records, self.current_music_id, code))

    def get_last_played_song(self) -> tuple[str, str, str] | None:
        """最後にプレイした曲の (曲名, ジャンル名, 難易度区分) を取得する（最新レコード）"""
        if not self.records:
            return None
        last = self.records[-1]
        return last.title, last.genre, last.difficulty

    # ------------------------------------------------------------------
    # レコード追加・DB保存
    # ------------------------------------------------------------------

    def add_record(self, record: PopnScoreRecord, min_interval_sec: float = 5.0) -> bool:
        """スコア記録を SQLite DB に保存する。

        連続保存防止のため、前回の保存から min_interval_sec 以内の場合は重複とみなしスキップ。
        """
        now = time.time()
        if (now - self._last_saved_time) < min_interval_sec:
            logger.debug("連続保存抑止のためスキップ (%.1f 秒経過)", now - self._last_saved_time)
            return False

        # 曲名や譜面情報、オプションの補完
        unidentified = not record.music_id and not self.current_music_id
        if not record.music_id:
            record.music_id = self.current_music_id
        if record.title == "Unknown" and self.current_song_title != "Unknown":
            record.title = self.current_song_title
        if not record.level and self.current_level:
            record.level = self.current_level
        if not record.difficulty and self.current_difficulty:
            record.difficulty = self.current_difficulty
        if record.options.to_summary() == "NORMAL":
            record.options = self.current_options
        # オプション値をマスターの表記に揃える
        self.db.normalize_options(record.options)

        # 今回の記録を足す前の履歴で、その譜面のベストと比べる
        self.last_comparison = compare_with_best(self.records, record)

        # SQLite データベースへ保存 (曲情報は除き、UUID で曲テーブルと結合)
        record_id = self.db.save_score(record)
        # 履歴一覧は self.records をそのまま表示するため、曲テーブル側の情報も埋めておく
        music = self.db.get_music(record.music_id)
        if music:
            record.genre = music["genre"] or ""
            record.artist = music["artist"] or ""
            record.ver = music["ver"] or ""
        if self.current_ocr_text:
            record.ocr_title = self.current_ocr_text
            self.db.set_ocr_title(record_id, self.current_ocr_text)
        self.last_unidentified_record = record if unidentified else None
        self.records.append(record)
        self._last_saved_time = now

        logger.info(
            "スコア記録保存 (DB ID:%d, UUID:%s): [Lv%s %s] %s - SCORE:%d (COOL:%d, GREAT:%d, GOOD:%d, BAD:%d, COMBO:%d, OPT:%s)",
            record_id,
            record.music_id,
            record.level,
            record.difficulty_code,
            record.title,
            record.score,
            record.cool,
            record.great,
            record.good,
            record.bad,
            record.combo,
            record.options.to_summary(),
        )
        return True

    def set_screenshot_file(self, record: PopnScoreRecord, filename: str) -> None:
        """記録にスクリーンショットのファイル名を紐づける。"""
        if record.record_id is None:
            return
        self.db.set_screenshot_file(record.record_id, filename)
        record.screenshot_file = filename

    def update_record(self, record: PopnScoreRecord) -> None:
        """手動修正したスコア記録を DB に反映し、履歴を読み込み直す。"""
        self.db.update_score(record)
        logger.info("スコア記録修正 (DB ID:%s): %s - SCORE:%d", record.record_id, record.title, record.score)
        self.load_from_db()

    def delete_records(self, records: list[PopnScoreRecord]) -> None:
        """スコア記録を DB から削除し、履歴を読み込み直す。"""
        ids = [r.record_id for r in records if r.record_id is not None]
        if len(ids) != len(records):
            raise ValueError("record_id の無いレコードは削除できません")
        self.db.delete_scores(ids)
        for r in records:
            logger.info("スコア記録削除 (DB ID:%s): %s - SCORE:%d", r.record_id, r.title, r.score)
        self.load_from_db()

    def load_from_db(self) -> None:
        """SQLite DB から最新のスコア履歴を読み込む"""
        try:
            self.records = self.db.load_scores()
            logger.info("SQLite DB から %d 件のスコア履歴を読み込みました", len(self.records))
        except Exception as e:
            logger.error("DB スコア履歴読み込みエラー: %s", e)

    # ------------------------------------------------------------------
    # バックアップ・復元・インポート
    # ------------------------------------------------------------------

    def backup(self, dest_path: str) -> None:
        """データベース全体 (スコア・曲テーブル・曲名の読み替え) をバックアップする。"""
        self.db.backup_to(dest_path)

    def restore(self, src_path: str) -> None:
        """バックアップでデータベースの中身を置き換え、履歴を読み込み直す。"""
        self.db.restore_from(src_path)
        self.last_unidentified_record = None
        self.load_from_db()

    # ------------------------------------------------------------------
    # CSV 出力・エクスポート
    # ------------------------------------------------------------------

    def export_csv(self, dest_path: str | None = None) -> str:
        """スコア管理テーブルと曲テーブルを結合して CSV ファイルを出力する"""
        out_path = dest_path or self.csv_path
        self.db.export_csv(out_path)
        return out_path

    def import_csv(self, src_path: str) -> int:
        """CSV ファイルからスコアを取り込み、履歴を読み込み直す。取り込んだ件数を返す"""
        count = self.db.import_csv(src_path)
        if count > 0:
            self.load_from_db()
        return count

    def open_csv(self) -> bool:
        """最新の DB 状態を CSV に出力し、システムの既定アプリケーション（Excel等）で開く"""
        try:
            self.export_csv(self.csv_path)
            os.startfile(os.path.abspath(self.csv_path))
            return True
        except Exception as e:
            logger.error("CSV ファイル起動エラー: %s", e)
            return False
