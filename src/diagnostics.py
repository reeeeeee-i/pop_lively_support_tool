"""認識診断データ (読み取りに失敗・不一致だった画面と、その正解値) の保存

診断モードが有効なとき、曲を特定できなかったプレー画面・読み取りに不確かな点があったリザルト画面・
判定内訳の読み取りがリザルトと食い違ったプレー画面を diagnostics フォルダに保存する。
正解値を入力 (確定) したものは、tools/build_*_templates.py のサンプルとして使える
(tools/diag_samples.py)。曲名は確定すると、曲名の読み替えとして学習する。
"""
from __future__ import annotations

import json
import os
from datetime import datetime

from PIL import Image

from src.logger import get_logger

logger = get_logger(__name__)

DIAGNOSTICS_DIR = "diagnostics"
_INDEX_FILE = "index.json"
# 確定していない診断データの保存上限 (1 件あたり数 MB になるため、古いものから消す)
_MAX_UNCONFIRMED = 60

KIND_TITLE = "title"      # 曲を特定できなかったプレー画面
KIND_RESULT = "result"    # 読み取りに不確かな点があったリザルト画面
KIND_JUDGE = "judge"      # 判定内訳の読み取りがリザルトと食い違ったプレー画面
KIND_LABELS = {KIND_TITLE: "曲名", KIND_RESULT: "リザルト", KIND_JUDGE: "判定内訳"}


class DiagnosticStore:
    """診断データ (画像 + index.json) の保存先"""

    def __init__(self, folder: str = DIAGNOSTICS_DIR):
        self.folder = folder

    # ------------------------------------------------------------------

    @property
    def _index_path(self) -> str:
        return os.path.join(self.folder, _INDEX_FILE)

    def entries(self) -> list[dict]:
        """診断データの一覧 (古い順)。"""
        try:
            with open(self._index_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, list) else []
        except (OSError, ValueError):
            return []

    def _write(self, entries: list[dict]) -> None:
        os.makedirs(self.folder, exist_ok=True)
        with open(self._index_path, "w", encoding="utf-8") as f:
            json.dump(entries, f, ensure_ascii=False, indent=1)

    def image_path(self, entry: dict) -> str:
        return os.path.join(self.folder, entry["file"])

    # ------------------------------------------------------------------

    def add(
        self, kind: str, image: Image.Image, read: dict, suggested: dict | None = None, note: str = ""
    ) -> dict:
        """診断データを 1 件保存する。

        read: そのとき読み取れた値 / suggested: 正解の見当 (リザルトの値など。確定するまで正解としては使わない)
        """
        now = datetime.now()
        entry_id = f"{now:%Y%m%d_%H%M%S}_{now.microsecond // 1000:03d}"
        entry = {
            "id": entry_id,
            "kind": kind,
            "file": f"{kind}_{entry_id}.png",
            "created": now.strftime("%Y-%m-%d %H:%M:%S"),
            "read": read,
            "suggested": suggested,
            "truth": None,
            "note": note,
        }
        os.makedirs(self.folder, exist_ok=True)
        image.convert("RGB").save(self.image_path(entry))
        entries = self.entries() + [entry]
        entries = self._prune(entries)
        self._write(entries)
        logger.info("認識診断データを保存: %s (%s)", entry["file"], note)
        return entry

    def _prune(self, entries: list[dict]) -> list[dict]:
        """確定していないデータが上限を超えたら、古いものから消す。"""
        unconfirmed = [e for e in entries if e.get("truth") is None]
        excess = max(0, len(unconfirmed) - _MAX_UNCONFIRMED)
        for entry in unconfirmed[:excess]:
            self._remove_file(entry)
            entries.remove(entry)
        return entries

    def _remove_file(self, entry: dict) -> None:
        try:
            os.remove(self.image_path(entry))
        except OSError:
            pass

    def set_truth(self, entry_id: str, truth: dict | None) -> None:
        """正解値を確定する (None で確定を取り消す)。"""
        entries = self.entries()
        for entry in entries:
            if entry["id"] == entry_id:
                entry["truth"] = truth
        self._write(entries)

    def delete(self, entry_id: str) -> None:
        entries = self.entries()
        for entry in [e for e in entries if e["id"] == entry_id]:
            self._remove_file(entry)
            entries.remove(entry)
        self._write(entries)
