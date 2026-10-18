"""日本語 UI 文字列定義"""


class UIText:

    class window:
        main_title     = "pop'n music Lively サポートツール"
        settings_title = "設定"

    class menu:
        file          = "ファイル(&F)"
        settings      = "設定(&C)..."
        obs_settings  = "OBS 制御設定(&O)..."
        open_screenshot_dir = "スクリーンショットのフォルダを開く(&P)"
        reset_count   = "本日の打鍵数をリセット(&R)"
        exit          = "終了(&X)"
        score         = "スコア(&S)"
        score_history = "スコア履歴 / CSV表示(&H)..."
        export_csv    = "CSVファイルを出力(&E)..."
        import_csv    = "CSVファイルから取り込み(&I)..."
        open_csv      = "CSVファイルを開く(&O)"
        stats         = "統計(&T)..."
        data          = "データ(&D)"
        update_music_list = "曲リストをファイルから更新(&U)..."
        update_music_list_url = "曲リストをURLから更新(&W)..."
        backup        = "バックアップを作成(&B)..."
        restore       = "バックアップから復元(&L)..."
        diagnostics   = "認識診断(&G)..."
        help          = "ヘルプ(&H)"
        check_update  = "更新を確認(&U)..."
        about         = "バージョン情報(&A)..."
        session_summary = "セッションサマリー(&M)..."

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
        screenshot_saved = "スクリーンショットを保存しました: {path}"
        screenshot_failed = "スクリーンショットを保存できませんでした"
        screenshot_no_frame = "スクリーンショットを保存できません（画面を取得できていません）"
        obs_connected    = "OBS 接続中"
        obs_disconnected = "OBS 未接続"

    class feature:
        tab_general                     = "一般"
        tab_record                      = "記録・保存"
        tab_capture                     = "キャプチャ"
        view_group                      = "表示"
        behavior_group                  = "動作"
        log_group                       = "ログ"
        update_group                    = "更新"
        game_capture_group              = "ゲーム画面取得"
        capture_method_direct           = "直接取得 (DXCAM)"
        capture_method_direct_legacy    = "直接取得 (旧方式)"
        capture_method_obs              = "OBS WebSocket 経由"
        capture_priority_help           = (
            "チェックを入れた方式を、上から順に試します。"
            "指定秒数フレームを取得できないと、次の方式に切り替えます。"
        )
        capture_move_up                 = "↑"
        capture_move_down               = "↓"
        capture_fallback_seconds        = "切り替えまでの待ち時間"
        capture_fallback_seconds_tip    = "この秒数フレームを取得できなかったら、次の方式に切り替えます。"
        direct_capture_all_monitors     = "常に全モニターを対象にする"
        direct_capture_all_monitors_tip = "旧直接取得で使います。"
        keep_on_top                     = "常に最前面表示する"
        last_song_display               = "最後にプレイした曲の表記"
        last_song_display_title         = "曲名"
        last_song_display_genre         = "ジャンル名"
        last_song_display_genre_title   = "ジャンル名(曲名)"
        lively_single_cpu               = "Lively の CPU 割り当てを 1 コアにする（ロード時間短縮）"
        lively_single_cpu_tip           = (
            "Lively の起動を検出したら、使用率が最小の CPU だけを割り当て、優先度を「高」にします。\n"
            "無効に戻すと、起動中の Lively の割り当ても元に戻します。"
        )
        log_max_size                    = "ログの最大容量"
        log_max_size_tip                = (
            "log フォルダ全体の容量の上限です。\n"
            "上限を超えると、古いログから自動的に削除します。"
        )
        score_save_group                = "スコア保存時の条件"
        check_update_on_startup         = "起動時に新しいバージョンを確認する"
        check_update_on_startup_tip     = (
            "起動時に、GitHub のリリースで新しいバージョンがないか確認します (確認のため GitHub に接続します)。\n"
            "新しいバージョンがあるときだけ、更新の案内を表示します。\n"
            "無効のときも、メニュー → ヘルプ → 更新を確認 でいつでも確認できます。"
        )
        music_list_url                  = "曲リストの取得先 URL"
        music_list_url_tip              = (
            "メニュー → データ → 曲リストをURLから更新 で取得する popn_music_list.json の URL です (https のみ)。\n"
            "空欄にすると、既定の URL (このツールのリポジトリの main ブランチ) に戻ります。"
        )
        diagnostics_enabled             = "読み取りに失敗した画面を診断データとして保存する"
        diagnostics_enabled_tip         = (
            "曲を特定できなかったプレー画面、読み取りに不確かな点があったリザルト画面、判定内訳がリザルトと\n"
            "食い違ったプレー画面を diagnostics フォルダに保存します。保存したデータは、メニュー → データ →\n"
            "認識診断 で正解値を確定すると、テンプレート作成ツールのサンプルにできます。"
        )
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
            "「自己ベスト」は、リザルト画面に「NEW RECORD!」が表示され、BEST SCORE の差分が + のときに保存します\n"
            "（差分が読み取れないときは「NEW RECORD!」のみで判断します）。\n"
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
        chart_info     = "この譜面の成績"
        pick_song      = "曲を選択..."
        pick_song_tip  = "曲を特定できなかったときに、正しい曲を選びます。選んだ曲は次回から自動で認識します。"
        song_unidentified = "曲を特定できませんでした (読み取り: {text})"
        reset_notes    = "本日の打鍵数をリセット"
        screenshot_tip = "現在の画面のスクリーンショットを保存"
        open_screenshot_dir = "スクリーンショットのフォルダを開く"
        reload_capture = "🔄"
        reload_capture_tip = "画面取り込みをリロード (最優先の方式から試し直す)"
        none_song     = "なし"
