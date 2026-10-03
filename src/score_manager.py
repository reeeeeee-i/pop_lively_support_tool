"""pop'n music Lively スコア管理・SQLite/CSVマネージャー"""
from __future__ import annotations

import csv
import os
import time
from pathlib import Path
from typing import List, Optional

from src.classes import PopnOptions, PopnScoreRecord
from src.db import CSV_HEADERS, PopnDatabase
from src.logger import get_logger

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
        self.records: List[PopnScoreRecord] = []
        self.current_options: PopnOptions = PopnOptions()
        self.current_music_id: str = ""
        self.current_song_title: str = "Unknown"
        self.current_level: int | str = ""
        self.current_difficulty: str = ""
        self._last_saved_time: float = 0.0

        # 初回セットアップ: 曲テーブルが空なら JSON からインポート
        if self.db.get_music_count() == 0 and os.path.exists(self.music_json_path):
            logger.info("初回起動: 曲リスト JSON からインポートを開始します...")
            self.db.import_music_list_json(self.music_json_path)

        # スコア履歴読み込み
        self.load_from_db()

        # 既存 CSV があり、DB にスコアがまだない場合は移行
        if len(self.records) == 0 and os.path.exists(self.csv_path):
            logger.info("既存の CSV ファイルからスコア履歴を移行します: %s", self.csv_path)
            imported_count = self.db.import_csv(self.csv_path)
            if imported_count > 0:
                self.load_from_db()

    # ------------------------------------------------------------------
    # オプション・曲名・難易度管理
    # ------------------------------------------------------------------

    def set_current_options(self, options: PopnOptions) -> None:
        self.current_options = options
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
        music = self.db.match_music(text, difficulty)
        if music is None:
            return False
        self.current_music_id = music["music_id"]
        self.set_current_song_title(music["title"])
        self.set_current_chart(music["level"], difficulty)
        return True

    def reset_current_song(self) -> None:
        """次の曲に前曲の情報が誤適用されないよう曲名・レベル・難易度を初期化"""
        self.current_music_id = ""
        self.current_song_title = "Unknown"
        self.current_level = ""
        self.current_difficulty = ""

    def get_today_notes(self, date_str: str | None = None) -> int:
        """指定日（デフォルトは本日）の記録から総打鍵数を計算する"""
        from datetime import datetime
        target = date_str or datetime.now().strftime("%Y-%m-%d")
        return self.db.get_today_notes(target)

    def get_last_played_song(self) -> str:
        """最後にプレイした曲名を取得する（最新レコード）"""
        if self.records:
            last = self.records[-1]
            diff = last.difficulty_code
            if diff:
                return f"{last.title} [{diff}]"
            return last.title
        return ""

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
        if not record.music_id:
            record.music_id = self.current_music_id
        if record.title == "Unknown" and self.current_song_title != "Unknown":
            record.title = self.current_song_title
        if not record.level and self.current_level:
            record.level = self.current_level
        if not record.difficulty and self.current_difficulty:
            record.difficulty = self.current_difficulty
        if not record.options.to_summary() or record.options.to_summary() == "NORMAL":
            record.options = self.current_options

        # SQLite データベースへ保存 (曲情報は除き、UUID で曲テーブルと結合)
        record_id = self.db.save_score(record)
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

    def load_from_db(self) -> None:
        """SQLite DB から最新のスコア履歴を読み込む"""
        try:
            self.records = self.db.load_scores()
            logger.info("SQLite DB から %d 件のスコア履歴を読み込みました", len(self.records))
        except Exception as e:
            logger.error("DB スコア履歴読み込みエラー: %s", e)

    def load_csv(self) -> None:
        """互換性メソッド: DB から履歴を再読み込み"""
        self.load_from_db()

    # ------------------------------------------------------------------
    # CSV 出力・エクスポート
    # ------------------------------------------------------------------

    def export_csv(self, dest_path: Optional[str] = None) -> str:
        """スコア管理テーブルと曲テーブルを結合して CSV ファイルを出力する"""
        out_path = dest_path or self.csv_path
        self.db.export_csv(out_path)
        return out_path

    def open_csv(self) -> bool:
        """最新の DB 状態を CSV に出力し、システムの既定アプリケーション（Excel等）で開く"""
        try:
            self.export_csv(self.csv_path)
            os.startfile(os.path.abspath(self.csv_path))
            return True
        except Exception as e:
            logger.error("CSV ファイル起動エラー: %s", e)
            return False
