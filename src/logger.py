import logging
import os
import sys
from logging.handlers import RotatingFileHandler

# ログ保存ディレクトリの作成
LOG_DIR = "log"
os.makedirs(LOG_DIR, exist_ok=True)

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
        file_handler = RotatingFileHandler(
            log_file, maxBytes=2 * 1024 * 1024, backupCount=3, encoding='utf-8'
        )
        file_handler.setFormatter(formatter)
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
        logger.addHandler(stream_handler)

    return logger

# デフォルトインスタンス（後方互換性のため）
logger = get_logger()
