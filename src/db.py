"""pop'n music Lively SQLite データベース管理モジュール

曲マスターテーブル (musics) と スコア管理テーブル (scores) を管理します。
"""
from __future__ import annotations

import csv
import difflib
import json
import os
import sqlite3
import unicodedata
import uuid
from typing import List, Optional, Tuple

from src.classes import PopnOptions, PopnScoreRecord
from src.logger import get_logger

logger = get_logger(__name__)

# CSV出力ヘッダー (11種の個別オプションに対応。使用オプション要約列は除外)
CSV_HEADERS = [
    "レベル",
    "曲名",
    "難易度区分",
    "SCORE",
    "COOL",
    "GREAT",
    "GOOD",
    "BAD",
    "COMBO",
    "HI-SPEED",
    "POP-KUN",
    "GAUGE TYPE",
    "GUIDE SE",
    "RANDOM",
    "JUDGE+",
    "HIDDEN",
    "SUDDEN",
    "OJAMA1",
    "OJAMA2",
    "AUTO",
    "プレー日時",
]


def _normalize_title(s: str) -> str:
    if not s:
        return ""
    s = s.replace("Ⓤ", "[UPPER]").replace("🪐", "●")
    s = unicodedata.normalize("NFKC", s)
    s = s.replace("～", "〜")
    return " ".join(s.split()).strip().lower()


# OCR 文字列との照合: これ未満の類似度は不一致とみなす
_MATCH_MIN_RATIO = 0.72
# OCR 文字列との照合: 次点の曲との類似度差がこれ未満なら、取り違えを避けて不一致とみなす
_MATCH_MIN_MARGIN = 0.08
# これ未満の文字数の曲名は 1 文字の誤読で別の曲になりうるので、完全一致のみ採用する
_MATCH_MIN_FUZZY_LEN = 4

_DIFFICULTY_COLUMNS = {"EASY": "easy", "NORMAL": "normal", "HYPER": "hyper", "EX": "ex"}


def _match_key(s: str) -> str:
    """OCR 文字列と曲名を突き合わせるためのキー。空白と波ダッシュ類の表記揺れを吸収する。"""
    s = _normalize_title(s)
    for ch in "〜∼˜":
        s = s.replace(ch, "~")
    return "".join(s.split())


class PopnDatabase:
    """SQLite データベース操作クラス"""

    def __init__(self, db_path: str = "popn.db"):
        self.db_path = db_path
        self._conn: Optional[sqlite3.Connection] = None
        self._match_index: Optional[dict[str, list[dict]]] = None  # match_music 用の曲名キー索引
        self._connect()
        self.init_tables()

    def _connect(self) -> None:
        try:
            self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            with self._conn:
                self._conn.execute("PRAGMA foreign_keys = ON;")
                self._conn.execute("PRAGMA journal_mode = WAL;")
        except Exception as e:
            logger.error("DB 接続エラー (%s): %s", self.db_path, e)
            raise

    def close(self) -> None:
        if self._conn:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None

    # ------------------------------------------------------------------
    # テーブル初期化 & マイグレーション
    # ------------------------------------------------------------------

    def init_tables(self) -> None:
        """曲テーブル (musics) および スコア管理テーブル (scores) を作成・マイグレーション"""
        with self._conn:
            # 1. 曲テーブル (musics)
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS musics (
                    music_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    genre TEXT DEFAULT '',
                    artist TEXT DEFAULT '',
                    ver TEXT DEFAULT '',
                    bpm TEXT DEFAULT '',
                    easy INTEGER,
                    normal INTEGER,
                    hyper INTEGER,
                    ex INTEGER,
                    pack TEXT DEFAULT ''
                );
                """
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_musics_title ON musics (title);"
            )

            # 2. スコア管理テーブル (scores) のマイグレーションチェック
            # level カラムの排除および11種類のオプションカラムの存在を確認
            cursor = self._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='scores';"
            )
            if cursor.fetchone():
                info_cur = self._conn.execute("PRAGMA table_info(scores);")
                columns = {row["name"] for row in info_cur.fetchall()}
                needs_migration = ("level" in columns) or ("gauge_type" not in columns)

                if needs_migration:
                    logger.info("スコアテーブルのマイグレーションを実行します (levelカラム削除 / オプション拡張)...")
                    self._conn.execute(
                        """
                        CREATE TABLE scores_new (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            music_id TEXT NOT NULL,
                            difficulty TEXT DEFAULT '',
                            score INTEGER DEFAULT 0,
                            cool INTEGER DEFAULT 0,
                            great INTEGER DEFAULT 0,
                            good INTEGER DEFAULT 0,
                            bad INTEGER DEFAULT 0,
                            combo INTEGER DEFAULT 0,
                            options_summary TEXT DEFAULT 'NORMAL',
                            hispeed TEXT DEFAULT 'OFF',
                            popkun TEXT DEFAULT 'NORMAL',
                            gauge_type TEXT DEFAULT 'NORMAL',
                            guide_se TEXT DEFAULT 'OFF',
                            random TEXT DEFAULT 'OFF',
                            judge_plus TEXT DEFAULT 'OFF',
                            hidden TEXT DEFAULT 'OFF',
                            sudden TEXT DEFAULT 'OFF',
                            ojama1 TEXT DEFAULT 'OFF',
                            ojama2 TEXT DEFAULT 'OFF',
                            auto TEXT DEFAULT 'OFF',
                            played_at TEXT NOT NULL,
                            FOREIGN KEY (music_id) REFERENCES musics (music_id)
                        );
                        """
                    )
                    # 既存カラムからデータ移行
                    gauge_col = "gauge" if "gauge" in columns else ("gauge_type" if "gauge_type" in columns else "'NORMAL'")
                    rand_col = "arrangement" if "arrangement" in columns else ("random" if "random" in columns else "'OFF'")
                    self._conn.execute(
                        f"""
                        INSERT INTO scores_new (
                            id, music_id, difficulty, score, cool, great, good, bad,
                            combo, options_summary, hispeed, popkun, gauge_type, random, played_at
                        )
                        SELECT 
                            id, music_id, difficulty, score, cool, great, good, bad,
                            combo, options_summary, hispeed, popkun, {gauge_col}, {rand_col}, played_at
                        FROM scores;
                        """
                    )
                    self._conn.execute("DROP TABLE scores;")
                    self._conn.execute("ALTER TABLE scores_new RENAME TO scores;")
                    logger.info("スコアテーブルのマイグレーション完了")

            # テーブルが存在しない場合の新規作成
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS scores (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    music_id TEXT NOT NULL,
                    difficulty TEXT DEFAULT '',
                    score INTEGER DEFAULT 0,
                    cool INTEGER DEFAULT 0,
                    great INTEGER DEFAULT 0,
                    good INTEGER DEFAULT 0,
                    bad INTEGER DEFAULT 0,
                    combo INTEGER DEFAULT 0,
                    options_summary TEXT DEFAULT 'NORMAL',
                    hispeed TEXT DEFAULT '1.0',
                    popkun TEXT DEFAULT 'NORMAL',
                    gauge_type TEXT DEFAULT 'NORMAL',
                    guide_se TEXT DEFAULT 'OFF',
                    random TEXT DEFAULT 'OFF',
                    judge_plus TEXT DEFAULT 'OFF',
                    hidden TEXT DEFAULT 'OFF',
                    sudden TEXT DEFAULT 'OFF',
                    ojama1 TEXT DEFAULT 'OFF',
                    ojama2 TEXT DEFAULT 'OFF',
                    auto TEXT DEFAULT 'OFF',
                    played_at TEXT NOT NULL,
                    FOREIGN KEY (music_id) REFERENCES musics (music_id)
                );
                """
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_scores_music_id ON scores (music_id);"
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_scores_played_at ON scores (played_at);"
            )

    # ------------------------------------------------------------------
    # 曲テーブルインポート (popn_music_list.json)
    # ------------------------------------------------------------------

    def import_music_list_json(
        self, json_path: str = "popn_music_list.json", update_json: bool = True
    ) -> int:
        """popn_music_list.json から曲データをインポートする。
        各曲に一意の UUID (music_id) を付与する。
        """
        if not os.path.exists(json_path):
            logger.warning("曲リスト JSON が見つかりません: %s", json_path)
            return 0

        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            logger.error("JSON 読み込みエラー (%s): %s", json_path, e)
            return 0

        if not isinstance(data, list):
            logger.error("JSON フォーマット不正 (リストではありません): %s", json_path)
            return 0

        existing_map = {}
        with self._conn:
            cursor = self._conn.execute(
                "SELECT music_id, title, genre, ver, artist FROM musics"
            )
            for row in cursor.fetchall():
                key = (row["title"], row["genre"], row["ver"], row["artist"])
                existing_map[key] = row["music_id"]

        json_modified = False
        records_to_insert: List[Tuple] = []

        for item in data:
            title = str(item.get("title", "")).strip()
            genre = str(item.get("genre", "")).strip()
            ver = str(item.get("ver", "")).strip()
            artist = str(item.get("artist", "")).strip()
            bpm = str(item.get("bpm", "")).strip()
            easy = item.get("easy")
            normal = item.get("normal")
            hyper = item.get("hyper")
            ex = item.get("ex")
            pack = str(item.get("pack", "")).strip()

            key = (title, genre, ver, artist)
            item_uuid = item.get("music_id") or item.get("uuid")
            if not item_uuid:
                if key in existing_map:
                    item_uuid = existing_map[key]
                else:
                    item_uuid = str(uuid.uuid4())
                item["music_id"] = item_uuid
                json_modified = True

            existing_map[key] = item_uuid

            records_to_insert.append(
                (
                    item_uuid,
                    title,
                    genre,
                    artist,
                    ver,
                    bpm,
                    int(easy) if easy is not None and str(easy).isdigit() else None,
                    int(normal) if normal is not None and str(normal).isdigit() else None,
                    int(hyper) if hyper is not None and str(hyper).isdigit() else None,
                    int(ex) if ex is not None and str(ex).isdigit() else None,
                    pack,
                )
            )

        with self._conn:
            self._conn.executemany(
                """
                INSERT INTO musics (
                    music_id, title, genre, artist, ver, bpm, easy, normal, hyper, ex, pack
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(music_id) DO UPDATE SET
                    title = excluded.title,
                    genre = excluded.genre,
                    artist = excluded.artist,
                    ver = excluded.ver,
                    bpm = excluded.bpm,
                    easy = excluded.easy,
                    normal = excluded.normal,
                    hyper = excluded.hyper,
                    ex = excluded.ex,
                    pack = excluded.pack;
                """,
                records_to_insert,
            )

        if update_json and json_modified:
            try:
                with open(json_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                logger.info("JSON に UUID を付与して保存しました: %s", json_path)
            except Exception as e:
                logger.error("JSON UUID 保存エラー: %s", e)

        self._match_index = None
        logger.info("曲テーブルに %d 件の曲をインポートしました", len(records_to_insert))
        return len(records_to_insert)

    def get_music_count(self) -> int:
        """曲テーブルのレコード数を取得"""
        with self._conn:
            cursor = self._conn.execute("SELECT COUNT(*) AS cnt FROM musics")
            row = cursor.fetchone()
            return row["cnt"] if row else 0

    # ------------------------------------------------------------------
    # 曲の検索・UUID解決
    # ------------------------------------------------------------------

    def find_music_id(
        self, title: str, difficulty: str = "", level: int | str = ""
    ) -> str:
        """曲名から曲テーブル (musics) の UUID (music_id) を解決する。
        該当が見つからない場合は自動的に新規 UUID を発行して曲テーブルに登録する。
        """
        title = (title or "Unknown").strip()
        norm_t = _normalize_title(title)

        with self._conn:
            cursor = self._conn.execute(
                "SELECT music_id, title, easy, normal, hyper, ex FROM musics WHERE title = ?",
                (title,),
            )
            rows = cursor.fetchall()

            if not rows:
                cursor = self._conn.execute(
                    "SELECT music_id, title, easy, normal, hyper, ex FROM musics"
                )
                all_rows = cursor.fetchall()
                matched = [r for r in all_rows if _normalize_title(r["title"]) == norm_t]
                if matched:
                    rows = matched

            if rows:
                if len(rows) == 1:
                    return rows[0]["music_id"]

                diff_code = difficulty.strip().upper()
                target_level = int(level) if str(level).isdigit() else None

                if target_level is not None:
                    for r in rows:
                        if diff_code in ("L", "EASY", "LIGHT") and r["easy"] == target_level:
                            return r["music_id"]
                        elif diff_code in ("N", "NORMAL") and r["normal"] == target_level:
                            return r["music_id"]
                        elif diff_code in ("H", "HYPER") and r["hyper"] == target_level:
                            return r["music_id"]
                        elif diff_code in ("E", "EX") and r["ex"] == target_level:
                            return r["music_id"]

                return rows[0]["music_id"]

            # 未登録曲の場合、曲テーブルに新規 UUID で登録
            new_id = str(uuid.uuid4())
            self._conn.execute(
                """
                INSERT INTO musics (music_id, title, genre, artist, ver, bpm, easy, normal, hyper, ex, pack)
                VALUES (?, ?, '', '', '', '', NULL, NULL, NULL, NULL, '');
                """,
                (new_id, title),
            )
            logger.info("未登録曲を曲テーブルに新規登録: [UUID: %s] %s", new_id, title)
            return new_id

    def match_music(self, text: str, difficulty: str = "") -> Optional[dict]:
        """OCR で読んだ曲名から曲テーブルの曲を特定する。

        完全一致を優先し、なければ類似度が最も高い曲を採用する。
        確信が持てない場合（類似度が低い・次点と僅差）は None を返す。
        戻り値には music_id / title / level (difficulty に対応するレベル) 等を含む。
        """
        key = _match_key(text)
        if not key:
            return None

        if self._match_index is None:
            with self._conn:
                rows = self._conn.execute(
                    "SELECT music_id, title, genre, easy, normal, hyper, ex, pack FROM musics"
                ).fetchall()
            index: dict[str, list[dict]] = {}
            for r in rows:
                index.setdefault(_match_key(r["title"]), []).append(dict(r))
            self._match_index = index

        candidates = self._match_index.get(key)
        if not candidates:
            if len(key) < _MATCH_MIN_FUZZY_LEN:
                return None
            matcher = difflib.SequenceMatcher(autojunk=False)
            matcher.set_seq2(key)
            best_key, best, second = "", 0.0, 0.0
            for cand in self._match_index:
                matcher.set_seq1(cand)
                if matcher.quick_ratio() <= second:
                    continue
                ratio = matcher.ratio()
                if ratio > best:
                    best_key, best, second = cand, ratio, best
                elif ratio > second:
                    second = ratio
            if best < _MATCH_MIN_RATIO or best - second < _MATCH_MIN_MARGIN:
                logger.debug(
                    "曲名照合: '%s' は不一致 (最良 '%s' %.2f / 次点 %.2f)", text, best_key, best, second
                )
                return None
            candidates = self._match_index[best_key]

        # 同名曲（ウラ譜面・LIVE版・カバー等）は、その難易度の譜面があり Lively 収録の曲を優先
        column = _DIFFICULTY_COLUMNS.get(difficulty.strip().upper())
        music = max(
            candidates,
            key=lambda m: (column is None or m[column] is not None, bool(m["pack"])),
        )
        if len(candidates) > 1:
            logger.info("曲名照合: '%s' は同名曲が %d 件あります", music["title"], len(candidates))
        return {**music, "level": music[column] if column and music[column] is not None else ""}

    # ------------------------------------------------------------------
    # スコア保存・読み込み
    # ------------------------------------------------------------------

    def save_score(self, record: PopnScoreRecord) -> int:
        """スコア記録を scores テーブルに保存する。
        曲情報および level は除き、UUID (music_id) とプレイ実績・11個のオプションを保存する。
        """
        music_id = record.music_id or self.find_music_id(
            record.title, record.difficulty_code, record.level
        )
        record.music_id = music_id

        with self._conn:
            cursor = self._conn.execute(
                """
                INSERT INTO scores (
                    music_id, difficulty, score, cool, great, good, bad,
                    combo, options_summary,
                    hispeed, popkun, gauge_type, guide_se, random,
                    judge_plus, hidden, sudden, ojama1, ojama2, auto,
                    played_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    music_id,
                    record.difficulty_code,
                    record.score,
                    record.cool,
                    record.great,
                    record.good,
                    record.bad,
                    record.combo,
                    record.options.to_summary(),
                    record.options.hispeed,
                    record.options.popkun,
                    record.options.gauge_type,
                    record.options.guide_se,
                    record.options.random,
                    record.options.judge_plus,
                    record.options.hidden,
                    record.options.sudden,
                    record.options.ojama1,
                    record.options.ojama2,
                    record.options.auto,
                    record.timestamp,
                ),
            )
            record_id = cursor.lastrowid
            record.record_id = record_id
            return record_id

    def load_scores(self) -> List[PopnScoreRecord]:
        """scores テーブルと musics テーブルを結合し、スコア履歴一覧を取得する。
        レベル情報は曲テーブルの難易度別レベルから導出します。
        """
        with self._conn:
            cursor = self._conn.execute(
                """
                SELECT 
                    s.id AS record_id,
                    s.music_id,
                    COALESCE(
                        CASE UPPER(s.difficulty)
                            WHEN 'L' THEN m.easy
                            WHEN 'EASY' THEN m.easy
                            WHEN 'N' THEN m.normal
                            WHEN 'NORMAL' THEN m.normal
                            WHEN 'H' THEN m.hyper
                            WHEN 'HYPER' THEN m.hyper
                            WHEN 'E' THEN m.ex
                            WHEN 'EX' THEN m.ex
                            ELSE ''
                        END,
                        ''
                    ) AS calc_level,
                    COALESCE(m.title, 'Unknown') AS title,
                    s.difficulty,
                    s.score,
                    s.cool,
                    s.great,
                    s.good,
                    s.bad,
                    s.combo,
                    s.options_summary,
                    s.hispeed,
                    s.popkun,
                    s.gauge_type,
                    s.guide_se,
                    s.random,
                    s.judge_plus,
                    s.hidden,
                    s.sudden,
                    s.ojama1,
                    s.ojama2,
                    s.auto,
                    s.played_at
                FROM scores s
                LEFT JOIN musics m ON s.music_id = m.music_id
                ORDER BY s.played_at ASC, s.id ASC;
                """
            )
            rows = cursor.fetchall()

        records: List[PopnScoreRecord] = []
        for r in rows:
            opt = PopnOptions(
                hispeed=r["hispeed"] if r["hispeed"] and r["hispeed"] != "OFF" else "1.0",
                popkun=r["popkun"] or "NORMAL",
                gauge_type=r["gauge_type"] or "NORMAL",
                guide_se=r["guide_se"] or "OFF",
                random=r["random"] or "OFF",
                judge_plus=r["judge_plus"] or "OFF",
                hidden=r["hidden"] or "OFF",
                sudden=r["sudden"] or "OFF",
                ojama1=r["ojama1"] or "OFF",
                ojama2=r["ojama2"] or "OFF",
                auto=r["auto"] or "OFF",
            )
            rec = PopnScoreRecord(
                title=r["title"],
                level=r["calc_level"] if r["calc_level"] is not None else "",
                difficulty=r["difficulty"],
                score=r["score"],
                cool=r["cool"],
                great=r["great"],
                good=r["good"],
                bad=r["bad"],
                combo=r["combo"],
                options=opt,
                timestamp=r["played_at"],
                music_id=r["music_id"],
                record_id=r["record_id"],
            )
            records.append(rec)
        return records

    def get_today_notes(self, date_str: str) -> int:
        """指定日 (YYYY-MM-DD) の総打鍵数を計算"""
        pattern = f"{date_str}%"
        with self._conn:
            cursor = self._conn.execute(
                """
                SELECT SUM(cool + great + good + bad) AS total
                FROM scores
                WHERE played_at LIKE ?;
                """,
                (pattern,),
            )
            row = cursor.fetchone()
            if row and row["total"] is not None:
                return int(row["total"])
        return 0

    # ------------------------------------------------------------------
    # CSV エクスポート・インポート
    # ------------------------------------------------------------------

    def export_csv(self, csv_path: str = "popn_score.csv") -> int:
        """scores と musics を結合して CSV ファイルを出力する"""
        records = self.load_scores()
        try:
            with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(CSV_HEADERS)
                for r in records:
                    writer.writerow(r.to_csv_row())
            logger.info("CSV エクスポート完了: %s (%d 件)", csv_path, len(records))
            return len(records)
        except Exception as e:
            logger.error("CSV エクスポートエラー (%s): %s", csv_path, e)
            raise

    def import_csv(self, csv_path: str = "popn_score.csv") -> int:
        """既存の CSV ファイルから scores テーブルへインポートする。
        旧形式 (15列) と新形式 (22列) の両方に対応します。
        """
        if not os.path.exists(csv_path):
            return 0

        try:
            with open(csv_path, "r", encoding="utf-8-sig") as f:
                reader = csv.reader(f)
                header = next(reader, None)
                if not header:
                    return 0

                col_map = {col.strip(): idx for idx, col in enumerate(header)}
                has_named_header = "曲名" in col_map or "SCORE" in col_map

                rows_to_save = []

                # 重複防止用
                with self._conn:
                    cursor = self._conn.execute("SELECT played_at, score FROM scores")
                    existing_scores = {(r["played_at"], r["score"]) for r in cursor.fetchall()}

                for row in reader:
                    if not row:
                        continue
                    try:
                        def get_val(col_name: str, fallback_idx: int = -1, default: str = "") -> str:
                            if has_named_header and col_name in col_map:
                                idx = col_map[col_name]
                                return row[idx] if idx < len(row) else default
                            if 0 <= fallback_idx < len(row):
                                return row[fallback_idx]
                            return default

                        def get_int(col_name: str, fallback_idx: int = -1, default: int = 0) -> int:
                            v = get_val(col_name, fallback_idx, "")
                            return int(v) if v.isdigit() else default

                        if has_named_header:
                            level           = get_val("レベル", 0, "")
                            title           = get_val("曲名", 1, "Unknown")
                            difficulty      = get_val("難易度区分", 2, "")
                            score           = get_int("SCORE", 3, 0)
                            cool            = get_int("COOL", 4, 0)
                            great           = get_int("GREAT", 5, 0)
                            good            = get_int("GOOD", 6, 0)
                            bad             = get_int("BAD", 7, 0)
                            combo           = get_int("COMBO", 8, 0)
                            hispeed         = get_val("HI-SPEED", -1) or get_val("Hi-speed", -1, "1.0")
                            if hispeed == "OFF":
                                hispeed = "1.0"
                            popkun          = get_val("POP-KUN", -1) or get_val("ポップ君", -1, "NORMAL")
                            gauge_type      = get_val("GAUGE TYPE", -1) or get_val("ゲージ", -1, "NORMAL")
                            guide_se        = get_val("GUIDE SE", -1, "OFF")
                            random          = get_val("RANDOM", -1) or get_val("配置", -1, "OFF")
                            judge_plus      = get_val("JUDGE+", -1, "OFF")
                            hidden          = get_val("HIDDEN", -1, "OFF")
                            sudden          = get_val("SUDDEN", -1, "OFF")
                            ojama1          = get_val("OJAMA1", -1, "OFF")
                            ojama2          = get_val("OJAMA2", -1, "OFF")
                            auto            = get_val("AUTO", -1, "OFF")
                            timestamp       = get_val("プレー日時", -1, "")
                            options_summary = get_val("使用オプション", -1, "NORMAL")
                        elif len(row) >= 21:
                            level           = row[0]
                            title           = row[1]
                            difficulty      = row[2]
                            score           = int(row[3]) if row[3].isdigit() else 0
                            cool            = int(row[4]) if row[4].isdigit() else 0
                            great           = int(row[5]) if row[5].isdigit() else 0
                            good            = int(row[6]) if row[6].isdigit() else 0
                            bad             = int(row[7]) if row[7].isdigit() else 0
                            combo           = int(row[8]) if row[8].isdigit() else 0
                            hispeed         = row[9]
                            popkun          = row[10]
                            gauge_type      = row[11]
                            guide_se        = row[12]
                            random          = row[13]
                            judge_plus      = row[14]
                            hidden          = row[15]
                            sudden          = row[16]
                            ojama1          = row[17]
                            ojama2          = row[18]
                            auto            = row[19]
                            timestamp       = row[20]
                            options_summary = "NORMAL"
                        elif len(row) >= 15:
                            level           = row[0]
                            title           = row[1]
                            difficulty      = row[2]
                            score           = int(row[3]) if row[3].isdigit() else 0
                            cool            = int(row[4]) if row[4].isdigit() else 0
                            great           = int(row[5]) if row[5].isdigit() else 0
                            good            = int(row[6]) if row[6].isdigit() else 0
                            bad             = int(row[7]) if row[7].isdigit() else 0
                            options_summary = row[8]
                            combo           = int(row[9]) if row[9].isdigit() else 0
                            hispeed         = row[10]
                            popkun          = row[11]
                            gauge_type      = row[12]
                            random          = row[13]
                            guide_se        = "OFF"
                            judge_plus      = "OFF"
                            hidden          = "OFF"
                            sudden          = "OFF"
                            ojama1          = "OFF"
                            ojama2          = "OFF"
                            auto            = "OFF"
                            timestamp       = row[14]
                        else:
                            if len(row) < 7:
                                continue
                            title       = row[0]
                            difficulty  = "E"
                            level       = ""
                            score       = int(row[1]) if row[1].isdigit() else 0
                            cool        = int(row[2]) if row[2].isdigit() else 0
                            great       = int(row[3]) if row[3].isdigit() else 0
                            good        = int(row[4]) if row[4].isdigit() else 0
                            bad         = int(row[5]) if row[5].isdigit() else 0
                            combo       = int(row[6]) if row[6].isdigit() else 0
                            options_summary = row[7] if len(row) > 7 else "NORMAL"
                            hispeed     = row[8] if len(row) > 8 else "OFF"
                            popkun      = row[9] if len(row) > 9 else "NORMAL"
                            gauge_type  = row[10] if len(row) > 10 else "NORMAL"
                            random      = row[11] if len(row) > 11 else "OFF"
                            guide_se    = "OFF"
                            judge_plus  = "OFF"
                            hidden      = "OFF"
                            sudden      = "OFF"
                            ojama1      = "OFF"
                            ojama2      = "OFF"
                            auto        = "OFF"
                            timestamp   = row[12] if len(row) > 12 else ""

                        if (timestamp, score) in existing_scores:
                            continue

                        # 曲テーブルから UUID を検索（level は検索の絞り込みにのみ使用）
                        music_id = self.find_music_id(title, difficulty, level)

                        rows_to_save.append(
                            (
                                music_id,
                                difficulty,
                                score,
                                cool,
                                great,
                                good,
                                bad,
                                combo,
                                options_summary,
                                hispeed,
                                popkun,
                                gauge_type,
                                guide_se,
                                random,
                                judge_plus,
                                hidden,
                                sudden,
                                ojama1,
                                ojama2,
                                auto,
                                timestamp,
                            )
                        )
                        existing_scores.add((timestamp, score))
                    except Exception as e:
                        logger.debug("CSV 行インポートスキップ: %s", e)
                        continue

                if rows_to_save:
                    with self._conn:
                        self._conn.executemany(
                            """
                            INSERT INTO scores (
                                music_id, difficulty, score, cool, great, good, bad,
                                combo, options_summary,
                                hispeed, popkun, gauge_type, guide_se, random,
                                judge_plus, hidden, sudden, ojama1, ojama2, auto,
                                played_at
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                            """,
                            rows_to_save,
                        )
                    logger.info("CSV から %d 件のスコアをインポートしました", len(rows_to_save))
                return len(rows_to_save)
        except Exception as e:
            logger.error("CSV インポートエラー: %s", e)
            return 0
