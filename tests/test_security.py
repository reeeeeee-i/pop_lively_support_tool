"""署名・取得・更新まわりのセキュリティのテスト

    python -m unittest discover -s tests -v
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import unittest
import urllib.error
import urllib.request
import zipfile
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.makedirs(os.path.join(ROOT, "log"), exist_ok=True)

from src import ed25519, music_list_fetch as mlf, secure_http, signing, updater  # noqa: E402

# RFC 8032 section 7.1 のテストベクター (秘密鍵, 公開鍵, メッセージ, 署名)
_VECTORS = [
    ("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60",
     "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a", "",
     "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b"),
    ("4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb",
     "3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c", "72",
     "92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da085ac1e43e15996e458f3613d0f11d8c387b2eaeb4302aeeb00d291612bb0c00"),
]
_SECRET = bytes(range(32))
_PUBLIC = ed25519.secret_to_public(_SECRET)
_KEYS = {signing.key_id(_PUBLIC): _PUBLIC.hex()}
_L = 2 ** 252 + 27742317777372353535851937790883648493


def _music(n=3, **overrides):
    items = [{"title": f"曲{i}", "genre": "", "artist": "a", "ver": "v", "bpm": "120", "pack": "",
              "easy": 5, "normal": 10, "hyper": 20, "ex": 30,
              "music_id": f"00000000-0000-4000-8000-{i:012d}"} for i in range(n)]
    items[0].update(overrides)
    return items


class Ed25519Test(unittest.TestCase):
    def test_rfc_vectors(self):
        for sk, pk, msg, sig in (tuple(bytes.fromhex(x) for x in v) for v in _VECTORS):
            self.assertEqual(ed25519.secret_to_public(sk), pk)
            self.assertEqual(ed25519.sign(sk, msg), sig)
            self.assertTrue(ed25519.verify(pk, msg, sig))
            self.assertFalse(ed25519.verify(pk, msg + b"x", sig))

    def test_rejects_malformed(self):
        sig = ed25519.sign(_SECRET, b"m")
        self.assertFalse(ed25519.verify(_PUBLIC, b"m", sig[:-1]))
        self.assertFalse(ed25519.verify(_PUBLIC[:-1], b"m", sig))
        self.assertFalse(ed25519.verify(b"\xff" * 32, b"m", sig))
        # S >= L (署名の可鍛性)
        s = (int.from_bytes(sig[32:], "little") + _L).to_bytes(32, "little")
        self.assertFalse(ed25519.verify(_PUBLIC, b"m", sig[:32] + s))


class SigningTest(unittest.TestCase):
    def _sig(self, **kw):
        args = dict(kind=signing.KIND_MUSIC_LIST, name="popn_music_list.json", version="5",
                    sha256=hashlib.sha256(b"data").hexdigest(), size=4)
        args.update(kw)
        return signing.create_signature_file(_SECRET, **args)

    def verify(self, sig, **kw):
        kw.setdefault("kind", signing.KIND_MUSIC_LIST)
        return signing.verify_signature(sig, trusted_keys=_KEYS, **kw)

    def test_valid(self):
        info = self.verify(self._sig(), name="popn_music_list.json",
                           sha256=hashlib.sha256(b"data").hexdigest(), size=4)
        self.assertEqual(info.version, "5")

    def test_tampered_fields_rejected(self):
        data = json.loads(self._sig())
        for field, value in (("version", "6"), ("sha256", "0" * 64), ("size", 5), ("name", "x.json")):
            bad = dict(data, **{field: value})
            with self.assertRaises(signing.SignatureError, msg=field):
                self.verify(json.dumps(bad).encode())

    def test_wrong_content_kind_name(self):
        sig = self._sig()
        with self.assertRaises(signing.SignatureError):
            self.verify(sig, sha256=hashlib.sha256(b"other").hexdigest())
        with self.assertRaises(signing.SignatureError):
            self.verify(sig, size=99)
        with self.assertRaises(signing.SignatureError):
            self.verify(sig, kind=signing.KIND_RELEASE)   # 曲リストの署名をリリースに流用できない
        with self.assertRaises(signing.SignatureError):
            self.verify(sig, name="other.json")

    def test_untrusted_or_missing_keys(self):
        with self.assertRaises(signing.SignatureError):
            signing.verify_signature(self._sig(), kind=signing.KIND_MUSIC_LIST, trusted_keys={})
        other = ed25519.secret_to_public(b"\x01" * 32)
        with self.assertRaises(signing.SignatureError):
            signing.verify_signature(self._sig(), kind=signing.KIND_MUSIC_LIST,
                                     trusted_keys={signing.key_id(other): other.hex()})
        # 鍵 ID を偽って、別の公開鍵を指させても拒否
        with self.assertRaises(signing.SignatureError):
            signing.verify_signature(self._sig(), kind=signing.KIND_MUSIC_LIST,
                                     trusted_keys={signing.key_id(_PUBLIC): other.hex()})

    def test_garbage(self):
        for blob in (b"", b"not json", b"[]", b"{}", b'{"format":1}', b"x" * 100000):
            with self.assertRaises(signing.SignatureError):
                self.verify(blob)

    def test_signature_bit_flip(self):
        data = json.loads(self._sig())
        sig = bytearray.fromhex(data["signature"])
        sig[3] ^= 1
        with self.assertRaises(signing.SignatureError):
            self.verify(json.dumps(dict(data, signature=sig.hex())).encode())

    def test_shipped_key_and_music_list_signature(self):
        """リポジトリの曲リストの署名が、組み込まれた公開鍵で検証できる"""
        path = os.path.join(ROOT, "popn_music_list.json")
        with open(path, "rb") as f, open(path + ".sig", "rb") as g:
            info = signing.verify_content(f.read(), g.read(), kind=signing.KIND_MUSIC_LIST,
                                          name=mlf.MUSIC_LIST_NAME)
        self.assertTrue(info.version.isdigit())


class MusicListTest(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(len(mlf.validate_music_items(_music(), require_ids=True)), 3)

    def test_rejects_bad_items(self):
        bad_cases = [
            [], {}, "x", [1], [{"title": ""}], [{"title": 5}], _music(title="a" * 1000),
            _music(title="a\x00b"), _music(easy=-1), _music(easy=999), _music(easy="x"), _music(easy=True),
            _music(music_id="not-a-uuid"), _music() + [_music()[0]],   # music_id の重複
            [{"title": "x"}],   # require_ids 時に ID が無い
        ]
        for case in bad_cases:
            with self.assertRaises(mlf.MusicListFetchError, msg=repr(case)[:60]):
                mlf.validate_music_items(case, require_ids=True)

    def test_drops_unknown_keys(self):
        item = _music(1, evil="<script>")[0]
        self.assertNotIn("evil", mlf.validate_music_items([item])[0])

    def _sign(self, items, serial="3"):
        data = json.dumps(items, ensure_ascii=False).encode()
        sig = signing.create_signature_file(_SECRET, signing.KIND_MUSIC_LIST, mlf.MUSIC_LIST_NAME, serial,
                                            hashlib.sha256(data).hexdigest(), len(data))
        return data, sig

    def _fetch(self, data, sig, last_serial=0):
        def fake(url, *a, **k):
            return sig if url.endswith(".sig") else data
        with mock.patch.object(secure_http, "fetch_bytes", fake), \
                mock.patch.object(signing, "TRUSTED_PUBLIC_KEYS", _KEYS):
            return mlf.fetch_music_list("https://example.com/popn_music_list.json", last_serial)

    def test_fetch_ok_rollback_and_tamper(self):
        data, sig = self._sign(_music())
        self.assertEqual(self._fetch(data, sig).serial, 3)
        with self.assertRaises(mlf.MusicListFetchError):        # 巻き戻し (取り込み済みより古い)
            self._fetch(data, sig, last_serial=4)
        self.assertEqual(self._fetch(data, sig, last_serial=3).serial, 3)
        with self.assertRaises(mlf.MusicListFetchError):        # 内容の改ざん
            self._fetch(data.replace("曲1".encode(), "曲X".encode()), sig)
        with self.assertRaises(mlf.MusicListFetchError):        # 署名ファイルなし
            self._fetch(data, b"")
        # 署名は正しくても、中身が不正なら拒否する
        bad, bad_sig = self._sign(_music(title="a\x00b"))
        with self.assertRaises(mlf.MusicListFetchError):
            self._fetch(bad, bad_sig)

    def test_local_file(self):
        with tempfile.TemporaryDirectory() as d:
            data, sig = self._sign(_music())
            path = os.path.join(d, "list.json")
            with open(path, "wb") as f:
                f.write(data)
            self.assertIsNone(mlf.load_local_music_list(path).signed)   # 署名なし (呼び出し側が確認する)
            with open(path + ".sig", "wb") as f:
                f.write(sig)
            with mock.patch.object(signing, "TRUSTED_PUBLIC_KEYS", _KEYS):
                self.assertEqual(mlf.load_local_music_list(path).serial, 3)
                with open(path, "wb") as f:                              # 署名があるのに内容が違う
                    f.write(data + b" ")
                with self.assertRaises(mlf.MusicListFetchError):
                    mlf.load_local_music_list(path)


class SecureHttpTest(unittest.TestCase):
    def test_check_url(self):
        secure_http.check_url("https://raw.githubusercontent.com/a/b")
        for url in ("http://example.com/x", "ftp://example.com/x", "file:///c:/x",
                    "https://u:p@example.com/x", "https:///x"):
            with self.assertRaises(secure_http.FetchError, msg=url):
                secure_http.check_url(url)
        for url in ("https://evil.example.com/x", "https://notgithub.com/x"):
            with self.assertRaises(secure_http.FetchError, msg=url):
                secure_http.check_url(url, secure_http.GITHUB_HOST_SUFFIXES)
        secure_http.check_url("https://objects.githubusercontent.com/x", secure_http.GITHUB_HOST_SUFFIXES)

    def test_redirect_policy(self):
        handler = secure_http._SafeRedirectHandler(secure_http.GITHUB_HOST_SUFFIXES)
        req = urllib.request.Request("https://github.com/x")
        for bad in ("http://github.com/x", "https://evil.example.com/x"):
            with self.assertRaises(urllib.error.URLError):
                handler.redirect_request(req, None, 302, "Found", {}, bad)
        self.assertIsNotNone(
            handler.redirect_request(req, None, 302, "Found", {}, "https://objects.githubusercontent.com/x"))


class UpdaterTest(unittest.TestCase):
    def _zip(self, folder, files, name="u.zip"):
        path = os.path.join(folder, name)
        with zipfile.ZipFile(path, "w") as z:
            for n, c in files.items():
                z.writestr(n, c)
        return path

    def test_extract_rejects_malicious_zips(self):
        with tempfile.TemporaryDirectory() as d:
            for name in ("../evil.txt", "/abs.txt", "C:/x.txt", "a/../../b.txt", "a:stream.txt", "..\\evil.txt"):
                with self.assertRaises(updater.UpdateError, msg=name):
                    updater.extract(self._zip(d, {name: "x"}), os.path.join(d, "out"))
            self.assertFalse(os.path.exists(os.path.join(d, "evil.txt")))
            # シンボリックリンク
            path = os.path.join(d, "link.zip")
            with zipfile.ZipFile(path, "w") as z:
                info = zipfile.ZipInfo("lnk")
                info.external_attr = 0o120777 << 16
                z.writestr(info, "/etc/passwd")
            with self.assertRaises(updater.UpdateError):
                updater.extract(path, os.path.join(d, "out2"))
            # 展開後サイズの過大
            with mock.patch.object(updater, "_EXTRACT_MAX_BYTES", 5):
                with self.assertRaises(updater.UpdateError):
                    updater.extract(self._zip(d, {"a.txt": "x" * 100}, "big.zip"), os.path.join(d, "out3"))
            # zip として読めないファイル
            notzip = os.path.join(d, "notzip.zip")
            with open(notzip, "w") as f:
                f.write("x")
            with self.assertRaises(updater.UpdateError):
                updater.extract(notzip, os.path.join(d, "out4"))

    def test_extract_ok(self):
        with tempfile.TemporaryDirectory() as d:
            z = self._zip(d, {"app/pop_lively_support_tool.exe": "x", "app/lib/a.txt": "y"})
            updater.extract(z, os.path.join(d, "out"))
            self.assertTrue(updater.find_app_root(os.path.join(d, "out")).endswith("app"))

    def test_batch_rejects_unsafe_paths(self):
        for bad in ("C:\\a%PATH%\\b", 'C:\\a"b', "C:\\a&calc", "C:\\a^b", "C:\\a|b", "C:\\a\nb", "C:\\a!b"):
            with self.assertRaises(updater.UpdateError, msg=bad):
                updater.build_update_script(1, bad, "C:\\app", "C:\\app\\_update")
        script = updater.build_update_script(123, "C:\\s", "C:\\アプリ", "C:\\アプリ\\_update")
        self.assertIn('set "PID=123"', script)
        self.assertIn('"config.json"', script)

    def test_parse_release_requires_signature_asset_and_trusted_urls(self):
        base = "https://github.com/reeeeeee-i/pop_lively_support_tool/releases/download/261101/"
        name = "pop_lively_support_tool_261101.zip"
        good = {"tag_name": "261101", "assets": [
            {"name": name, "browser_download_url": base + name},
            {"name": name + ".sig", "browser_download_url": base + name + ".sig"}]}
        self.assertEqual(updater.parse_release(good)[3], name)
        with self.assertRaises(updater.UpdateError):   # .sig が無い
            updater.parse_release({"assets": good["assets"][:1]})
        evil = json.loads(json.dumps(good))
        evil["assets"][0]["browser_download_url"] = "https://evil.example.com/a.zip"
        with self.assertRaises(updater.UpdateError):
            updater.parse_release(evil)

    def _fake_release(self, version="261101", tag="261101", name="pop_lively_support_tool_261101.zip",
                      sig_name=None, kind=signing.KIND_RELEASE):
        sig = signing.create_signature_file(_SECRET, kind, sig_name or name, version, "a" * 64, 1000)
        base = "https://github.com/reeeeeee-i/pop_lively_support_tool/releases/download/" + tag + "/"
        api = {"tag_name": tag, "assets": [
            {"name": name, "browser_download_url": base + name},
            {"name": name + ".sig", "browser_download_url": base + name + ".sig"}]}

        def fake(url, *a, **k):
            return sig if url.endswith(".sig") else json.dumps(api).encode()
        return fake

    def test_fetch_latest_release_verifies_signature(self):
        with mock.patch.object(signing, "TRUSTED_PUBLIC_KEYS", _KEYS):
            with mock.patch.object(secure_http, "fetch_bytes", self._fake_release()):
                self.assertEqual(updater.fetch_latest_release().tag, "261101")
            cases = {
                "署名済みの古い版を新しいタグで配る": self._fake_release(version="261004"),
                "曲リストの署名をリリースに流用": self._fake_release(kind=signing.KIND_MUSIC_LIST),
                "別名の zip の署名を流用": self._fake_release(sig_name="other.zip"),
            }
            for label, fake in cases.items():
                with mock.patch.object(secure_http, "fetch_bytes", fake):
                    with self.assertRaises(updater.UpdateError, msg=label):
                        updater.fetch_latest_release()
        # 信頼する鍵が無ければ拒否
        with mock.patch.object(signing, "TRUSTED_PUBLIC_KEYS", {}), \
                mock.patch.object(secure_http, "fetch_bytes", self._fake_release()):
            with self.assertRaises(updater.UpdateError):
                updater.fetch_latest_release()

    def test_download_verifies_hash_and_size(self):
        data = b"zipdata" * 100
        sha = hashlib.sha256(data).hexdigest()
        url = updater._DOWNLOAD_PREFIX + "261101/x.zip"

        def fake_stream(u, dest, max_bytes, hasher, hosts, progress, cancelled):
            payload = data[:max_bytes]
            with open(dest, "wb") as f:
                f.write(payload)
            hasher.update(payload)
            return len(payload)

        with tempfile.TemporaryDirectory() as d, mock.patch.object(secure_http, "stream_to_file", fake_stream):
            dest = os.path.join(d, "u.zip")
            updater.download(url, dest, len(data), sha)
            self.assertTrue(os.path.exists(dest))
            for size, digest in ((len(data), "0" * 64), (len(data) - 1, sha)):
                with self.assertRaises(updater.UpdateError):
                    updater.download(url, dest, size, digest)
                self.assertFalse(os.path.exists(dest))          # 不一致のファイルは残さない
            with self.assertRaises(updater.UpdateError):
                updater.download("https://evil.example.com/u.zip", dest, len(data), sha)


if __name__ == "__main__":
    unittest.main()
