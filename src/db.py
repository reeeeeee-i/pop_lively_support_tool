"""pop'n music Lively SQLite データベース管理モジュール

曲マスターテーブル (musics)、オプションマスターテーブル (option_masters)、
スコア管理テーブル (scores) を管理します。
"""
from __future__ import annotations

import csv
import difflib
import json
import os
import sqlite3
import unicodedata
import uuid

from src.classes import DIFFICULTY_LEVEL_COLUMNS, PopnOptions, PopnScoreRecord, difficulty_code
from src.logger import get_logger
from src.option_master import (
    OPTION_DEFAULTS,
    OPTION_KEYS,
    OPTION_LABELS,
    OPTION_MASTER,
    OPTION_NAMES,
    normalize_option,
)

logger = get_logger(__name__)

# CSV 出力ヘッダー
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
    *(OPTION_LABELS[key] for key in OPTION_KEYS),
    "プレー日時",
]

# scores テーブルに保存する列 (id / modified 以外)。INSERT の列順
_SCORE_COLUMNS = (
    "music_id", "difficulty", "score", "cool", "great", "good", "bad", "combo",
    "options_summary", *OPTION_KEYS, "played_at",
)
_INSERT_SCORE_SQL = (
    f"INSERT INTO scores ({', '.join(_SCORE_COLUMNS)})"
    f" VALUES ({', '.join('?' * len(_SCORE_COLUMNS))});"
)
# 修正時に上書きする列 (プレー日時は変えない)
_UPDATE_COLUMNS = _SCORE_COLUMNS[:-1]

# scores テーブルの定義。後から追加した列 (_SCORES_ADDED_COLUMNS) は ALTER TABLE で足す
_SCORES_DDL = """
    CREATE TABLE {table} (
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
_SCORES_ADDED_COLUMNS = (
    ("modified", "INTEGER DEFAULT 0"),  # 修正済フラグ
    ("ojama1_zutto", "TEXT DEFAULT 'OFF'"),
    ("ojama2_zutto", "TEXT DEFAULT 'OFF'"),
)

_MUSIC_COLUMNS = "music_id, title, genre, artist, ver, easy, normal, hyper, ex"

# ------------------------------------------------------------------
# CSV インポートの列定義
# ------------------------------------------------------------------

_CSV_INT_FIELDS = ("score", "cool", "great", "good", "bad", "combo")
# 列が無い・空欄の場合の値 (数値項目は 0)
_CSV_DEFAULTS = {
    "level": "",
    "title": "Unknown",
    "difficulty": "",
    "options_summary": "NORMAL",
    "played_at": "",
    **OPTION_DEFAULTS,
}
# 列名付き CSV: 項目 → 列名の候補 (先頭が現行の列名、以降は旧形式の列名)
_CSV_COLUMN_NAMES = {
    "level": ("レベル",),
    "title": ("曲名",),
    "difficulty": ("難易度区分",),
    "score": ("SCORE",),
    "cool": ("COOL",),
    "great": ("GREAT",),
    "good": ("GOOD",),
    "bad": ("BAD",),
    "combo": ("COMBO",),
    "options_summary": ("使用オプション",),
    "played_at": ("プレー日時",),
    **{key: (OPTION_LABELS[key],) for key in OPTION_KEYS},
    "hispeed": (OPTION_LABELS["hispeed"], "Hi-speed"),
    "popkun": (OPTION_LABELS["popkun"], "ポップ君"),
    "gauge_type": (OPTION_LABELS["gauge_type"], "ゲージ"),
    "random": (OPTION_LABELS["random"], "配置"),
}
# 列名の無い旧形式 CSV: (最小列数, {項目: 列位置}, 既定値の上書き)。列数の多い形式から順に判定する
_CSV_LEGACY_LAYOUTS = (
    (21, {
        "level": 0, "title": 1, "difficulty": 2,
        "score": 3, "cool": 4, "great": 5, "good": 6, "bad": 7, "combo": 8,
        "hispeed": 9, "popkun": 10, "gauge_type": 11, "guide_se": 12, "random": 13,
        "judge_plus": 14, "hidden": 15, "sudden": 16, "ojama1": 17, "ojama2": 18, "auto": 19,
        "played_at": 20,
    }, {}),
    (15, {
        "level": 0, "title": 1, "difficulty": 2,
        "score": 3, "cool": 4, "great": 5, "good": 6, "bad": 7,
        "options_summary": 8, "combo": 9,
        "hispeed": 10, "popkun": 11, "gauge_type": 12, "random": 13,
        "played_at": 14,
    }, {}),
    (7, {
        "title": 0,
        "score": 1, "cool": 2, "great": 3, "good": 4, "bad": 5, "combo": 6,
        "options_summary": 7,
        "hispeed": 8, "popkun": 9, "gauge_type": 10, "random": 11,
        "played_at": 12,
    }, {"difficulty": "EX"}),
)


def _csv_named_layout(header: list[str]) -> dict[str, int] | None:
    """ヘッダー行から {項目: 列位置} を作る。列名付きの形式でなければ None。"""
    col_map = {col.strip(): idx for idx, col in enumerate(header)}
    if "曲名" not in col_map and "SCORE" not in col_map:
        return None
    layout = {}
    for field, names in _CSV_COLUMN_NAMES.items():
        for name in names:
            if name in col_map:
                layout[field] = col_map[name]
                break
    return layout


def _parse_csv_row(row: list[str], named_layout: dict[str, int] | None) -> dict | None:
    """CSV の 1 行を {項目: 値} にする。旧形式で列数が足りない行は None。"""
    if named_layout is not None:
        layout, overrides = named_layout, {}
    else:
        for min_cols, layout, overrides in _CSV_LEGACY_LAYOUTS:
            if len(row) >= min_cols:
                break
        else:
            return None

    fields = {**_CSV_DEFAULTS, **overrides}
    for field, idx in layout.items():
        if idx < len(row) and row[idx] != "":
            fields[field] = row[idx]
    for field in _CSV_INT_FIELDS:
        value = fields.get(field, "")
        fields[field] = int(value) if value.isdigit() else 0
    if fields["hispeed"] == "OFF":
        fields["hispeed"] = "1.0"   # 旧形式は等速を OFF と記録していた
    return fields


def _to_level(value) -> int | None:
    """曲リスト JSON のレベル値。譜面が無い (数値でない) 場合は None。"""
    return int(value) if value is not None and str(value).isdigit() else None


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
        self._conn: sqlite3.Connection | None = None
        self._match_index: dict[str, list[dict]] | None = None  # match_music 用の曲名キー索引
        self._option_values: dict[str, list[str]] | None = None  # オプションマスターのキャッシュ
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
        """曲テーブル (musics)・スコア管理テーブル (scores)・オプションマスター (option_masters) を作成・マイグレーション"""
        with self._conn:
            self._init_musics()
            self._init_scores()
            self._init_option_masters()
        self._option_values = None

    def _init_musics(self) -> None:
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
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_musics_title ON musics (title);")

    def _score_column_names(self) -> set[str]:
        """scores テーブルの列名。テーブルが無ければ空集合。"""
        return {row["name"] for row in self._conn.execute("PRAGMA table_info(scores);")}

    def _init_scores(self) -> None:
        columns = self._score_column_names()
        if not columns:
            self._conn.execute(_SCORES_DDL.format(table="scores"))
        elif "level" in columns or "gauge_type" not in columns:
            self._migrate_legacy_scores(columns)

        # 後から追加した列が無い既存 DB には列を追加
        columns = self._score_column_names()
        for name, definition in _SCORES_ADDED_COLUMNS:
            if name not in columns:
                self._conn.execute(f"ALTER TABLE scores ADD COLUMN {name} {definition};")
        # 旧データは EX を "E" と記録していた
        self._conn.execute("UPDATE scores SET difficulty = 'EX' WHERE UPPER(difficulty) = 'E';")
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_scores_music_id ON scores (music_id);")
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_scores_played_at ON scores (played_at);")

    def _migrate_legacy_scores(self, columns: set[str]) -> None:
        """旧形式の scores テーブル (level 列あり / オプション列が gauge・arrangement) を作り直す。"""
        logger.info("スコアテーブルのマイグレーションを実行します (levelカラム削除 / オプション拡張)...")
        self._conn.execute(_SCORES_DDL.format(table="scores_new"))
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

    def _init_option_masters(self) -> None:
        # 選択肢の定義元は src/option_master.py。起動のたびに定義どおりに入れ直す
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS option_masters (
                option_key TEXT NOT NULL,
                option_name TEXT NOT NULL,
                value TEXT NOT NULL,
                sort_order INTEGER NOT NULL,
                is_default INTEGER DEFAULT 0,
                PRIMARY KEY (option_key, value)
            );
            """
        )
        self._conn.execute("DELETE FROM option_masters;")
        self._conn.executemany(
            "INSERT INTO option_masters (option_key, option_name, value, sort_order, is_default)"
            " VALUES (?, ?, ?, ?, ?);",
            [
                (key, OPTION_NAMES[key], value, order, int(value == OPTION_DEFAULTS[key]))
                for key in OPTION_KEYS
                for order, value in enumerate(OPTION_MASTER[key])
            ],
        )

    # ------------------------------------------------------------------
    # オプションマスター
    # ------------------------------------------------------------------

    def get_option_values(self, key: str) -> list[str]:
        """オプション項目 (key = scores の列名) の選択肢をゲーム内の表示順で返す。"""
        if self._option_values is None:
            with self._conn:
                rows = self._conn.execute(
                    "SELECT option_key, value FROM option_masters ORDER BY option_key, sort_order;"
                ).fetchall()
            values: dict[str, list[str]] = {}
            for r in rows:
                values.setdefault(r["option_key"], []).append(r["value"])
            self._option_values = values
        return list(self._option_values.get(key, []))

    def normalize_option(self, key: str, text: str) -> str | None:
        """読み取った文字列・手入力された文字列をマスターの値に正規化する。該当が無ければ None。"""
        return normalize_option(key, text, self.get_option_values(key))

    def normalize_options(self, options: PopnOptions) -> PopnOptions:
        """各オプション値をマスターの表記に揃える。マスターに無い値はそのまま残す。"""
        for key in OPTION_KEYS:
            raw = getattr(options, key)
            value = self.normalize_option(key, raw)
            if value is None:
                logger.warning("オプションマスターに無い値です: %s = '%s'", OPTION_NAMES[key], raw)
            else:
                setattr(options, key, value)
        return options

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
        records_to_insert: list[tuple] = []

        for item in data:
            title = str(item.get("title", "")).strip()
            genre = str(item.get("genre", "")).strip()
            ver = str(item.get("ver", "")).strip()
            artist = str(item.get("artist", "")).strip()
            bpm = str(item.get("bpm", "")).strip()
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
                    *(_to_level(item.get(column)) for column in ("easy", "normal", "hyper", "ex")),
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
                rows = [r for r in cursor.fetchall() if _normalize_title(r["title"]) == norm_t]

            if rows:
                # 同名曲は、その難易度のレベルが一致する曲を選ぶ
                column = DIFFICULTY_LEVEL_COLUMNS.get(difficulty_code(difficulty))
                if len(rows) > 1 and column and str(level).isdigit():
                    for r in rows:
                        if r[column] == int(level):
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

    def match_music(self, text: str, difficulty: str = "") -> dict | None:
        """OCR で読んだ曲名から曲テーブルの曲を特定する。

        完全一致を優先し、なければ類似度が最も高い曲を採用する。
        確信が持てない場合（類似度が低い・次点と僅差）は None を返す。
        戻り値には music_id / title / level (difficulty に対応するレベル) 等を含む。
        """
        key = _match_key(text)
        if not key:
            return None

        index = self._get_match_index()
        candidates = index.get(key)
        if not candidates:
            best_key = self._closest_match_key(key, text)
            if best_key is None:
                return None
            candidates = index[best_key]

        # 同名曲（ウラ譜面・LIVE版・カバー等）は、その難易度の譜面があり Lively 収録の曲を優先
        column = DIFFICULTY_LEVEL_COLUMNS.get(difficulty_code(difficulty))
        music = max(
            candidates,
            key=lambda m: (column is None or m[column] is not None, bool(m["pack"])),
        )
        if len(candidates) > 1:
            logger.info("曲名照合: '%s' は同名曲が %d 件あります", music["title"], len(candidates))
        return {**music, "level": music[column] if column and music[column] is not None else ""}

    def _get_match_index(self) -> dict[str, list[dict]]:
        """曲名の照合キー → 曲 (同名曲は複数) の索引"""
        if self._match_index is None:
            with self._conn:
                rows = self._conn.execute(
                    "SELECT music_id, title, genre, easy, normal, hyper, ex, pack FROM musics"
                ).fetchall()
            index: dict[str, list[dict]] = {}
            for r in rows:
                index.setdefault(_match_key(r["title"]), []).append(dict(r))
            self._match_index = index
        return self._match_index

    def _closest_match_key(self, key: str, text: str) -> str | None:
        """索引の中で key に最も似た照合キーを返す。確信が持てなければ None。"""
        if len(key) < _MATCH_MIN_FUZZY_LEN:
            return None
        matcher = difflib.SequenceMatcher(autojunk=False)
        matcher.set_seq2(key)
        best_key, best, second = "", 0.0, 0.0
        for cand in self._get_match_index():
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
        return best_key

    # ------------------------------------------------------------------
    # スコア保存・読み込み
    # ------------------------------------------------------------------

    @staticmethod
    def _score_values(record: PopnScoreRecord) -> tuple:
        """scores テーブルに保存する値。並びは _SCORE_COLUMNS"""
        return (
            record.music_id,
            record.difficulty_code,
            record.score,
            record.cool,
            record.great,
            record.good,
            record.bad,
            record.combo,
            record.options.to_summary(),
            *(getattr(record.options, key) for key in OPTION_KEYS),
            record.timestamp,
        )

    def save_score(self, record: PopnScoreRecord) -> int:
        """スコア記録を scores テーブルに保存する。
        曲情報および level は除き、UUID (music_id) とプレイ実績・オプションを保存する。
        """
        if not record.music_id:
            record.music_id = self.find_music_id(record.title, record.difficulty_code, record.level)

        with self._conn:
            cursor = self._conn.execute(_INSERT_SCORE_SQL, self._score_values(record))
            record.record_id = cursor.lastrowid
            return record.record_id

    def delete_scores(self, record_ids: list[int]) -> int:
        """スコア記録を削除し、削除した件数を返す。"""
        with self._conn:
            cursor = self._conn.executemany(
                "DELETE FROM scores WHERE id = ?;", [(i,) for i in record_ids]
            )
            return cursor.rowcount

    def update_score(self, record: PopnScoreRecord) -> None:
        """既存のスコア記録 (record.record_id) を上書きし、修正済フラグを立てる。"""
        if record.record_id is None:
            raise ValueError("record_id の無いレコードは更新できません")
        assignments = ", ".join(f"{column} = ?" for column in _UPDATE_COLUMNS)
        values = self._score_values(record)[:len(_UPDATE_COLUMNS)]
        with self._conn:
            self._conn.execute(
                f"UPDATE scores SET {assignments}, modified = 1 WHERE id = ?;",
                (*values, record.record_id),
            )

    def get_music(self, music_id: str) -> dict | None:
        """曲テーブルの 1 曲を返す。未登録なら None。"""
        with self._conn:
            row = self._conn.execute(
                f"SELECT {_MUSIC_COLUMNS} FROM musics WHERE music_id = ?",
                (music_id,),
            ).fetchone()
        return dict(row) if row else None

    def list_musics(self) -> list[dict]:
        """曲テーブルの全曲を曲名順で返す。"""
        with self._conn:
            rows = self._conn.execute(
                f"SELECT {_MUSIC_COLUMNS} FROM musics ORDER BY title COLLATE NOCASE, ver;"
            ).fetchall()
        return [dict(r) for r in rows]

    def load_scores(self) -> list[PopnScoreRecord]:
        """scores テーブルと musics テーブルを結合し、スコア履歴一覧を取得する。
        レベル情報は曲テーブルの難易度別レベルから導出します。
        """
        with self._conn:
            rows = self._conn.execute(
                f"""
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
                    COALESCE(m.genre, '') AS genre,
                    COALESCE(m.artist, '') AS artist,
                    COALESCE(m.ver, '') AS ver,
                    s.difficulty,
                    s.score,
                    s.cool,
                    s.great,
                    s.good,
                    s.bad,
                    s.combo,
                    {", ".join(f"s.{key}" for key in OPTION_KEYS)},
                    s.played_at,
                    COALESCE(s.modified, 0) AS modified
                FROM scores s
                LEFT JOIN musics m ON s.music_id = m.music_id
                ORDER BY s.played_at ASC, s.id ASC;
                """
            ).fetchall()

        records: list[PopnScoreRecord] = []
        for r in rows:
            options = PopnOptions(**{key: r[key] or OPTION_DEFAULTS[key] for key in OPTION_KEYS})
            if options.hispeed == "OFF":
                options.hispeed = OPTION_DEFAULTS["hispeed"]   # 旧データは等速を OFF と記録していた
            records.append(PopnScoreRecord(
                title=r["title"],
                level=r["calc_level"],
                difficulty=r["difficulty"],
                score=r["score"],
                cool=r["cool"],
                great=r["great"],
                good=r["good"],
                bad=r["bad"],
                combo=r["combo"],
                options=options,
                timestamp=r["played_at"],
                music_id=r["music_id"],
                record_id=r["record_id"],
                genre=r["genre"],
                artist=r["artist"],
                ver=r["ver"],
                modified=bool(r["modified"]),
            ))
        return records

    def get_today_notes(self, date_str: str) -> int:
        """指定日 (YYYY-MM-DD) の総打鍵数を計算（BAD は見逃し扱いで含めない）"""
        with self._conn:
            row = self._conn.execute(
                "SELECT COALESCE(SUM(cool + great + good), 0) AS total FROM scores WHERE played_at LIKE ?;",
                (f"{date_str}%",),
            ).fetchone()
        return int(row["total"])

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

        列名付きの形式 (現行・旧) と、列名の無い旧形式 (_CSV_LEGACY_LAYOUTS) に対応する。
        プレー日時とスコアが同じ記録は取り込み済みとみなしてスキップする。
        """
        if not os.path.exists(csv_path):
            return 0

        try:
            with open(csv_path, "r", encoding="utf-8-sig") as f:
                reader = csv.reader(f)
                header = next(reader, None)
                if not header:
                    return 0
                named_layout = _csv_named_layout(header)

                with self._conn:
                    cursor = self._conn.execute("SELECT played_at, score FROM scores")
                    existing_scores = {(r["played_at"], r["score"]) for r in cursor.fetchall()}

                rows_to_save = []
                for row in reader:
                    if not row:
                        continue
                    try:
                        fields = _parse_csv_row(row, named_layout)
                        if fields is None:
                            continue
                        key = (fields["played_at"], fields["score"])
                        if key in existing_scores:
                            continue
                        existing_scores.add(key)

                        # 曲テーブルから UUID を検索（level は検索の絞り込みにのみ使用）
                        fields["music_id"] = self.find_music_id(
                            fields["title"], fields["difficulty"], fields["level"]
                        )
                        rows_to_save.append(tuple(fields[column] for column in _SCORE_COLUMNS))
                    except Exception as e:
                        logger.debug("CSV 行インポートスキップ: %s", e)

            if rows_to_save:
                with self._conn:
                    self._conn.executemany(_INSERT_SCORE_SQL, rows_to_save)
                logger.info("CSV から %d 件のスコアをインポートしました", len(rows_to_save))
            return len(rows_to_save)
        except Exception as e:
            logger.error("CSV インポートエラー: %s", e)
            return 0
