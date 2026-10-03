"""pop'n music Lively データベース管理スクリプト

曲リストのインポート、CSVエクスポート・インポート、ステータス確認を行えます。
"""
from __future__ import annotations

import argparse
import sys

from src.config import Config
from src.db import PopnDatabase


def main():
    parser = argparse.ArgumentParser(description="pop'n music Lively DB Management Tool")
    parser.add_argument(
        "action",
        choices=["import-music", "export-csv", "import-csv", "stats"],
        help="実行するアクション",
    )
    parser.add_argument(
        "--db",
        default=None,
        help="SQLite データベースファイルパス (デフォルト: config.json の score_db_path または popn.db)",
    )
    parser.add_argument(
        "--json",
        default="popn_music_list.json",
        help="曲リスト JSON パス (デフォルト: popn_music_list.json)",
    )
    parser.add_argument(
        "--csv",
        default=None,
        help="CSV ファイルパス (デフォルト: config.json の score_csv_path または popn_score.csv)",
    )

    args = parser.parse_args()

    config = Config()
    db_path = args.db or config.score_db_path or "popn.db"
    csv_path = args.csv or config.score_csv_path or "popn_score.csv"

    print(f"データベース: {db_path}")
    db = PopnDatabase(db_path)

    if args.action == "import-music":
        print(f"曲リストをインポート中: {args.json} -> {db_path} (UUID付与)")
        count = db.import_music_list_json(args.json, update_json=True)
        print(f"インポート完了: {count} 曲を登録・更新しました。")

    elif args.action == "export-csv":
        print(f"スコア履歴を CSV へエクスポート中: {db_path} -> {csv_path}")
        count = db.export_csv(csv_path)
        print(f"エクスポート完了: {count} 件のスコアを出力しました ({csv_path})。")

    elif args.action == "import-csv":
        print(f"CSV からスコアをインポート中: {csv_path} -> {db_path}")
        count = db.import_csv(csv_path)
        print(f"インポート完了: {count} 件のスコアを取り込みました。")

    elif args.action == "stats":
        music_count = db.get_music_count()
        scores = db.load_scores()
        print("=== DB 統計情報 ===")
        print(f"曲テーブル (musics): {music_count} 件")
        print(f"スコアテーブル (scores): {len(scores)} 件")
        if scores:
            print(f"最新プレイ曲: {scores[-1].title} [{scores[-1].difficulty_code}] ({scores[-1].timestamp})")

    db.close()


if __name__ == "__main__":
    main()
