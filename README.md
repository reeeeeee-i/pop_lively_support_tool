# pop'n music Lively 打鍵カウンタ

pop'n music Lively 専用の打鍵数カウンタツールです。  
beatmania IIDX INFINITAS 向けツール [inf_daken_counter_obsw](../inf_daken_counter_obsw) を参考に、pop'n music Lively 専用として新規開発しました。

## 機能

- プレー中の判定内訳（COOL / GREAT / GOOD / BAD）をリアルタイム集計
- 打鍵数（全判定の合計）を表示
- ゲーム画面の自動検出（プレー / 選曲 / リザルト / オプション）
- OBS WebSocket 連動（録画開始・停止、シーン切り替えなど）
- ゲーム画面キャプチャ方式: 直接取得 (DXCAM) / 旧直接取得 / OBS WebSocket 経由
- フルスクリーン・ウィンドウモード両対応

## 動作環境

- OS: Windows 10 / 11
- pop'n music Lively

## 使い方

1. pop'n music Lively を起動する
2. `popn_counter.pyw` を実行する
3. ゲーム画面が自動検出される
4. プレー中の判定内訳が自動的にカウントされる

## 設定

メニュー → ファイル → 設定 から以下を変更できます。

| 設定項目 | 説明 |
|---------|------|
| ゲーム画面取得 | 直接取得 (DXCAM) / 旧直接取得 / OBS WebSocket 経由 |
| 常に最前面表示 | ウィンドウを常に最前面に表示する |
| OBS ホスト/ポート/パスワード | OBS WebSocket 接続先 |
| ゲームキャプチャソース名 | OBS WebSocket 経由時のソース名 |

## OBS 自動制御

`config.json` の `obs_control_settings` を直接編集して設定します。

```json
"obs_control_settings": [
  {"trigger": "play_start", "action": "start_recording"},
  {"trigger": "play_end",   "action": "stop_recording"},
  {"trigger": "result_start", "action": "switch_scene", "scene": "リザルト"}
]
```

| トリガー | タイミング |
|---------|----------|
| `play_start`  | プレー画面に入った瞬間 |
| `play_end`    | プレー画面から出た瞬間 |
| `result_start` | リザルト画面に入った瞬間 |
| `result_end`  | リザルト → 選曲に戻った瞬間 |

| アクション | 説明 |
|----------|------|
| `start_recording` | OBS 録画開始 |
| `stop_recording`  | OBS 録画停止 |
| `start_streaming` | OBS 配信開始 |
| `stop_streaming`  | OBS 配信停止 |
| `switch_scene`    | OBS シーン切り替え（`scene` パラメータで指定） |

## 判定読み取りの仕組み

プレー画面下部バーに表示される「BAD / GOOD / GREAT / COOL」の各色ピクセル数を
フレームごとに計測し、前フレームとの増減から判定発生を検出します。

| 判定 | 表示色 |
|-----|-------|
| COOL | マゼンタ |
| GREAT | 黄 |
| GOOD | 赤 |
| BAD | シアン |

> **注意**: 座標・しきい値は `src/define.py` に定義されています。
> 実機での動作確認後、`PosJudge` の各 `*_AREA` 座標の微調整が必要な場合があります。

## 曲名・難易度区分の読み取りの仕組み

プレー画面上部の曲名バーから、プレー中の曲と難易度区分を特定します (`src/song_reader.py`)。

1. 黒地に白文字の曲名バーを検出し、曲名を Windows 標準 OCR (`Windows.Media.Ocr`) で文字列にする
2. OCR 結果を曲テーブル (musics) の曲名とあいまい照合して曲を特定する（多少の誤字は吸収）
3. 曲名バー右端の丸アイコンの色から難易度区分を判定する

| 難易度区分 | アイコンの色 |
|-----|-------|
| EASY | 青 |
| NORMAL | 緑 |
| HYPER | 橙 |
| EX | 赤〜ピンク |

レベルは特定した曲と難易度区分から曲テーブルを引いて求めます。

> **注意**: 日本語の OCR 言語パック（日本語版 Windows には標準で入っています）と `winrt-*` パッケージが必要です。
> 使えない環境では曲名は `Unknown` のまま記録されます。
> 同名曲（ウラ譜面・LIVE版・カバー等）は曲名だけでは区別できないため、その難易度の譜面がある Lively 収録曲を優先します。
> 特定できなかった場合は曲名バーの画像を `out/last_song_title.png` に保存します。

## スコア管理・データベース (SQLite & CSV)

- **曲マスター管理 (musics テーブル)**:
  - `popn_music_list.json` からインポートされ、各楽曲に一意の **UUID** (`music_id`) が付与されます。
- **スコア管理 (scores テーブル)**:
  - リザルト画面で検出されたスコアを記録します。
  - スコアテーブル側には曲名やレベルなどの曲情報は持たず、**UUID (`music_id`)** を用いて曲マスターテーブルと結合して管理されます（レベルは難易度区分と曲テーブルから自動導出）。
  - 保存される項目: 難易度区分、SCORE、COOL、GREAT、GOOD、BAD、COMBO、プレー日時、および以下の **11 種類のオプション**:
    - **HI-SPEED** (`hispeed`: デフォルト値 `"1.0"`)
    - **POP-KUN** (`popkun`)
    - **GAUGE TYPE** (`gauge_type`)
    - **GUIDE SE** (`guide_se`)
    - **RANDOM** (`random`)
    - **JUDGE+** (`judge_plus`)
    - **HIDDEN** (`hidden`)
    - **SUDDEN** (`sudden`)
    - **OJAMA1** (`ojama1`)
    - **OJAMA2** (`ojama2`)
    - **AUTO** (`auto`)
- **CSV エクスポート機能**:
  - メニューの「スコア → CSVファイルを出力...」またはスコア履歴ダイアログの「CSVエクスポート...」から、SQLite のスコア管理テーブルと曲テーブルを JOIN して以下の 21 列の CSV ファイルを出力できます（「使用オプション」要約列は除外され、各個別オプション列が出力されます）：
  ```csv
  レベル,曲名,難易度区分,SCORE,COOL,GREAT,GOOD,BAD,COMBO,HI-SPEED,POP-KUN,GAUGE TYPE,GUIDE SE,RANDOM,JUDGE+,HIDDEN,SUDDEN,OJAMA1,OJAMA2,AUTO,プレー日時
  ```

### データベース管理ツール (`manage_db.py`)

コマンドラインから曲データのインポートや CSV のエクスポート・インポートを実行できます。

```bash
# popn_music_list.json から曲テーブルへインポート（UUID付与）
python manage_db.py import-music

# SQLite から CSV へエクスポート
python manage_db.py export-csv

# 既存 CSV から SQLite へインポート
python manage_db.py import-csv

# DB 統計情報の確認
python manage_db.py stats
```

## ファイル構成

```
popn_daken_counter/
├── popn_counter.pyw     # メインエントリ
├── manage_db.py         # DB管理 CLI ツール
├── popn_music_list.json # 楽曲マスターJSON (UUID付き)
├── popn.db              # SQLite データベース (musics, scores)
├── popn_score.csv       # スコアエクスポート先 CSV
├── pyproject.toml
├── config.json          # 実行時設定（自動生成）
├── src/
│   ├── classes.py       # データクラス・列挙型
│   ├── config.py        # 設定クラス
│   ├── config_dialog.py # 設定ダイアログ
│   ├── db.py            # SQLite DB 管理・CSV入出力
│   ├── define.py        # 座標・ハッシュ定数
│   ├── direct_window_capture.py   # 旧直接取得
│   ├── dxcam_window_capture.py    # DXCAM直接取得
│   ├── funcs.py         # ユーティリティ
│   ├── logger.py        # ログ管理
│   ├── obs_websocket_manager.py   # OBS WebSocket管理
│   ├── score_dialog.py  # スコア履歴・CSVエクスポートダイアログ
│   ├── score_manager.py # スコア管理マネージャー
│   ├── screen_reader.py # 画面状態検出・判定読み取り
│   ├── song_reader.py   # プレー画面の曲名 (OCR)・難易度区分読み取り
│   └── ui_jp.py         # UI文字列（日本語）
└── log/                 # ログ出力先
```
