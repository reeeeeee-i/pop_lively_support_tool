"""pop'n music Lively 専用データクラス・列挙型定義"""
from enum import Enum


class PopnJudge:
    """1フレームで検出した判定内訳の増分"""

    def __init__(self, cool: int = 0, great: int = 0, good: int = 0, bad: int = 0):
        self.cool  = cool
        self.great = great
        self.good  = good
        self.bad   = bad

    @property
    def notes(self) -> int:
        """打鍵数 = COOL + GREAT + GOOD + BAD（全判定の合計）"""
        return self.cool + self.great + self.good + self.bad

    def __repr__(self):
        return (
            f"PopnJudge(cool={self.cool}, great={self.great}, "
            f"good={self.good}, bad={self.bad})"
        )


class PopnOptions:
    """使用オプション管理クラス

    対象オプション項目:
    - HI-SPEED
    - POP-KUN
    - GAUGE TYPE
    - GUIDE SE
    - RANDOM
    - JUDGE+
    - HIDDEN
    - SUDDEN
    - OJAMA1
    - OJAMA2
    - AUTO
    """

    def __init__(
        self,
        hispeed: str = "1.0",
        popkun: str = "NORMAL",
        gauge_type: str = "NORMAL",
        guide_se: str = "OFF",
        random: str = "OFF",
        judge_plus: str = "OFF",
        hidden: str = "OFF",
        sudden: str = "OFF",
        ojama1: str = "OFF",
        ojama2: str = "OFF",
        auto: str = "OFF",
        extra: dict | None = None,
        # 旧プロパティ名との後方互換用
        gauge: str | None = None,
        arrangement: str | None = None,
    ):
        self.hispeed: str = hispeed
        self.popkun: str = popkun
        self.gauge_type: str = gauge if gauge is not None else gauge_type
        self.guide_se: str = guide_se
        self.random: str = arrangement if arrangement is not None else random
        self.judge_plus: str = judge_plus
        self.hidden: str = hidden
        self.sudden: str = sudden
        self.ojama1: str = ojama1
        self.ojama2: str = ojama2
        self.auto: str = auto
        self.extra: dict = extra if extra is not None else {}

    @property
    def gauge(self) -> str:
        """互換用プロパティ"""
        return self.gauge_type

    @gauge.setter
    def gauge(self, val: str) -> None:
        self.gauge_type = val

    @property
    def arrangement(self) -> str:
        """互換用プロパティ"""
        return self.random

    @arrangement.setter
    def arrangement(self, val: str) -> None:
        self.random = val

    def to_summary(self) -> str:
        """画面表示および要約文字列"""
        parts = []
        if self.hispeed and self.hispeed not in ("OFF", "1.0", "x1.0"):
            parts.append(f"HI-SPEED:{self.hispeed}")
        if self.popkun and self.popkun != "NORMAL":
            parts.append(f"POP-KUN:{self.popkun}")
        if self.gauge_type and self.gauge_type != "NORMAL":
            parts.append(f"GAUGE TYPE:{self.gauge_type}")
        if self.guide_se and self.guide_se != "OFF":
            parts.append(f"GUIDE SE:{self.guide_se}")
        if self.random and self.random != "OFF":
            parts.append(f"RANDOM:{self.random}")
        if self.judge_plus and self.judge_plus != "OFF":
            parts.append(f"JUDGE+:{self.judge_plus}")
        if self.hidden and self.hidden != "OFF":
            parts.append(f"HIDDEN:{self.hidden}")
        if self.sudden and self.sudden != "OFF":
            parts.append(f"SUDDEN:{self.sudden}")
        if self.ojama1 and self.ojama1 != "OFF":
            parts.append(f"OJAMA1:{self.ojama1}")
        if self.ojama2 and self.ojama2 != "OFF":
            parts.append(f"OJAMA2:{self.ojama2}")
        if self.auto and self.auto != "OFF":
            parts.append(f"AUTO:{self.auto}")
        for k, v in self.extra.items():
            if v:
                parts.append(f"{k}:{v}")
        return " / ".join(parts) if parts else "NORMAL"

    def to_dict(self) -> dict:
        return {
            "hispeed": self.hispeed,
            "popkun": self.popkun,
            "gauge_type": self.gauge_type,
            "guide_se": self.guide_se,
            "random": self.random,
            "judge_plus": self.judge_plus,
            "hidden": self.hidden,
            "sudden": self.sudden,
            "ojama1": self.ojama1,
            "ojama2": self.ojama2,
            "auto": self.auto,
            "extra": dict(self.extra),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "PopnOptions":
        if not isinstance(d, dict):
            return cls()
        return cls(
            hispeed=d.get("hispeed", "1.0"),
            popkun=d.get("popkun", "NORMAL"),
            gauge_type=d.get("gauge_type") or d.get("gauge", "NORMAL"),
            guide_se=d.get("guide_se", "OFF"),
            random=d.get("random") or d.get("arrangement", "OFF"),
            judge_plus=d.get("judge_plus", "OFF"),
            hidden=d.get("hidden", "OFF"),
            sudden=d.get("sudden", "OFF"),
            ojama1=d.get("ojama1", "OFF"),
            ojama2=d.get("ojama2", "OFF"),
            auto=d.get("auto", "OFF"),
            extra=d.get("extra", {}),
        )

    def __repr__(self) -> str:
        return f"PopnOptions({self.to_summary()})"


class PopnScoreRecord:
    """1プレーごとのスコア記録クラス"""

    def __init__(
        self,
        title: str = "Unknown",
        level: int | str = "",
        difficulty: str = "",
        score: int = 0,
        cool: int = 0,
        great: int = 0,
        good: int = 0,
        bad: int = 0,
        combo: int = 0,
        options: PopnOptions | None = None,
        timestamp: str = "",
        music_id: str = "",
        record_id: int | None = None,
    ):
        from datetime import datetime

        self.title: str = title
        self.level: int | str = level
        self.difficulty: str = difficulty
        self.score: int = score
        self.cool: int = cool
        self.great: int = great
        self.good: int = good
        self.bad: int = bad
        self.combo: int = combo
        self.options: PopnOptions = options if options is not None else PopnOptions()
        self.timestamp: str = timestamp or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.music_id: str = music_id
        self.record_id: int | None = record_id

    @property
    def total_notes(self) -> int:
        return self.cool + self.great + self.good + self.bad

    @property
    def difficulty_code(self) -> str:
        """難易度区分コード (L/N/H/E) を返す。
        L: EASY / Light
        N: NORMAL
        H: HYPER
        E: EX
        """
        d = str(self.difficulty).strip().upper()
        if d in ("EX", "E"):
            return "E"
        elif d in ("HYPER", "H"):
            return "H"
        elif d in ("NORMAL", "N"):
            return "N"
        elif d in ("EASY", "LIGHT", "L"):
            return "L"
        return d or ""

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "level": self.level,
            "difficulty": self.difficulty,
            "score": self.score,
            "cool": self.cool,
            "great": self.great,
            "good": self.good,
            "bad": self.bad,
            "combo": self.combo,
            "options": self.options.to_dict(),
            "timestamp": self.timestamp,
            "music_id": self.music_id,
            "record_id": self.record_id,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "PopnScoreRecord":
        return cls(
            title=d.get("title", "Unknown"),
            level=d.get("level", ""),
            difficulty=d.get("difficulty", "E"),
            score=d.get("score", 0),
            cool=d.get("cool", 0),
            great=d.get("great", 0),
            good=d.get("good", 0),
            bad=d.get("bad", 0),
            combo=d.get("combo", 0),
            options=PopnOptions.from_dict(d.get("options", {})),
            timestamp=d.get("timestamp", ""),
            music_id=d.get("music_id", ""),
            record_id=d.get("record_id"),
        )

    def to_csv_row(self) -> list:
        """CSV 1行分のリスト。
        指定順序: レベル, 曲名, 難易度区分 (L/N/H/E), SCORE, COOL, GREAT, GOOD, BAD, COMBO, 各種オプション..., プレー日時
        """
        return [
            self.level if self.level else "",
            self.title,
            self.difficulty_code,
            self.score,
            self.cool,
            self.great,
            self.good,
            self.bad,
            self.combo,
            self.options.hispeed,
            self.options.popkun,
            self.options.gauge_type,
            self.options.guide_se,
            self.options.random,
            self.options.judge_plus,
            self.options.hidden,
            self.options.sudden,
            self.options.ojama1,
            self.options.ojama2,
            self.options.auto,
            self.timestamp,
        ]


class DetectMode(Enum):
    """現在の画面状態"""
    unknown          = 0
    select           = 1   # 選曲画面
    play             = 2   # プレー画面
    result           = 3   # リザルト画面
    option           = 4   # オプション画面
    title            = 5   # タイトル画面
    ticket           = 6   # チケット画面
    character_select = 7   # キャラクターセレクト画面
    exit             = 8   # 終了画面
    loading          = 9   # ロード画面（画面遷移中）
