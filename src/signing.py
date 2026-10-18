"""配布物 (曲リストの JSON・ツール本体の zip) の署名の検証

署名は Ed25519。開発者だけが持つ秘密鍵で署名し、アプリは src/trusted_keys.py の公開鍵で検証する。
GitHub のアカウントやリポジトリ、通信路が侵害されても、秘密鍵が無ければ偽物を配布できない。

署名ファイル (JSON) は、配布物のハッシュ・サイズ・名前・バージョンを束ねた「マニフェスト」に署名したもの。
署名の対象にバージョンを含めるので、古い (署名済みの) 配布物を新しいものとして配ることもできない。
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass

from src import ed25519
from src.trusted_keys import TRUSTED_PUBLIC_KEYS

KIND_MUSIC_LIST = "music-list"
KIND_RELEASE = "release"
SIGNATURE_SUFFIX = ".sig"
MAX_SIGNATURE_BYTES = 16 * 1024

_FORMAT_VERSION = 1
_ALGORITHM = "ed25519"
_MESSAGE_HEADER = "popn-signed-v1"
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_HEX128 = re.compile(r"^[0-9a-f]{128}$")
_KINDS = (KIND_MUSIC_LIST, KIND_RELEASE)


class SignatureError(Exception):
    """署名を検証できなかったとき (偽造・改ざん・形式不正・未署名) のエラー。メッセージは利用者向け"""


@dataclass
class SignedInfo:
    """検証に成功した署名の内容"""
    kind: str
    name: str
    version: str
    sha256: str
    size: int
    key_id: str


def key_id(public_key: bytes) -> str:
    """公開鍵の識別子 (SHA-256 の先頭 8 バイトを 16 進で)"""
    return hashlib.sha256(public_key).hexdigest()[:16]


def manifest_message(kind: str, name: str, version: str, sha256: str, size: int) -> bytes:
    """署名の対象にするバイト列。区切りに改行を使うので、各項目に改行は含められない。"""
    for value in (kind, name, version, sha256):
        if "\n" in str(value) or "\r" in str(value):
            raise ValueError("マニフェストの項目に改行は使えません")
    return "\n".join([
        _MESSAGE_HEADER, f"kind={kind}", f"name={name}", f"version={version}", f"sha256={sha256}", f"size={size}",
    ]).encode("utf-8")


def create_signature_file(
    secret: bytes, kind: str, name: str, version: str, sha256: str, size: int
) -> bytes:
    """署名ファイル (JSON) を作る。開発者の手元 (tools/sign_release.py) で使う。"""
    public = ed25519.secret_to_public(secret)
    signature = ed25519.sign(secret, manifest_message(kind, name, version, sha256, size))
    data = {
        "format": _FORMAT_VERSION, "algorithm": _ALGORITHM, "key_id": key_id(public),
        "kind": kind, "name": name, "version": version, "sha256": sha256, "size": size,
        "signature": signature.hex(),
    }
    return (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _parse(sig_data: bytes) -> dict:
    if len(sig_data) > MAX_SIGNATURE_BYTES:
        raise SignatureError("署名ファイルが大きすぎます")
    try:
        data = json.loads(sig_data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as e:
        raise SignatureError("署名ファイルを読めません") from e
    if not isinstance(data, dict):
        raise SignatureError("署名ファイルの形式が正しくありません")
    str_fields = ("algorithm", "key_id", "kind", "name", "version", "sha256", "signature")
    if data.get("format") != _FORMAT_VERSION or data.get("algorithm") != _ALGORITHM:
        raise SignatureError("対応していない形式の署名です")
    if any(not isinstance(data.get(f), str) for f in str_fields) or not isinstance(data.get("size"), int):
        raise SignatureError("署名ファイルの形式が正しくありません")
    if data["kind"] not in _KINDS or not _HEX64.match(data["sha256"]) or not _HEX128.match(data["signature"]):
        raise SignatureError("署名ファイルの形式が正しくありません")
    if len(data["name"]) > 200 or len(data["version"]) > 50 or data["size"] < 0:
        raise SignatureError("署名ファイルの形式が正しくありません")
    return data


def verify_signature(
    sig_data: bytes, *, kind: str, name: str | None = None, sha256: str | None = None,
    size: int | None = None, trusted_keys: dict[str, str] | None = None,
) -> SignedInfo:
    """署名ファイルを検証する。

    kind: 想定する種類 (曲リストの署名を、ツール本体の署名として使い回すことを防ぐ)
    name / sha256 / size: 指定すると、署名に含まれる値がこれと一致することも確かめる
    trusted_keys: 信頼する公開鍵 {key_id: 16 進}。省略すると src/trusted_keys.py の鍵
    """
    keys = TRUSTED_PUBLIC_KEYS if trusted_keys is None else trusted_keys
    data = _parse(sig_data)
    if not keys:
        raise SignatureError("署名の検証に使う公開鍵が設定されていません (src/trusted_keys.py)")
    public_hex = keys.get(data["key_id"])
    if public_hex is None:
        raise SignatureError("信頼していない鍵で署名されています")
    try:
        public = bytes.fromhex(public_hex)
    except ValueError as e:
        raise SignatureError("公開鍵の設定が正しくありません") from e
    if key_id(public) != data["key_id"]:
        raise SignatureError("公開鍵の設定が正しくありません")

    message = manifest_message(data["kind"], data["name"], data["version"], data["sha256"], data["size"])
    if not ed25519.verify(public, message, bytes.fromhex(data["signature"])):
        raise SignatureError("署名が正しくありません。ファイルが改ざんされている可能性があります")
    if data["kind"] != kind:
        raise SignatureError("署名の種類が一致しません")
    if name is not None and data["name"] != name:
        raise SignatureError("署名の対象のファイル名が一致しません")
    if sha256 is not None and data["sha256"] != sha256.lower():
        raise SignatureError("ファイルの内容が署名と一致しません。ファイルが改ざんされている可能性があります")
    if size is not None and data["size"] != size:
        raise SignatureError("ファイルのサイズが署名と一致しません")
    return SignedInfo(data["kind"], data["name"], data["version"], data["sha256"], data["size"], data["key_id"])


def verify_content(
    content: bytes, sig_data: bytes, *, kind: str, name: str,
    trusted_keys: dict[str, str] | None = None,
) -> SignedInfo:
    """content (小さなファイルの全体) が、署名どおりの内容であることを確かめる。"""
    return verify_signature(
        sig_data, kind=kind, name=name, sha256=hashlib.sha256(content).hexdigest(), size=len(content),
        trusted_keys=trusted_keys,
    )
