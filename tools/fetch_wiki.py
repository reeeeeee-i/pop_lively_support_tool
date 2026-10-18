"""曲リストの元になる HTML を BEMANIWiki から取得して tmp_scrape/ に保存する (開発者用・自動更新用)

    python tools/fetch_wiki.py [出力フォルダ (既定: tmp_scrape)]

保存したファイルは generate_music_list.py が読む。取得は 3 ページだけで、1 秒以上あけて順に行う。
"""
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

BASE = "https://bemaniwiki.com/?"
PAGES = {
    "shinkyoku.html": "pop'n music High☆Cheers!!/新曲リスト",
    "kyukyoku.html": "pop'n music High☆Cheers!!/旧曲リスト",
    "lively.html": "pop'n music Lively/全曲リスト",
}
USER_AGENT = "pop_lively_support_tool-music-list-updater (+https://github.com/reeeeeee-i/pop_lively_support_tool)"


def fetch(page: str, retries: int = 3) -> str:
    url = BASE + urllib.parse.quote_plus(page, safe="")
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=60) as res:
                text = res.read().decode("utf-8")
            if "<table" not in text:
                raise ValueError("表が見つかりません")
            return text
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(5 * (attempt + 1))
    raise SystemExit(f"取得に失敗しました ({page}): {last}")


def main() -> None:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "tmp_scrape")
    out.mkdir(parents=True, exist_ok=True)
    for i, (name, page) in enumerate(PAGES.items()):
        if i:
            time.sleep(2)
        text = fetch(page)
        (out / name).write_text(text, encoding="utf-8", newline="\n")
        print(f"{name}: {len(text)} 文字")


if __name__ == "__main__":
    main()
