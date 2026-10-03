"""pop'n music Lively 画面状態検出・判定内訳読み取り"""
from __future__ import annotations

import imagehash
import numpy as np
import os
from datetime import datetime
from PIL import Image

from src.classes import DetectMode, PopnJudge, PopnOptions, PopnScoreRecord
from src.define import (
    PosIsPlay,
    PosMusicSelect,
    PosResult,
    PosOption,
    PosTitle,
    PosTicket,
    PosCharacterSelect,
    PosExit,
    PosJudge,
    PosOptionItems,
    PosLoading,
)
from src.logger import get_logger
from src.result_reader import ResultValues, read_result_values
from src.song_reader import PlaySongInfo, crop_title, read_play_song

logger = get_logger(__name__)


class ScreenReader:
    """pop'n music Lively の画面状態検出と判定内訳読み取りを担う。

    判定内訳の読み取り方針:
        プレー画面下部バーに「BAD 0010 GOOD 0010 GREAT 0003 COOL 0003」が
        リアルタイムで表示される。累計値が各フレームで変化するため、
        各色ピクセル数の増分から「このフレームで何判定が発生したか」を推定する。

        色の対応:
            BAD   → シアン (R<150, G>180, B>180)
            GOOD  → 赤     (R>200, G<80,  B<80)
            GREAT → 黄     (R>200, G>200, B<80)
            COOL  → マゼンタ (R>200, G<80, B>200)
    """

    def __init__(self):
        self._prev_bad_px   = 0
        self._prev_good_px  = 0
        self._prev_great_px = 0
        self._prev_cool_px  = 0
        self._judge_initialized = False

    def reset_judge(self) -> None:
        """プレー開始時に呼ぶ。前フレームキャッシュをリセット。"""
        self._prev_bad_px   = 0
        self._prev_good_px  = 0
        self._prev_great_px = 0
        self._prev_cool_px  = 0
        self._judge_initialized = False

    # ------------------------------------------------------------------
    # 画面状態検出
    # ------------------------------------------------------------------

    def is_play(self, image: Image.Image) -> bool:
        """プレー画面かどうか（左上リトライ枠またはGROOVE GAUGEラベルで判定）"""
        try:
            # 1. 左上の「Esc長押しでリタイア / F1長押しでリトライ」枠（常時固定表示）
            if hasattr(PosIsPlay, "AHASH_RETRY") and PosIsPlay.AHASH_RETRY:
                h_retry = imagehash.average_hash(image.crop(PosIsPlay.AREA_RETRY))
                ref_retry = imagehash.hex_to_hash(PosIsPlay.AHASH_RETRY)
                if (ref_retry - h_retry) <= PosIsPlay.THRESHOLD:
                    return True

            # 2. GROOVE GAUGE ラベルエリア
            area_gauge = getattr(PosIsPlay, "AREA_GAUGE", PosIsPlay.AREA)
            ahash_gauge = getattr(PosIsPlay, "AHASH_GAUGE", PosIsPlay.AHASH)
            h_gauge = imagehash.average_hash(image.crop(area_gauge))
            ref_gauge = imagehash.hex_to_hash(ahash_gauge)
            return (ref_gauge - h_gauge) <= PosIsPlay.THRESHOLD
        except Exception:
            return False

    def is_result(self, image: Image.Image) -> bool:
        """リザルト画面かどうか（スコアパネル左側固定ラベル列で判定）"""
        try:
            # 1. スコアパネル左側の固定ラベル列エリア（キャラクターやスコア値に依存せず完全不変）
            if hasattr(PosResult, "AHASH_PANEL") and PosResult.AHASH_PANEL:
                h_panel = imagehash.average_hash(image.crop(PosResult.AREA_PANEL))
                ref_panel = imagehash.hex_to_hash(PosResult.AHASH_PANEL)
                if (ref_panel - h_panel) <= PosResult.THRESHOLD:
                    return True

            # 2. 左下の「白 ★オプション もう一度」操作ボタン
            if hasattr(PosResult, "AHASH_AGAIN_BTN") and PosResult.AHASH_AGAIN_BTN:
                h_again = imagehash.average_hash(image.crop(PosResult.AREA_AGAIN_BTN))
                ref_again = imagehash.hex_to_hash(PosResult.AHASH_AGAIN_BTN)
                if (ref_again - h_again) <= PosResult.THRESHOLD:
                    return True

            # 旧定義互換
            h = imagehash.average_hash(image.crop(PosResult.AREA))
            ref = imagehash.hex_to_hash(PosResult.AHASH)
            return (ref - h) <= PosResult.THRESHOLD
        except Exception:
            return False

    def is_option(self, image: Image.Image) -> bool:
        """オプション画面かどうか（OptionSelect画面および詳細設定画面の両方に対応）"""
        try:
            # 1. OptionSelect 画面 (曲決定直後) の「OptionSelect」ロゴ
            h_decide   = imagehash.average_hash(image.crop(PosOption.AREA_DECIDE))
            ref_decide = imagehash.hex_to_hash(PosOption.AHASH_DECIDE)
            if (ref_decide - h_decide) <= PosOption.THRESHOLD:
                return True

            # 2. 詳細設定画面 (設定切替ボタン: フル設定切替 または シンプル設定切替)
            h_btn = imagehash.average_hash(image.crop(PosOption.AREA_BTN))
            btn_hashes = getattr(PosOption, "AHASH_BTN_LIST", [])
            if not btn_hashes:
                btn_hashes = [PosOption.AHASH_BTN]
                if hasattr(PosOption, "AHASH_BTN_FULL") and PosOption.AHASH_BTN_FULL:
                    btn_hashes.append(PosOption.AHASH_BTN_FULL)
            for ref_str in btn_hashes:
                if (imagehash.hex_to_hash(ref_str) - h_btn) <= PosOption.THRESHOLD:
                    return True

            # 3. 詳細設定画面 (中央上部の「CATEGORY」プレート)
            if hasattr(PosOption, "AREA_CATEGORY") and hasattr(PosOption, "AHASH_CATEGORY_LIST"):
                h_cat = imagehash.average_hash(image.crop(PosOption.AREA_CATEGORY))
                for ref_str in PosOption.AHASH_CATEGORY_LIST:
                    if (imagehash.hex_to_hash(ref_str) - h_cat) <= PosOption.THRESHOLD:
                        return True

            # 4. 詳細設定画面 (右端の「CUSTOMIZE YOUR GAMEPLAY」縦テキスト)
            if hasattr(PosOption, "AREA_CUSTOMIZE") and hasattr(PosOption, "AHASH_CUSTOMIZE_LIST"):
                h_cust = imagehash.average_hash(image.crop(PosOption.AREA_CUSTOMIZE))
                for ref_str in PosOption.AHASH_CUSTOMIZE_LIST:
                    if (imagehash.hex_to_hash(ref_str) - h_cust) <= PosOption.THRESHOLD:
                        return True

            return False
        except Exception:
            return False

    def is_title(self, image: Image.Image) -> bool:
        """タイトル画面かどうか"""
        if not PosTitle.AHASH:
            return False
        try:
            h   = imagehash.average_hash(image.crop(PosTitle.AREA))
            ref = imagehash.hex_to_hash(PosTitle.AHASH)
            return (ref - h) <= PosTitle.THRESHOLD
        except Exception:
            return False

    def is_ticket(self, image: Image.Image) -> bool:
        """チケット画面かどうか（右上のTicketロゴ）"""
        if not PosTicket.AHASH_LOGO:
            return False
        try:
            h_logo   = imagehash.average_hash(image.crop(PosTicket.AREA_LOGO))
            ref_logo = imagehash.hex_to_hash(PosTicket.AHASH_LOGO)
            return (ref_logo - h_logo) <= PosTicket.THRESHOLD
        except Exception:
            return False

    def is_character_select(self, image: Image.Image) -> bool:
        """キャラクターセレクト画面かどうか"""
        if not PosCharacterSelect.AHASH:
            return False
        try:
            h   = imagehash.average_hash(image.crop(PosCharacterSelect.AREA))
            ref = imagehash.hex_to_hash(PosCharacterSelect.AHASH)
            return (ref - h) <= PosCharacterSelect.THRESHOLD
        except Exception:
            return False

    def is_exit(self, image: Image.Image) -> bool:
        """終了画面（See you!!）かどうか"""
        if not PosExit.AHASH:
            return False
        try:
            h   = imagehash.average_hash(image.crop(PosExit.AREA))
            ref = imagehash.hex_to_hash(PosExit.AHASH)
            return (ref - h) <= PosExit.THRESHOLD
        except Exception:
            return False

    def is_loading(self, image: Image.Image) -> bool:
        """ロード画面（画面遷移中）かどうか。

        グリッド型ロード画面（CHARA SELECT / MUSIC SELECT / OPTION SELECT / STAGE RESULT）
        およびプレーロード画面（"Let's enjoy music!"）を検出する。
        """
        try:
            # 1. グリッド型ロード画面 — 左上 pop'n music ロゴ + POP'N MUSIC パネル
            h_logo = imagehash.average_hash(image.crop(PosLoading.AREA_GRID_LOGO))
            ref_logo = imagehash.hex_to_hash(PosLoading.AHASH_GRID_LOGO)
            if (ref_logo - h_logo) <= PosLoading.THRESHOLD:
                return True

            # 2. グリッド型ロード画面 — 下段全体
            h_bottom = imagehash.average_hash(image.crop(PosLoading.AREA_GRID_BOTTOM))
            ref_bottom = imagehash.hex_to_hash(PosLoading.AHASH_GRID_BOTTOM)
            if (ref_bottom - h_bottom) <= PosLoading.THRESHOLD:
                return True

            # 3. プレーロード画面 — "Let's enjoy music!" バナー
            h_play = imagehash.average_hash(image.crop(PosLoading.AREA_PLAY_BANNER))
            ref_play = imagehash.hex_to_hash(PosLoading.AHASH_PLAY_BANNER)
            if (ref_play - h_play) <= PosLoading.THRESHOLD:
                return True

            return False
        except Exception:
            return False

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
            if arr.std() < 5.0:
                return False
            return True
        except Exception:
            return False

    def is_music_select(self, image: Image.Image) -> bool:
        """選曲画面かどうか（右上のMusicSelectロゴまたは左下のBackspaceボタンで判定）"""
        try:
            # 1. 通常選曲時の右上「MusicSelect」ロゴ
            if hasattr(PosMusicSelect, "AHASH_LOGO") and PosMusicSelect.AHASH_LOGO:
                h_logo = imagehash.average_hash(image.crop(PosMusicSelect.AREA_LOGO))
                ref_logo = imagehash.hex_to_hash(PosMusicSelect.AHASH_LOGO)
                if (ref_logo - h_logo) <= PosMusicSelect.THRESHOLD:
                    return True

            # 2. カテゴリ選択中等も含めて常に表示される左下ボタン
            if hasattr(PosMusicSelect, "AHASH_BACKSPACE") and PosMusicSelect.AHASH_BACKSPACE:
                h_bs = imagehash.average_hash(image.crop(PosMusicSelect.AREA_BACKSPACE))
                ref_bs = imagehash.hex_to_hash(PosMusicSelect.AHASH_BACKSPACE)
                if (ref_bs - h_bs) <= PosMusicSelect.THRESHOLD:
                    return True

            # 旧定義互換
            ahash = getattr(PosMusicSelect, "AHASH", "")
            if ahash:
                h = imagehash.average_hash(image.crop(PosMusicSelect.AREA))
                ref = imagehash.hex_to_hash(ahash)
                return (ref - h) <= PosMusicSelect.THRESHOLD

            return False
        except Exception:
            return False

    def detect_mode(self, image: Image.Image) -> DetectMode:
        """現在の画面状態を返す。

        指定された制御ルールの順序:
          0. 有効なゲーム画面かどうか（黒画面・未取得時は unknown）
          1. ロード画面 (loading) — 画面遷移中のグリッドロード画面 / プレーロード画面
          2. タイトル (title)
          3. チケット (ticket)
          4. キャラセレクト (character_select)
          5. オプション (option)
          6. 終了画面 (exit)
          7. プレー画面 (play)
          8. リザルト (result)
          9. 選曲 (select)
        """
        # 0. 有効なゲーム画面が取得できているか確認（黒画面・未取得時は unknown）
        if not self.is_valid_game_screen(image):
            return DetectMode.unknown

        # 1. ロード画面（画面遷移中）
        if self.is_loading(image):
            return DetectMode.loading

        # 2. タイトル
        if self.is_title(image):
            return DetectMode.title

        # 3. チケット
        if self.is_ticket(image):
            return DetectMode.ticket

        # 4. キャラセレクト
        if self.is_character_select(image):
            return DetectMode.character_select

        # 5. オプション
        if self.is_option(image):
            return DetectMode.option

        # 6. 終了画面 (See you!!)
        if self.is_exit(image):
            return DetectMode.exit

        # 7. プレー画面
        if self.is_play(image):
            return DetectMode.play

        # 8. リザルト
        if self.is_result(image):
            return DetectMode.result

        # 9. 選曲
        if self.is_music_select(image):
            return DetectMode.select

        return DetectMode.unknown

    # ------------------------------------------------------------------
    # 判定内訳読み取り
    # ------------------------------------------------------------------

    @staticmethod
    def _count_color_pixels(
        arr: np.ndarray,
        r_range: tuple[int, int],
        g_range: tuple[int, int],
        b_range: tuple[int, int],
    ) -> int:
        """配列 arr 内で RGB 条件を満たすピクセル数を返す。"""
        r = arr[:, :, 0]
        g = arr[:, :, 1]
        b = arr[:, :, 2]
        mask = (
            (r >= r_range[0]) & (r <= r_range[1]) &
            (g >= g_range[0]) & (g <= g_range[1]) &
            (b >= b_range[0]) & (b <= b_range[1])
        )
        return int(np.sum(mask))

    def detect_judge(self, image: Image.Image) -> PopnJudge:
        """プレー画面から判定内訳の変化量を取得して返す。

        前フレームとのカラーピクセル数差分が CHANGE_THRESHOLD 以上あれば
        その判定が1つ発生したとみなす。

        Returns:
            PopnJudge: このフレームで発生した判定数（0 or 1 ずつ）
        """
        arr = np.array(image)

        def crop(area: tuple[int, int, int, int]) -> np.ndarray:
            x1, y1, x2, y2 = area
            return arr[y1:y2, x1:x2]

        # 各エリアの対象色ピクセル数を計測 (BAD:シアン, GOOD:赤, GREAT:橙, COOL:マゼンタ)
        bad_px   = self._count_color_pixels(crop(PosJudge.BAD_AREA),   (0, 120),   (150, 255), (180, 255))
        good_px  = self._count_color_pixels(crop(PosJudge.GOOD_AREA),  (180, 255), (0, 80),    (0, 80))
        great_px = self._count_color_pixels(crop(PosJudge.GREAT_AREA), (180, 255), (90, 180),  (0, 80))
        cool_px  = self._count_color_pixels(crop(PosJudge.COOL_AREA),  (180, 255), (0, 80),    (180, 255))

        # 初回フレームは初期値サンプリングのみ
        if self._judge_initialized:
            d_bad   = abs(bad_px   - self._prev_bad_px)
            d_good  = abs(good_px  - self._prev_good_px)
            d_great = abs(great_px - self._prev_great_px)
            d_cool  = abs(cool_px  - self._prev_cool_px)
        else:
            d_bad = d_good = d_great = d_cool = 0
            self._judge_initialized = True

        self._prev_bad_px   = bad_px
        self._prev_good_px  = good_px
        self._prev_great_px = great_px
        self._prev_cool_px  = cool_px

        t = PosJudge.CHANGE_THRESHOLD
        return PopnJudge(
            bad   = 1 if d_bad   >= t else 0,
            good  = 1 if d_good  >= t else 0,
            great = 1 if d_great >= t else 0,
            cool  = 1 if d_cool  >= t else 0,
        )

    # ------------------------------------------------------------------
    # オプション認識 (オプション画面)
    # ------------------------------------------------------------------

    def read_options(self, image: Image.Image) -> PopnOptions:
        """オプション選択画面から使用オプションを識別・取得する。
        スクショ未整備時は最新の既定オプションを保持する。
        """
        opt = PopnOptions()
        try:
            # 抽出画像保存 (キャリブレーション用)
            os.makedirs("out", exist_ok=True)
            image.crop(PosOptionItems.HISPEED_AREA).save("out/opt_hispeed.png")
            image.crop(PosOptionItems.POPKUN_AREA).save("out/opt_popkun.png")
            image.crop(PosOptionItems.GAUGE_AREA).save("out/opt_gauge.png")
            image.crop(PosOptionItems.ARRANGEMENT_AREA).save("out/opt_arrangement.png")
        except Exception as e:
            logger.debug("オプション領域キャプチャ失敗: %s", e)

        return opt

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

        def pick(read: int | None, live: int) -> int:
            return read if read is not None else live

        cool  = pick(values.cool,  live_judge.cool if live_judge else 0)
        great = pick(values.great, live_judge.great if live_judge else 0)
        good  = pick(values.good,  live_judge.good if live_judge else 0)
        bad   = pick(values.bad,   live_judge.bad if live_judge else 0)
        combo = pick(values.combo, 0)

        score = values.score
        if score is None:
            # スコア推定値 (画像から読めなかった場合の補助)
            total_notes = cool + great + good + bad
            score = int((cool * 100000 + great * 70000 + good * 40000) / total_notes) if total_notes > 0 else 0

        return PopnScoreRecord(
            title=title,
            level=level,
            difficulty=difficulty,
            score=score,
            cool=cool,
            great=great,
            good=good,
            bad=bad,
            combo=combo,
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

