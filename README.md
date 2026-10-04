# pop_lively_support_tool

pop'n music Lively 専用のサポートツールです。  
beatmania IIDX INFINITAS 向けツール [inf_daken_counter_obsw](https://github.com/dj-kata/inf_daken_counter_obsw) を参考に、pop'n music Lively 専用として新規開発しました。

## 機能

- プレー中の判定内訳（COOL / GREAT / GOOD / BAD）をリアルタイム集計
- 打鍵数（COOL + GREAT + GOOD の合計。BAD は見逃し扱いで含めない）を表示
- ゲーム画面の自動検出（プレー / 選曲 / リザルト / オプション）
- OBS WebSocket 連動（録画開始・停止、シーン切り替えなど）
- ゲーム画面キャプチャ方式: 直接取得 (DXCAM) / 旧直接取得 / OBS WebSocket 経由
- フルスクリーン・ウィンドウモード両対応

## 動作環境

- OS: Windows 10 / 11
- pop'n music Lively

## 使い方

1. pop'n music Lively を起動する
2. `pop_lively_support_tool.exe` を実行する
3. ゲーム画面が自動検出される
4. プレー中の判定内訳が自動的にカウントされる

## 設定

メニュー → ファイル → 設定 から以下を変更できます。

| 設定項目 | 説明 |
|---------|------|
| ゲーム画面取得 | 直接取得 (DXCAM) / 旧直接取得 / OBS WebSocket 経由 |
| 常に最前面表示 | ウィンドウを常に最前面に表示する |
| Lively の CPU 割り当てを 1 コアにする | Lively のロード時間短縮。起動を検出したら、使用率が最小の CPU だけを割り当て、優先度を「高」にする（既定は無効） |
| リザルトのスクリーンショット | 無効 / 保存 / 自己ベストのみ保存（既定は無効）。スコアを記録したときのリザルト画面を、保存先フォルダ（既定は `result_screenshots`）に `日時_曲名_難易度_スコア.png` で保存する。「自己ベストのみ保存」は同じ曲・難易度のスコアを更新したとき（初プレーを含む）だけ保存する |
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

プレー画面下部バーに表示される「BAD / GOOD / GREAT / COOL」の累計値を、
数字として読み取ります (`src/judge_reader.py`)。

- 数字は 4 桁固定で、先頭の 0 埋めは暗く、有効な桁だけが明るく表示されます。
  判定ごとの色（COOL: マゼンタ / GREAT: 橙 / GOOD: 赤 / BAD: シアン）で明るい桁だけを取り出し、
  テンプレート (`src/judge_templates.py`) と照合します。
- 累計値そのものを読むため、フレームを取りこぼしても打鍵数はずれません。
  累計値は増える一方なので、減った値や急に増えた値は読み誤りとして採用しません。
- リザルト画面を読めた時点で、その曲の分はリザルト画面の値に置き換えます。
  リザルトに到達しなかった曲（リタイア・リトライ）は、プレー中に読めた値を本日の打鍵数に加算します。
  曲の切り替わりは、累計値が 0 付近に戻ったことで判断します。

読み誤る数字が見つかった場合は、その画面のスクリーンショットと正解値を
`tools/build_judge_templates.py` の `SAMPLES` に追加して実行し、テンプレートを作り直します。

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

## 使用オプションの読み取りの仕組み

オプション画面から使用オプションを読み取ります (`src/option_reader.py`)。

### 設定を開いている間（右下の設定一覧）

1. こげ茶色のパネルに並ぶ 11 行（上から ハイスピード / ポップ君 / ゲージタイプ / GUIDE SE / RANDOM / JUDGE+ / HIDDEN / SUDDEN / OJAMA1 / OJAMA2 / AUTO。シンプル設定では上 4 行のみ）を、各行の下線を手がかりに検出する
2. 各行の文字を Windows 標準 OCR で文字列にし、オプションマスターの値に正規化する（多少の誤字は吸収）
3. OJAMA 行の先頭に黄色の「ずっと」があれば「OJAMA ずっと」を ON とする

### 設定を開いていない間（OptionSelect 画面のオプションアイコン）

| 項目 | 読み取り方法 |
|-----|-------|
| ハイスピード | bpm 行の「150 × 2.9 = 435」を OCR で読む |
| ポップ君 / ゲージタイプ / RANDOM / JUDGE+ / AUTO | アイコンの絵柄をテンプレート (`src/option_templates.py`) と照合 |
| HIDDEN / SUDDEN | アイコン内の数字を 1 文字ずつテンプレートと照合 |
| GUIDE SE | OFF のみ判別（「ON 大」と「ON 小」は同じ絵柄のため区別不可） |
| OJAMA1 / OJAMA2 | OFF のみ判別（設定中は番号しか表示されず、種類が分からない） |

テンプレートは `tools/build_option_templates.py` で、設定値の分かっているスクリーンショットから生成します。
読めないアイコンや数字が見つかったら、スクリーンショットと設定値を `SAMPLES` に追加して再実行してください。

どちらの場合も、同じ内容が続けて読めた時点で現在の使用オプションに反映し、以降のリザルトで記録されます。読めなかった項目は直前の値を引き継ぎます。

## スコア管理・データベース (SQLite & CSV)

- **曲マスター管理 (musics テーブル)**:
  - `popn_music_list.json` からインポートされ、各楽曲に一意の **UUID** (`music_id`) が付与されます。
- **スコア管理 (scores テーブル)**:
  - リザルト画面で検出されたスコアを記録します。
  - スコアテーブル側には曲名やレベルなどの曲情報は持たず、**UUID (`music_id`)** を用いて曲マスターテーブルと結合して管理されます（レベルは難易度区分と曲テーブルから自動導出）。
  - 保存される項目: 難易度区分、SCORE、COOL、GREAT、GOOD、BAD、COMBO、プレー日時、および以下の **13 種類のオプション**:
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
    - **OJAMA1 ずっと** (`ojama1_zutto`)
    - **OJAMA2 ずっと** (`ojama2_zutto`)
    - **AUTO** (`auto`)
- **オプションマスター (option_masters テーブル)**:
  - 各オプション項目の選択肢をゲーム内の表示順で保持します（定義元は `src/option_master.py`。起動時に定義どおりに入れ直されます）。
  - スコア保存時のオプション値の表記統一（例: `x3.5` → `3.5`、`ON大` → `ON 大`）と、スコア記録の修正画面の選択肢に使われます。
- **CSV エクスポート機能**:
  - メニューの「スコア → CSVファイルを出力...」またはスコア履歴ダイアログの「CSVエクスポート...」から、SQLite のスコア管理テーブルと曲テーブルを JOIN して以下の 23 列の CSV ファイルを出力できます（「使用オプション」要約列は除外され、各個別オプション列が出力されます）：
  ```csv
  レベル,曲名,難易度区分,SCORE,COOL,GREAT,GOOD,BAD,COMBO,HI-SPEED,POP-KUN,GAUGE TYPE,GUIDE SE,RANDOM,JUDGE+,HIDDEN,SUDDEN,OJAMA1,OJAMA2,OJAMA1ずっと,OJAMA2ずっと,AUTO,プレー日時
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
pop_lively_support_tool/
├── pop_lively_support_tool.pyw  # メインエントリ
├── manage_db.py         # DB管理 CLI ツール
├── popn_music_list.json # 楽曲マスターJSON (UUID付き)
├── popn.db              # SQLite データベース (musics, scores)
├── popn_score.csv       # スコアエクスポート先 CSV
├── pyproject.toml
├── LICENSE              # Apache License 2.0
├── config.json          # 実行時設定（自動生成）
├── src/
│   ├── classes.py       # データクラス・列挙型
│   ├── config.py        # 設定クラス
│   ├── config_dialog.py # 設定ダイアログ
│   ├── cpu_affinity.py  # Lively の CPU 割り当て変更（ロード時間短縮）
│   ├── db.py            # SQLite DB 管理・CSV入出力
│   ├── define.py        # 座標・ハッシュ定数
│   ├── direct_window_capture.py   # 旧直接取得
│   ├── dxcam_window_capture.py    # DXCAM直接取得 (HDR 有効時は旧直接取得で取り込む)
│   ├── hdr_monitor.py             # モニターの HDR 有効状態の取得
│   ├── funcs.py         # ユーティリティ
│   ├── logger.py        # ログ管理
│   ├── obs_websocket_manager.py   # OBS WebSocket管理
│   ├── option_master.py # オプションマスター（各項目の選択肢）
│   ├── option_reader.py # オプション画面の設定一覧 (OCR)・オプションアイコン読み取り
│   ├── option_templates.py # オプションアイコンのテンプレート (自動生成)
│   ├── score_dialog.py  # スコア履歴・CSVエクスポートダイアログ
│   ├── score_manager.py # スコア管理マネージャー
│   ├── screen_reader.py # 画面状態検出・判定読み取り
│   ├── song_reader.py   # プレー画面の曲名 (OCR)・難易度区分読み取り
│   └── ui_jp.py         # UI文字列（日本語）
└── log/                 # ログ出力先
```

## ライセンス

本ツールは [Apache License 2.0](LICENSE) のもとで公開しています。
利用・改変・再配布は同ライセンスの条件に従ってください。

- 再配布する場合は、ライセンス文 (`LICENSE`) と著作権表示を添付してください。
- 改変したファイルを再配布する場合は、変更を加えた旨を明示してください。
- 本ツールの一部（OBS WebSocket 接続管理 `src/obs_websocket_manager.py`、OBS 制御設定ダイアログ `src/obs_dialog.py`、ビルド設定 `setup.py`）は、dj-kata 氏の [inf_daken_counter_obsw](https://github.com/dj-kata/inf_daken_counter_obsw)（Apache License 2.0）をもとに、pop'n music Lively 向けに改変したものです。該当ファイルの先頭に、改変した旨を記載しています。
- 本ツールが利用している外部ライブラリ（PySide6、NumPy、Pillow、ImageHash、DXcam、obsws-python、winrt など）には、それぞれのライセンスが適用されます。

## 免責事項

- 本ツールは個人が開発した**非公式**のツールです。株式会社コナミデジタルエンタテインメント、株式会社コナミアーケードゲームスをはじめとする KONAMI グループ各社とは**一切関係がなく**、承認・推奨・サポートを受けたものでもありません。本ツールについて KONAMI へ問い合わせることはおやめください。
- 「pop'n music」「beatmania IIDX」などのゲーム名・名称は、各権利者の商標または登録商標です。
- 本ツールは**利用者自身の責任**で使用してください。本ツールは現状有姿 (AS IS) で提供され、動作・読み取り結果の正確性・特定目的への適合性などについて、いかなる保証もしません。
- 本ツールの使用または使用不能によって生じたいかなる損害・不利益（ゲームアカウントへの措置、スコアデータの消失・誤記録、PC や OBS の不具合、録画・配信の失敗などを含みます）についても、作者は一切の責任を負いません。
- 本ツールの使用がゲームの利用規約に抵触しないかどうかは、利用者自身で確認・判断してください。

### 使用上の注意

- 本ツールはゲーム画面の映像を読み取って動作します。ゲームのプログラム・メモリ・通信内容の読み書きや改変は行いません。
- 「Lively の CPU 割り当てを 1 コアにする」を有効にした場合のみ、ゲームプロセスの CPU 割り当てと優先度を OS の機能で変更します（既定は無効）。この機能を使うかどうかも利用者自身の判断でお願いします。
- ゲームのアップデートで画面レイアウトが変わると、判定・曲名・スコアなどを正しく読み取れなくなることがあります。
- スコアは `popn.db` に保存されます。大切な記録は、定期的に `popn.db` のコピーや CSV エクスポートでバックアップを取ってください。
