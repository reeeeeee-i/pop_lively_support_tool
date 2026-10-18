"""認識診断データ (diagnostics フォルダ) から、テンプレート作成ツール用のサンプルを読み込む。

アプリの「認識診断」で正解値を確定したデータが対象。フォルダは環境変数 DIAGNOSTICS_DIR で変えられる
(既定はリポジトリ直下の diagnostics。配布版を使っている場合は、そのフォルダを指定する)。
"""
from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def diag_samples(kind: str, to_text: bool = False) -> list[tuple[str, dict]]:
    """kind ('judge' / 'result') の確定済みデータを (画像パス, 正解値) のリストで返す。

    to_text: 正解値を文字列にする (リザルトのテンプレート作成ツールは行ごとの文字列を使う)。
    """
    folder = Path(os.environ.get("DIAGNOSTICS_DIR", ROOT / "diagnostics"))
    try:
        entries = json.loads((folder / "index.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    samples = []
    for entry in entries:
        truth = entry.get("truth")
        if entry.get("kind") != kind or not isinstance(truth, dict):
            continue
        path = folder / entry["file"]
        if not path.is_file():
            continue
        values = {k: (str(v) if to_text else int(v)) for k, v in truth.items()}
        samples.append((str(path), values))
    return samples
