"""配布物 (曲リストの JSON・ツール本体の zip) に署名するツール (開発者用)

アプリは、署名を検証できない曲リスト・更新を使わない (src/signing.py)。配布物を公開する前に、このツールで
署名ファイル (.sig) を作り、配布物と一緒に公開する。

    python tools/sign_release.py genkey                      # 署名用の鍵を作る (最初に 1 回)
    python tools/sign_release.py sign-music popn_music_list.json
    python tools/sign_release.py sign-release dist/pop_lively_support_tool_261101.zip --tag 261101
    python tools/sign_release.py verify popn_music_list.json          # 署名の確認 (公開鍵は src/trusted_keys.py)

秘密鍵はファイルに 16 進で保存する (既定: ~/.pop_lively_support_tool/signing_key.hex)。
**秘密鍵はリポジトリに入れない・他人に渡さない・バックアップを別の場所に残す。** 漏れた場合は、
新しい鍵を作って src/trusted_keys.py を差し替え、新しい鍵で署名したバージョンを配布し直す。
鍵は --key か、環境変数 POP_SIGNING_KEY で指定もできる。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src import ed25519, signing  # noqa: E402
from src.app_version import EXE_NAME, parse_version  # noqa: E402
from src.music_list_fetch import MUSIC_LIST_NAME, MusicListFetchError, parse_music_list  # noqa: E402
from src.trusted_keys import TRUSTED_PUBLIC_KEYS  # noqa: E402

DEFAULT_KEY_PATH = Path.home() / ".pop_lively_support_tool" / "signing_key.hex"


def _key_path(arg: str | None) -> Path:
    return Path(arg or os.environ.get("POP_SIGNING_KEY") or DEFAULT_KEY_PATH)


def _load_secret(path: Path) -> bytes:
    try:
        secret = bytes.fromhex(path.read_text(encoding="ascii").strip())
    except (OSError, ValueError) as e:
        raise SystemExit(f"秘密鍵を読めません ({path}): {e}\n先に genkey で鍵を作ってください")
    if len(secret) != 32:
        raise SystemExit(f"秘密鍵の形式が正しくありません ({path})")
    return secret


def _restrict_permissions(path: Path) -> None:
    """鍵ファイルを自分だけが読めるようにする (Windows は icacls、それ以外は chmod)。"""
    try:
        if os.name == "nt":
            user = os.environ.get("USERNAME", "")
            subprocess.run(
                ["icacls", str(path), "/inheritance:r", "/grant:r", f"{user}:F"],
                check=True, capture_output=True,
            )
        else:
            os.chmod(path, 0o600)
    except (OSError, subprocess.CalledProcessError) as e:
        print(f"注意: 鍵ファイルの権限を制限できませんでした ({e})。手動で自分だけが読めるようにしてください")


def _sha256(path: Path) -> tuple[str, int]:
    digest, size = hashlib.sha256(), 0
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _self_check(sig_data: bytes, secret: bytes, **expected) -> signing.SignedInfo:
    """作った署名を、署名した鍵の公開鍵で検証し直す (作成の取り違えを防ぐ)。"""
    public = ed25519.secret_to_public(secret)
    return signing.verify_signature(sig_data, trusted_keys={signing.key_id(public): public.hex()}, **expected)


# ----------------------------------------------------------------------

def cmd_genkey(args) -> None:
    path = _key_path(args.key)
    if path.exists():
        raise SystemExit(f"既に鍵があります: {path}\n(上書きしません。別の場所に作るときは --key を指定してください)")
    path.parent.mkdir(parents=True, exist_ok=True)
    secret = os.urandom(32)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="ascii") as f:
        f.write(secret.hex() + "\n")
    _restrict_permissions(path)
    public = ed25519.secret_to_public(secret)
    print(f"秘密鍵を作りました: {path}")
    print("  → リポジトリに入れず、別の場所にもバックアップを取ってください")
    print(f"key_id : {signing.key_id(public)}")
    print(f"公開鍵 : {public.hex()}")
    print("\nsrc/trusted_keys.py の TRUSTED_PUBLIC_KEYS に、次の 1 行を追加してください:")
    print(f'    "{signing.key_id(public)}": "{public.hex()}",')


def cmd_sign_music(args) -> None:
    path = Path(args.file)
    data = path.read_bytes()
    try:
        items = parse_music_list(data, require_ids=True)
    except MusicListFetchError as e:
        raise SystemExit(f"曲リストの検証に失敗しました (署名しません): {e}")
    sig_path = Path(str(path) + signing.SIGNATURE_SUFFIX)
    serial = args.serial
    if serial is None:
        previous = 0
        try:
            previous = int(json.loads(sig_path.read_text(encoding="utf-8"))["version"])
        except (OSError, ValueError, KeyError, TypeError):
            pass
        serial = previous + 1
    secret = _load_secret(_key_path(args.key))
    sha, size = hashlib.sha256(data).hexdigest(), len(data)
    sig = signing.create_signature_file(secret, signing.KIND_MUSIC_LIST, MUSIC_LIST_NAME, str(serial), sha, size)
    _self_check(sig, secret, kind=signing.KIND_MUSIC_LIST, name=MUSIC_LIST_NAME, sha256=sha, size=size)
    sig_path.write_bytes(sig)
    print(f"署名しました: {sig_path}  ({len(items)} 曲 / 通し番号 {serial})")
    print("曲リストの JSON と、この .sig を一緒にコミットしてください (.sig の通し番号は増える一方にしてください)")


def cmd_sign_release(args) -> None:
    path = Path(args.file)
    if parse_version(args.tag) is None:
        raise SystemExit("--tag は YYMMDD または YYMMDD.N の形式で指定してください (pyproject.toml の version と同じ)")
    try:
        with zipfile.ZipFile(path) as zf:
            names = [n.replace("\\", "/") for n in zf.namelist()]
    except zipfile.BadZipFile:
        raise SystemExit("zip として読めません")
    if not any(n == EXE_NAME or n.endswith("/" + EXE_NAME) for n in names):
        raise SystemExit(f"zip に {EXE_NAME} がありません (署名しません)")
    secret = _load_secret(_key_path(args.key))
    sha, size = _sha256(path)
    sig = signing.create_signature_file(secret, signing.KIND_RELEASE, path.name, args.tag, sha, size)
    _self_check(sig, secret, kind=signing.KIND_RELEASE, name=path.name, sha256=sha, size=size)
    sig_path = Path(str(path) + signing.SIGNATURE_SUFFIX)
    sig_path.write_bytes(sig)
    print(f"署名しました: {sig_path}  (バージョン {args.tag} / SHA-256 {sha[:16]}...)")
    print(f"リリース (タグ {args.tag}) に、{path.name} と {sig_path.name} の両方を添付してください")


def cmd_verify(args) -> None:
    path = Path(args.file)
    sig_path = Path(args.sig or str(path) + signing.SIGNATURE_SUFFIX)
    sha, size = _sha256(path)
    sig = sig_path.read_bytes()
    kind = json.loads(sig.decode("utf-8")).get("kind")
    name = MUSIC_LIST_NAME if kind == signing.KIND_MUSIC_LIST else path.name
    try:
        info = signing.verify_signature(sig, kind=kind, name=name, sha256=sha, size=size)
    except signing.SignatureError as e:
        raise SystemExit(f"NG: {e}")
    print(f"OK: {info.kind} / {info.name} / バージョン {info.version} / 鍵 {info.key_id}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("genkey", help="署名用の鍵を作る")
    p.add_argument("--key", help="秘密鍵の保存先")
    p.set_defaults(func=cmd_genkey)

    p = sub.add_parser("sign-music", help="曲リストに署名する")
    p.add_argument("file")
    p.add_argument("--key")
    p.add_argument("--serial", type=int, help="通し番号 (省略すると、前の署名の番号 + 1)")
    p.set_defaults(func=cmd_sign_music)

    p = sub.add_parser("sign-release", help="リリースの zip に署名する")
    p.add_argument("file")
    p.add_argument("--tag", required=True, help="リリースのタグ (= pyproject.toml の version)")
    p.add_argument("--key")
    p.set_defaults(func=cmd_sign_release)

    p = sub.add_parser("verify", help="署名を確認する (公開鍵は src/trusted_keys.py)")
    p.add_argument("file")
    p.add_argument("--sig")
    p.set_defaults(func=cmd_verify)

    args = parser.parse_args()
    if args.command == "verify" and not TRUSTED_PUBLIC_KEYS:
        raise SystemExit("src/trusted_keys.py に公開鍵がありません")
    args.func(args)


if __name__ == "__main__":
    main()
