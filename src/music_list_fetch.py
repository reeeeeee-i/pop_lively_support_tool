"""曲リスト (popn_music_list.json) の取得・検証

取得先の既定は、このリポジトリの main ブランチに置いた popn_music_list.json (GitHub の raw URL)。

安全のため、取得した曲リストは次の検証を通ったものだけを使う。
  1. https のみ・リダイレクトも https のみ・サイズ上限 (src/secure_http.py)
  2. 開発者の署名 (<URL>.sig、Ed25519) の検証。署名は内容のハッシュを束ねているので、1 バイトでも
     改ざんされていれば拒否する (src/signing.py)
  3. 署名に含まれる通し番号が、これまでに取り込んだ最大値より小さくない (古い曲リストへの巻き戻しを防ぐ)
  4. 曲リストの中身の検証 (項目の型・長さ・範囲・制御文字・UUID・重複)
"""
from __future__ import annotations

import json
import os
import re
import uuid
from dataclasses import dataclass

from src import secure_http, signing
from src.logger import get_logger
from src.signing import SignatureError, SignedInfo

logger = get_logger(__name__)

DEFAULT_MUSIC_LIST_URL = (
    "https://raw.githubusercontent.com/reeeeeee-i/pop_lively_support_tool/main/popn_music_list.json"
)
MUSIC_LIST_NAME = "popn_music_list.json"   # 署名に記録するファイル名 (取得先の名前とは無関係に固定)
_MAX_BYTES = 20 * 1024 * 1024   # 曲リストは約 1.2MB。想定外に大きいものは取り込まない
_MAX_SONGS = 20000
_TEXT_LIMITS = {"title": 300, "genre": 300, "artist": 600, "ver": 100, "bpm": 50, "pack": 200}
_BANNER_LIMIT = 1024   # バナーの特徴量 (base64 の文字列。約 260 文字)
_BASE64 = re.compile(r"[A-Za-z0-9+/]*={0,2}")
_LEVEL_COLUMNS = ("easy", "normal", "hyper", "ex")
_LEVEL_RANGE = (1, 60)
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


class MusicListFetchError(Exception):
    """曲リストを取得できない、または検証に通らないときのエラー (メッセージは利用者向け)"""


@dataclass
class MusicList:
    """検証済みの曲リスト"""
    items: list[dict]
    serial: int | None   # 署名の通し番号 (署名の無いローカルファイルは None)
    signed: SignedInfo | None
    source: str


# ----------------------------------------------------------------------
# 中身の検証
# ----------------------------------------------------------------------

def _clean_text(value, field: str, index: int) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise MusicListFetchError(f"{index + 1} 件目: {field} の型が正しくありません")
    if len(value) > _TEXT_LIMITS[field]:
        raise MusicListFetchError(f"{index + 1} 件目: {field} が長すぎます")
    if _CONTROL_CHARS.search(value):
        raise MusicListFetchError(f"{index + 1} 件目: {field} に制御文字が含まれています")
    return value


def _clean_banner(value, index: int) -> str:
    if value is None or value == "":
        return ""
    if not isinstance(value, str) or len(value) > _BANNER_LIMIT or not _BASE64.fullmatch(value):
        raise MusicListFetchError(f"{index + 1} 件目: banner の形式が正しくありません")
    return value


def _clean_level(value, field: str, index: int):
    if value is None or value == "":
        return None
    if isinstance(value, bool) or not isinstance(value, (int, str)) or not str(value).isdigit():
        raise MusicListFetchError(f"{index + 1} 件目: {field} が数値ではありません")
    level = int(value)
    if not _LEVEL_RANGE[0] <= level <= _LEVEL_RANGE[1]:
        raise MusicListFetchError(f"{index + 1} 件目: {field} が範囲外です")
    return level


def validate_music_items(items, require_ids: bool = False) -> list[dict]:
    """曲リストの中身を検証し、既知の項目だけを取り出した曲の配列を返す。

    require_ids: 全曲に music_id (UUID) を必須にする (配信される曲リストは、スコアとの紐づけに使う ID を固定する)
    """
    if not isinstance(items, list) or not items:
        raise MusicListFetchError("曲リストの形式が正しくありません (曲の配列ではありません)")
    if len(items) > _MAX_SONGS:
        raise MusicListFetchError("曲リストの曲数が多すぎます")
    cleaned, seen_ids = [], set()
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            raise MusicListFetchError(f"{i + 1} 件目: 曲の形式が正しくありません")
        song = {field: _clean_text(item.get(field), field, i) for field in _TEXT_LIMITS}
        if not song["title"].strip():
            raise MusicListFetchError(f"{i + 1} 件目: 曲名がありません")
        for column in _LEVEL_COLUMNS:
            song[column] = _clean_level(item.get(column), column, i)
        song["banner"] = _clean_banner(item.get("banner"), i)
        music_id = item.get("music_id") or item.get("uuid")
        if music_id:
            try:
                music_id = str(uuid.UUID(str(music_id)))
            except ValueError as e:
                raise MusicListFetchError(f"{i + 1} 件目: music_id が UUID ではありません") from e
            if music_id in seen_ids:
                raise MusicListFetchError(f"{i + 1} 件目: music_id が重複しています")
            seen_ids.add(music_id)
            song["music_id"] = music_id
        elif require_ids:
            raise MusicListFetchError(f"{i + 1} 件目: music_id がありません")
        cleaned.append(song)
    return cleaned


def parse_music_list(data: bytes, require_ids: bool = False) -> list[dict]:
    """JSON のバイト列を曲リストとして検証して返す。"""
    try:
        items = json.loads(data.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError, RecursionError) as e:
        raise MusicListFetchError(f"曲リストの JSON を読めませんでした: {e}") from e
    return validate_music_items(items, require_ids)


# ----------------------------------------------------------------------
# 取得 (署名の検証つき)
# ----------------------------------------------------------------------

def fetch_music_list(url: str, last_serial: int = 0) -> MusicList:
    """url から曲リストと署名 (url + ".sig") を取得し、署名と中身を検証して返す。

    last_serial: これまでに取り込んだ署名の通し番号。これより小さい (古い) 曲リストは拒否する。
    """
    try:
        data = secure_http.fetch_bytes(url, _MAX_BYTES, None, "曲リスト")
        sig = secure_http.fetch_bytes(
            url + signing.SIGNATURE_SUFFIX, signing.MAX_SIGNATURE_BYTES, None, "署名ファイル"
        )
    except secure_http.FetchError as e:
        raise MusicListFetchError(str(e)) from e
    info = _verify(data, sig)
    serial = _serial(info)
    if serial < last_serial:
        raise MusicListFetchError(
            f"取得した曲リストは、取り込み済みのもの (通し番号 {last_serial}) より古い (通し番号 {serial}) ため拒否しました"
        )
    items = parse_music_list(data, require_ids=True)
    logger.info("曲リストを取得・検証しました: %s (%d 曲 / 通し番号 %d / 鍵 %s)", url, len(items), serial, info.key_id)
    return MusicList(items, serial, info, url)


def _verify(data: bytes, sig: bytes) -> SignedInfo:
    try:
        return signing.verify_content(data, sig, kind=signing.KIND_MUSIC_LIST, name=MUSIC_LIST_NAME)
    except SignatureError as e:
        raise MusicListFetchError(f"署名の検証に失敗しました: {e}") from e


def _serial(info: SignedInfo) -> int:
    if not info.version.isdigit():
        raise MusicListFetchError("署名の通し番号が正しくありません")
    return int(info.version)


def load_local_music_list(path: str) -> MusicList:
    """ローカルの曲リストを読んで検証する。

    同じフォルダに <ファイル名>.sig があれば署名も検証し、署名が不正ならエラーにする。
    署名が無い場合は signed=None で返す (呼び出し側が、利用者に確認する)。
    """
    try:
        with open(path, "rb") as f:
            data = f.read(_MAX_BYTES + 1)
    except OSError as e:
        raise MusicListFetchError(f"ファイルを読めませんでした: {e}") from e
    if len(data) > _MAX_BYTES:
        raise MusicListFetchError("曲リストのサイズが大きすぎます")
    info, serial = None, None
    sig_path = path + signing.SIGNATURE_SUFFIX
    if os.path.isfile(sig_path):
        try:
            with open(sig_path, "rb") as f:
                sig = f.read(signing.MAX_SIGNATURE_BYTES + 1)
        except OSError as e:
            raise MusicListFetchError(f"署名ファイルを読めませんでした: {e}") from e
        info = _verify(data, sig)
        serial = _serial(info)
    return MusicList(parse_music_list(data), serial, info, path)
