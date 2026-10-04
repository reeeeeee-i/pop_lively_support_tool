"""pop'n music Lively 画面状態検出・判定内訳読み取り"""
from __future__ import annotations

import functools
import os
from datetime import datetime

import imagehash
import numpy as np
from PIL import Image

from src.classes import DetectMode, PopnJudge, PopnOptions, PopnScoreRecord
from src.define import (
    PosIsPlay,
    PosMusicSelect,
    PosResult,
    PosOption,
    PosTitle,
    PosTicket,
    PosStatus,
    PosCharacterSelect,
    PosExit,
    PosLoading,
)
from src.judge_reader import JUDGE_NAMES, read_judge_counts
from src.logger import get_logger
from src.option_reader import has_option_icons, read_option_icons, read_option_list
from src.result_reader import ResultValues, read_result_values
from src.song_reader import PlaySongInfo, crop_title, read_play_song

logger = get_logger(__name__)

# 判定内訳: 1 フレームでこれを超えて増えた値は、次のフレームでも裏付けが取れてから採用する
_JUDGE_MAX_STEP = 20
# 判定内訳: 全判定が減った状態がこのフレーム数続いたら、次の曲 (またはリトライ) が始まったとみなす
_JUDGE_RESTART_FRAMES = 5


@functools.lru_cache(maxsize=None)
def _ref_hash(hex_str: str) -> imagehash.ImageHash:
    return imagehash.hex_to_hash(hex_str)


def _matches(image: Image.Image, threshold: int, *marks: tuple) -> bool:
    """画面の目印 (領域, 基準ハッシュまたはそのリスト) のいずれかに一致するか。

    領域の average hash と基準ハッシュの距離が threshold 以内なら一致とみなす。
    """
    try:
        for area, refs in marks:
            h = imagehash.average_hash(image.crop(area))
            if isinstance(refs, str):
                refs = (refs,)
            if any(_ref_hash(ref) - h <= threshold for ref in refs):
                return True
    except Exception:
        pass
    return False


class ScreenReader:
    """pop'n music Lively の画面状態検出と判定内訳読み取りを担う。

    判定内訳の読み取り方針:
        プレー画面下部バーに「BAD 0010 GOOD 0010 GREAT 0003 COOL 0003」が
        リアルタイムで表示される。この累計値を数字として読み取り (src/judge_reader.py)、
        読み誤りを弾きながら曲ごとの判定内訳として保持する。
    """

    def __init__(self):
        self.reset_judge()

    def reset_judge(self) -> None:
        """保持している判定内訳をリセットする（スコア記録後・カウントリセット時）。"""
        self._judge = dict.fromkeys(JUDGE_NAMES, 0)
        self._judge_pending: dict[str, int] = {}
        self._judge_restart_frames = 0

    # ------------------------------------------------------------------
    # 画面状態検出
    # ------------------------------------------------------------------

    def is_play(self, image: Image.Image) -> bool:
        """プレー画面かどうか"""
        return _matches(
            image, PosIsPlay.THRESHOLD,
            # 左上の「Esc長押しでリタイア / F1長押しでリトライ」枠（常時固定表示）
            (PosIsPlay.AREA_RETRY, PosIsPlay.AHASH_RETRY_LIST),
            # GROOVE GAUGE ラベル
            (PosIsPlay.AREA_GAUGE, PosIsPlay.AHASH_GAUGE),
        )

    def is_result(self, image: Image.Image) -> bool:
        """リザルト画面かどうか"""
        return _matches(
            image, PosResult.THRESHOLD,
            # スコアパネル左側の固定ラベル列（キャラクターやスコア値に依存せず完全不変）
            (PosResult.AREA_PANEL, PosResult.AHASH_PANEL),
            # 左下の「白 ★オプション もう一度」操作ボタン
            (PosResult.AREA_AGAIN_BTN, PosResult.AHASH_AGAIN_BTN),
        )

    def is_option(self, image: Image.Image) -> bool:
        """オプション画面かどうか（OptionSelect 画面および詳細設定画面の両方に対応）"""
        if _matches(
            image, PosOption.THRESHOLD,
            # OptionSelect 画面 (曲決定直後) の「OptionSelect」ロゴ
            (PosOption.AREA_DECIDE, PosOption.AHASH_DECIDE),
            # 詳細設定画面の設定切替ボタン (フル設定切替 / シンプル設定切替)
            (PosOption.AREA_BTN, PosOption.AHASH_BTN_LIST),
            # 詳細設定画面の中央上部「CATEGORY」プレート
            (PosOption.AREA_CATEGORY, PosOption.AHASH_CATEGORY_LIST),
        ):
            return True
        try:
            # OptionSelect 画面のオプションアイコン (ロゴの位置がずれるキャプチャ方式向け)
            return has_option_icons(np.asarray(image.convert("RGB")))
        except Exception:
            return False

    def is_title(self, image: Image.Image) -> bool:
        """タイトル画面かどうか"""
        return _matches(image, PosTitle.THRESHOLD, (PosTitle.AREA, PosTitle.AHASH))

    def is_ticket(self, image: Image.Image) -> bool:
        """チケット画面かどうか"""
        return _matches(
            image, PosTicket.THRESHOLD,
            # 右上の「Ticket」ロゴ
            (PosTicket.AREA_LOGO, PosTicket.AHASH_LOGO),
            # 右下の所持チケット表示（カテゴリ選択中はロゴが隠れるため）
            (PosTicket.AREA_OWNED, PosTicket.AHASH_OWNED),
        )

    def is_status(self, image: Image.Image) -> bool:
        """ステータス画面かどうか"""
        return _matches(
            image, PosStatus.THRESHOLD,
            # 右上の「Status」ロゴ
            (PosStatus.AREA_LOGO, PosStatus.AHASH_LOGO),
            # プレーヤーカード右下の「ポプともLivelyID：」ラベル
            (PosStatus.AREA_ID, PosStatus.AHASH_ID),
        )

    def is_character_select(self, image: Image.Image) -> bool:
        """キャラクターセレクト画面かどうか"""
        return _matches(
            image, PosCharacterSelect.THRESHOLD,
            # 右下の「1 お気に入り」操作ボタン
            (PosCharacterSelect.AREA, PosCharacterSelect.AHASH),
            # 左下の「player」ラベル（お気に入りボタンが「解除」に変わっている場合向け）
            (PosCharacterSelect.AREA_PLAYER, PosCharacterSelect.AHASH_PLAYER),
        )

    def is_exit(self, image: Image.Image) -> bool:
        """終了画面（See you!!）かどうか"""
        return _matches(image, PosExit.THRESHOLD, (PosExit.AREA, PosExit.AHASH))

    def is_loading(self, image: Image.Image) -> bool:
        """ロード画面（画面遷移中）かどうか。

        グリッド型ロード画面（CHARA SELECT / MUSIC SELECT / OPTION SELECT / STAGE RESULT）
        およびプレーロード画面（"Let's enjoy music!"）を検出する。
        """
        return _matches(
            image, PosLoading.THRESHOLD,
            # グリッド型ロード画面: 左上の pop'n music ロゴ + POP'N MUSIC パネル
            (PosLoading.AREA_GRID_LOGO, PosLoading.AHASH_GRID_LOGO),
            # グリッド型ロード画面: 下段全体
            (PosLoading.AREA_GRID_BOTTOM, PosLoading.AHASH_GRID_BOTTOM),
            # プレーロード画面: "Let's enjoy music!" バナー
            (PosLoading.AREA_PLAY_BANNER, PosLoading.AHASH_PLAY_BANNER),
        )

    def is_valid_game_screen(self, image: Image.Image) -> bool:
        """有効なゲーム画面が取り込めているかどうかを判定する。
        OBS接続中に対象ウィンドウが未起動・フック前・最小化中などの場合、
        完全な黒画面（全ピクセル0）または極めて低輝度・無変化の画像が返される。
        """
        try:
            # 高速化のため縮小してピクセル統計を計算 (160x90)
            small = image.resize((160, 90), Image.Resampling.NEAREST)
            arr = np.array(small)
            # 黒画面または極端な低輝度の場合は未取得
            if arr.max() < 25 or arr.mean() < 8.0:
                return False
            # 単色ブランク画面の排除
            return bool(arr.std() >= 5.0)
        except Exception:
            return False

    def is_music_select(self, image: Image.Image) -> bool:
        """選曲画面かどうか"""
        return _matches(
            image, PosMusicSelect.THRESHOLD,
            # 通常選曲時の右上「MusicSelect」ロゴ
            (PosMusicSelect.AREA_LOGO, PosMusicSelect.AHASH_LOGO),
            # カテゴリ選択中等も含めて常に表示される左下の Backspace ボタン
            (PosMusicSelect.AREA_BACKSPACE, PosMusicSelect.AHASH_BACKSPACE),
            # ダイアログ (クエスト・判定調整・キーコンフィグ等) を開いていても残る左下ボタンの左側
            (PosMusicSelect.AREA_GUIDE, PosMusicSelect.AHASH_GUIDE),
        )

    def detect_mode(self, image: Image.Image) -> DetectMode:
        """現在の画面状態を返す。

        黒画面・未取得時は unknown。それ以外は以下の順に判定し、最初に一致したものを返す。
        """
        if not self.is_valid_game_screen(image):
            return DetectMode.unknown

        checks = (
            (DetectMode.loading,          self.is_loading),
            (DetectMode.title,            self.is_title),
            (DetectMode.status,           self.is_status),
            (DetectMode.ticket,           self.is_ticket),
            (DetectMode.character_select, self.is_character_select),
            (DetectMode.option,           self.is_option),
            (DetectMode.exit,             self.is_exit),
            (DetectMode.play,             self.is_play),
            (DetectMode.result,           self.is_result),
            (DetectMode.select,           self.is_music_select),
        )
        for mode, check in checks:
            if check(image):
                return mode
        return DetectMode.unknown

    # ------------------------------------------------------------------
    # 判定内訳読み取り
    # ------------------------------------------------------------------

    def detect_judge(self, image: Image.Image) -> tuple[PopnJudge, bool]:
        """プレー画面から現在の曲の判定内訳 (累計値) を読み取る。

        累計値は増える一方なので、減った値や急に増えた値は読み誤りとして採用しない。
        読めなかった判定は直前の値のまま。

        Returns:
            (判定内訳の累計値, 次の曲の開始を検出して累計値が巻き戻ったか)
        """
        counts = read_judge_counts(image)
        current = self._judge

        # 全判定が読めていて大きく減っている状態が続く → 次の曲が始まり 0 から数え直している
        restarted = False
        if (
            None not in counts.values()
            and all(counts[n] <= current[n] for n in JUDGE_NAMES)
            and sum(counts.values()) * 2 <= sum(current.values())
            and sum(current.values()) > 0
        ):
            self._judge_restart_frames += 1
            if self._judge_restart_frames >= _JUDGE_RESTART_FRAMES:
                self.reset_judge()
                current = self._judge
                restarted = True
        else:
            self._judge_restart_frames = 0

        for name in JUDGE_NAMES:
            value = counts[name]
            if value is None or value < current[name]:
                continue
            base = current[name]
            if value > base + _JUDGE_MAX_STEP:
                # 急な増加は、前フレームの値からも無理なく続いている場合だけ採用する
                base = self._judge_pending.get(name, -1)
                if not base <= value <= base + _JUDGE_MAX_STEP:
                    self._judge_pending[name] = value
                    continue
            self._judge_pending.pop(name, None)
            current[name] = value

        return PopnJudge(**current), restarted

    # ------------------------------------------------------------------
    # オプション認識 (オプション画面)
    # ------------------------------------------------------------------

    def read_options(self, image: Image.Image) -> dict[str, str] | None:
        """オプション画面から使用オプションを読み取る。

        設定を開いている間は右下の設定一覧、開いていない OptionSelect 画面では
        オプションアイコンから読む。戻り値は {項目キー: 値} (読めなかった項目は含まない)。
        どちらも表示されていなければ None。
        """
        try:
            values = read_option_list(image)
            return values if values is not None else read_option_icons(image)
        except Exception as e:
            logger.error("オプション読み取りエラー: %s", e)
            return None

    # ------------------------------------------------------------------
    # 曲名認識 (プレー画面上部)
    # ------------------------------------------------------------------

    def read_play_song(self, image: Image.Image) -> PlaySongInfo:
        """プレー画面上部の曲名バーから曲名 (OCR 文字列) と難易度区分を読み取る。
        曲名は誤字を含みうるので、ScoreManager.identify_song で曲テーブルと照合して使う。
        """
        try:
            return read_play_song(image)
        except Exception as e:
            logger.error("曲名読み取りエラー: %s", e)
            return PlaySongInfo()

    @staticmethod
    def save_unread_title(image: Image.Image) -> None:
        """曲を特定できなかったプレー画面の曲名バーを保存する (調査用)。"""
        try:
            crop = crop_title(image)
            if crop is not None:
                os.makedirs("out", exist_ok=True)
                crop.save("out/last_song_title.png")
        except Exception as e:
            logger.debug("曲名バー保存失敗: %s", e)

    # ------------------------------------------------------------------
    # リザルト画面認識
    # ------------------------------------------------------------------

    def read_result_values(self, image: Image.Image) -> ResultValues | None:
        """リザルト画面のスコアパネルから数値を読み取る。パネルが見つからなければ None。"""
        try:
            return read_result_values(image)
        except Exception as e:
            logger.error("リザルト読み取りエラー: %s", e)
            return None

    def read_result(
        self,
        image: Image.Image,
        live_judge: PopnJudge | None = None,
        options: PopnOptions | None = None,
        title: str = "Unknown",
        level: int | str = "",
        difficulty: str = "",
        values: ResultValues | None = None,
    ) -> PopnScoreRecord:
        """リザルト画面からスコア、COOL等の判定数、コンボ数を取得する。

        values を省略した場合は image から読み取る。
        読めなかった項目のみ、プレー中のライブ集計値 (live_judge) や推定値で補う。
        """
        if values is None:
            values = self.read_result_values(image)

        try:
            os.makedirs("out", exist_ok=True)
            image.save("out/last_result.png")
        except Exception:
            pass

        if values is None:
            logger.warning("リザルト: スコアパネルを検出できませんでした。ライブ集計値で代用します")
            values = ResultValues()
        if values.notes or not values.is_complete:
            for note in values.notes:
                logger.warning("リザルト読み取り: %s", note)
            self._save_unread_result(image)

        live = live_judge or PopnJudge()
        judge = {
            name: read if (read := getattr(values, name)) is not None else getattr(live, name)
            for name in JUDGE_NAMES
        }

        score = values.score
        if score is None:
            # スコア推定値 (画像から読めなかった場合の補助)
            total = sum(judge.values())
            weighted = judge["cool"] * 100000 + judge["great"] * 70000 + judge["good"] * 40000
            score = int(weighted / total) if total > 0 else 0

        return PopnScoreRecord(
            title=title,
            level=level,
            difficulty=difficulty,
            score=score,
            **judge,
            combo=values.combo if values.combo is not None else 0,
            options=options or PopnOptions(),
        )

    @staticmethod
    def _save_unread_result(image: Image.Image) -> None:
        """読み取りに不確かな点があったリザルト画面を保存する。

        tools/build_digit_templates.py の SAMPLES に正解値とともに追加すれば、
        未収録の数字のテンプレートを増やせる。
        """
        try:
            os.makedirs("out/result_unread", exist_ok=True)
            image.save(f"out/result_unread/{datetime.now():%Y%m%d_%H%M%S}.png")
        except Exception as e:
            logger.debug("未読リザルト保存失敗: %s", e)

