"""公式サイトの楽曲一覧から、曲ごとのバナー画像と曲情報を取得する (開発者用・自動更新用)

    python tools/fetch_banners.py [出力フォルダ (既定: tmp_banners)] [--missing 曲リスト.json]

--missing を付けると、曲リストの中でバナーの特徴量 (banner) がまだ無い曲の画像だけを取得する
(自動更新用)。付けなければ全曲分を取得する。

出力フォルダに banners/*.png と index.json (ジャンル・曲名・アーティスト・Lv・バナーのファイル名) を保存する。
画像はリポジトリに含めない (tmp_banners/ は .gitignore 済み)。配布するのは画像から作った特徴量だけ
(generate_music_list.py が popn_music_list.json に書き込む)。

取得済みの画像は再取得しない。サイトへの負荷を避けるため、接続は 4 本までで、1 本ごとに取得のあと 1 秒あける。
"""
import hashlib
import html
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

SITE = "https://p.eagate.573.jp"
LIST_URL = SITE + "/game/popn/popn29/music/list.html?page={page}&version=-1&lv=0&bemani=0&category=0&keyword=&sort=music&sort_type=up"
USER_AGENT = "pop_lively_support_tool-music-list-updater (+https://github.com/reeeeeee-i/pop_lively_support_tool)"
INTERVAL_SEC = 1.0   # 1 本の接続ごとに、取得のあと 1 秒あける
WORKERS = 4

_ENTRY = re.compile(
    r'<li><img src="(?P<img>[^"]+)" /></li><li><p>(?P<genre>.*?)</p><p>(?P<title>.*?)</p><p>(?P<artist>.*?)</p></li>\s*'
    r'<li>(?P<levels>.*?)</li>',
    re.S,
)
_LEVEL = re.compile(r'<span>(LIGHT|NORMAL|HYPER|EX)</span>([^<]*)</p>')


def _get(url: str, retries: int = 3) -> bytes:
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=60) as res:
                return res.read()
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(5 * (attempt + 1))
    raise SystemExit(f"取得に失敗しました ({url}): {last}")


def parse_page(text: str) -> list[dict]:
    entries = []
    for m in _ENTRY.finditer(text):
        levels = {name: (int(v) if v.strip().isdigit() else None) for name, v in _LEVEL.findall(m["levels"])}
        entries.append({
            "genre": html.unescape(m["genre"]).strip(),
            "title": html.unescape(m["title"]).strip(),
            "artist": html.unescape(m["artist"]).strip(),
            "easy": levels.get("LIGHT"),
            "normal": levels.get("NORMAL"),
            "hyper": levels.get("HYPER"),
            "ex": levels.get("EX"),
            "img": html.unescape(m["img"]),
        })
    return entries


def _songs_without_banner(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [s for s in json.load(f) if not s.get("banner")]


def main() -> None:
    args = sys.argv[1:]
    missing_path = None
    if "--missing" in args:
        i = args.index("--missing")
        missing_path = args[i + 1]
        del args[i:i + 2]
    out = Path(args[0] if args else "tmp_banners")
    (out / "banners").mkdir(parents=True, exist_ok=True)

    first = _get(LIST_URL.format(page=0)).decode("utf-8")
    pages = max((int(v) for v in re.findall(r'<option value="(\d+)" data-flg="\d+">', first)), default=0) + 1
    print(f"{pages} ページ")

    items: list[dict] = []
    for page in range(pages):
        text = first if page == 0 else _get(LIST_URL.format(page=page)).decode("utf-8")
        entries = parse_page(text)
        if not entries:
            raise SystemExit(f"ページ {page} から曲を読み取れませんでした")
        items.extend(entries)
        if page:
            time.sleep(INTERVAL_SEC)
    print(f"{len(items)} 曲")

    urls = {}
    for item in items:
        url = urllib.parse.urljoin(SITE, item.pop("img"))
        item["banner"] = hashlib.sha1(url.encode()).hexdigest()[:16] + ".png"
        urls[item["banner"]] = url

    wanted = set(urls)
    if missing_path:
        # バナーの無い曲に対応する画像だけを取得する (曲との照合は generate_music_list.py と同じ)
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from generate_music_list import build_entry_pools, find_entry

        pools = build_entry_pools(items)
        songs = _songs_without_banner(missing_path)
        found = [find_entry(s, pools) for s in songs]
        wanted = {e["banner"] for e in found if e}
        print(f"バナーの無い曲 {len(songs)} 曲のうち、公式サイトに画像があるのは {len(wanted)} 枚")

    jobs = [(urls[name], out / "banners" / name) for name in sorted(wanted) if not (out / "banners" / name).exists()]

    def download(job):
        url, path = job
        part = path.with_suffix(".part")
        part.write_bytes(_get(url))
        part.replace(path)   # 途中で止まっても欠けた画像が残らないようにする
        time.sleep(INTERVAL_SEC)

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for n, _ in enumerate(pool.map(download, jobs), 1):
            if n % 100 == 0:
                print(f"  バナー {n}/{len(jobs)} 枚取得")
    downloaded = len(jobs)

    (out / "index.json").write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")
    print(f"完了: 新規 {downloaded} 枚 / 全 {len(items)} 曲")


if __name__ == "__main__":
    main()
