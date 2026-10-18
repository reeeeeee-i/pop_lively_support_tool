"""スコア履歴の集計 (ベスト比較・期間別・レベル別・曲別推移・セッションサマリー・絞り込み)

GUI に依存しない純粋な集計処理。入力は PopnScoreRecord のリスト (プレー日時の昇順)。

FULL COMBO / PERFECT は BAD / GOOD の数だけで判定する (リザルト画面の「Retire」表示は
記録に残していないため、リタイアしたプレーも BAD が 0 なら FULL COMBO 扱いになりうる)。
"""
from __future__ import annotations

import csv
import os
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from src.classes import PopnScoreRecord

_TIME_FORMAT = "%Y-%m-%d %H:%M:%S"


# ----------------------------------------------------------------------
# 記録 1 件の判定
# ----------------------------------------------------------------------

def parse_time(timestamp: str) -> datetime | None:
    try:
        return datetime.strptime(timestamp, _TIME_FORMAT)
    except (TypeError, ValueError):
        return None


def chart_key(record: PopnScoreRecord) -> tuple[str, str]:
    """譜面 = 曲 + 難易度区分"""
    return record.music_id, record.difficulty_code


def record_level(record: PopnScoreRecord) -> int | None:
    return int(record.level) if str(record.level).isdigit() else None


def is_full_combo(record: PopnScoreRecord) -> bool:
    return record.total_notes > 0 and record.bad == 0


def is_perfect(record: PopnScoreRecord) -> bool:
    return is_full_combo(record) and record.good == 0


# ----------------------------------------------------------------------
# 譜面ごとのベスト比較
# ----------------------------------------------------------------------

@dataclass
class ChartSummary:
    """ある譜面のこれまでのプレー状況"""
    play_count: int = 0
    best_score: int | None = None
    last_score: int | None = None


def summarize_chart(records: list[PopnScoreRecord], music_id: str, difficulty: str) -> ChartSummary:
    """譜面 (music_id + 難易度区分コード) のプレー回数・ベスト・前回スコア。"""
    summary = ChartSummary()
    for r in records:
        if r.music_id != music_id or r.difficulty_code != difficulty:
            continue
        summary.play_count += 1
        summary.last_score = r.score
        if summary.best_score is None or r.score > summary.best_score:
            summary.best_score = r.score
    return summary


def describe_chart(summary: ChartSummary) -> str:
    """選曲・プレー中に出す、その譜面のこれまでの成績"""
    if summary.play_count == 0:
        return "初プレー"
    return f"ベスト {summary.best_score:,} / 前回 {summary.last_score:,} ({summary.play_count} 回プレー)"


@dataclass
class ScoreComparison:
    """今回のスコアと、それまでのベストとの比較"""
    score: int
    prev_best: int | None
    prev_count: int

    @property
    def first_play(self) -> bool:
        return self.prev_count == 0

    @property
    def is_new_best(self) -> bool:
        return self.prev_best is not None and self.score > self.prev_best

    @property
    def diff(self) -> int | None:
        return None if self.prev_best is None else self.score - self.prev_best

    def text(self) -> str:
        if self.first_play:
            return f"初プレー: {self.score:,}"
        label = "NEW BEST! " if self.is_new_best else ""
        return f"{label}{self.score:,} (ベスト {self.prev_best:,} {self.diff:+,})"


def compare_with_best(
    records: list[PopnScoreRecord], record: PopnScoreRecord
) -> ScoreComparison | None:
    """records (今回の記録を含まない) の中のベストと今回のスコアを比べる。曲が不明なら None。"""
    if not record.music_id:
        return None
    summary = summarize_chart(records, record.music_id, record.difficulty_code)
    return ScoreComparison(record.score, summary.best_score, summary.play_count)


# ----------------------------------------------------------------------
# 期間別の打鍵数・プレー数
# ----------------------------------------------------------------------

PERIOD_UNITS = ("day", "week", "month")


@dataclass
class PeriodStat:
    start: date
    label: str
    notes: int = 0
    plays: int = 0


def _period_start(d: date, unit: str) -> date:
    if unit == "week":
        return d - timedelta(days=d.weekday())   # 月曜始まり
    if unit == "month":
        return d.replace(day=1)
    return d


def _next_period(d: date, unit: str) -> date:
    if unit == "week":
        return d + timedelta(days=7)
    if unit == "month":
        return date(d.year + d.month // 12, d.month % 12 + 1, 1)
    return d + timedelta(days=1)


def _prev_period(d: date, unit: str) -> date:
    if unit == "week":
        return d - timedelta(days=7)
    if unit == "month":
        return date(d.year - (d.month == 1), (d.month - 2) % 12 + 1, 1)
    return d - timedelta(days=1)


def _period_label(d: date, unit: str) -> str:
    if unit == "month":
        return f"{d.year}/{d.month:02d}"
    return f"{d.month:02d}/{d.day:02d}"


def aggregate_periods(
    records: list[PopnScoreRecord], unit: str = "day", limit: int | None = 30,
    today: date | None = None,
) -> list[PeriodStat]:
    """期間 (日・週・月) ごとの打鍵数とプレー数。プレーの無い期間も 0 として含める。

    limit: 今日を含む直近の期間数。None なら最初の記録から今日まで。
    """
    today = today or date.today()
    notes: dict[date, int] = defaultdict(int)
    plays: dict[date, int] = defaultdict(int)
    first: date | None = None
    for r in records:
        t = parse_time(r.timestamp)
        if t is None:
            continue
        key = _period_start(t.date(), unit)
        notes[key] += r.cool + r.great + r.good
        plays[key] += 1
        first = key if first is None or key < first else first

    end = _period_start(today, unit)
    if limit is not None:
        start = end
        for _ in range(limit - 1):
            start = _prev_period(start, unit)
    else:
        start = first or end

    stats = []
    cursor = start
    while cursor <= end:
        stats.append(PeriodStat(cursor, _period_label(cursor, unit), notes[cursor], plays[cursor]))
        cursor = _next_period(cursor, unit)
    return stats


# ----------------------------------------------------------------------
# レベル別の集計
# ----------------------------------------------------------------------

@dataclass
class LevelStat:
    level: int
    plays: int = 0
    charts: int = 0
    full_combo_charts: int = 0
    perfect_charts: int = 0
    best_average: float = 0.0
    """譜面ごとのベストスコアの平均"""
    best_score: int = 0


def level_stats(records: list[PopnScoreRecord], difficulty: str = "") -> list[LevelStat]:
    """レベルごとのプレー状況。difficulty (L/N/H/EX) を指定するとその難易度区分だけを集計する。"""
    plays: dict[int, int] = defaultdict(int)
    charts: dict[int, dict[tuple, dict]] = defaultdict(dict)
    for r in records:
        level = record_level(r)
        if level is None or (difficulty and r.difficulty_code != difficulty):
            continue
        plays[level] += 1
        chart = charts[level].setdefault(chart_key(r), {"best": 0, "fc": False, "perfect": False})
        chart["best"] = max(chart["best"], r.score)
        chart["fc"] = chart["fc"] or is_full_combo(r)
        chart["perfect"] = chart["perfect"] or is_perfect(r)

    result = []
    for level in sorted(plays):
        bests = [c["best"] for c in charts[level].values()]
        result.append(LevelStat(
            level=level,
            plays=plays[level],
            charts=len(bests),
            full_combo_charts=sum(c["fc"] for c in charts[level].values()),
            perfect_charts=sum(c["perfect"] for c in charts[level].values()),
            best_average=sum(bests) / len(bests),
            best_score=max(bests),
        ))
    return result


# ----------------------------------------------------------------------
# 曲別の推移
# ----------------------------------------------------------------------

@dataclass
class ChartEntry:
    """プレー済みの譜面 1 つ分 (曲別推移の選択肢)"""
    music_id: str
    difficulty: str
    title: str
    level: int | None
    play_count: int
    best_score: int
    last_played: str


def list_charts(records: list[PopnScoreRecord]) -> list[ChartEntry]:
    """プレー済みの譜面を、最後にプレーした順 (新しい順) で返す。"""
    entries: dict[tuple, ChartEntry] = {}
    for r in records:
        key = chart_key(r)
        entry = entries.get(key)
        if entry is None:
            entries[key] = ChartEntry(
                r.music_id, r.difficulty_code, r.title, record_level(r), 1, r.score, r.timestamp
            )
        else:
            entry.play_count += 1
            entry.best_score = max(entry.best_score, r.score)
            entry.last_played = max(entry.last_played, r.timestamp)
            entry.level = entry.level if entry.level is not None else record_level(r)
    return sorted(entries.values(), key=lambda e: e.last_played, reverse=True)


def chart_history(
    records: list[PopnScoreRecord], music_id: str, difficulty: str
) -> list[PopnScoreRecord]:
    """譜面のプレー履歴 (古い順)"""
    return [r for r in records if r.music_id == music_id and r.difficulty_code == difficulty]


# ----------------------------------------------------------------------
# セッションサマリー
# ----------------------------------------------------------------------

@dataclass
class BestUpdate:
    title: str
    difficulty: str
    level: int | None
    prev_best: int
    score: int


@dataclass
class SessionSummary:
    start: datetime
    end: datetime
    plays: int = 0
    charts: int = 0
    notes: int = 0
    first_plays: int = 0
    full_combos: int = 0
    perfects: int = 0
    average_score: float = 0.0
    max_level: int | None = None
    best_updates: list[BestUpdate] = field(default_factory=list)


def summarize_session(
    records: list[PopnScoreRecord], start: datetime, end: datetime | None = None
) -> SessionSummary:
    """start 以降の記録をまとめる。start より前の記録は、ベスト更新・初プレーの判定に使う。"""
    end = end or datetime.now()
    start_text = start.strftime(_TIME_FORMAT)
    summary = SessionSummary(start, end)
    best: dict[tuple, int] = {}
    session_charts = set()
    score_total = 0
    for r in sorted(records, key=lambda r: r.timestamp):
        key = chart_key(r)
        prev = best.get(key)
        if r.timestamp >= start_text:
            summary.plays += 1
            summary.notes += r.cool + r.great + r.good
            score_total += r.score
            session_charts.add(key)
            summary.full_combos += is_full_combo(r)
            summary.perfects += is_perfect(r)
            level = record_level(r)
            if level is not None and (summary.max_level is None or level > summary.max_level):
                summary.max_level = level
            if prev is None:
                summary.first_plays += 1
            elif r.score > prev:
                summary.best_updates.append(
                    BestUpdate(r.title, r.difficulty_code, level, prev, r.score)
                )
        best[key] = r.score if prev is None else max(prev, r.score)
    summary.charts = len(session_charts)
    summary.average_score = score_total / summary.plays if summary.plays else 0.0
    return summary


def format_session_summary(s: SessionSummary) -> str:
    """セッションサマリーの表示用テキスト"""
    elapsed = max(0, int((s.end - s.start).total_seconds()))
    hours, rest = divmod(elapsed, 3600)
    lines = [
        f"期間: {s.start:%Y-%m-%d %H:%M} ～ {s.end:%H:%M} ({hours}時間{rest // 60:02d}分)",
        f"プレー数: {s.plays} 回 ({s.charts} 譜面)",
        f"打鍵数: {s.notes:,}",
    ]
    if s.plays:
        lines.append(f"平均スコア: {s.average_score:,.0f}")
        if s.max_level is not None:
            lines.append(f"最高レベル: Lv{s.max_level}")
        lines.append(
            f"FULL COMBO: {s.full_combos} 回 / PERFECT: {s.perfects} 回 / 初プレー譜面: {s.first_plays}"
        )
    lines.append(f"自己ベスト更新: {len(s.best_updates)} 件")
    for u in s.best_updates:
        level = f"Lv{u.level} " if u.level is not None else ""
        lines.append(f"  ・{u.title} [{level}{u.difficulty}] {u.prev_best:,} → {u.score:,} ({u.score - u.prev_best:+,})")
    return "\n".join(lines)


_SESSION_LOG_HEADERS = [
    "開始", "終了", "プレー数", "譜面数", "打鍵数", "自己ベスト更新", "初プレー",
    "FULL COMBO", "PERFECT", "平均スコア",
]


def append_session_log(path: str, s: SessionSummary) -> None:
    """セッションサマリーを CSV の末尾に 1 行追記する (ファイルが無ければヘッダー付きで作る)。"""
    new_file = not os.path.exists(path)
    with open(path, "a", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        if new_file:
            writer.writerow(_SESSION_LOG_HEADERS)
        writer.writerow([
            s.start.strftime(_TIME_FORMAT), s.end.strftime(_TIME_FORMAT), s.plays, s.charts, s.notes,
            len(s.best_updates), s.first_plays, s.full_combos, s.perfects, round(s.average_score),
        ])


# ----------------------------------------------------------------------
# スコア履歴の絞り込み
# ----------------------------------------------------------------------

CLEAR_ALL = ""
CLEAR_FULL_COMBO = "fullcombo"
CLEAR_PERFECT = "perfect"
CLEAR_NOT_FULL_COMBO = "not_fullcombo"

PERIOD_ALL = ""
PERIOD_TODAY = "today"
PERIOD_7DAYS = "7days"
PERIOD_30DAYS = "30days"
PERIOD_MONTH = "month"


@dataclass
class RecordFilter:
    """スコア履歴の絞り込み条件 (空の項目は条件なし)"""
    difficulty: str = ""
    level_min: int | None = None
    level_max: int | None = None
    clear: str = CLEAR_ALL
    period: str = PERIOD_ALL
    best_only: bool = False
    """各譜面の最高スコアの記録 (同点なら最も古いもの) だけ"""

    @property
    def active(self) -> bool:
        return self != RecordFilter()

    def _period_start(self, today: date) -> date | None:
        if self.period == PERIOD_TODAY:
            return today
        if self.period == PERIOD_7DAYS:
            return today - timedelta(days=6)
        if self.period == PERIOD_30DAYS:
            return today - timedelta(days=29)
        if self.period == PERIOD_MONTH:
            return today.replace(day=1)
        return None

    def apply(
        self, records: list[PopnScoreRecord], today: date | None = None
    ) -> list[PopnScoreRecord]:
        """条件に合う記録を、元の順序のまま返す。"""
        today = today or date.today()
        since = self._period_start(today)
        best_ids: set[int] | None = None
        if self.best_only:
            best: dict[tuple, PopnScoreRecord] = {}
            for r in records:
                top = best.get(chart_key(r))
                if top is None or r.score > top.score:
                    best[chart_key(r)] = r
            best_ids = {id(r) for r in best.values()}

        result = []
        for r in records:
            if self.difficulty and r.difficulty_code != self.difficulty:
                continue
            if self.level_min is not None or self.level_max is not None:
                level = record_level(r)
                if level is None:
                    continue
                if self.level_min is not None and level < self.level_min:
                    continue
                if self.level_max is not None and level > self.level_max:
                    continue
            if self.clear == CLEAR_FULL_COMBO and not is_full_combo(r):
                continue
            if self.clear == CLEAR_PERFECT and not is_perfect(r):
                continue
            if self.clear == CLEAR_NOT_FULL_COMBO and is_full_combo(r):
                continue
            if since is not None:
                t = parse_time(r.timestamp)
                if t is None or t.date() < since:
                    continue
            if best_ids is not None and id(r) not in best_ids:
                continue
            result.append(r)
        return result


# ----------------------------------------------------------------------
# 共有用テキスト
# ----------------------------------------------------------------------

def format_share_text(s: SessionSummary) -> str:
    """X などに投稿するための短いテキスト"""
    lines = [
        "pop'n music Lively のセッション結果",
        f"プレー {s.plays} 回 / 打鍵数 {s.notes:,}",
    ]
    if s.plays:
        lines.append(f"自己ベスト更新 {len(s.best_updates)} 件 / FULL COMBO {s.full_combos} 回")
    lines.append("#popn")
    return "\n".join(lines)


def records_with_screenshots(records: list[PopnScoreRecord], since: datetime) -> list[PopnScoreRecord]:
    """since 以降にプレーし、リザルトのスクリーンショットを保存した記録 (古い順)"""
    since_text = since.strftime(_TIME_FORMAT)
    result = [r for r in records if r.screenshot_file and r.timestamp >= since_text]
    return sorted(result, key=lambda r: r.timestamp)
