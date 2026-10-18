"""外部から取得するときの共通処理 (https の強制・リダイレクトの制限・サイズの上限)

曲リストと更新ファイルの取得で使う。取得したものの真正性は、ここではなく署名 (src/signing.py) で確かめる。
ここでは、通信路上の改ざんや、想定外の相手・サイズへの接続を防ぐ。
"""
from __future__ import annotations

import ssl
import urllib.error
import urllib.request
from typing import Callable
from urllib.parse import urlsplit

from src.app_version import APP_NAME

TIMEOUT_SEC = 20
_CHUNK = 256 * 1024

# リリースの添付ファイルの取得で、リダイレクト先として許す GitHub のホスト (末尾一致)
GITHUB_HOST_SUFFIXES = ("github.com", "githubusercontent.com")


class FetchError(Exception):
    """取得できないときのエラー (メッセージは利用者向け)"""


def _host_allowed(host: str, suffixes: tuple[str, ...] | None) -> bool:
    if suffixes is None:
        return True
    host = host.lower()
    return any(host == s or host.endswith("." + s) for s in suffixes)


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    """リダイレクトを https に限り、許可したホストへのものだけ追う。"""

    def __init__(self, host_suffixes: tuple[str, ...] | None):
        self._host_suffixes = host_suffixes

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parts = urlsplit(newurl)
        if parts.scheme != "https" or not _host_allowed(parts.hostname or "", self._host_suffixes):
            raise urllib.error.URLError(f"許可されていないリダイレクト先です: {parts.scheme}://{parts.hostname}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _opener(host_suffixes: tuple[str, ...] | None) -> urllib.request.OpenerDirector:
    context = ssl.create_default_context()          # 証明書とホスト名を検証する
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    return urllib.request.build_opener(
        urllib.request.HTTPSHandler(context=context), _SafeRedirectHandler(host_suffixes)
    )


def check_url(url: str, host_suffixes: tuple[str, ...] | None = None) -> None:
    """https の URL で、(指定があれば) 許可したホストであることを確かめる。"""
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname:
        raise FetchError("取得先 URL は https:// で始まる必要があります")
    if parts.username or parts.password:
        raise FetchError("取得先 URL にユーザー情報は指定できません")
    if not _host_allowed(parts.hostname, host_suffixes):
        raise FetchError(f"許可されていない取得先です: {parts.hostname}")


def open_url(url: str, host_suffixes: tuple[str, ...] | None = None, accept: str = "*/*"):
    """検証済みの接続で url を開く (呼び出し側が with で閉じる)。"""
    check_url(url, host_suffixes)
    request = urllib.request.Request(url, headers={
        "User-Agent": APP_NAME,
        "Accept": accept,
        "Accept-Encoding": "identity",   # 圧縮されたデータを受け取らない (展開後のサイズが読めなくなるため)
    })
    try:
        return _opener(host_suffixes).open(request, timeout=TIMEOUT_SEC)
    except urllib.error.HTTPError as e:
        raise FetchError(f"取得できませんでした (HTTP {e.code})") from e
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise FetchError(f"取得できませんでした: {getattr(e, 'reason', e)}") from e


def read_limited(response, max_bytes: int, what: str = "ファイル") -> bytes:
    """応答を max_bytes までの範囲で読む。超えたら FetchError。"""
    declared = response.headers.get("Content-Length")
    if declared and declared.isdigit() and int(declared) > max_bytes:
        raise FetchError(f"{what}のサイズが大きすぎます")
    try:
        data = response.read(max_bytes + 1)
    except OSError as e:
        raise FetchError(f"取得できませんでした: {e}") from e
    if len(data) > max_bytes:
        raise FetchError(f"{what}のサイズが大きすぎます")
    return data


def fetch_bytes(
    url: str, max_bytes: int, host_suffixes: tuple[str, ...] | None = None, what: str = "ファイル",
    accept: str = "*/*",
) -> bytes:
    """url の内容を max_bytes までの範囲で取得する。"""
    with open_url(url, host_suffixes, accept) as response:
        return read_limited(response, max_bytes, what)


def stream_to_file(
    url: str, dest: str, max_bytes: int, hasher, host_suffixes: tuple[str, ...] | None,
    progress: Callable[[int, int], None] | None = None, cancelled: Callable[[], bool] | None = None,
) -> int:
    """url を dest に保存しながら hasher (hashlib のオブジェクト) に流し込む。保存したバイト数を返す。"""
    done = 0
    with open_url(url, host_suffixes) as response:
        declared = response.headers.get("Content-Length")
        total = int(declared) if declared and declared.isdigit() else 0
        if total > max_bytes:
            raise FetchError("ファイルのサイズが大きすぎます")
        with open(dest, "wb") as out:
            while True:
                if cancelled and cancelled():
                    raise FetchError("キャンセルしました")
                try:
                    chunk = response.read(_CHUNK)
                except OSError as e:
                    raise FetchError(f"ダウンロードできませんでした: {e}") from e
                if not chunk:
                    break
                done += len(chunk)
                if done > max_bytes:
                    raise FetchError("ファイルのサイズが大きすぎます")
                out.write(chunk)
                hasher.update(chunk)
                if progress:
                    progress(done, total)
    return done
