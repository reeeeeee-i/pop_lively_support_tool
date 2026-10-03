"""pop'n music Lively 画面識別用の座標・ハッシュ定数。

撮影環境: ウィンドウモード 1710×1000px
本ファイルの座標はすべて 1920×1080 スケール後の値。
_normalize_size() でリサイズされた画像に適用する。

変換式: x_new = int(x_orig * 1920 / 1710), y_new = int(y_orig * 1080 / 1000)
"""


class PosIsPlay:
    """プレー画面識別用 (1920x1080 座標)。
    下部 GROOVE GAUGE ラベルエリア、および左上固定UI枠（Escでリタイア/F1でリトライ）を使用。
    """
    # 状態1: GROOVE GAUGE 文字ラベルエリア
    AREA_GAUGE  = (600, 932, 875, 965)
    AHASH_GAUGE = "c0c0c000ffffffff"

    # 状態2: 左上操作枠（Esc長押しでリタイア / F1長押しでリトライ）常時固定表示
    AREA_RETRY  = (10, 155, 125, 315)
    AHASH_RETRY = "fffe7cf6fffe0000"

    # 後方互換用エイリアス
    AREA        = AREA_GAUGE
    AHASH       = AHASH_GAUGE
    THRESHOLD   = 10


class PosMusicSelect:
    """選曲画面識別用 (1920x1080 座標)。
    通常選曲時は右上の「MusicSelect」ロゴ、
    カテゴリ選択時等も含めて常に表示される左下の「Backspaceでキャラセレへ」ボタンを使用。
    """
    # 状態1: 通常選曲時の右上「MusicSelect」ロゴ
    AREA_LOGO       = (1420, 35, 1880, 115)
    AHASH_LOGO      = "bc88888888b7ffff"

    # 状態2: 左下「Backspaceでキャラセレへ」操作ガイドボタン (カテゴリ選択時にも共通表示)
    AREA_BACKSPACE  = (10, 895, 230, 955)
    AHASH_BACKSPACE = "ff0000ff7f0005ff"

    THRESHOLD       = 10


class PosResult:
    """リザルト画面識別用 (1920x1080 座標)。
    スコアパネル左側の固定ラベル列（SCORE/COOL/GREAT/GOOD/BAD/COMBO/BEST SCORE）、
    および左下操作ボタンを使用。
    """
    # 状態1: スコアパネル左側固定ラベル列エリア (キャラクターや背景に影響されず完全不変)
    AREA_PANEL      = (680, 590, 1000, 960)
    AHASH_PANEL     = "f97170786070787e"

    # 状態2: 左下「白 ★オプション もう一度」操作ガイドボタン
    AREA_AGAIN_BTN  = (260, 875, 440, 945)
    AHASH_AGAIN_BTN = "7e7600087c417d7f"

    # 後方互換用エイリアス
    AREA            = AREA_PANEL
    AHASH           = AHASH_PANEL
    THRESHOLD       = 10


class PosOption:
    """オプション画面識別用。
    曲決定直後の OptionSelect 画面、およびオプション詳細設定画面の両方に対応。
    """
    # 状態1: OptionSelect 画面 (曲決定直後) の「OptionSelect」ロゴ
    AREA_DECIDE     = (670, 95, 1250, 195)
    AHASH_DECIDE    = "ffff1f0881808877"

    # 状態2: 詳細設定画面 (シンプル/フル設定切替ボタン)
    # 1080pフルスクリーン時およびウィンドウモード(クライアント領域ストレッチ等)の両方に対応
    AREA_BTN        = (1650, 875, 1895, 925)
    AHASH_BTN       = "007f7f7540c0e7ff"   # フル設定へ切替 (1080p)
    AHASH_BTN_FULL  = "00fffff48080f7ff"   # シンプル設定へ切替 (1080p)
    AHASH_BTN_LIST  = [
        "007f7f7540c0e7ff",  # フル設定へ切替 (1080p)
        "00fffff48080f7ff",  # シンプル設定へ切替 (1080p)
        "00feffffc000e7ff",  # シンプル設定へ切替 (ウィンドウ全体キャプチャ)
        "ffffe00000c2ff7f",  # シンプル設定へ切替 (ウィンドウクライアント領域)
        "feffc0000085fffe",  # シンプル設定へ切替 (クライアント代替)
    ]

    # 状態3: 詳細設定画面の中央上部「CATEGORY」プレート (常時固定表示)
    AREA_CATEGORY   = (1265, 318, 1485, 354)
    AHASH_CATEGORY_LIST = [
        "ff404242ff81ffff",  # ウィンドウクライアント領域
        "ff404042ff81ffff",  # ウィンドウクライアント領域 (別項目)
        "ff4e40427e8181ff",  # 1080p フルスクリーン
        "9999999bdb42c2c3",  # 1080p 代替
        "939393d3c342c6c7",  # 1080p 代替
    ]

    # 状態4: 詳細設定画面の右端縦テキスト「CUSTOMIZE YOUR GAMEPLAY」
    AREA_CUSTOMIZE  = (1680, 200, 1720, 540)
    AHASH_CUSTOMIZE_LIST = [
        "f0f0f2f8f0f0f0f0",
        "f1f1f1f1f1f1f1f1",
        "e3e3e3ebe3e3e3e3",
        "e3e3cbe3e3e3c3e3",
    ]

    THRESHOLD       = 10


class PosTitle:
    """タイトル画面識別用。
    中央の「pop'n music Lively」タイトルロゴを使用。
    """
    AREA      = (600, 320, 1320, 620)
    AHASH     = "bf9f0180809dfdff"
    THRESHOLD = 10


class PosTicket:
    """チケット画面識別用。
    右上の「Ticket」筆記体ロゴを使用。
    """
    AREA_LOGO = (1560, 20, 1880, 105)
    AHASH_LOGO = "ffbfb0e1c18081ff"
    THRESHOLD = 10


class PosCharacterSelect:
    """キャラクターセレクト画面識別用。
    右下の「1 お気に入り」操作ボタン（全キャラ・全カテゴリ共通）を使用。
    """
    AREA      = (1710, 860, 1895, 925)
    AHASH     = "807fffc1c1ff7e81"
    THRESHOLD = 10


class PosExit:
    """終了画面識別用。
    画面中央の特大「See you!!」ロゴを使用。
    """
    AREA      = (450, 500, 1470, 920)
    AHASH     = "a0263fe161031616"
    THRESHOLD = 10


class PosJudge:
    """プレー画面の判定内訳バー座標 (1920x1080)。

    画面下部に「BAD 0020 GOOD 0016 GREAT 0038 COOL 0125」が横並びで表示される。
    各判定の色:
      BAD   = シアン   (R<120, G>150, B>180)
      GOOD  = 赤       (R>180, G<80,  B<80)
      GREAT = 橙(黄)   (R>180, G=90..180, B<80)
      COOL  = マゼンタ (R>180, G<80,  B>180)

    実装: 前フレームとのカラーピクセル数の変化量で判定増分を推定する。
    """
    # バー全体エリア
    FULL_AREA   = (600, 1025, 1350, 1070)

    # 各判定のスキャンエリア (左→右: BAD / GOOD / GREAT / COOL)
    BAD_AREA    = (600,  1028, 780,  1067)   # シアン
    GOOD_AREA   = (780,  1028, 965,  1067)   # 赤
    GREAT_AREA  = (965,  1028, 1160, 1067)   # 橙
    COOL_AREA   = (1160, 1028, 1345, 1067)   # マゼンタ

    # 色変化検出しきい値
    # この値以上ピクセル数が変動したら「その判定が発生した」とみなす
    CHANGE_THRESHOLD = 8


class PosPlaySong:
    """プレー画面上部の曲名バー (1920x1080 座標)。
    黒地に白文字の曲名と、右端の丸い難易度アイコンが並ぶ。
    縦位置はキャプチャ方式によってずれるため、バーを動的に検出する (src/song_reader.py)。
    """
    TITLE_X        = (640, 1285)   # 曲名文字の表示域 (左右のアイコンを避けた範囲)
    SEARCH_BOTTOM  = 200           # バー探索範囲の下端
    BAR_HEIGHT     = (60, 110)     # バーとみなす高さの範囲
    DIFF_ICON_X    = 1330          # 難易度アイコンの中心 x (中心 y はバー中央)
    DIFF_ICON_HALF = 30            # 難易度アイコンの色を調べる範囲 (中心から ±px)


class PosOptionItems:
    """オプション設定画面の各項目スキャン領域 (1920x1080 座標)。
    スクショ撮影後に各設定値領域の座標・ハッシュ等を微調整可能。
    """
    HISPEED_AREA     = (500, 220, 1420, 300)
    POPKUN_AREA      = (500, 320, 1420, 400)
    GAUGE_TYPE_AREA  = (500, 420, 1420, 500)
    GUIDE_SE_AREA    = (500, 520, 1420, 600)
    RANDOM_AREA      = (500, 620, 1420, 700)
    JUDGE_PLUS_AREA  = (500, 720, 1420, 800)
    HIDDEN_AREA      = (500, 820, 1420, 900)
    SUDDEN_AREA      = (500, 920, 1420, 1000)
    OJAMA1_AREA      = (500, 1020, 1420, 1100)
    OJAMA2_AREA      = (500, 1120, 1420, 1200)
    AUTO_AREA        = (500, 1220, 1420, 1300)

    # 互換用エイリアス
    GAUGE_AREA       = GAUGE_TYPE_AREA
    ARRANGEMENT_AREA = RANDOM_AREA


class PosLoading:
    """ロード画面（画面遷移中）識別用 (1920x1080 座標)。

    グリッド型ロード画面:
        CHARA SELECT / MUSIC SELECT / OPTION SELECT / STAGE RESULT
        への遷移時に表示されるカラフルなタイルグリッド画面。
        中央赤パネルのテキストのみが異なるが、周囲のパネル配置は完全に同一。
        左上セクション（pop'n music ロゴ + POP'N MUSIC テキスト）を検出に使用。

    プレーロード画面:
        "Let's enjoy music!" バナーが表示されるプレー開始前のロード画面。
    """
    # 状態1: グリッド型ロード画面 — 左上2〜3パネル (pop'n music ロゴ + POP'N MUSIC テキスト)
    # 全グリッドロード画面で完全に同一のハッシュ (distance=0)
    AREA_GRID_LOGO   = (195, 35, 680, 260)
    AHASH_GRID_LOGO  = "1e9e1e1a12129e9e"

    # 状態2: グリッド型ロード画面 — 下段全体
    # 全グリッドロード画面で完全に同一のハッシュ (distance=0)
    AREA_GRID_BOTTOM  = (0, 570, 1920, 1080)
    AHASH_GRID_BOTTOM = "f2f8664f4f674747"

    # 状態3: プレーロード画面 — "Let's enjoy music!" 中央バナー
    AREA_PLAY_BANNER  = (350, 250, 1000, 580)
    AHASH_PLAY_BANNER = "00010101073f3f3f"

    THRESHOLD = 10

