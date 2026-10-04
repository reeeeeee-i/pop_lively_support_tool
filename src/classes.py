"""pop'n music Lively 専用データクラス・列挙型定義"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from src.option_master import OPTION_DEFAULTS, OPTION_KEYS, OPTION_LABELS

# 難易度区分コード (L/N/H/E) → 曲テーブルのレベル列
DIFFICULTY_LEVEL_COLUMNS = {"L": "easy", "N": "normal", "H": "hyper", "E": "ex"}

_DIFFICULTY_CODES = {
    "EASY": "L", "LIGHT": "L", "L": "L",
    "NORMAL": "N", "N": "N",
    "HYPER": "H", "H": "H",
    "EX": "E", "E": "E",
}

# 等速のハイスピード。旧データでは "OFF" / "x1.0" と記録されている
_HISPEED_OFF = ("OFF", "1.0", "x1.0")


def difficulty_code(difficulty: str) -> str:
    """難易度区分 (EASY / NORMAL / HYPER / EX など) をコード (L/N/H/E) にする。

    該当しない文字列は大文字にしてそのまま返す。
    """
    d = str(difficulty).strip().upper()
    return _DIFFICULTY_CODES.get(d, d)


def format_song(title: str, difficulty: str = "") -> str:
    """「曲名 [難易度区分コード]」形式の表示用文字列"""
    code = difficulty_code(difficulty)
    return f"{title} [{code}]" if code else title


@dataclass
class PopnJudge:
    """1 曲分の判定内訳"""
    cool: int = 0
    great: int = 0
    good: int = 0
    bad: int = 0

    @property
    def notes(self) -> int:
        """打鍵数 = COOL + GREAT + GOOD（BAD は基本的に見逃しなので含めない）"""
        return self.cool + self.great + self.good


@dataclass(eq=False, repr=False)
class PopnOptions:
    """使用オプション。

    項目 (属性名 = src/option_master.py の OPTION_KEYS) と各項目の選択肢は
    src/option_master.py を参照。
    """
    hispeed: str = OPTION_DEFAULTS["hispeed"]
    popkun: str = OPTION_DEFAULTS["popkun"]
    gauge_type: str = OPTION_DEFAULTS["gauge_type"]
    guide_se: str = OPTION_DEFAULTS["guide_se"]
    random: str = OPTION_DEFAULTS["random"]
    judge_plus: str = OPTION_DEFAULTS["judge_plus"]
    hidden: str = OPTION_DEFAULTS["hidden"]
    sudden: str = OPTION_DEFAULTS["sudden"]
    ojama1: str = OPTION_DEFAULTS["ojama1"]
    ojama2: str = OPTION_DEFAULTS["ojama2"]
    ojama1_zutto: str = OPTION_DEFAULTS["ojama1_zutto"]
    ojama2_zutto: str = OPTION_DEFAULTS["ojama2_zutto"]
    auto: str = OPTION_DEFAULTS["auto"]
    extra: dict = field(default_factory=dict)

    def to_summary(self) -> str:
        """既定値から変更されている項目だけを並べた要約文字列"""
        parts = []
        for key in OPTION_KEYS:
            value = getattr(self, key)
            if not value or value == OPTION_DEFAULTS[key]:
                continue
            if key == "hispeed" and value in _HISPEED_OFF:
                continue
            parts.append(f"{OPTION_LABELS[key]}:{value}")
        parts.extend(f"{k}:{v}" for k, v in self.extra.items() if v)
        return " / ".join(parts) if parts else "NORMAL"

    def to_dict(self) -> dict:
        return {**{key: getattr(self, key) for key in OPTION_KEYS}, "extra": dict(self.extra)}

    @classmethod
    def from_dict(cls, d: dict) -> "PopnOptions":
        if not isinstance(d, dict):
            return cls()
        return cls(
            **{key: d.get(key, OPTION_DEFAULTS[key]) for key in OPTION_KEYS},
            extra=d.get("extra", {}),
        )

    def __repr__(self) -> str:
        return f"PopnOptions({self.to_summary()})"


@dataclass(eq=False)
class PopnScoreRecord:
    """1プレーごとのスコア記録クラス"""
    title: str = "Unknown"
    level: int | str = ""
    difficulty: str = ""
    score: int = 0
    cool: int = 0
    great: int = 0
    good: int = 0
    bad: int = 0
    combo: int = 0
    options: PopnOptions = field(default_factory=PopnOptions)
    timestamp: str = ""
    """プレー日時。省略時は現在時刻"""
    music_id: str = ""
    record_id: int | None = None
    genre: str = ""
    artist: str = ""
    ver: str = ""
    modified: bool = False
    """記録後にスコア内容を手動修正したか"""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    @property
    def total_notes(self) -> int:
        return self.cool + self.great + self.good + self.bad

    @property
    def difficulty_code(self) -> str:
        """難易度区分コード (L: EASY / N: NORMAL / H: HYPER / E: EX)"""
        return difficulty_code(self.difficulty)

    def to_csv_row(self) -> list:
        """CSV 1行分のリスト。列順は src/db.py の CSV_HEADERS"""
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
            *(getattr(self.options, key) for key in OPTION_KEYS),
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
