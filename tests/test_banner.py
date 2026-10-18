"""オプション画面のバナーによる曲の特定のテスト

    python -m unittest discover -s tests -v
"""
from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import unittest

import numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.makedirs(os.path.join(ROOT, "log"), exist_ok=True)

from src.banner_reader import (  # noqa: E402
    BannerIndex, banner_feature, decode_feature, encode_feature, locate_banner, read_banner,
)
from src.db import PopnDatabase  # noqa: E402


def _banner(seed: int, size=(244, 58)) -> Image.Image:
    """乱数の模様のバナー (曲ごとに異なる絵の代わり)。"""
    rng = np.random.default_rng(seed)
    small = rng.integers(0, 256, (4, 16, 3), dtype=np.uint8)
    return Image.fromarray(small).resize(size, Image.Resampling.BICUBIC)


def _screen(banner: Image.Image, top: int = 294, height: int = 132) -> np.ndarray:
    """バナーを黒い縁取りで囲んでオプション画面 (1920x1080) に置いた画像。"""
    arr = np.full((1080, 1920, 3), (240, 80, 160), dtype=np.uint8)
    x0, x1 = 690, 1237
    arr[top - 5:top + height + 5, x0 - 5:x1 + 5] = 0
    arr[top:top + height, x0:x1] = np.asarray(banner.convert("RGB").resize((x1 - x0, height)))
    return arr


class BannerReaderTest(unittest.TestCase):
    def test_locate_follows_vertical_offset_and_scale(self):
        for top, height in ((294, 132), (330, 132), (300, 150)):
            box = locate_banner(_screen(_banner(1), top, height))
            self.assertIsNotNone(box, (top, height))
            x0, y0, x1, y1 = box
            self.assertLessEqual(abs(y0 - top), 2)
            self.assertLessEqual(abs(y1 - (top + height)), 2)
            self.assertLessEqual(abs(x0 - 690), 2)

    def test_locate_with_top_edge_covered(self):
        arr = _screen(_banner(1), 328, 132)
        arr[320:332, 700:800] = (250, 250, 250)   # ランクの演出などで上辺の一部が隠れる
        box = locate_banner(arr)
        self.assertIsNotNone(box)
        self.assertLessEqual(abs(box[1] - 328), 2)
        self.assertLessEqual(abs(box[0] - 690), 2)

    def test_low_correlation_needs_large_margin(self):
        base = banner_feature(_banner(1))
        other = banner_feature(_banner(2))
        mixed = base * 0.65 + other * 0.1   # 公式サイトの画像とゲーム内の画像が少し違う曲のつもり
        mixed = mixed / np.linalg.norm(mixed)
        index = BannerIndex([("a", base), ("b", other), ("c", banner_feature(_banner(3)))])
        self.assertEqual(index.match(mixed)[0], "a")
        crowded = BannerIndex([("a", base), ("b", mixed * 0.99 + other * 0.01), ("c", other)])
        self.assertIsNone(crowded.match(mixed * 0.7 + other * 0.3))

    def test_locate_none_without_banner(self):
        self.assertIsNone(locate_banner(np.full((1080, 1920, 3), 200, dtype=np.uint8)))

    def test_read_matches_site_banner_despite_rescale(self):
        site = _banner(7)
        feature = read_banner(Image.fromarray(_screen(site)))
        self.assertIsNotNone(feature)
        self.assertGreater(float(feature @ banner_feature(site)), 0.95)
        self.assertLess(float(feature @ banner_feature(_banner(8))), 0.5)

    def test_encode_decode_roundtrip(self):
        v = banner_feature(_banner(3))
        w = decode_feature(encode_feature(v))
        self.assertGreater(float(v @ w), 0.999)
        self.assertIsNone(decode_feature("!!!"))
        self.assertIsNone(decode_feature(encode_feature(v)[:-8]))

    def test_brightness_change_is_tolerated(self):
        site = _banner(5)
        darker = Image.fromarray((np.asarray(site.convert("RGB")) * 0.8).astype(np.uint8))
        self.assertGreater(float(banner_feature(darker) @ banner_feature(site)), 0.98)


class BannerIndexTest(unittest.TestCase):
    def test_match_and_rejections(self):
        feats = {f"m{i}": banner_feature(_banner(i)) for i in range(20)}
        index = BannerIndex(list(feats.items()))
        found = index.match(feats["m3"])
        self.assertEqual(found[0], "m3")
        self.assertIsNone(index.match(banner_feature(_banner(999))))   # どの曲にも似ていない

    def test_identical_banners_are_ambiguous(self):
        v = banner_feature(_banner(1))
        index = BannerIndex([("a", v), ("b", v.copy()), ("c", banner_feature(_banner(2)))])
        self.assertIsNone(index.match(v))


class MusicListValidationTest(unittest.TestCase):
    def test_banner_is_kept_only_when_well_formed(self):
        from src import music_list_fetch as mlf
        good = encode_feature(banner_feature(_banner(1)))
        item = {"title": "t", "banner": good}
        self.assertEqual(mlf.validate_music_items([item])[0]["banner"], good)
        self.assertEqual(mlf.validate_music_items([{"title": "t"}])[0]["banner"], "")
        for bad in ("<script>", "A" * 5000, 123):
            with self.assertRaises(mlf.MusicListFetchError):
                mlf.validate_music_items([{"title": "t", "banner": bad}])


class DatabaseBannerTest(unittest.TestCase):
    def test_import_and_match(self):
        feats = [banner_feature(_banner(i)) for i in range(5)]
        songs = [
            {"music_id": f"id{i}", "title": f"曲{i}", "genre": "g", "artist": "a", "ver": "v", "bpm": "100",
             "easy": 5, "normal": 10, "hyper": 20, "ex": 30, "pack": "", "banner": encode_feature(f)}
            for i, f in enumerate(feats)
        ]
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "list.json")
            import json
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(songs, fh, ensure_ascii=False)
            db = PopnDatabase(os.path.join(folder, "t.db"))
            try:
                db.import_music_list_json(path, update_json=False)
                self.assertEqual(db.match_banner(feats[2])["music_id"], "id2")
                self.assertEqual(db.music_with_level("id2", "HYPER")["level"], 20)

                # バナーの無い古い曲リストで更新しても、特徴量は消えない
                for s in songs:
                    del s["banner"]
                with open(path, "w", encoding="utf-8") as fh:
                    json.dump(songs, fh, ensure_ascii=False)
                db.import_music_list_json(path, update_json=False)
                self.assertEqual(db.match_banner(feats[4])["music_id"], "id4")
            finally:
                db.close()

    def test_old_database_gets_banner_column(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "old.db")
            con = sqlite3.connect(path)
            con.execute("CREATE TABLE musics (music_id TEXT PRIMARY KEY, title TEXT NOT NULL, genre TEXT DEFAULT '', "
                        "artist TEXT DEFAULT '', ver TEXT DEFAULT '', bpm TEXT DEFAULT '', easy INTEGER, normal INTEGER, "
                        "hyper INTEGER, ex INTEGER, pack TEXT DEFAULT '')")
            con.commit()
            con.close()
            db = PopnDatabase(path)
            try:
                cols = {r["name"] for r in db._conn.execute("PRAGMA table_info(musics)")}
                self.assertIn("banner", cols)
            finally:
                db.close()


if __name__ == "__main__":
    unittest.main()
