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
    # タイトルバー込みのキャプチャでは GROOVE GAUGE の領域に曲の進行バーが入り込み、
    # 曲が進むとハッシュが変わるため、こちらの枠でも判定できるようにしておく
    AREA_RETRY  = (10, 155, 125, 315)
    AHASH_RETRY_LIST = [
        "fffe7cf6fffe0000",  # 1080p (クライアント領域)
        "0073f77e3c63ff7f",  # タイトルバー込みのウィンドウ全体キャプチャ (1368x806)
        "2073ff7e20637f7e",  # タイトルバー込みのウィンドウ全体キャプチャ (1710x1000)
    ]

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

    # 状態3: 左下「Esc長押しでゲーム終了 / Backspaceでキャラセレへ」ボタンの左側 (1080p)
    # カテゴリ選択中のほか、クエスト・カスタマイズフォルダ・判定調整・キーコンフィグの
    # ダイアログを開いている間も、ダイアログに隠れずに残る範囲
    AREA_GUIDE      = (25, 865, 175, 945)
    AHASH_GUIDE     = "4d02ff00ffff0007"

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

    # 右端の縦テキスト「CUSTOMIZE YOUR GAMEPLAY」は、選曲画面のダイアログ
    # (判定調整・キーコンフィグ等) にも同じ枠で表示されるため、目印には使わない

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
    右上の「Ticket」筆記体ロゴ、および右下の所持チケット表示を使用。
    """
    # 状態1: 右上「Ticket」ロゴ (カテゴリ選択中は隠れる)
    AREA_LOGO = (1560, 20, 1880, 105)
    AHASH_LOGO = "ffbfb0e1c18081ff"

    # 状態2: 右下の所持チケット表示のアイコンと「Livelyチケット」ラベル (枚数は含めない)
    # カテゴリ選択中も表示される
    AREA_OWNED  = (1480, 808, 1890, 858)
    AHASH_OWNED = "e0e2afa81718e8e0"

    THRESHOLD = 10


class PosStatus:
    """ステータス画面識別用 (1920x1080 座標)。
    右上の「Status」ロゴ、およびプレーヤーカード右下の「ポプともLivelyID：」ラベルを使用。
    どちらもカードのフェードイン中から表示完了後まで不変。
    """
    # 状態1: 右上「Status」ロゴ
    AREA_LOGO  = (1600, 20, 1880, 95)
    AHASH_LOGO = "ff1bc2c29080ff7f"

    # 状態2: 「ポプともLivelyID：」ラベル (ID の数字は含めない)
    AREA_ID    = (1005, 800, 1245, 845)
    AHASH_ID   = "ffff1d000100ffff"

    THRESHOLD  = 10


class PosCharacterSelect:
    """キャラクターセレクト画面識別用。
    右下の「1 お気に入り」操作ボタン、および左下の「player」ラベルを使用。
    """
    # 状態1: 右下「1 お気に入り」操作ボタン
    # (お気に入り登録済みのキャラクターを選択中は「1 解除」に変わる)
    AREA      = (1710, 860, 1895, 925)
    AHASH     = "807fffc1c1ff7e81"

    # 状態2: 左下のプレーヤー名プレート上部の「player」ラベル (プレーヤー名は含めない)
    AREA_PLAYER  = (30, 820, 335, 850)
    AHASH_PLAYER = "7f6f430044c7f7ff"

    THRESHOLD = 10


class PosExit:
    """終了画面識別用。
    画面中央の特大「See you!!」ロゴを使用。
    """
    AREA      = (450, 500, 1470, 920)
    AHASH     = "a0263fe161031616"
    THRESHOLD = 10


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


class PosOptionList:
    """オプション選択画面右下の設定一覧 (1920x1080 座標)。
    こげ茶色のパネルに現在の設定値が 11 行並び、各行の下に色付きの下線が引かれている。
    縦位置はキャプチャ方式によってずれるため、下線を動的に検出する (src/option_reader.py)。
    """
    SEARCH_AREA   = (1120, 430, 1760, 1010)   # 下線の探索範囲
    LINE_LENGTH   = (300, 420)                # 下線とみなす長さの範囲
    PITCH         = (30.0, 44.0)              # 行間隔とみなす範囲
    SIMPLE_PITCH  = (75.0, 100.0)             # シンプル設定 (4 行) の行間隔とみなす範囲
    SIMPLE_TEXT_RATIO = 0.42                  # シンプル設定の行間隔に対するフル設定の行間隔の比
    TEXT_OVERHANG = 10                        # 文字が下線の右端からはみ出す幅 (パネル右端は含めない)


class PosOptionIcons:
    """OptionSelect 画面中央下のオプションアイコン (1920x1080 座標)。
    黒い角丸の枠に、フル設定では 上段 5 個 / 下段 6 個、シンプル設定では 4 個が 1 段で並ぶ。
    縦位置・縦倍率はキャプチャ方式によって変わるため、枠を動的に検出する (src/option_reader.py)。
    """
    BAND_X           = (700, 1220)     # 黒枠の行判定に使う横範囲
    SEARCH_Y         = (560, 1010)     # 黒枠の探索範囲
    BOX_HEIGHT       = 212             # 基準の枠の高さ (タイトルバー込みのキャプチャ)
    BOX_HEIGHT_RANGE = (195, 240)      # 枠とみなす高さの範囲

    BOX_WIDTH_RANGE  = (520, 580)      # 枠とみなす幅の範囲

    # アイコンの中心 x (枠の幅に対する比率)、中心 y (枠の高さに対する比率)
    ROW_X    = ((0.162, 0.333, 0.496, 0.662, 0.831),
                (0.082, 0.255, 0.415, 0.584, 0.751, 0.918))
    ROW_Y    = (0.269, 0.736)
    SIMPLE_X = (0.153, 0.387, 0.624, 0.853)
    SIMPLE_ROW_Y = 0.5
    ICON_HALF = 46                     # アイコンの切り出し範囲 (中心から ±px)

    # HIDDEN / SUDDEN のアイコン内の値。アイコン中心からの相対位置
    VALUE_Y          = (-2, 34)
    VALUE_GLYPH_X    = (27, 9, -9, -27)   # 右の文字から順
    VALUE_GLYPH_HALF = 9

    BPM_X = (0.391, 0.982)              # bpm 行の「× 2.9 = 435」の横範囲 (枠の幅に対する比率)


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

