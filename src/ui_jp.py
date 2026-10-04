"""日本語 UI 文字列定義"""


class UIText:

    class window:
        main_title     = "pop'n music Lively サポートツール"
        settings_title = "設定"

    class menu:
        file          = "ファイル(&F)"
        settings      = "設定(&C)..."
        obs_settings  = "OBS 制御設定(&O)..."
        reset_count   = "本日の打鍵数をリセット(&R)"
        exit          = "終了(&X)"
        score         = "スコア(&S)"
        score_history = "スコア履歴 / CSV表示(&H)..."
        export_csv    = "CSVファイルを出力(&E)..."
        open_csv      = "CSVファイルを開く(&O)"

    class status:
        waiting_game     = "ゲーム画面を待機中..."
        playing          = "プレー中"
        result           = "リザルト"
        select           = "選曲中"
        option           = "オプション"
        title            = "タイトル"
        status           = "ステータス"
        ticket           = "チケット"
        character_select = "キャラセレクト"
        exit             = "終了画面"
        loading          = "ロード中"
        retire_skipped   = "リタイアのためスコアを保存しませんでした"
        obs_connected    = "OBS 接続中"
        obs_disconnected = "OBS 未接続"

    class feature:
        game_capture_group              = "ゲーム画面取得"
        capture_method_direct           = "直接取得 (DXCAM)"
        capture_method_direct_legacy    = "直接取得 (旧方式)"
        capture_method_obs              = "OBS WebSocket 経由"
        direct_capture_all_monitors     = "常に全モニターを対象にする"
        direct_capture_all_monitors_tip = "旧直接取得で使います。"
        other_group                     = "その他"
        keep_on_top                     = "常に最前面表示する"
        lively_single_cpu               = "Lively の CPU 割り当てを 1 コアにする（ロード時間短縮）"
        lively_single_cpu_tip           = (
            "Lively の起動を検出したら、使用率が最小の CPU だけを割り当て、優先度を「高」にします。\n"
            "無効に戻すと、起動中の Lively の割り当ても元に戻します。"
        )
        score_save_group                = "スコア保存時の条件"
        score_skip_retire               = "retire 時は保存しない"
        score_skip_retire_tip           = (
            "リタイアしたプレー（リザルト画面に「Retire」と表示されるプレー）のスコアを記録しません。\n"
            "打鍵数は本日の打鍵数に加算します。"
        )
        screenshot_group                = "リザルトのスクリーンショット"
        screenshot_cond                 = "保存条件:"
        screenshot_cond_all             = "毎回"
        screenshot_cond_best            = "自己ベスト"
        screenshot_cond_fullcombo       = "FULL COMBO"
        screenshot_cond_perfect         = "PERFECT"
        screenshot_cond_tip             = (
            "スコアを記録したときのリザルト画面を保存します。\n"
            "チェックした条件のいずれかを満たしたときに保存します（すべて外すと保存しません）。\n"
            "「自己ベスト」は、同じ曲・難易度のスコアを更新したとき（初プレーを含む）に保存します。\n"
            "曲を特定できなかったプレーは比較できないため保存します。\n"
            "「FULL COMBO」は BAD が 0、「PERFECT」は GOOD と BAD が 0 のときに保存します。"
        )
        screenshot_dir                  = "保存先フォルダ:"
        screenshot_dir_browse           = "参照..."
        screenshot_dir_dialog           = "スクリーンショットの保存先フォルダ"
        screenshot_format               = "保存形式:"
        screenshot_format_png           = "PNG"
        screenshot_format_jpeg          = "JPEG"
        screenshot_quality              = "JPEG 圧縮率:"
        screenshot_quality_tip          = (
            "左ほど圧縮率が高く、ファイルは小さくなりますが画質が落ちます。\n"
            "ファイルサイズは 1920x1080 のリザルト画面での目安です。"
        )
        screenshot_quality_value        = "品質 {quality} (目安: 約 {size})"
        screenshot_png_size             = "(目安: 約 {size})"

    class obs_dialog:
        title       = "OBS 制御設定"
        host        = "OBS ホスト:"
        port        = "OBS ポート:"
        password    = "OBS パスワード:"
        source      = "ゲームキャプチャソース名:"
        scene_col   = "起動時シーンコレクション (空=変更なし):"
        triggers    = "OBS 自動制御トリガー"
        help_text   = (
            "トリガーに応じて OBS を自動操作します。\n"
            "メニューの「ファイル → OBS 制御設定」から設定してください。"
        )

    class main_display:
        group          = "ステータス"
        current_mode   = "現在のモード"
        uptime         = "起動時間"
        today_notes    = "本日の打鍵数"
        last_song      = "最後にプレイした曲"
        reset_notes    = "本日の打鍵数をリセット"
        none_song      = "なし"
