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
        ticket           = "チケット"
        character_select = "キャラセレクト"
        exit             = "終了画面"
        loading          = "ロード中"
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
        websocket_port                  = "データ表示用ポート:"
        screenshot_group                = "リザルトのスクリーンショット"
        screenshot_mode                 = "撮影:"
        screenshot_mode_off             = "無効"
        screenshot_mode_all             = "保存"
        screenshot_mode_best            = "自己ベストのみ保存"
        screenshot_mode_tip             = (
            "スコアを記録したときのリザルト画面を PNG で保存します。\n"
            "「自己ベストのみ保存」は、同じ曲・難易度のスコアを更新したとき（初プレーを含む）だけ保存します。\n"
            "曲を特定できなかったプレーは比較できないため保存します。"
        )
        screenshot_dir                  = "保存先フォルダ:"
        screenshot_dir_browse           = "参照..."
        screenshot_dir_dialog           = "スクリーンショットの保存先フォルダ"

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
            "config.json の obs_control_settings を直接編集して設定してください。\n\n"
            "例: [{\"trigger\": \"play_start\", \"action\": \"start_recording\"}]"
        )

    class main_display:
        group          = "ステータス"
        current_mode   = "現在のモード"
        uptime         = "起動時間"
        today_notes    = "本日の打鍵数"
        last_song      = "最後にプレイした曲"
        reset_notes    = "本日の打鍵数をリセット"
        none_song      = "なし"
