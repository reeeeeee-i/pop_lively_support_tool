"""ユーティリティ関数"""
from __future__ import annotations
from src.config import Config


def load_ui_text(config: Config):
    """言語設定に応じた UI 文字列クラスを返す（現在は日本語のみ）"""
    from src.ui_jp import UIText
    return UIText
