# CLAUDE.md

このファイルは、Claude Code がこのリポジトリで作業するときの指針です。機能・操作の詳細は `README.md` を参照してください（ここには重複して書かず、開発で守るべきことを中心に記載します）。

## プロジェクト概要

`pop_lively_support_tool`: pop'n music Lively 向けの非公式サポートツール（Windows 専用の PySide6 デスクトップアプリ）。ゲーム画面の映像を読み取り、打鍵数のカウント、スコア記録、統計、スクリーンショット保存、OBS WebSocket 連動を行う。ゲームのメモリ・通信には触れない（画面キャプチャのみ）。ライセンスは Apache-2.0。

- 言語・UI 文言・コミットメッセージ・コメントはすべて**日本語**
- Python 3.11 以上、依存管理は [uv](https://docs.astral.sh/uv/)（`pyproject.toml` / `uv.lock`）
- exe 化は cx_Freeze（`setup.py`）

## よく使うコマンド

```bash
uv sync                                    # 仮想環境 (.venv) を作る
python -m unittest discover -s tests -v    # テスト（署名・取得・更新・バナー・起動時更新）
python manage_db.py stats                  # DB 管理 CLI (import-music / export-csv / import-csv / stats)
```

- 実行: `run.bat`（`.venv` の pythonw で `pop_lively_support_tool.pyw` を起動）
- exe ビルド: `build.bat`（`dist\pop_lively_support_tool\` に出力）
- ゲーム画面・OBS・Windows OCR に依存するため、Windows 以外では GUI 部分は動かない。変更の動作確認が実機でしかできない場合は、その旨を報告に明記すること

## ディレクトリ構成

- `pop_lively_support_tool.pyw` — メインエントリ（メインウィンドウ・各処理の統括）
- `src/` — 本体モジュール
  - 画面読み取り: `screen_reader.py`（画面状態検出）, `judge_reader.py`（判定累計値）, `result_reader.py`（リザルト）, `song_reader.py`（曲名バー OCR・難易度）, `banner_reader.py`（曲バナーの特徴量照合）, `option_reader.py`（使用オプション）
  - テンプレート（**自動生成**、手編集しない）: `judge_templates.py`, `digit_templates.py`, `option_templates.py`
  - 画面取得: `dxcam_window_capture.py`, `direct_window_capture.py`, `hdr_monitor.py`, OBS 経由は `obs_websocket_manager.py`
  - データ: `db.py`（SQLite・CSV 入出力）, `score_manager.py`, `option_master.py`, `score_stats.py`
  - UI: `config_dialog.py`, `obs_dialog.py`, `score_dialog.py`, `stats_dialog.py`, `chart_widgets.py`, `update_dialog.py`, `diagnostics_dialog.py`, `ui_jp.py`（UI 文字列）
  - 配布物の保護・更新: `signing.py`, `ed25519.py`, `trusted_keys.py`, `secure_http.py`, `music_list_fetch.py`, `updater.py`, `app_version.py`
  - その他: `classes.py`（データクラス・列挙型）, `config.py`, `define.py`（座標・ハッシュ定数）, `funcs.py`, `logger.py`, `cpu_affinity.py`, `startup_check.py`, `diagnostics.py`, `session_image.py`
- `tools/` — 開発者用スクリプト（テンプレート生成 `build_*_templates.py`、`fetch_wiki.py`、`fetch_banners.py`、`check_music_list.py`、`sign_release.py`、アイコン生成など）
- `generate_music_list.py` — Wiki の HTML から `popn_music_list.json` を生成
- `popn_music_list.json` / `.sig` — 曲リスト本体とその署名（アプリが GitHub の `main` から取得する配信物）
- `tests/` — unittest
- `.github/workflows/update-music-list.yml` — 曲リストの毎週自動更新
- `.github/rulesets/main-protected.json` — `main` ブランチ保護の定義

実行時に生成され git 管理外のもの: `config.json`, `popn.db`, `popn_score.csv`, `log/`, `backup/`, `diagnostics/`, `result_screenshots/`, `tmp_banners/`, `tmp_scrape/`, `out/`。これらは絶対にコミットしない（`.gitignore` 済み）。

## 開発上のルール

### バージョン管理とリリース

- バージョンの唯一の定義元は `pyproject.toml` の `version`。形式は `YYMMDD`、同日の再リリースは `YYMMDD.N`（例: `261024.1`）。ビルドで exe 用の `26.10.24.1` 形式に自動変換される
- バージョンを上げるコミットは「ver を 261024.1 に変更」の形式
- リリースのタグ名は version と同一。添付物は `pop_lively_support_tool*.zip` と、その署名 `.zip.sig`（署名が無いリリースはアプリが更新に使わない）。詳細は README の「リリースの作り方」を参照
- 新しい `src/` モジュールを追加したら、`setup.py` の `includes` にも追加する（cx_Freeze のビルドに含めるため）

### ブランチ・PR

- `main` は保護されており直接プッシュ不可。必ず `claude/<内容>-<hash>` や `feature/...` などのブランチから PR を作ってマージする（マージコミットで履歴を残す運用）
- コミットメッセージは日本語の簡潔な命令・体言止め（例: 「統計画面でデータなし表示中にツールチップが出る不具合を修正」）
- `auto/music-list-*` は曲リスト自動更新の Actions が作るブランチなので手で触らない

### セキュリティ（重要）

- 曲リスト・本体更新は **Ed25519 署名の検証が必須**。署名検証・https 限定・サイズ上限・zip 展開の検査・ロールバック防止を弱める変更をしない。公開鍵が無いときは拒否する（安全側）設計を維持する
- **秘密鍵・署名鍵（`signing_key*`、`*.key`、環境変数 `POP_SIGNING_KEY`、Actions の Secrets）をコミット・ログ・出力に含めない**。パスワードや API キー、ローカルの絶対パスもコミットしない
- `popn_music_list.json` と `.sig` は `.gitattributes` で改行変換を禁止している。**署名後に JSON を編集・再整形しない**（バイト列が変わると署名検証に失敗する）。署名の手順は README の「曲リストの配信」を参照
- セキュリティ関連を触ったら `tests/test_security.py` を実行・必要ならテストを追加する

### 曲リストとデータベース

- 各曲の `music_id`（UUID）は**変えない**。スコアは `music_id` で曲テーブルと結合して管理しているため、変えると記録との紐づけが切れる。曲リスト再生成時は既存の `music_id` と `banner`（特徴量）を引き継ぐ
- スコアテーブルは曲名・レベルを持たない（曲マスターから導出）。DB スキーマを変えるときは既存の `popn.db` が移行できることを確認し、CSV の列（26 列）・インポート互換（旧形式含む）を壊さない
- オプション値の選択肢と表記は `src/option_master.py` が定義元（起動時に入れ直される）
- 曲リストは毎週金曜に Actions が自動更新（Wiki 再生成 → 不足バナー取得 → 特徴量付与 → 異常検査 → 署名 → PR 作成・マージ）。手動で更新するときも同じ手順に従う

### 画面認識まわり

- 判定は 4 桁の累計値を色で抽出してテンプレート照合する。累計値は単調増加なので、減少・急増は誤読として捨てる設計
- 曲特定の優先順位は、バナー特徴量照合 → 曲名 OCR（Windows 標準 OCR とあいまい照合）。難易度区分はプレー画面の曲名バーのアイコン色から判定する
- 座標・色・ハッシュなどの定数は `src/define.py` にまとめる。ゲームのアップデートでレイアウトが変わると認識が壊れるため、座標は 1920x1080 基準で扱い、キャプチャ方式（DXCAM / 旧直接取得 / OBS）による縦位置・倍率の違いに注意する
- 読み誤りが見つかったら、スクリーンショットと正解値を `tools/build_*_templates.py` の `SAMPLES` に追加して再実行し、`*_templates.py` を作り直す。診断データ（`diagnostics/`）で確定した値は自動でサンプルに使われる
- 画像認識の変更は、手元のサンプル画像で前後比較して精度が落ちていないことを確認する

### 設定・UI

- 設定は `src/config.py` と `config.json`。既定値は保守的に（機能を有効にするかは利用者の選択に任せる。例: 起動時の更新チェックは既定で「確認しない」、スクリーンショット保存は既定で無効）
- UI 文言は日本語。ダークモードでも読める文字色にする（固定色を使う場合は背景も指定）
- 設定画面は「一般・記録保存・キャプチャ・OBS」の 4 タブ構成
- 自動更新は、設定・スコア・ログ・スクリーンショット・診断データ・バックアップを上書きしてはならない

### ドキュメント

- 機能・設定・手順を変えたら `README.md` を同じ PR で更新する（README が利用者向け・開発者向け両方の仕様書を兼ねている）
- 免責事項・ライセンス表記（dj-kata 氏の `inf_daken_counter_obsw` 由来ファイルの改変表記を含む）を消さない

## 作業時の注意

- 既存のコードスタイル（型ヒント、`from __future__ import annotations`、`logger = get_logger(__name__)` による logging）に合わせる
- Windows 専用 API（ctypes, winrt, dxcam）を使う箇所は、テストから import されても落ちないよう配慮する（`tests/` は `log/` を作成してから import している）
- 公開リポジトリのため、個人情報・ローカルパス・認証情報・利用者のスコアデータをコミットやコメント、PR に含めない
