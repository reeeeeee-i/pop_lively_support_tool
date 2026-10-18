"""アプリの自動更新 (GitHub Releases) — GUI に依存しない処理

流れ: 最新リリースの確認と署名の検証 → zip のダウンロードとハッシュの照合 → 展開 →
更新用のバッチを起動してアプリを終了 → バッチがアプリの終了を待って上書きコピーし、再起動する。

安全のための仕組み:
  - リリースには、zip と、その署名ファイル (<zip名>.sig、Ed25519) が必要。署名は開発者の秘密鍵でしか作れず、
    アプリは src/trusted_keys.py の公開鍵で検証する。署名が無い・不正・信頼しない鍵のリリースは、
    GitHub 上のものでも使わない (GitHub のアカウントやリリースが侵害されても、偽の更新は配れない)
  - 署名には、zip の SHA-256・サイズ・ファイル名・バージョンが含まれる。ダウンロードした zip は
    署名どおりの内容でなければ破棄する。署名済みの古い版を新しい版として配ることもできない
  - 通信は https のみ。リダイレクトも https かつ GitHub のホストだけ (src/secure_http.py)
  - 展開では、展開先の外への書き出し・不正なファイル名・展開後サイズの過大を拒否する
  - 設定・スコア・ログなど、利用者のデータは上書きしない (_KEEP_FILES / _KEEP_DIRS)
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass
from typing import Callable

from src import secure_http, signing
from src.app_version import APP_NAME, EXE_NAME, app_dir, parse_version
from src.logger import get_logger
from src.secure_http import FetchError, GITHUB_HOST_SUFFIXES
from src.signing import SignatureError

logger = get_logger(__name__)

REPO = "reeeeeee-i/pop_lively_support_tool"
RELEASES_PAGE = f"https://github.com/{REPO}/releases"
_LATEST_API = f"https://api.github.com/repos/{REPO}/releases/latest"
_DOWNLOAD_PREFIX = f"https://github.com/{REPO}/releases/download/"
_API_MAX_BYTES = 2 * 1024 * 1024
_ZIP_MAX_BYTES = 1024 * 1024 * 1024          # 配布版の zip は約 200MB
_EXTRACT_MAX_BYTES = 3 * 1024 * 1024 * 1024  # 展開後の合計サイズの上限
_EXTRACT_MAX_FILES = 50000
STAGING_DIR = "_update"

# 更新で上書きしない利用者のデータ
_KEEP_FILES = (
    "config.json", "popn.db", "popn.db-wal", "popn.db-shm", "popn_score.csv", "popn_session_log.csv", "update.log",
)
_KEEP_DIRS = ("log", "result_screenshots", "diagnostics", "backup", "out", STAGING_DIR)
# バッチに埋め込むパスに使えない文字 (% は変数展開、" は引用の破れ、改行は命令の混入になる)
_BATCH_UNSAFE = re.compile(r'[%"\r\n\x00!^&|<>]')


class UpdateError(Exception):
    """更新できないときのエラー (メッセージは利用者向け)"""


@dataclass
class ReleaseInfo:
    tag: str
    notes: str
    page_url: str
    asset_name: str
    asset_url: str
    size: int         # 署名されたサイズ
    sha256: str       # 署名された SHA-256
    key_id: str       # 署名した鍵


# ----------------------------------------------------------------------
# 最新リリースの確認 (署名つき)
# ----------------------------------------------------------------------

def _asset_url(asset: dict) -> str:
    url = str(asset.get("browser_download_url", ""))
    if not url.startswith(_DOWNLOAD_PREFIX):
        raise UpdateError("リリースの添付ファイルの URL が、このツールのリリースのものではありません")
    return url


def parse_release(data: dict) -> tuple[str, str, str, str, str, str]:
    """GitHub API の releases/latest の応答から (タグ, 更新内容, ページ URL, zip 名, zip URL, 署名 URL) を取り出す。"""
    assets = {str(a.get("name", "")): a for a in data.get("assets", []) if isinstance(a, dict)}
    for name, asset in assets.items():
        if name.startswith(APP_NAME) and name.lower().endswith(".zip"):
            sig_asset = assets.get(name + signing.SIGNATURE_SUFFIX)
            if sig_asset is None:
                raise UpdateError("最新のリリースに署名ファイル (.sig) がないため、更新を中止しました")
            return (
                str(data.get("tag_name", "")), str(data.get("body") or ""),
                str(data.get("html_url") or RELEASES_PAGE),
                name, _asset_url(asset), _asset_url(sig_asset),
            )
    raise UpdateError("最新のリリースに、更新用の zip ファイルがありません")


def fetch_latest_release() -> ReleaseInfo:
    """GitHub の最新リリースを取得し、署名を検証して返す。検証に通らなければ UpdateError。"""
    try:
        raw = secure_http.fetch_bytes(
            _LATEST_API, _API_MAX_BYTES, GITHUB_HOST_SUFFIXES, "リリース情報", accept="application/vnd.github+json"
        )
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("形式が正しくありません")
        tag, notes, page_url, name, zip_url, sig_url = parse_release(data)
        sig = secure_http.fetch_bytes(sig_url, signing.MAX_SIGNATURE_BYTES, GITHUB_HOST_SUFFIXES, "署名ファイル")
    except FetchError as e:
        raise UpdateError(f"最新バージョンを確認できませんでした: {e}") from e
    except ValueError as e:
        raise UpdateError(f"最新バージョンの情報を読めませんでした: {e}") from e

    try:
        info = signing.verify_signature(sig, kind=signing.KIND_RELEASE, name=name)
    except SignatureError as e:
        raise UpdateError(f"署名の検証に失敗したため、更新を中止しました: {e}") from e
    # 署名されたバージョンと、タグが一致すること (古い署名済みの zip を新しいタグで配ることを防ぐ)
    signed_version, tag_version = parse_version(info.version), parse_version(tag)
    if signed_version is None or signed_version != tag_version:
        raise UpdateError("署名されたバージョンが、リリースのタグと一致しないため、更新を中止しました")
    if not 0 < info.size <= _ZIP_MAX_BYTES:
        raise UpdateError("署名されたファイルサイズが正しくないため、更新を中止しました")
    return ReleaseInfo(tag, notes, page_url, name, zip_url, info.size, info.sha256, info.key_id)


# ----------------------------------------------------------------------
# ダウンロード・展開
# ----------------------------------------------------------------------

def download(
    url: str, dest: str, expected_size: int, expected_sha256: str,
    progress: Callable[[int, int], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> None:
    """url を dest にダウンロードし、署名で保証されたサイズと SHA-256 に一致するか検証する。

    一致しなければ、ダウンロードしたファイルを削除して UpdateError にする。
    """
    if not url.startswith(_DOWNLOAD_PREFIX):
        raise UpdateError("ダウンロード先がこのツールのリリースではないため、中止しました")
    hasher = hashlib.sha256()
    try:
        done = secure_http.stream_to_file(
            url, dest, expected_size, hasher, GITHUB_HOST_SUFFIXES, progress, cancelled
        )
        if done != expected_size:
            raise UpdateError(f"ダウンロードしたサイズが署名と一致しません ({done} / {expected_size} バイト)")
        if hasher.hexdigest() != expected_sha256.lower():
            raise UpdateError(
                "ダウンロードしたファイルの SHA-256 が署名と一致しません。ファイルが改ざんされている可能性があります"
            )
    except FetchError as e:
        _remove(dest)
        raise UpdateError(f"ダウンロードできませんでした: {e}") from e
    except UpdateError:
        _remove(dest)
        raise


def _remove(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


def _check_member_name(name: str) -> None:
    """zip 内のファイル名が安全か。絶対パス・.. ・ドライブ指定・NTFS の代替データストリーム (:) を拒否する。"""
    normalized = name.replace("\\", "/")
    parts = [p for p in normalized.split("/") if p]
    if (
        not parts or normalized.startswith("/") or any(p == ".." for p in parts)
        or any(":" in p for p in parts) or "\x00" in name
    ):
        raise UpdateError(f"zip に不正なパスが含まれています: {name}")


def extract(zip_path: str, dest: str, progress: Callable[[int, int], None] | None = None) -> None:
    """zip を dest に展開する。展開先の外への書き出し・不正なパス・過大なサイズ・シンボリックリンクを拒否する。"""
    root = os.path.realpath(dest)
    try:
        with zipfile.ZipFile(zip_path) as zf:
            members = zf.infolist()
            if len(members) > _EXTRACT_MAX_FILES:
                raise UpdateError("zip のファイル数が多すぎます")
            if sum(m.file_size for m in members) > _EXTRACT_MAX_BYTES:
                raise UpdateError("zip の展開後のサイズが大きすぎます")
            for i, member in enumerate(members, 1):
                _check_member_name(member.filename)
                if stat.S_ISLNK(member.external_attr >> 16):
                    raise UpdateError(f"zip にシンボリックリンクが含まれています: {member.filename}")
                target = os.path.realpath(os.path.join(dest, member.filename))
                if target != root and not target.startswith(root + os.sep):
                    raise UpdateError(f"zip に不正なパスが含まれています: {member.filename}")
                zf.extract(member, dest)
                if progress:
                    progress(i, len(members))
    except zipfile.BadZipFile as e:
        raise UpdateError("ダウンロードしたファイルが zip として読めません") from e


def find_app_root(folder: str) -> str:
    """展開したフォルダの中で、実行ファイル (exe) があるフォルダを返す (zip 直下か、1 階層下)。"""
    for current, dirs, files in os.walk(folder):
        if EXE_NAME in files:
            return current
        if os.path.relpath(current, folder).count(os.sep) >= 1:
            dirs[:] = []
    raise UpdateError(f"更新ファイルに {EXE_NAME} が見つかりません")


# ----------------------------------------------------------------------
# 適用 (アプリ終了後に上書きコピーして再起動するバッチ)
# ----------------------------------------------------------------------

def _batch_path(path: str) -> str:
    """バッチに埋め込むパス。変数展開や命令の混入につながる文字を含むものは拒否する。"""
    if _BATCH_UNSAFE.search(path):
        raise UpdateError(
            f"フォルダのパスに更新で使えない文字が含まれているため、自動更新できません: {path}\n"
            "リリースページから手動で更新してください"
        )
    return path


def build_update_script(pid: int, source: str, target: str, stage: str) -> str:
    """更新用バッチの内容。アプリ (pid) の終了を待ち、利用者のデータを除いて上書きコピーし、再起動する。"""
    keep_files = " ".join(f'"{name}"' for name in _KEEP_FILES)
    keep_dirs = " ".join(f'"{name}"' for name in _KEEP_DIRS)
    source, target, stage = _batch_path(source), _batch_path(target), _batch_path(stage)
    log = os.path.join(target, "log", "update.log")
    return "\r\n".join([
        "@echo off",
        "chcp 65001 >nul",
        f'set "PID={int(pid)}"',
        f'set "SRC={source}"',
        f'set "DST={target}"',
        f'set "STAGE={stage}"',
        f'set "LOG={log}"',
        'if not exist "%DST%\\log" mkdir "%DST%\\log"',
        'echo [%date% %time%] update start >> "%LOG%"',
        ":wait",
        'tasklist /FI "PID eq %PID%" /NH 2>nul | find "%PID%" >nul',
        "if not errorlevel 1 (",
        "    ping -n 2 127.0.0.1 >nul",
        "    goto wait",
        ")",
        f'robocopy "%SRC%" "%DST%" /E /R:15 /W:2 /NFL /NDL /NJH /NJS /NP /XF {keep_files} /XD {keep_dirs} >> "%LOG%" 2>&1',
        "set RC=%ERRORLEVEL%",
        'echo [%date% %time%] robocopy exit code %RC% >> "%LOG%"',
        # robocopy は 8 以上が失敗。失敗しても、いま入っているバージョンを起動し直す
        f'start "" "%DST%\\{EXE_NAME}"',
        'rmdir /s /q "%STAGE%" >nul 2>&1',
        '(goto) 2>nul & del "%~f0"',
        "",
    ])


def launch_update_script(pid: int, source: str, target: str, stage: str) -> None:
    """更新用バッチを書き出して、アプリとは切り離して起動する。"""
    content = build_update_script(pid, source, target, stage)   # パスの検証も兼ねる
    # バッチ自身が作業フォルダ (終了時に削除する) の中にあると消せないので、一時フォルダに置く
    script = os.path.join(tempfile.gettempdir(), f"{APP_NAME}_apply_update.bat")
    with open(script, "w", encoding="utf-8", newline="") as f:
        f.write(content)
    # 見えないコンソールで起動する (DETACHED_PROCESS だとバッチ内のコマンドが動かないことがある)。
    # アプリが終了しても、子プロセスは残って処理を続ける
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen(
        ["cmd", "/c", script], creationflags=flags, close_fds=True,
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    logger.info("更新用バッチを起動しました: %s", script)


def prepare_staging() -> str:
    """更新用の作業フォルダ (アプリのフォルダ内) を空の状態で用意して返す。書き込めなければ UpdateError。"""
    stage = os.path.join(app_dir(), STAGING_DIR)
    try:
        shutil.rmtree(stage, ignore_errors=True)
        os.makedirs(stage)
    except OSError as e:
        raise UpdateError(
            f"アプリのフォルダに書き込めないため、自動更新できません ({e})。\n"
            "リリースページから手動で更新してください"
        ) from e
    return stage
