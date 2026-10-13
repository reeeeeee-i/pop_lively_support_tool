import logging
import os
import sys
import threading
from logging.handlers import RotatingFileHandler

# ログ保存ディレクトリの作成
LOG_DIR = "log"
os.makedirs(LOG_DIR, exist_ok=True)

# ログフォルダ全体の最大容量 (MB)。設定 (log_max_size_mb) で変更できる
DEFAULT_LOG_MAX_SIZE_MB = 20
LOG_MAX_SIZE_MB_RANGE = (1, 1000)
_BACKUP_COUNT = 3
# 1 ファイルあたりの上限の下限。容量を小さくしすぎてもローテーションが頻発しないようにする
_MIN_FILE_BYTES = 16 * 1024

_max_total_bytes = DEFAULT_LOG_MAX_SIZE_MB * 1024 * 1024
_handlers: list["_CappedRotatingFileHandler"] = []
# ローテーションと古いログの削除は、複数のハンドラーで同時に行わない
_rotate_lock = threading.RLock()


class _CappedRotatingFileHandler(RotatingFileHandler):
    """ローテーションのたびに、ログフォルダ全体が最大容量に収まるよう古いログを削除する。"""

    def doRollover(self):
        with _rotate_lock:
            super().doRollover()
            _prune_old_logs()


def _is_log_file(name: str) -> bool:
    """ログファイル (xxx.log) か、そのバックアップ (xxx.log.1 など) か。"""
    stem, ext = os.path.splitext(name)
    return ext == ".log" or (ext[1:].isdigit() and stem.endswith(".log"))


def _update_file_limits() -> None:
    """最大容量を書き込み中のファイル数で分け、1 ファイルあたりの上限を決める。

    書き込み中のファイルは削除できないため、その合計を最大容量の半分までに抑え、
    残りをバックアップに充てる。
    """
    if not _handlers:
        return
    max_bytes = max(_MIN_FILE_BYTES, _max_total_bytes // (2 * len(_handlers)))
    for handler in _handlers:
        handler.maxBytes = max_bytes


def _prune_old_logs() -> None:
    """ログフォルダが最大容量を超えていたら、更新日時の古いファイルから削除する。

    書き込み中のファイルは削除しない。次のローテーションまでに上限いっぱいまで
    増えるので、その分を先に見込んでおく。
    """
    with _rotate_lock:
        active = {os.path.abspath(handler.baseFilename): handler.maxBytes for handler in _handlers}
        total = sum(active.values())
        removable = []
        try:
            for entry in os.scandir(LOG_DIR):
                if not entry.is_file() or not _is_log_file(entry.name):
                    continue
                stat = entry.stat()
                reserved = active.get(os.path.abspath(entry.path))
                if reserved is None:
                    total += stat.st_size
                    removable.append((stat.st_mtime, stat.st_size, entry.path))
                else:
                    # 上限を下げた直後は、次のローテーションまで上限より大きいことがある
                    total += max(0, stat.st_size - reserved)
        except OSError:
            return
        for _, size, path in sorted(removable):
            if total <= _max_total_bytes:
                break
            try:
                os.remove(path)
                total -= size
            except OSError:
                pass


def set_log_max_size_mb(size_mb: int) -> None:
    """ログフォルダ全体の最大容量 (MB) を変更し、超えている分の古いログを削除する。"""
    global _max_total_bytes
    low, high = LOG_MAX_SIZE_MB_RANGE
    with _rotate_lock:
        _max_total_bytes = max(low, min(high, size_mb)) * 1024 * 1024
        _update_file_limits()
        _prune_old_logs()


def get_logger(name=None):
    '''
    モジュール名に基づいてloggerを取得

    Args:
        name: モジュール名（通常は __name__ を渡す）
              Noneの場合はメインスクリプト名を使用

    Returns:
        logging.Logger: 指定されたモジュール用のlogger
    '''
    if name is None:
        main_file = os.path.splitext(os.path.basename(sys.argv[0]))[0]
        log_file = os.path.join(LOG_DIR, f"{main_file}.log")
        logger_name = "app_logger"
    else:
        module_name = name.split('.')[-1] if '.' in name else name
        log_file = os.path.join(LOG_DIR, f"{module_name}.log")
        logger_name = name

    logger = logging.getLogger(logger_name)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    if not logger.handlers:
        formatter = logging.Formatter(
            '[%(asctime)s] [%(levelname)s] %(filename)s:%(lineno)d:%(funcName)s - %(message)s'
        )
        file_handler = _CappedRotatingFileHandler(
            log_file, backupCount=_BACKUP_COUNT, encoding='utf-8'
        )
        file_handler.setFormatter(formatter)
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
        logger.addHandler(stream_handler)
        with _rotate_lock:
            _handlers.append(file_handler)
            _update_file_limits()

    return logger

# デフォルトインスタンス（後方互換性のため）
logger = get_logger()
