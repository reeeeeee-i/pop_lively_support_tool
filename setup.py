"""pop_lively_support_tool - cx_Freeze ビルド設定
G:\\Download\\inf_daken_counter の構成をベースに作成
"""

import os
from pathlib import Path
import sys
from cx_Freeze import Executable, setup

# PySide6のパスを取得
include_files = []
try:
    import PySide6

    pyside6_path = Path(PySide6.__file__).parent

    # プラグインディレクトリ（platforms, stylesなど）
    plugins_dir = pyside6_path / "plugins"
    if plugins_dir.exists():
        include_files.append((str(plugins_dir), "lib/PySide6/plugins"))

    # Qt翻訳ファイル
    translations_dir = pyside6_path / "translations"
    if translations_dir.exists():
        include_files.append((str(translations_dir), "lib/PySide6/translations"))

    # Qt.conf（プラグインパスを指定）
    qt_conf_content = """[Paths]
Prefix = .
Binaries = .
Plugins = lib/PySide6/plugins
"""
    with open("qt.conf", "w", encoding="utf-8") as f:
        f.write(qt_conf_content)
    include_files.append(("qt.conf", "qt.conf"))

except ImportError:
    print("Warning: PySide6 not found. Build may not work correctly.")

# 設定ファイル・関連ファイル
if os.path.exists("config.json"):
    include_files.append(("config.json", "config.json"))

# 曲リスト (初回起動時に曲テーブルへ取り込む。無いと曲の特定・曲の選択ができない)
if os.path.exists("popn_music_list.json"):
    include_files.append(("popn_music_list.json", "popn_music_list.json"))

if os.path.exists("README.md"):
    include_files.append(("README.md", "README.md"))

# アイコンファイル
icon_path = None
if os.path.exists("src/icon.ico"):
    include_files.append(("src/icon.ico", "src/icon.ico"))
    icon_path = "src/icon.ico"

# ビルドオプション
build_exe_options = {
    # 含めるパッケージ
    "packages": [
        "PySide6.QtCore",
        "PySide6.QtGui",
        "PySide6.QtWidgets",
        "obsws_python",
        "websocket",
        "PIL",
        "numpy",
        "imagehash",
        "json",
        "traceback",
        "logging",
        "logging.handlers",
        "hashlib",
        "math",
        "datetime",
        "time",
        "threading",
        "os",
        "sys",
        "enum",
        "html",
        "csv",
        "ctypes",
        "ctypes.wintypes",
        "dxcam",
        "comtypes",
        "winrt",
        "asyncio",
        "concurrent.futures",
    ],
    # 含めるモジュール
    "includes": [
        "src",
        "src.classes",
        "src.config",
        "src.config_dialog",
        "src.cpu_affinity",
        "src.define",
        "src.direct_window_capture",
        "src.dxcam_window_capture",
        "src.funcs",
        "src.logger",
        "src.obs_dialog",
        "src.obs_websocket_manager",
        "src.screen_reader",
        "src.result_reader",
        "src.song_reader",
        "src.digit_templates",
        "src.judge_reader",
        "src.judge_templates",
        "src.hdr_monitor",
        "src.score_manager",
        "src.score_dialog",
        "src.ui_jp",
        "ctypes",
        "ctypes.wintypes",
        "ctypes.util",
        "PIL.ImageGrab",
    ],
    # 除外するパッケージ（ファイルサイズ削減）
    "excludes": [
        "matplotlib",
        "pandas",
        "scipy",
        "test",
        "unittest",
        "email",
        "distutils",
        "setuptools",
        "pip",
        # PySide6の不要なモジュール
        "PySide6.QtNetwork",
        "PySide6.QtOpenGL",
        "PySide6.QtPrintSupport",
        "PySide6.QtQml",
        "PySide6.QtQuick",
        "PySide6.QtSql",
        "PySide6.QtTest",
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineWidgets",
        "PySide6.Qt3DCore",
        "PySide6.Qt3DRender",
        "PySide6.QtCharts",
        "PySide6.QtDataVisualization",
        "obsws_python.requests",
    ],
    "include_files": include_files,
    "include_msvcr": True,
    "zip_include_packages": [],
    "zip_exclude_packages": ["obsws_python"],
    "optimize": 2,
    "build_exe": "dist/pop_lively_support_tool",
}

# 実行形式ベース
base = None
if sys.platform == "win32":
    base = "Win32GUI"

executables = [
    Executable(
        script="pop_lively_support_tool.pyw",
        base=base,
        target_name="pop_lively_support_tool.exe",
        icon=icon_path,
        shortcut_name="pop_lively_support_tool",
        shortcut_dir="DesktopFolder",
    )
]

setup(
    name="pop_lively_support_tool",
    version="1.0.0",
    description="pop_lively_support_tool",
    options={
        "build_exe": build_exe_options,
    },
    executables=executables,
)
