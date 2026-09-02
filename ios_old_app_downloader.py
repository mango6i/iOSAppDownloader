# -*- coding: utf-8 -*-
"""
iOS Old App Downloader v2.0

Tabs:
  1. Search   - iTunes Search API
  2. History  - local and Apple history sources
  3. Download - download queue and live log
  4. Packages - installed IPA management

Window frame is adapted from the desktop "IP Batch Converter" tool.
"""
import sys, os, json, time, subprocess, io, re, base64, shutil, threading, ctypes, socket, ssl, tempfile, atexit, html, unicodedata
import zipfile, plistlib, urllib.parse, urllib.request, urllib.error, uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from ctypes import windll

_QT_DLL_HANDLES = []
_QT_PRELOAD_HANDLES = []
if getattr(sys, "frozen", False) and os.name == "nt":
    _frozen_root = getattr(sys, "_MEIPASS", "")
    _qt_bin = os.path.join(_frozen_root, "PyQt6", "Qt6", "bin")
    if os.path.isdir(_frozen_root):
        _QT_DLL_HANDLES.append(os.add_dll_directory(_frozen_root))
    if os.path.isdir(_qt_bin):
        _QT_DLL_HANDLES.append(os.add_dll_directory(_qt_bin))
        os.environ["PATH"] = _qt_bin + os.pathsep + os.environ.get("PATH", "")
        for _qt_dll in ("Qt6Core.dll", "Qt6Gui.dll", "Qt6Widgets.dll"):
            try:
                _QT_PRELOAD_HANDLES.append(ctypes.WinDLL(os.path.join(_qt_bin, _qt_dll)))
            except Exception:
                pass

def _show_error(title, msg):
    try:
        windll.user32.MessageBoxW(0, msg, title, 0x10)
    except Exception:
        try:
            import tkinter.messagebox as mb
            mb.showerror(title, msg)
        except Exception:
            pass

try:
    import PyQt6
except Exception as _e:
    if getattr(sys, "frozen", False):
        _show_error(
            "启动失败",
            "程序自带的界面组件未能载入。\n\n"
            "最常见原因是杀毒软件（火绒 / 360 / 电脑管家 / Windows Defender 等）"
            "拦截了本程序的自解压过程，把运行组件隔离了。\n\n"
            "请按以下顺序处理：\n"
            "① 把本程序加入杀毒软件的白名单（信任列表），并恢复被隔离的文件；\n"
            "② 重新运行；若仍失败，把程序复制到另一个目录（如 D:\\Tools）再试；\n"
            "③ 也可以右键 → 「以管理员身份运行」。\n\n"
            "原始错误：%s" % _e)
    else:
        _show_error("依赖缺失",
                    "当前缺少 PyQt6 依赖。\n\n"
                    "你运行的是源码文件，请先安装依赖：\npip install PyQt6\n\n"
                    "如果你想要无需安装的版本，请使用打包好的 "
                    "iOSAppDownloader_v1.0.5.exe。\n\n原始错误：%s" % _e)
    sys.exit(1)

from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QLabel, QPushButton, QSystemTrayIcon, QMenu, QMessageBox,
                             QScrollArea, QFrame, QGridLayout, QColorDialog,
                             QProgressBar, QCheckBox, QDoubleSpinBox,
                             QLineEdit, QDialog, QComboBox, QListWidget, QListWidgetItem,
                             QListView, QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
                             QStackedWidget, QTabBar, QSizePolicy, QSpacerItem, QFileDialog)
from PyQt6.QtGui import (QColor, QLinearGradient, QRadialGradient, QConicalGradient,
                         QBrush, QPainter, QPainterPath, QFont, QIcon, QPixmap,
                         QAction, QPen, QImage, QDesktopServices)
from PyQt6.QtCore import (Qt, QPoint, QPointF, QRect, QTimer, pyqtSignal, QObject, QThread,
                         QUrl, QSize, QStandardPaths, QLocale)

# ─────────────────────────────────────────────
# ─────────────────────────────────────────────

# ─────────────────────────────────────────────
# ─────────────────────────────────────────────
if getattr(sys, "frozen", False):
    APP_DIR = os.path.dirname(os.path.abspath(sys.argv[0]))
    _MEIPASS = getattr(sys, "_MEIPASS", None)
else:
    APP_DIR = os.path.dirname(os.path.abspath(__file__))
    _MEIPASS = None

_LOCAL_DATA_ROOT = os.environ.get("LOCALAPPDATA") or os.path.join(APP_DIR, "data")
IPATOOL_SESSION_HOME = os.path.join(
    _LOCAL_DATA_ROOT, "iOSOldAppDownloader", "ipatool-rs-home")
IPATOOL_SEED_ROOT = (os.path.join(_MEIPASS, "engine_seed") if _MEIPASS else
                     os.path.join(APP_DIR, "ipatool", "engine_seed"))
IPATOOL_PROCESS_LOCK = threading.Lock()
_LOGIN_CHALLENGE_PROXY = None
_LOGIN_CHALLENGE_PROXY_LOCK = threading.Lock()
_ENGINE_HOME_LOCK = threading.Lock()
_ACTIVE_TOOL_WORKERS = set()
_DIAGNOSTIC_LOCK = threading.Lock()
_DIAGNOSTIC_PATH = os.path.join(
    _LOCAL_DATA_ROOT, "iOSOldAppDownloader", "last_runtime_error.log")
_ICON_CACHE = {}
_ICON_CACHE_LOCK = threading.Lock()
_ICON_CACHE_LIMIT = 256


def _diagnostic(event, detail=""):
    try:
        safe = re.sub(r"[\w.+-]+@[\w.-]+", "***", str(detail or ""))
        safe = re.sub(r'("(?:password|password_token)"\s*:\s*)"(?:[^"\\]|\\.)*"',
                      r'\1"***"', safe, flags=re.IGNORECASE)
        with _DIAGNOSTIC_LOCK:
            os.makedirs(os.path.dirname(_DIAGNOSTIC_PATH), exist_ok=True)
            if os.path.isfile(_DIAGNOSTIC_PATH) and os.path.getsize(_DIAGNOSTIC_PATH) > 1048576:
                os.replace(_DIAGNOSTIC_PATH, _DIAGNOSTIC_PATH + ".old")
            with open(_DIAGNOSTIC_PATH, "a", encoding="utf-8") as fh:
                fh.write("%s | %s | %s\n" %
                         (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), event, safe[:2000]))
    except Exception:
        pass


def _unhandled_exception(exc_type, exc_value, exc_traceback):
    try:
        import traceback
        detail = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
    except Exception:
        detail = repr(exc_value)
    _diagnostic("unhandled_exception", detail)
    try:
        _show_error("软件运行错误", "程序遇到未处理的异常，已阻止闪退。\n\n%s" % str(exc_value))
    except Exception:
        pass


sys.excepthook = _unhandled_exception

def find_ipatool():
    """"""
    cands = []
    if _MEIPASS:
        cands.append(os.path.join(_MEIPASS, "ipatool.exe"))
    cands += [
        os.path.join(APP_DIR, "ipatool", "kosthi", "ipatool.exe"),
        os.path.join(APP_DIR, "kosthi", "ipatool.exe"),
        os.path.join(APP_DIR, "ipatool.exe"),
    ]
    for c in cands:
        if os.path.exists(c):
            return c
    return None

IPATOOL_PATH = find_ipatool()
def _default_download_dir():
    try:
        d = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DesktopLocation)
        if d and os.path.isdir(d):
            return d
    except Exception:
        pass
    return os.path.join(os.path.expanduser("~"), "Desktop")
IPAS_DIR = _default_download_dir()
os.makedirs(IPAS_DIR, exist_ok=True)

PROXY_MODE = "auto"
PROXY_CUSTOM = ""

KEYCHAIN_PASSPHRASE = "iOSOldAppDownloader2026"


def _ht(text):
    return html.escape(str(text or "")).replace("\n", "<br>")


def _normalize_2fa_code(value):
    normalized = unicodedata.normalize("NFKC", str(value or "").strip())
    return re.sub(r"[\s-]+", "", normalized)


# ─────────────────────────────────────────────
# 语言设置
# 修改中文/英文界面文案时，优先在下面的 TRANSLATIONS 中修改；
# 首页“请先登录”弹窗的完整内容在 startup_login_message() 中修改。
# ─────────────────────────────────────────────
LANGUAGE_MODE = "auto"  # auto: 跟随 Windows 系统语言；zh: 中文；en: English
STARTUP_REPO_URL = "https://github.com/mango6i/iOSAppDownloader"
APP_VERSION = "1.0.5"

TRANSLATIONS = {
    "zh": {
        "window_title": "iOS旧版应用下载 v%s" % APP_VERSION,
        "app_title": "iOS 旧版应用下载",
        "tray_tip": "iOS旧版应用下载",
        "show_window": "显示窗口",
        "exit": "退出",
        "not_logged": "未登录",
        "checking": "检测中...",
        "logged_in_prefix": "已登录：",
        "settings_tip": "设置 / 登录 Apple ID",
        "minimize": "最小化",
        "close": "关闭",
        "tab_search": "APP搜索",
        "tab_history": "历史版本",
        "tab_download": "下载应用",
        "tab_install": "安装包管理",
        "settings_title": "设置 / 登录 Apple ID",
        "password_label": "密码:",
        "backend_label": "登录后端:",
        "code_label": "验证码:",
        "email_placeholder": "你的 Apple ID 邮箱",
        "password_placeholder": "Apple ID 密码",
        "code_placeholder": "6 位验证码",
        "submit_code": "提交验证码",
        "login": "登录 / 重新登录",
        "logout": "注销登录",
        "logging_in": "登录中...",
        "confirm_login": "确认登录状态...",
        "download_dir": "下载目录:",
        "open": "打开",
        "change": "更改",
        "proxy": "代理:",
        "proxy_auto": "跟随系统",
        "proxy_direct": "直连（ipatool-rs）",
        "proxy_custom": "自定义",
        "custom_proxy_placeholder": "自定义代理地址，如 http://127.0.0.1:7890",
        "network_diag": "网络诊断:",
        "start_diag": "开始诊断",
        "diagnosing": "诊断中…",
        "diag_hint": "检测当前网络能否通过 Apple 登录认证",
        "done": "完成",
        "language": "界面语言:",
        "software_version": "软件版本：v%s" % APP_VERSION,
        "language_auto": "跟随系统（自动）",
        "language_zh": "简体中文",
        "language_en": "English",
        "search_placeholder": "输入应用名称 / 关键词",
        "region_cn": "中国区",
        "region_hk": "中国香港",
        "region_mo": "中国澳门",
        "region_tw": "中国台湾",
        "region_us": "美区",
        "region_jp": "日区",
        "region_gb": "英国",
        "region_kr": "韩国",
        "region_sg": "新加坡",
        "show_label": "显示:",
        "limit_prefix": "前",
        "search": "搜索",
        "search_flow": "流程：登录 Apple ID（右上角⚙）→ 搜索应用 → 双击进入历史版本 → 双击版本号直接下载。右键可前往 App Store / 复制链接。",
        "startup_title": "请先登录",
        "startup_message": "使用前请先登录 Apple ID。<br><br>"
                          "点击右上角「⚙ 设置」→ 填写 Apple ID 和 Apple ID 密码 → 点「登录 / 重新登录」。<br>"
                          "若账号开启双重认证，会直接在设置窗口内输入 6 位验证码，不会跳转到其他窗口。<br><br>"
                          "登录成功后即可：搜索应用 → 选择历史版本 → 直接下载旧版 IPA。<br><br>",
        "open_source_notice": "本软件以开源并且免费，切勿上当受骗！！！",
        "open_source_link": "开源地址",
        "status_loading": "正在读取登录状态...",
        "status_logged": "当前状态：已登录<br>账号：",
        "status_logged_out": "当前状态：未登录<br>填写 Apple ID 和密码后点「登录 / 重新登录」，若开启双重认证，会在下方输入 6 位验证码。",
        "confirm_exit_title": "确认退出",
        "confirm_exit_message": "确定要退出程序吗？",
        "ok": "确定",
        "cancel": "取消",
        "official_versions": "官方版本列表",
        "login_free_lookup": "免登录查询",
        "select": "选择",
        "version": "版本号",
        "version_id": "版本ID",
        "size": "大小",
        "updated": "更新日期",
        "name": "名称",
        "downloaded_total": "已下载 / 总大小",
        "speed": "速度",
        "progress": "进度",
        "time_remaining": "用时 / 剩余",
        "actions": "操作",
        "account_prefix": "当前账号：",
        "fill_email_title": "提示",
        "fill_email_message": "请填写 Apple ID 邮箱。",
        "fill_password_message": "请填写 Apple ID 密码。",
        "component_error_title": "软件组件异常",
        "component_error_message": "登录组件缺失，当前程序可能不完整。\n请重新下载完整的软件。",
        "login_reading": "正在读取登录状态...",
        "login_code_status": "正在验证双重认证码...<br>请稍候。",
        "login_start_status": "正在登录...<br>正在连接 Apple 服务器，请稍候。",
        "need_2fa_title": "需要双重认证",
        "need_2fa_message": "Apple 正在尝试向你的受信任设备发送验证码。\n如果手机没有弹出通知，请在手机上手动获取 6 位验证码，然后点“提交验证码”。",
        "twofa_status_html": "<p style='margin:0 0 4px 0'><b>🔐 需要双重认证</b></p><p style='margin:0'>请查看受信任设备上的 Apple 通知；若没有弹出，请在手机上手动获取 6 位验证码，再在下方输入。</p>",
        "login_success_title": "登录成功",
        "login_success_message": "Apple ID 登录成功，账号状态已经确认。",
        "logout_progress": "正在注销...",
        "logged_out_title": "已注销",
        "logged_out_message": "已退出登录。",
        "download_signin_title": "尚未登录",
        "download_signin_message": "下载前需要先登录 Apple ID。\n\n请点击右上角“设置”按钮，填写 Apple ID 和密码完成登录。若账号开启双重认证，会在设置窗口内输入 6 位验证码。",
        "code_invalid": "请输入完整的 6 位数字验证码。",
        "password_expired": "密码已过期，请重新输入密码后点登录。",
        "search_empty_title": "提示",
        "search_empty_message": "请输入要搜索的应用名称！",
        "region_notice_title": "区域账号提示",
        "region_notice_message": "你选择了%s。\n\n免登录查询可以继续使用；如果要加载官方版本列表或下载，请确保登录的 Apple ID 拥有该区域 App Store 账号或购买权限。\n\n没有对应区域账号时，可能无法获取版本或下载 IPA。",
        "download_queue_hint": "下载队列（任务加入后自动开始；最多同时下载 10 个）：",
        "start_all": "开始 / 继续全部",
        "clear_finished": "清理已结束",
        "waiting_download": "等待下载",
        "download_status_queued": "等待下载",
        "download_status_downloading": "下载中",
        "download_status_paused": "已暂停",
        "download_status_completed": "已完成",
        "download_status_failed": "下载失败",
        "download_status_cancelled": "已取消",
        "task_open": "打开",
        "task_resume": "继续",
        "task_retry": "重试",
        "task_pause": "暂停",
        "task_remove": "删除",
        "searching": "搜索中：%s（%s，前 %d 个）...",
        "search_results_hint": "找到 %d 个结果。双击任意应用进入「历史版本」，选择版本后即可直接下载旧版。",
        "search_failed": "搜索失败",
        "open_store": "前往 App Store",
        "copy_link": "复制链接",
        "find_versions_local": "查找版本 ID（免登录）",
        "copied_title": "已复制",
        "copied_message": "App Store 链接已复制到剪贴板。",
        "no_rating": "暂无评分",
        "price": "价格 %s",
        "free": "免费",
        "version_value": "版本 %s",
        "not_available": "暂未获取",
        "developer": "开发者 %s",
        "bundle": "包名 %s",
        "category": "分类 %s  |  ",
        "no_app_selected": "尚未选择应用。请到「APP搜索」中双击任意应用。",
        "history_mode_label": "查找版本 ID 模式:",
        "load_history": "加载历史版本",
        "select_all": "全选",
        "invert": "反选",
        "download_selected": "下载选中版本",
        "cancel_select_all": "取消全选",
        "choose_app_title": "提示",
        "choose_app_message": "请先到「APP搜索」中双击选择一个应用。",
        "current_app": "当前应用：%s  (包名 %s  |  App ID %s)",
        "history_count": "%s  共 %d 个历史版本（勾选或双击行即可下载）。",
        "history_failed": "获取历史版本失败",
        "load_failed": "获取失败",
        "fetch_on_download": "下载时获取",
        "reading_size": "读取中",
        "overall_progress": "总进度 %d%%（已完成 %d / %d）",
        "active_waiting": "正在下载 %d 个，等待 %d 个",
        "recent_complete": "最近一个下载任务已完成",
        "download_failed_hint": "有下载任务失败，请点“重试”",
        "download_closed": "下载窗口已关闭",
        "empty_queue_title": "提示",
        "empty_queue_message": "下载队列为空，请到「历史版本」勾选或双击要下载的版本。",
        "genuine_suffix": "（正版）",
        "copy_version_id": "复制版本 ID",
        "export_version_ids": "导出全部版本 ID 到剪贴板",
        "version_id_copied": "版本 ID %s 已复制。",
        "version_ids_copied": "%d 条版本 ID 已复制到剪贴板。",
        "install_header": "已下载的安装包（目录: %s）：",
        "open_folder": "打开目录",
        "delete_selected": "删除选中",
        "clear_all": "清空全部",
        "refresh": "刷新",
        "install_tip": "安装到手机（真实有效）：\n1. 手机「卸载 App」（设置→通用→iPhone 储存空间→卸载，保留数据）；\n2. 电脑用 iMazing 3.4.0 或 爱思助手「导入安装」选择上方 IPA；\n3. 装完：设置→App Store→关闭「App 更新」，避免被覆盖回新版。\n操作：双击=打开所在文件夹；可多选后点「删除选中」；右键可「在文件夹中打开 / 删除 / 复制路径」。",
        "no_downloaded_ipa": "（暂无已下载的 IPA，先到「下载应用」执行下载）",
        "open_folder_context": "在文件夹中打开",
        "copy_path": "复制路径",
        "delete": "删除",
        "path_copied": "路径已复制：\n%s",
        "confirm_delete_one": "确定删除该 IPA？\n%s",
        "delete_failed": "删除失败",
        "select_packages": "请先选中要删除的安装包（可配合 Ctrl / Shift 多选）。",
        "confirm_delete_many": "确定删除以下 %d 个安装包？\n\n%s\n\n删除后无法恢复。",
        "partial_delete_failed": "部分删除失败",
        "deleted_packages": "已删除 %d 个安装包。",
        "nothing_to_clear": "当前没有可清空的安装包。",
        "confirm_clear": "确定清空全部 %d 个安装包？\n\n目录：%s\n\n删除后无法恢复。",
        "clear_result": "已清空，其中 %d 个删除失败。",
        "cleared_packages": "已清空 %d 个安装包。",
    },
    "en": {
        "window_title": "iOS Old App Downloader v%s" % APP_VERSION,
        "app_title": "iOS Old App Downloader",
        "tray_tip": "iOS Old App Downloader",
        "show_window": "Show window",
        "exit": "Exit",
        "not_logged": "Not signed in",
        "checking": "Checking...",
        "logged_in_prefix": "Signed in: ",
        "settings_tip": "Settings / Sign in Apple ID",
        "minimize": "Minimize",
        "close": "Close",
        "tab_search": "App Search",
        "tab_history": "Version History",
        "tab_download": "Downloads",
        "tab_install": "Package Manager",
        "settings_title": "Settings / Sign in Apple ID",
        "password_label": "Password:",
        "backend_label": "Sign-in engine:",
        "code_label": "Verification code:",
        "email_placeholder": "Your Apple ID email",
        "password_placeholder": "Apple ID password",
        "code_placeholder": "6-digit code",
        "submit_code": "Submit code",
        "login": "Sign in / Sign in again",
        "logout": "Sign out",
        "logging_in": "Signing in...",
        "confirm_login": "Confirming sign-in...",
        "download_dir": "Download folder:",
        "open": "Open",
        "change": "Change",
        "proxy": "Proxy:",
        "proxy_auto": "Use system setting",
        "proxy_direct": "Direct (ipatool-rs)",
        "proxy_custom": "Custom",
        "custom_proxy_placeholder": "Custom proxy, e.g. http://127.0.0.1:7890",
        "network_diag": "Network check:",
        "start_diag": "Run check",
        "diagnosing": "Checking...",
        "diag_hint": "Check whether this network can reach Apple sign-in services",
        "done": "Done",
        "language": "Language:",
        "software_version": "Version: v%s" % APP_VERSION,
        "language_auto": "Follow system (Auto)",
        "language_zh": "简体中文",
        "language_en": "English",
        "search_placeholder": "App name / keyword",
        "region_cn": "China Mainland",
        "region_hk": "Hong Kong",
        "region_mo": "Macau",
        "region_tw": "Taiwan",
        "region_us": "United States",
        "region_jp": "Japan",
        "region_gb": "United Kingdom",
        "region_kr": "South Korea",
        "region_sg": "Singapore",
        "show_label": "Show:",
        "limit_prefix": "First",
        "search": "Search",
        "search_flow": "Flow: sign in Apple ID (⚙ at top right) → search an app → double-click to open version history → double-click a version to download. Right-click to open the App Store page or copy its link.",
        "startup_title": "Sign in first",
        "startup_message": "Please sign in with an Apple ID before using the app.<br><br>"
                          "Click the top-right 「⚙ Settings」 button → enter your Apple ID and password → click 「Sign in / Sign in again」.<br>"
                          "If two-factor authentication is enabled, enter the 6-digit code directly in the Settings window; no other window will open.<br><br>"
                          "After signing in: search an app → choose Version History → download the old IPA.<br><br>",
        "open_source_notice": "This software is open-source and free. Beware of scams!!!",
        "open_source_link": "Open-source repository",
        "status_loading": "Reading sign-in status...",
        "status_logged": "Status: signed in<br>Account: ",
        "status_logged_out": "Status: not signed in<br>Enter your Apple ID and password, then click 「Sign in / Sign in again」. If two-factor authentication is enabled, enter the 6-digit code below.",
        "confirm_exit_title": "Confirm exit",
        "confirm_exit_message": "Are you sure you want to exit?",
        "ok": "OK",
        "cancel": "Cancel",
        "official_versions": "Official version list",
        "login_free_lookup": "Login-free lookup",
        "select": "Select",
        "version": "Version",
        "version_id": "Version ID",
        "size": "Size",
        "updated": "Updated",
        "name": "Name",
        "downloaded_total": "Downloaded / Total",
        "speed": "Speed",
        "progress": "Progress",
        "time_remaining": "Time / Remaining",
        "actions": "Actions",
        "account_prefix": "Account: ",
        "fill_email_title": "Notice",
        "fill_email_message": "Please enter your Apple ID email.",
        "fill_password_message": "Please enter your Apple ID password.",
        "component_error_title": "Component error",
        "component_error_message": "The sign-in component is missing or incomplete.\nPlease download the complete package again.",
        "login_reading": "Reading sign-in status...",
        "login_code_status": "Verifying the two-factor code...<br>Please wait.",
        "login_start_status": "Signing in...<br>Connecting to Apple services. Please wait.",
        "need_2fa_title": "Two-factor authentication required",
        "need_2fa_message": "Apple is trying to send a code to your trusted device.\nIf no notification appears, manually get a 6-digit code on your phone, then click Submit code.",
        "twofa_status_html": "<p style='margin:0 0 4px 0'><b>🔐 Two-factor authentication required</b></p><p style='margin:0'>Check your trusted Apple device; if no notification appears, manually get a 6-digit code and enter it below.</p>",
        "login_success_title": "Sign-in successful",
        "login_success_message": "Apple ID sign-in succeeded and the account status was confirmed.",
        "logout_progress": "Signing out...",
        "logged_out_title": "Signed out",
        "logged_out_message": "You have been signed out.",
        "download_signin_title": "Not signed in",
        "download_signin_message": "You must sign in with an Apple ID before downloading.\n\nClick Settings at the top right and enter your Apple ID and password. If two-factor authentication is enabled, enter the 6-digit code in the Settings window.",
        "code_invalid": "Please enter the complete 6-digit verification code.",
        "password_expired": "The password entry has expired. Enter it again and click Sign in.",
        "search_empty_title": "Notice",
        "search_empty_message": "Please enter an app name to search.",
        "region_notice_title": "Regional account notice",
        "region_notice_message": "You selected %s.\n\nLogin-free lookup can still be used. To load the official version list or download an IPA, the signed-in Apple ID must have an App Store account or purchase permission for this region.\n\nWithout a matching regional account, versions or downloads may be unavailable.",
        "download_queue_hint": "Download queue (tasks start automatically; up to 10 at once):",
        "start_all": "Start / resume all",
        "clear_finished": "Clear finished",
        "waiting_download": "Waiting",
        "download_status_queued": "Waiting",
        "download_status_downloading": "Downloading",
        "download_status_paused": "Paused",
        "download_status_completed": "Completed",
        "download_status_failed": "Failed",
        "download_status_cancelled": "Cancelled",
        "task_open": "Open",
        "task_resume": "Resume",
        "task_retry": "Retry",
        "task_pause": "Pause",
        "task_remove": "Remove",
        "searching": "Searching: %s (%s, first %d items)...",
        "search_results_hint": "Found %d result(s). Double-click an app to open Version History and download an older version.",
        "search_failed": "Search failed",
        "open_store": "Open App Store",
        "copy_link": "Copy link",
        "find_versions_local": "Find version IDs (login-free)",
        "copied_title": "Copied",
        "copied_message": "The App Store link was copied to the clipboard.",
        "no_rating": "No rating",
        "price": "Price %s",
        "free": "Free",
        "version_value": "Version %s",
        "not_available": "Not available",
        "developer": "Developer %s",
        "bundle": "Bundle %s",
        "category": "Category %s  |  ",
        "no_app_selected": "No app selected. Double-click an app in App Search first.",
        "history_mode_label": "Version ID source:",
        "load_history": "Load version history",
        "select_all": "Select all",
        "invert": "Invert",
        "download_selected": "Download selected",
        "cancel_select_all": "Clear selection",
        "choose_app_title": "Notice",
        "choose_app_message": "Please select an app by double-clicking it in App Search first.",
        "current_app": "Current app: %s  (Bundle %s  |  App ID %s)",
        "history_count": "%s  %d historical version(s) (check or double-click a row to download).",
        "history_failed": "Failed to get version history",
        "load_failed": "Load failed",
        "fetch_on_download": "Fetch on download",
        "reading_size": "Reading",
        "overall_progress": "Overall %d%% (%d / %d completed)",
        "active_waiting": "Downloading %d, waiting %d",
        "recent_complete": "The most recent download task completed",
        "download_failed_hint": "A download failed. Click Retry to try again.",
        "download_closed": "Download window closed",
        "empty_queue_title": "Notice",
        "empty_queue_message": "The download queue is empty. Select or double-click a version in Version History first.",
        "genuine_suffix": " (App Store)",
        "copy_version_id": "Copy version ID",
        "export_version_ids": "Export all version IDs to clipboard",
        "version_id_copied": "Version ID %s was copied.",
        "version_ids_copied": "%d version ID(s) were copied to the clipboard.",
        "install_header": "Downloaded packages (folder: %s):",
        "open_folder": "Open folder",
        "delete_selected": "Delete selected",
        "clear_all": "Clear all",
        "refresh": "Refresh",
        "install_tip": "Install on an iPhone:\n1. Offload the app on the phone (Settings → General → iPhone Storage → Offload App) to keep its data.\n2. On the computer, use iMazing 3.4.0 or another IPA installer to import the IPA above.\n3. After installation, turn off App Updates in Settings → App Store to avoid an automatic upgrade.\nDouble-click an item to open its folder; use multi-select and Delete selected; right-click for folder, delete, or copy-path actions.",
        "no_downloaded_ipa": "(No downloaded IPA yet. Start a download from Downloads.)",
        "open_folder_context": "Open containing folder",
        "copy_path": "Copy path",
        "delete": "Delete",
        "path_copied": "Path copied:\n%s",
        "confirm_delete_one": "Delete this IPA?\n%s",
        "delete_failed": "Delete failed",
        "select_packages": "Select at least one package first (Ctrl / Shift can select multiple).",
        "confirm_delete_many": "Delete these %d packages?\n\n%s\n\nThis cannot be undone.",
        "partial_delete_failed": "Some deletions failed",
        "deleted_packages": "%d package(s) deleted.",
        "nothing_to_clear": "There are no packages to clear.",
        "confirm_clear": "Clear all %d packages?\n\nFolder: %s\n\nThis cannot be undone.",
        "clear_result": "Cleared; %d package(s) could not be deleted.",
        "cleared_packages": "%d package(s) cleared.",
    },
}


def detect_system_language():
    """Use the Windows/Qt system locale to choose Chinese or English."""
    try:
        locale_name = (QLocale.system().name() or "").lower()
        if locale_name.startswith("zh") or QLocale.system().language() == QLocale.Language.Chinese:
            return "zh"
    except Exception:
        pass
    return "en"


def current_language():
    return LANGUAGE_MODE if LANGUAGE_MODE in ("zh", "en") else detect_system_language()


def tr(key):
    lang = current_language()
    return TRANSLATIONS.get(lang, TRANSLATIONS["zh"]).get(key, key)


def localized(zh, en):
    """Return a short runtime message in the currently selected language."""
    return en if current_language() == "en" else zh


def region_name(code):
    return tr("region_" + str(code or "cn"))


def limit_name(number):
    return "%s %d %s" % (tr("limit_prefix"), number, "items" if current_language() == "en" else "个")


def startup_login_message():
    """Homepage sign-in dialog text; edit the two language entries above to change it."""
    return (tr("startup_message")
            + "<span style='font-size:16px;color:#d00000;font-weight:700;'>"
            + tr("open_source_notice") + "</span><br>"
            + "<a href='%s' style='font-size:16px;color:#1677ff;'>%s</a>"
            % (STARTUP_REPO_URL, tr("open_source_link")))

# ─────────────────────────────────────────────
# ─────────────────────────────────────────────
def get_config_path():
    return None

CONFIG_PATH = get_config_path()
BG_MODE = "dual"
BG_DIRECTION = "diagonal"
BG_EFFECTIVE_DIR = "diagonal"
BG_RANDOM_PARAMS = {}
BG_COLORS = [QColor(255,209,220), QColor(180,210,255), QColor(200,245,230), QColor(255,240,200)]
WINDOW_WIDTH = 1000
WINDOW_HEIGHT = 720

COMBO_STYLE = (
    "QComboBox{background:rgba(255,255,255,80);border:1px solid rgba(255,255,255,130);"
    "border-radius:8px;padding:6px 10px;font-size:13px;color:#222;min-width:90px;}"
    "QComboBox:hover{background:rgba(255,255,255,120);}"
    "QComboBox::drop-down{border:none;width:24px;background:transparent;}"
    "QComboBox::down-arrow{image:none;border-left:5px solid transparent;border-right:5px solid transparent;"
    "border-top:6px solid rgba(60,60,60,200);width:0px;height:0px;}"
    "QComboBox QAbstractItemView{background:#ffffff;border:none;border-radius:8px;"
    "padding:4px;outline:none;}"
    "QComboBox QAbstractItemView::item{min-height:28px;padding:6px 10px;"
    "border-radius:6px;color:#222;background:#ffffff;}"
    "QComboBox QAbstractItemView::item:selected{background:rgba(0,122,255,170);color:#fff;}"
    "QComboBox QAbstractItemView::item:hover{background:rgba(0,122,255,90);color:#222;}"
)


def style_combo_clean(combo):
    combo.setStyleSheet(COMBO_STYLE)
    combo.setView(QListView())
    combo.setMaxVisibleItems(10)
    combo.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    view = combo.view()
    if view:
        view.setStyleSheet("QListView{background:#ffffff;border:none;outline:none;padding:4px;}")
        view.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        w = view.window()
        if w:
            w.setWindowFlags(Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint |
                             Qt.WindowType.NoDropShadowWindowHint)
            w.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

def save_config():
    return

def load_config():
    return


APPLE_ID_SAVE = ""
COUNTRY_SAVE = "cn"

LOGIN_MODE = "ipatool"
LOGIN_MODES = (
    ("ipatool", "官方 Kosthi/ipatool-rs v0.1.8"),
)

# ─────────────────────────────────────────────
# ─────────────────────────────────────────────
def get_stops_for_mode(mode, colors):
    if mode == "single":
        return [colors[0]] if colors else [QColor(240, 240, 240)]
    elif mode == "dual":
        c0 = colors[0] if colors else QColor(240, 240, 240)
        c1 = colors[1] if len(colors) > 1 else c0
        return [c0, c1]
    else:
        c0 = colors[0] if len(colors) > 0 else QColor(255, 255, 255)
        c1 = colors[1] if len(colors) > 1 else c0
        c2 = colors[2] if len(colors) > 2 else c0
        c3 = colors[3] if len(colors) > 3 else c1
        return [c0, c1, c2, c3]

def apply_gradient_stops(gradient, mode, colors):
    stops = get_stops_for_mode(mode, colors)
    if mode == "single":
        gradient.setColorAt(0.0, stops[0])
    elif mode == "dual":
        gradient.setColorAt(0.0, stops[0]); gradient.setColorAt(1.0, stops[1])
    else:
        gradient.setColorAt(0.0, stops[0]); gradient.setColorAt(0.33, stops[1])
        gradient.setColorAt(0.66, stops[2]); gradient.setColorAt(1.0, stops[3])

def paint_background(painter, x, y, w, h, mode, colors, direction, params=None):
    if not colors:
        painter.fillRect(x, y, w, h, QBrush(QColor(240, 240, 240))); return
    if mode == "single":
        painter.fillRect(x, y, w, h, QBrush(colors[0])); return
    if direction == "diagonal":
        g = QLinearGradient(x, y, x + w, y + h); apply_gradient_stops(g, mode, colors)
        painter.fillRect(x, y, w, h, QBrush(g))
    elif direction == "reverse":
        g = QLinearGradient(x + w, y + h, x, y); apply_gradient_stops(g, mode, colors)
        painter.fillRect(x, y, w, h, QBrush(g))
    else:
        g = QLinearGradient(x, y, x + w, y + h); apply_gradient_stops(g, mode, colors)
        painter.fillRect(x, y, w, h, QBrush(g))

# ─────────────────────────────────────────────
# ─────────────────────────────────────────────
def _icon_file_candidates():
    paths = []
    if _MEIPASS:
        paths.append(os.path.join(_MEIPASS, "appstore.ico"))
    paths.append(os.path.join(APP_DIR, "appstore.ico"))
    paths.append(os.path.join(APP_DIR, "appstore.png"))
    return paths


def generate_app_icon(size=256):
    for path in _icon_file_candidates():
        try:
            if not os.path.isfile(path):
                continue
            icon = QIcon(path)
            if not icon.isNull():
                return icon
        except Exception:
            continue
    try:
        from PIL import Image, ImageDraw, ImageFont
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        try:
            font = ImageFont.truetype("seguiemj.ttf", int(size * 0.78))
        except Exception:
            font = ImageFont.load_default()
        emoji = "\U0001F4E5"
        bbox = draw.textbbox((0, 0), emoji, font=font)
        tw = bbox[2] - bbox[0]; th = bbox[3] - bbox[1]
        x = (size - tw) / 2 - bbox[0]; y = (size - th) / 2 - bbox[1]
        draw.text((x, y), emoji, font=font, embedded_color=True)
        buf = io.BytesIO(); img.save(buf, format="PNG"); buf.seek(0)
        pm = QPixmap(); pm.loadFromData(buf.read()); pm.setDevicePixelRatio(1.0)
        return QIcon(pm)
    except Exception:
        pm = QPixmap(64, 64); pm.fill(QColor(80, 120, 255))
        return QIcon(pm)

_app_icon_cache = None
def get_app_icon():
    global _app_icon_cache
    if _app_icon_cache is None:
        _app_icon_cache = generate_app_icon()
    return _app_icon_cache

# ─────────────────────────────────────────────
# ─────────────────────────────────────────────
class CustomToolTip(QWidget):
    def __init__(self, text, parent=None):
        super().__init__(parent, Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedHeight(24)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        lbl = QLabel(text)
        lbl.setStyleSheet("QLabel{color:#000;font-size:12px;background:transparent;}")
        layout.addWidget(lbl)
        self.opacity = 0.0
        self.setWindowOpacity(self.opacity)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._fade_in)
        self._timer.start(10)

    def _fade_in(self):
        self.opacity += 0.1
        if self.opacity >= 1.0:
            self.opacity = 1.0
            self._timer.stop()
        self.setWindowOpacity(self.opacity)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor(255, 255, 200, 220)))
        p.drawRoundedRect(self.rect(), 6, 6)


class ControlButton(QPushButton):
    def __init__(self, icon_text, tooltip_text, parent=None):
        super().__init__(icon_text, parent)
        self._tip_text = tooltip_text
        self._tip = None
        self.setFixedSize(40, 40)
        self.setStyleSheet("""
            QPushButton{background-color:rgba(255,255,255,51);color:rgba(0,0,0,179);
                       border-radius:20px;border:1px solid rgba(255,255,255,77);font-size:18px;font-weight:bold;}
            QPushButton:hover{background-color:rgba(255,255,255,77);}
        """)
        self.setMouseTracking(True)

    def enterEvent(self, event):
        if not self._tip:
            self._tip = CustomToolTip(self._tip_text)
            self._tip.adjustSize()
            rect = self.rect()
            global_pos = self.mapToGlobal(rect.center())
            self._tip.move(global_pos.x() - self._tip.width() // 2,
                          global_pos.y() + rect.height() // 2 + 6)
            self._tip.show()
        return super().enterEvent(event)

    def leaveEvent(self, event):
        if self._tip:
            self._tip.hide()
            self._tip.deleteLater()
            self._tip = None
        return super().leaveEvent(event)


class GradientFrame(QWidget):
    """"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background:transparent;border:none;")
        self.setMouseTracking(True)
        self._resize_active = False
        self._dragging = False
        self._drag_start = QPoint()
        self._last_cursor_edge = None

    def _get_main_window(self):
        w = self.window()
        return w if isinstance(w, TransparentMacWindow) else None

    def mousePressEvent(self, event):
        main = self._get_main_window()
        if main and event.button() == Qt.MouseButton.LeftButton:
            pos = self.mapTo(main, event.position().toPoint())
            edge = main._detect_edge(pos)
            if edge:
                self._resize_active = True
                main._resizing = True
                main._resize_edge = edge
                main._resize_start_pos = event.globalPosition().toPoint()
                main._resize_start_geom = main.geometry()
            else:
                self._dragging = True
                self._drag_start = event.globalPosition().toPoint()

    def mouseMoveEvent(self, event):
        main = self._get_main_window()
        if not main:
            return
        if self._resize_active and main._resizing:
            main._do_resize(event.globalPosition().toPoint())
        elif self._dragging:
            delta = event.globalPosition().toPoint() - self._drag_start
            main.move(main.pos() + delta)
            self._drag_start = event.globalPosition().toPoint()
        else:
            pos = self.mapTo(main, event.position().toPoint())
            m = main.RESIZE_MARGIN
            if pos.x() < m or pos.x() > main.width() - m or pos.y() < m or pos.y() > main.height() - m:
                edge = main._detect_edge(pos)
                if edge != self._last_cursor_edge:
                    self._last_cursor_edge = edge
                    main._apply_edge_cursor(edge)
            elif self._last_cursor_edge is not None:
                self._last_cursor_edge = None
                main.unsetCursor()

    def mouseReleaseEvent(self, event):
        main = self._get_main_window()
        if main and event.button() == Qt.MouseButton.LeftButton:
            if self._resize_active:
                self._resize_active = False
                main._resizing = False
                main._resize_edge = None
            self._dragging = False

    def leaveEvent(self, event):
        main = self._get_main_window()
        if main and not self._resize_active and not self._dragging:
            main.unsetCursor()
            self._last_cursor_edge = None

    def paintEvent(self, event):
        try:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
            painter.eraseRect(self.rect())
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
            path = QPainterPath()
            r = self.rect()
            path.addRoundedRect(r.x(), r.y(), r.width(), r.height(), 30, 30)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setClipPath(path)
            paint_background(painter, r.x(), r.y(), r.width(), r.height(),
                             BG_MODE, BG_COLORS, BG_EFFECTIVE_DIR, BG_RANDOM_PARAMS)
            painter.setClipping(False)
        except Exception:
            pass

class MacStyleMessageBox(QDialog):
    """"""
    def __init__(self, parent=None, title="提示", message="", icon_type="info", buttons=None,
                 rich_message=False):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        line_count = max(
            len((message or "").splitlines()),
            len(re.findall(r"<br\s*/?>", message or "", flags=re.IGNORECASE)) + 1)
        extra_lines = max(0, line_count - 3)
        self.setFixedSize(520, min(620, 240 + extra_lines * 20))
        self._dragging = False
        self._drag_start = QPoint()
        self.title = title
        self.message = message
        self.icon_type = icon_type
        self.btn_labels = buttons or [tr("ok")]
        self.rich_message = bool(rich_message)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)
        header = QHBoxLayout()
        icons = {"info": "\u2139\uFE0F", "success": "\u2705", "warning": "\u26A0\uFE0F", "question": "\u2753"}
        icon_lbl = QLabel(icons.get(self.icon_type, "\u2139\uFE0F"))
        icon_lbl.setStyleSheet("QLabel{font-size:32px;background:transparent;}")
        title_lbl = QLabel(self.title)
        title_lbl.setStyleSheet("QLabel{font-size:18px;font-weight:bold;color:#333;background:transparent;}")
        header.addWidget(icon_lbl)
        header.addWidget(title_lbl)
        header.addStretch()
        layout.addLayout(header)
        msg = QLabel(self.message)
        msg.setWordWrap(True)
        msg.setStyleSheet("QLabel{color:#555;font-size:13px;background:transparent;padding:4px 0;}")
        if self.rich_message:
            msg.setTextFormat(Qt.TextFormat.RichText)
            msg.setOpenExternalLinks(True)
            msg.setTextInteractionFlags(Qt.TextInteractionFlag.LinksAccessibleByMouse)
        else:
            msg.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(msg)
        layout.addStretch()
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        btn_style = "QPushButton{background:rgba(80,80,80,200);color:#fff;border-radius:8px;font-size:14px;font-weight:600;}"
        btn_style += "QPushButton:hover{background:rgba(40,40,40,220);}"
        cancel_style = "QPushButton{background:rgba(200,200,200,200);color:#333;border-radius:8px;font-size:14px;}"
        cancel_style += "QPushButton:hover{background:rgba(170,170,170,220);}"
        for label in self.btn_labels:
            btn = QPushButton(label)
            btn.setFixedSize(90, 34)
            if label in ("取消", "否", "Cancel", "No"):
                btn.setStyleSheet(cancel_style)
                btn.clicked.connect(self.reject)
            else:
                btn.setStyleSheet(btn_style)
                btn.clicked.connect(self.accept)
            btn_layout.addWidget(btn)
        layout.addLayout(btn_layout)
        center_window(self)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._drag_start = event.globalPosition().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._dragging:
            delta = event.globalPosition().toPoint() - self._drag_start
            self.move(self.pos() + delta)
            self._drag_start = event.globalPosition().toPoint()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = False
        super().mouseReleaseEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        r = self.rect()
        path.addRoundedRect(r.x() + 1, r.y() + 1, r.width() - 2, r.height() - 2, 15, 15)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor(255, 255, 255, 238)))
        painter.drawPath(path)
        border_path = QPainterPath()
        border_path.addRoundedRect(r.x() + 1, r.y() + 1, r.width() - 2, r.height() - 2, 15, 15)
        painter.setPen(QPen(QColor(0, 0, 0, 30), 0.5))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(border_path)
        super().paintEvent(event)


FIELD_LABEL_WIDTH = 96

INPUT_STYLE = (
    "QLineEdit{background:rgba(255,255,255,215);"
    "border:1.5px solid rgba(60,60,60,110);"
    "border-radius:10px;padding:8px 12px;font-size:13px;color:#222;"
    "selection-background-color:rgba(0,122,255,180);}"
    "QLineEdit:hover{border:1.5px solid rgba(40,40,40,160);}"
    "QLineEdit:focus{border:1.5px solid rgba(0,122,255,225);"
    "background:rgba(255,255,255,240);}"
)


def center_window(win):
    parent = win.parent()
    if parent is not None:
        try:
            g = parent.frameGeometry()
            win.move(g.center().x() - win.width() // 2, g.center().y() - win.height() // 2)
            return
        except Exception:
            pass
    try:
        scr = QApplication.primaryScreen()
    except Exception:
        scr = None
    if scr:
        g = scr.availableGeometry()
        win.move(g.center().x() - win.width() // 2, g.center().y() - win.height() // 2)


def make_field_label(text):
    lbl = QLabel(text)
    lbl.setFixedWidth(FIELD_LABEL_WIDTH)
    lbl.setWordWrap(False)
    lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    lbl.setStyleSheet("QLabel{font-size:13px;color:#444;background:transparent;}")
    return lbl


class SettingsDialog(QDialog):
    """"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        # The 2FA status card and code row are shown dynamically. Keep enough
        # vertical room for the rich text so it cannot be clipped.
        self.setFixedSize(580, 558)
        self._dragging = False
        self._drag_start = QPoint()
        self._threads = []
        self._login_busy = False
        self._logout_busy = False
        self._closing = False
        self._post_2fa_retrying = False
        self._pending_pwd = ""
        self._login_phase = "idle"
        self._i18n_widgets = []
        self._i18n_placeholders = []
        self._language_refreshing = False
        try:
            self.setWindowIcon(get_app_icon())
        except Exception:
            pass
        self._setup_ui()
        self._refresh_status()

    def _i18n_text(self, widget, key):
        self._i18n_widgets.append((widget, key))
        widget.setText(tr(key))
        return widget

    def _i18n_placeholder(self, widget, key):
        self._i18n_placeholders.append((widget, key))
        widget.setPlaceholderText(tr(key))
        return widget

    def _field_label(self, key):
        return self._i18n_text(make_field_label(tr(key)), key)

    def _retranslate_ui(self):
        for widget, key in self._i18n_widgets:
            try:
                widget.setText(tr(key))
            except Exception:
                pass
        for widget, key in self._i18n_placeholders:
            try:
                widget.setPlaceholderText(tr(key))
            except Exception:
                pass
        if hasattr(self, "proxy_mode_combo"):
            current = self.proxy_mode_combo.currentData()
            self.proxy_mode_combo.blockSignals(True)
            self.proxy_mode_combo.clear()
            self.proxy_mode_combo.addItem(tr("proxy_auto"), "auto")
            self.proxy_mode_combo.addItem(tr("proxy_direct"), "direct")
            self.proxy_mode_combo.addItem(tr("proxy_custom"), "custom")
            self.proxy_mode_combo.setCurrentIndex({"auto": 0, "direct": 1, "custom": 2}.get(current, 0))
            self.proxy_mode_combo.blockSignals(False)
        if hasattr(self, "language_combo"):
            current = self.language_combo.currentData() or LANGUAGE_MODE
            self.language_combo.blockSignals(True)
            self.language_combo.clear()
            self.language_combo.addItem(tr("language_auto"), "auto")
            self.language_combo.addItem(tr("language_zh"), "zh")
            self.language_combo.addItem(tr("language_en"), "en")
            idx = self.language_combo.findData(current)
            self.language_combo.setCurrentIndex(idx if idx >= 0 else 0)
            self.language_combo.blockSignals(False)

    def _on_language_changed(self, index):
        global LANGUAGE_MODE
        if self._language_refreshing or index < 0:
            return
        LANGUAGE_MODE = self.language_combo.itemData(index) or "auto"
        self._language_refreshing = True
        try:
            self._retranslate_ui()
        finally:
            self._language_refreshing = False
        parent = self.parent()
        if parent is not None and hasattr(parent, "_apply_language"):
            parent._apply_language()
        if self._login_phase == "idle":
            self._refresh_status()

    def _run_tool_async(self, args, callback, timeout=60, proxy=None):
        w = ToolWorker(args, timeout, proxy=proxy)
        self._threads.append(w)
        _ACTIVE_TOOL_WORKERS.add(w)

        def _slot(rc, out):
            try:
                callback(rc, out)
            except Exception as exc:
                _diagnostic("settings_callback_exception", repr(exc))
                try:
                    self._login_busy = False
                    self.login_btn.setEnabled(True)
                    self.login_btn.setText(tr("login"))
                    self.status_card.setText(localized(
                        "登录处理发生异常，已阻止程序退出。<br>%s",
                        "Sign-in error; the app remained open.<br>%s") % _ht(exc))
                    MacStyleMessageBox(self, title=localized("登录处理异常", "Sign-in error"),
                                       message=(localized("已阻止软件闪退。\n\n%s",
                                                          "The app remained open.\n\n%s") % str(exc)),
                                       icon_type="warning").exec()
                except Exception:
                    pass

        def _finished():
            if w in self._threads:
                self._threads.remove(w)
            _ACTIVE_TOOL_WORKERS.discard(w)
            w.deleteLater()

        w.done.connect(_slot)
        w.finished.connect(_finished)
        w.start()
        return w

    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(12)

        header = QHBoxLayout()
        icon_lbl = QLabel("\u2699\uFE0F")
        icon_lbl.setStyleSheet("QLabel{font-size:26px;background:transparent;}")
        title_lbl = self._i18n_text(QLabel(), "settings_title")
        title_lbl.setStyleSheet("QLabel{font-size:18px;font-weight:bold;color:#333;background:transparent;}")
        header.addWidget(icon_lbl)
        header.addWidget(title_lbl)
        header.addStretch()
        close_btn = QPushButton("×")
        close_btn.setFixedSize(32, 32)
        close_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        close_btn.setStyleSheet(
            "QPushButton{background:rgba(255,255,255,80);color:#333;border:none;border-radius:16px;"
            "font-size:20px;font-weight:bold;}QPushButton:hover{background:rgba(255,120,120,160);color:#fff;}")
        close_btn.clicked.connect(self.reject)
        header.addWidget(close_btn)
        root.addLayout(header)

        self.status_card = QLabel()
        self.status_card.setWordWrap(True)
        self.status_card.setMinimumHeight(92)
        self.status_card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self.status_card.setStyleSheet(
            "QLabel{font-size:14px;color:#222;background:rgba(255,255,255,85);"
            "border:1px solid rgba(0,122,255,90);border-radius:12px;"
            "padding:14px 16px;}")
        self.status_card.setTextFormat(Qt.TextFormat.RichText)
        root.addWidget(self.status_card)

        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(make_field_label("Apple ID:"))
        self.email_edit = QLineEdit()
        self._i18n_placeholder(self.email_edit, "email_placeholder")
        self.email_edit.setText(APPLE_ID_SAVE)
        self.email_edit.setStyleSheet(INPUT_STYLE)
        row.addWidget(self.email_edit, 1)
        root.addLayout(row)

        pwd_row = QHBoxLayout()
        pwd_row.setSpacing(8)
        pwd_row.addWidget(self._field_label("password_label"))
        self.pwd_edit = QLineEdit()
        self._i18n_placeholder(self.pwd_edit, "password_placeholder")
        self.pwd_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.pwd_edit.setStyleSheet(INPUT_STYLE)
        self.pwd_edit.returnPressed.connect(self._do_login)
        pwd_row.addWidget(self.pwd_edit, 1)
        root.addLayout(pwd_row)

        mode_row = QHBoxLayout()
        mode_row.setSpacing(8)
        mode_row.addWidget(self._field_label("backend_label"))
        mode_label = QLabel(localized("官方 Kosthi/ipatool-rs v0.1.8",
                                     "Official Kosthi/ipatool-rs v0.1.8"))
        mode_label.setStyleSheet(
            "QLabel{font-size:13px;color:#333;background:rgba(255,255,255,70);"
            "border-radius:8px;padding:8px 12px;}")
        mode_row.addWidget(mode_label, 1)
        mode_box = QWidget()
        mode_box.setLayout(mode_row)
        mode_box.setVisible(False)
        root.addWidget(mode_box)

        self.twofa_row = QHBoxLayout()
        self.twofa_row.setContentsMargins(0, 0, 0, 0)
        self.twofa_row.setSpacing(8)
        self.twofa_row.addWidget(self._field_label("code_label"))
        self.twofa_edit = QLineEdit()
        self._i18n_placeholder(self.twofa_edit, "code_placeholder")
        # Allow pasted codes containing a space or hyphen; submission normalizes
        # them to the six ASCII digits accepted by Apple.
        self.twofa_edit.setMaxLength(12)
        self.twofa_edit.setStyleSheet(INPUT_STYLE)
        self.twofa_edit.returnPressed.connect(self._do_login_with_2fa)
        self.twofa_row.addWidget(self.twofa_edit, 1)
        self.twofa_btn = self._i18n_text(QPushButton(), "submit_code")
        self.twofa_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.twofa_btn.setStyleSheet(
            "QPushButton{background:rgba(0,122,255,215);color:#fff;border:none;border-radius:10px;"
            "font-size:13px;font-weight:600;padding:8px 20px;}"
            "QPushButton:hover{background:rgba(0,100,220,235);}")
        self.twofa_btn.clicked.connect(self._do_login_with_2fa)
        self.twofa_row.addWidget(self.twofa_btn)
        self.twofa_row_widget = QWidget()
        self.twofa_row_widget.setLayout(self.twofa_row)
        self.twofa_row_widget.setVisible(False)
        root.addWidget(self.twofa_row_widget)

        ops = QHBoxLayout()
        ops.setSpacing(10)
        ops.addStretch()
        self.login_btn = self._i18n_text(QPushButton(), "login")
        self.login_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.login_btn.setStyleSheet(
            "QPushButton{background:#20a957;color:#fff;border:1px solid #168542;border-radius:10px;"
             "font-size:13px;font-weight:600;padding:8px 20px;}"
            "QPushButton:hover{background:#168b46;}QPushButton:disabled{background:#9bc9ac;color:#f5fff8;}")
        self.login_btn.clicked.connect(self._do_login)
        ops.addWidget(self.login_btn)
        self.logout_btn = self._i18n_text(QPushButton(), "logout")
        self.logout_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.logout_btn.setStyleSheet(
            "QPushButton{background:#e5484d;color:#fff;border:1px solid #bd2f35;border-radius:10px;"
            "font-size:13px;font-weight:600;padding:8px 20px;}"
            "QPushButton:hover{background:#c9363d;}QPushButton:disabled{background:#e5a2a5;color:#fff;}")
        self.logout_btn.clicked.connect(self._do_logout)
        ops.addWidget(self.logout_btn)
        ops.addStretch()
        root.addLayout(ops)

        dir_row = QHBoxLayout()
        dir_row.setSpacing(8)
        dir_row.addWidget(self._field_label("download_dir"))
        self.dir_lbl = QLabel(IPAS_DIR)
        self.dir_lbl.setStyleSheet("QLabel{font-size:12px;color:#555;background:transparent;}")
        self.dir_lbl.setWordWrap(True)
        dir_row.addWidget(self.dir_lbl, 1)
        open_dir_btn = self._i18n_text(QPushButton(), "open")
        open_dir_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        open_dir_btn.setStyleSheet(
            "QPushButton{background:rgba(255,255,255,90);color:#333;border:1px solid rgba(255,255,255,140);"
            "border-radius:8px;font-size:12px;font-weight:600;padding:5px 14px;}"
            "QPushButton:hover{background:rgba(255,255,255,140);}")
        open_dir_btn.clicked.connect(self._open_dir)
        dir_row.addWidget(open_dir_btn)
        change_dir_btn = self._i18n_text(QPushButton(), "change")
        change_dir_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        change_dir_btn.setStyleSheet(
            "QPushButton{background:rgba(255,255,255,90);color:#333;border:1px solid rgba(255,255,255,140);"
            "border-radius:8px;font-size:12px;font-weight:600;padding:5px 14px;}"
            "QPushButton:hover{background:rgba(255,255,255,140);}")
        change_dir_btn.clicked.connect(self._change_dir)
        dir_row.addWidget(change_dir_btn)
        root.addLayout(dir_row)

        proxy_row = QHBoxLayout()
        proxy_row.setSpacing(8)
        proxy_row.addWidget(self._field_label("proxy"))
        self.proxy_mode_combo = QComboBox()
        self.proxy_mode_combo.setStyleSheet(COMBO_STYLE)
        self.proxy_mode_combo.addItem(tr("proxy_auto"), "auto")
        self.proxy_mode_combo.addItem(tr("proxy_direct"), "direct")
        self.proxy_mode_combo.addItem(tr("proxy_custom"), "custom")
        self.proxy_mode_combo.setCurrentIndex({"auto": 0, "direct": 1, "custom": 2}.get(PROXY_MODE, 0))
        self.proxy_mode_combo.currentIndexChanged.connect(self._on_proxy_mode_changed)
        proxy_row.addWidget(self.proxy_mode_combo)
        self.proxy_custom_edit = QLineEdit()
        self._i18n_placeholder(self.proxy_custom_edit, "custom_proxy_placeholder")
        self.proxy_custom_edit.setText(PROXY_CUSTOM)
        self.proxy_custom_edit.setStyleSheet(INPUT_STYLE)
        self.proxy_custom_edit.textChanged.connect(self._on_proxy_custom_changed)
        self.proxy_custom_edit.setEnabled(PROXY_MODE == "custom")
        proxy_row.addWidget(self.proxy_custom_edit, 1)
        proxy_box = QWidget()
        proxy_box.setLayout(proxy_row)
        proxy_box.setContentsMargins(0, 0, 0, 0)
        # 代理仍由程序内部自动探测和使用，普通用户无需配置。
        proxy_box.setVisible(False)
        root.addWidget(proxy_box)

        diag_row = QHBoxLayout()
        diag_row.setSpacing(8)
        diag_row.addWidget(self._field_label("network_diag"))
        self.diag_btn = self._i18n_text(QPushButton(), "start_diag")
        self.diag_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.diag_btn.setStyleSheet(
            "QPushButton{background:rgba(255,255,255,90);color:#333;border:1px solid rgba(255,255,255,140);"
            "border-radius:8px;font-size:12px;font-weight:600;padding:5px 14px;}"
            "QPushButton:hover{background:rgba(255,255,255,140);}")
        self.diag_btn.clicked.connect(self._run_network_diag)
        diag_row.addWidget(self.diag_btn)
        self.diag_hint = self._i18n_text(QLabel(), "diag_hint")
        self.diag_hint.setStyleSheet("QLabel{font-size:11px;color:#777;background:transparent;}")
        diag_row.addWidget(self.diag_hint, 1)
        diag_box = QWidget()
        diag_box.setLayout(diag_row)
        diag_box.setContentsMargins(0, 0, 0, 0)
        diag_box.setVisible(False)
        root.addWidget(diag_box)

        root.addStretch()

        bottom = QHBoxLayout()
        bottom.addStretch()
        ok_btn = self._i18n_text(QPushButton(), "done")
        ok_btn.setFixedSize(100, 34)
        ok_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        ok_btn.setStyleSheet(
            "QPushButton{background:rgba(80,80,80,205);color:#fff;border:none;border-radius:9px;"
            "font-size:13px;font-weight:600;}QPushButton:hover{background:rgba(40,40,40,225);}")
        ok_btn.clicked.connect(self.accept)
        bottom.addWidget(ok_btn)
        root.addLayout(bottom)

        language_row = QHBoxLayout()
        language_row.setSpacing(8)
        language_row.addWidget(self._field_label("language"))
        self.language_combo = QComboBox()
        self.language_combo.setStyleSheet(COMBO_STYLE)
        self.language_combo.addItem(tr("language_auto"), "auto")
        self.language_combo.addItem(tr("language_zh"), "zh")
        self.language_combo.addItem(tr("language_en"), "en")
        language_index = self.language_combo.findData(LANGUAGE_MODE)
        self.language_combo.setCurrentIndex(language_index if language_index >= 0 else 0)
        style_combo_clean(self.language_combo)
        self.language_combo.currentIndexChanged.connect(self._on_language_changed)
        language_row.addWidget(self.language_combo, 1)
        root.insertLayout(root.count() - 1, language_row)

        version_label = self._i18n_text(QLabel(), "software_version")
        version_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        version_label.setStyleSheet(
            "QLabel{font-size:11px;color:#666;background:transparent;padding-top:2px;}")
        root.addWidget(version_label)

        signature = QLabel('<a href="https://github.com/mango6i/iOSAppDownloader">by：果果</a>')
        signature.setOpenExternalLinks(True)
        signature.setTextInteractionFlags(Qt.TextInteractionFlag.LinksAccessibleByMouse)
        signature.setAlignment(Qt.AlignmentFlag.AlignCenter)
        signature.setStyleSheet(
            "QLabel{font-size:11px;color:#777;background:transparent;padding-top:2px;}"
            "QLabel a{color:#777;text-decoration:none;}QLabel a:hover{color:#1677ff;}")
        root.addWidget(signature)
        center_window(self)

    def _refresh_status(self):
        if self._login_phase != "idle":
            return
        self.status_card.setText(tr("status_loading"))
        self._run_tool_async(["auth", "info", "--format", "json"], self._on_status_done, timeout=45)

    def _on_status_done(self, rc, out):
        if self._login_phase != "idle":
            return
        logged, _, who = _auth_result(rc, out)
        if logged:
            self.status_card.setText(tr("status_logged") + _ht(who or "Apple ID"))
        else:
            self.status_card.setText(tr("status_logged_out"))

    def _do_login(self):
        global APPLE_ID_SAVE
        email = self.email_edit.text().strip()
        pwd = self.pwd_edit.text().strip()
        if not email:
            MacStyleMessageBox(self, title=tr("fill_email_title"), message=tr("fill_email_message"), icon_type="warning").exec()
            return
        if not pwd:
            MacStyleMessageBox(self, title=tr("fill_email_title"), message=tr("fill_password_message"), icon_type="warning").exec()
            return
        if not IPATOOL_PATH or not os.path.exists(IPATOOL_PATH):
            MacStyleMessageBox(self, title=tr("component_error_title"),
                               message=tr("component_error_message"),
                               icon_type="warning").exec()
            return
        APPLE_ID_SAVE = email
        save_config()
        self._pending_pwd = pwd
        self._run_login(email, pwd)

    def _run_login(self, email, pwd, code=""):
        if getattr(self, "_login_busy", False):
            return
        if not code:
            # A fresh password attempt creates a fresh Apple challenge.
            _clear_login_challenge_proxy()
        self._login_busy = True
        self._login_phase = "verifying_code" if code else "verifying_password"
        self.login_btn.setEnabled(False)
        self.login_btn.setText(tr("logging_in"))
        self.logout_btn.setEnabled(False)
        self.twofa_btn.setEnabled(False)
        if not code:
            self.twofa_row_widget.setVisible(False)
        self.status_card.setText(tr("login_code_status") if code else tr("login_start_status"))
        args = ["auth", "login", "--email", email, "--password", pwd,
                "--non-interactive", "--format", "json"]
        if code:
            args += ["--auth-code", code]
        # A 2FA challenge can be tied to the route that created it. Force the
        # verification request through that exact route instead of probing a
        # different proxy and invalidating the freshly generated code.
        proxy = _get_login_challenge_proxy() if code else None
        _diagnostic("login_request", "with_2fa=%s mode=non_interactive" % bool(code))
        self._run_tool_async(
            args, lambda rc, out: self._on_login_done(rc, out, bool(code)),
            timeout=90, proxy=proxy)

    def _on_login_done(self, rc, out, had_code):
        _diagnostic("login_response", "rc=%s with_2fa=%s output_length=%s" %
                    (rc, bool(had_code), len(out or "")))
        # Closing Settings while a request is still running is a user action,
        # not an authentication failure. Never show a late error over the main
        # window after the dialog has gone away.
        if self._closing or rc == -4:
            self._login_busy = False
            self._login_phase = "idle"
            return
        self._login_busy = False
        self.login_btn.setEnabled(True)
        self.login_btn.setText(tr("login"))
        self.logout_btn.setEnabled(True)
        self.twofa_btn.setEnabled(True)
        low = (out or "").lower()
        authenticated, needs_code, _ = _auth_result(rc, out)

        # ipatool can return a 2FA-related error even though Apple has already
        # accepted the code and updated the stored session. Never declare a
        # valid code rejected from that text alone; verify the real session.
        if had_code:
            self._begin_login_confirmation(True, out)
            return

        if needs_code:
            self._login_phase = "waiting_code"
            self.twofa_row_widget.setVisible(True)
            self.twofa_edit.clear()
            self.twofa_edit.setFocus()
            self.status_card.setText(tr("twofa_status_html"))
            MacStyleMessageBox(self, title=tr("need_2fa_title"),
                               message=tr("need_2fa_message"), icon_type="info").exec()
            return

        if authenticated:
            self._begin_login_confirmation(False, out)
            return

        self._login_phase = "idle"

        if rc == -1:
            MacStyleMessageBox(self, title=tr("component_error_title"),
                               message=tr("component_error_message"),
                               icon_type="warning").exec()
            self._refresh_status()
            return

        if rc == -2:
            MacStyleMessageBox(self, title=localized("登录超时", "Sign-in timed out"),
                               message=localized("连接 Apple 服务器超时（90 秒）。\n请检查网络或代理后重试。",
                                                 "The connection to Apple timed out after 90 seconds.\n"
                                                 "Check your network or proxy and try again."),
                               icon_type="warning").exec()
            self.status_card.setText(localized("登录超时<br>请检查网络后重试。",
                                               "Sign-in timed out<br>Check your network and try again."))
            return

        if "403" in low or "forbidden" in low:
            tail = (out or "")[-600:]
            self.status_card.setText(localized("Apple 服务器返回 403 拒绝<br>请查看下方说明。",
                                               "Apple returned HTTP 403 (Forbidden)<br>See the details below."))
            MacStyleMessageBox(self, title=localized("登录被服务器拒绝 (403)", "Sign-in rejected (403)"),
                               message=localized(
                                   "Apple 认证服务器返回 HTTP 403（拒绝访问）。常见原因与排查：\n\n"
                                   "1. 该 Apple ID 可能需要在 appleid.apple.com 网页端处理（如同意新条款、解锁账号、验证支付方式）。\n"
                                   "2. 系统代理 / VPN / 防火墙可能拦截或改写了对 Apple 的请求，尝试关闭代理后再登录。\n"
                                   "3. Apple 对该账号或网络存在临时风控，可稍后重试或更换网络。\n\n"
                                   "原始错误：\n%s",
                                   "Apple returned HTTP 403 (Forbidden). Common causes:\n\n"
                                   "1. The Apple ID may need attention at appleid.apple.com (new terms, account unlock, or payment verification).\n"
                                   "2. A system proxy, VPN, or firewall may be blocking or rewriting Apple requests.\n"
                                   "3. Apple may be applying temporary risk controls to this account or network. Try again later or use another network.\n\n"
                                   "Raw error:\n%s") % tail,
                               icon_type="warning").exec()
            self._refresh_status()
            return

        if "something went wrong" in low or "unknown error" in low or "an error occurred" in low:
            tail = (out or "")[-1200:]
            self.status_card.setText(localized(
                "Apple 返回通用错误：something went wrong<br>请查看下方排查。",
                "Apple returned a generic error: something went wrong<br>See the details below."))
            MacStyleMessageBox(self, title=localized("登录被拒绝（Apple 通用错误）",
                                                      "Sign-in rejected (Apple generic error)"),
                               message=localized(
                                   "Apple 认证服务返回了通用错误 \"Something went wrong\"，通常无法由软件侧修复，根因在账号或网络层面：\n\n"
                                   "1. 优先排查账号：用浏览器打开 appleid.apple.com 登录该 Apple ID，按页面红色提示处理（同意新条款、验证支付方式、解锁账号），处理完再回本软件登录。\n"
                                   "2. 关闭系统代理 / VPN / 加速器后重试，避免请求被中间网络拦截或改写。\n"
                                   "3. 换网络（如手机热点）重试，排除本机网络风控。\n\n"
                                   "原始错误：\n%s",
                                   "Apple returned the generic error \"Something went wrong\". This is usually caused by the account or network rather than the app:\n\n"
                                   "1. Check the account at appleid.apple.com and follow any red prompts (terms, payment verification, or unlock).\n"
                                   "2. Retry with system proxy, VPN, or accelerator disabled to avoid request rewriting.\n"
                                   "3. Try another network, such as a phone hotspot.\n\n"
                                   "Raw error:\n%s") % tail,
                               icon_type="warning").exec()
            self._refresh_status()
            return

        if any(k in low for k in ("failed to initialize sap action signer", "create sap signer",
                                  "start apple sap runtime", "create unicorn engine",
                                  "load unicorn", "download unicorn")):
            tail = (out or "")[-500:]
            message = localized(
                "Apple 登录尚未进入验证码步骤，软件内部认证组件初始化失败。\n\n"
                "请重新启动软件后再试。若仍失败，请将下方错误内容一并反馈。\n\n%s",
                "Apple sign-in did not reach the verification-code step because the internal sign-in component failed to initialize.\n\n"
                "Restart the app and try again. If it still fails, include the error below when reporting it.\n\n%s") % tail
            self.status_card.setText(localized(
                "安全运行时初始化失败<br>请检查网络或代理后重试。<br><br>%s",
                "Secure sign-in runtime failed to initialize<br>Check your network or proxy and try again.<br><br>%s") % _ht(tail))
            MacStyleMessageBox(self, title=localized("登录环境初始化失败", "Sign-in environment failed"), message=message,
                               icon_type="warning").exec()
            self._refresh_status()
            return

        if any(k in low for k in ("proxy", "dial tcp", "connection refused", "no such host",
                                  "i/o timeout", "bag.xml", "network is unreachable",
                                  "tls handshake", "certificate")):
            MacStyleMessageBox(self, title=localized("网络连接失败", "Network connection failed"),
                               message=localized(
                                   "无法连接 Apple 服务器。\n\n"
                                   "请依次检查：\n"
                                   "1. 电脑网络是否正常\n"
                                   "2. 系统代理 / VPN 是否可用\n"
                                   "3. 防火墙是否拦截了本软件\n\n"
                                   "错误详情：\n%s",
                                   "Could not connect to Apple services.\n\n"
                                   "Check:\n"
                                   "1. Whether the computer network works\n"
                                   "2. Whether the system proxy / VPN works\n"
                                   "3. Whether the firewall is blocking this app\n\n"
                                   "Details:\n%s") % _friendly_auth_error(out),
                               icon_type="warning").exec()
            self.status_card.setText(localized(
                "网络连接失败<br>请检查网络或代理设置后重试。<br><br>%s",
                "Network connection failed<br>Check the network or proxy and try again.<br><br>%s")
                                      % _ht((out or "")[-300:]))
            return

        if _is_transient_apple_edge_error(out):
            _reset_auto_exit()

        tail = (out or "")[-500:]
        if any(k in low for k in ("incorrect", "invalid", "wrong", "bad", "fail")):
            if had_code:
                self._login_phase = "waiting_code"
                self.twofa_row_widget.setVisible(True)
            code_note = localized("（验证码可能有误或已过期）", " (the code may be invalid or expired)") if had_code else ""
            self.status_card.setText(localized("登录失败%s<br><br>%s",
                                               "Sign-in failed%s<br><br>%s") %
                                     (code_note, _ht(_friendly_auth_error(out))))
            MacStyleMessageBox(self, title=localized("登录失败", "Sign-in failed"),
                               message=(localized("验证码可能有误或已过期，请输入新验证码后重试。",
                                                  "The verification code may be invalid or expired. Enter a new code and try again.") if had_code else
                                        _friendly_auth_error(out)),
                               icon_type="warning").exec()
        else:
            self.status_card.setText(localized("登录未完成<br>%s", "Sign-in did not complete<br>%s")
                                     % _ht(_friendly_auth_error(out)))
            MacStyleMessageBox(self, title=localized("登录未完成", "Sign-in did not complete"),
                               message=_friendly_auth_error(out) + "\n\n" +
                                       localized("原始输出（请复制反馈）：\n", "Raw output (copy this when reporting):\n") +
                                       (out or "")[:1500],
                               icon_type="warning").exec()

    def _begin_login_confirmation(self, had_code, auth_out=""):
        if self._closing:
            return
        self._login_busy = True
        self._login_phase = "confirming"
        self.login_btn.setEnabled(False)
        self.login_btn.setText(tr("confirm_login"))
        self.logout_btn.setEnabled(False)
        self.twofa_btn.setEnabled(False)
        self.status_card.setText(localized(
            "验证码已提交<br>正在确认真实登录状态，请稍候。" if had_code else
            "认证已通过<br>正在确认账号登录状态，请稍候。",
            "Code submitted<br>Confirming the actual sign-in status..." if had_code else
            "Authentication accepted<br>Confirming account status..."))
        self._run_tool_async(
            ["auth", "info", "--format", "json"],
            lambda info_rc, info_out: self._on_login_verified(
                info_rc, info_out, bool(had_code), auth_out),
            timeout=45,
            proxy=_get_login_challenge_proxy())

    def _on_login_verified(self, rc, out, had_code, auth_out=""):
        _diagnostic("login_status_confirmation", "rc=%s with_2fa=%s output_length=%s" %
                    (rc, bool(had_code), len(out or "")))
        if self._closing:
            self._login_busy = False
            self._login_phase = "idle"
            return
        self._login_busy = False
        self.login_btn.setEnabled(True)
        self.login_btn.setText(tr("login"))
        self.logout_btn.setEnabled(True)
        self.twofa_btn.setEnabled(True)
        logged, _, who = _auth_result(rc, out)
        if logged:
            self._login_phase = "idle"
            self.status_card.setText(tr("status_logged") + _ht(who or self.email_edit.text().strip()))
            parent = self.parent()
            if parent is not None and hasattr(parent, "_on_login_status"):
                parent._on_login_status(rc, out)
            self.pwd_edit.clear()
            self.twofa_edit.clear()
            self._pending_pwd = ""
            _clear_login_challenge_proxy()
            self.twofa_row_widget.setVisible(False)
            MacStyleMessageBox(self, title=tr("login_success_title"),
                               message=tr("login_success_message"),
                               icon_type="success").exec()
            return
        if had_code and not self._post_2fa_retrying:
            # A correct code has been observed to complete Apple's challenge
            # while the code-submission command still exits with an error. A
            # plain login on the same route then returns the completed session.
            # Perform that recovery automatically before asking for a new code.
            self._post_2fa_retrying = True
            self._login_busy = True
            self._login_phase = "confirming"
            self.login_btn.setEnabled(False)
            self.login_btn.setText(tr("confirm_login"))
            self.logout_btn.setEnabled(False)
            self.twofa_btn.setEnabled(False)
            self.status_card.setText(localized(
                "正在完成 Apple 登录会话<br>请稍候，不要重复提交验证码。",
                "Completing the Apple sign-in session<br>Please wait; do not resubmit the code."))
            args = ["auth", "login", "--email", self.email_edit.text().strip(),
                    "--password", self._pending_pwd,
                    "--non-interactive", "--format", "json"]
            proxy = _get_login_challenge_proxy()
            _diagnostic("post_2fa_session_retry", "started same_route=%s" % (proxy is not None))
            self._run_tool_async(
                args, self._on_post_2fa_retry_done, timeout=90, proxy=proxy)
            return
        self._login_phase = "waiting_code" if had_code else "idle"
        self.twofa_row_widget.setVisible(bool(had_code))
        message = localized(
            "认证请求已返回，但账号状态确认失败，因此没有判定为登录成功。\n\n%s",
            "The authentication request returned, but the account status could not be confirmed, so sign-in was not marked successful.\n\n%s") % _friendly_auth_error(out)
        self.status_card.setText(localized(
            "认证请求已返回，但账号状态确认失败，因此没有判定为登录成功。<br><br>%s",
            "The authentication request returned, but the account status could not be confirmed.<br><br>%s") % _ht(_friendly_auth_error(out)))
        MacStyleMessageBox(self, title=localized("登录未完成", "Sign-in did not complete"), message=message, icon_type="warning").exec()

    def _on_post_2fa_retry_done(self, rc, out):
        self._post_2fa_retrying = False
        _diagnostic("post_2fa_session_retry", "rc=%s output_length=%s" %
                    (rc, len(out or "")))
        if self._closing:
            self._login_busy = False
            self._login_phase = "idle"
            return
        authenticated, needs_code, _ = _auth_result(rc, out)
        if authenticated:
            self._begin_login_confirmation(False, out)
            return
        if needs_code:
            self._login_busy = False
            self._login_phase = "waiting_code"
            self.login_btn.setEnabled(True)
            self.login_btn.setText(tr("login"))
            self.logout_btn.setEnabled(True)
            self.twofa_btn.setEnabled(True)
            self.twofa_row_widget.setVisible(True)
            self.twofa_edit.clear()
            self.twofa_edit.setFocus()
            self.status_card.setText(localized(
                "Apple 仍要求双重认证<br>请使用手机上最新生成的 6 位验证码。",
                "Apple still requires two-factor authentication<br>Use the newest 6-digit code generated on your device."))
            MacStyleMessageBox(
                self,
                title=tr("need_2fa_title"),
                message=localized(
                    "登录状态尚未完成。请在手机上重新获取一个最新验证码后提交；不要重复使用刚才的旧验证码。",
                    "The sign-in session is not complete. Generate the newest code on your device and submit it; do not reuse the previous code."),
                icon_type="info").exec()
            return
        self._login_busy = False
        self._on_login_done(rc, out, False)

    def _do_login_with_2fa(self):
        email = self.email_edit.text().strip()
        code = _normalize_2fa_code(self.twofa_edit.text())
        if not re.fullmatch(r"[0-9]{6}", code):
            MacStyleMessageBox(self, title=tr("fill_email_title"), message=tr("code_invalid"), icon_type="warning").exec()
            return
        self.twofa_edit.setText(code)
        pwd = getattr(self, "_pending_pwd", "")
        if not pwd:
            MacStyleMessageBox(self, title=tr("fill_email_title"), message=tr("password_expired"),
                               icon_type="warning").exec()
            return
        self._run_login(email, pwd, code)

    def _do_logout(self):
        if getattr(self, "_logout_busy", False):
            return
        if not IPATOOL_PATH or not os.path.exists(IPATOOL_PATH):
            MacStyleMessageBox(self, title=tr("component_error_title"),
                               message=localized("注销组件缺失，请重新下载完整的软件。",
                                                 "The sign-out component is missing. Download the complete package again."),
                               icon_type="warning").exec()
            return
        self._logout_busy = True
        self._login_phase = "logging_out"
        self.logout_btn.setEnabled(False)
        self.logout_btn.setText(tr("logout_progress"))
        self.login_btn.setEnabled(False)
        self.status_card.setText(localized("正在注销...", "Signing out..."))
        self._run_tool_async(["auth", "revoke", "--format", "json"], self._on_logout_done, timeout=60)

    def _on_logout_done(self, rc, out):
        self._logout_busy = False
        self._login_phase = "idle"
        self.logout_btn.setEnabled(True)
        self.logout_btn.setText(tr("logout"))
        self.login_btn.setEnabled(True)
        low = (out or "").lower()
        _clear_runtime_auth(revoke=(rc != 0))
        global APPLE_ID_SAVE
        APPLE_ID_SAVE = ""
        self.email_edit.clear()
        self.pwd_edit.clear()
        self.twofa_edit.clear()
        self._pending_pwd = ""
        _clear_login_challenge_proxy()
        if rc == 0:
            parent = self.parent()
            if parent is not None and hasattr(parent, "_on_login_status"):
                parent._on_login_status(1, "")
            MacStyleMessageBox(self, title=tr("logged_out_title"), message=tr("logged_out_message"), icon_type="success").exec()
        elif any(k in low for k in ("not logged", "not authenticated", "could not find",
                                    "no session", "keychain", "not signed")):
            MacStyleMessageBox(self, title=tr("choose_app_title"),
                               message=localized("当前未登录或凭据已失效。", "You are not signed in or the credentials have expired."),
                               icon_type="info").exec()
        else:
            MacStyleMessageBox(self, title=localized("注销结果", "Sign-out result"),
                               message=localized("返回码 %s\n%s", "Return code %s\n%s") %
                                       (rc, (out or "")[-400:]),
                               icon_type="info").exec()
        self._refresh_status()

    def _open_dir(self):
        try:
            os.startfile(IPAS_DIR)
        except Exception:
            QDesktopServices.openUrl(QUrl.fromLocalFile(IPAS_DIR))

    def accept(self):
        self._closing = True
        super().accept()

    def reject(self):
        self._closing = True
        super().reject()

    def _change_dir(self):
        global IPAS_DIR
        d = QFileDialog.getExistingDirectory(
            self, localized("选择下载目录", "Choose download folder"), IPAS_DIR)
        if d:
            IPAS_DIR = d
            self.dir_lbl.setText(d)

    def _on_proxy_mode_changed(self, idx):
        global PROXY_MODE
        PROXY_MODE = ["auto", "direct", "custom"][idx]
        self.proxy_custom_edit.setEnabled(PROXY_MODE == "custom")

    def _on_proxy_custom_changed(self, text):
        global PROXY_CUSTOM
        PROXY_CUSTOM = text.strip()

    def _run_network_diag(self):
        thread = getattr(self, "_diag_thread", None)
        if thread is not None and thread.isRunning():
            return
        self.diag_btn.setEnabled(False)
        self.diag_btn.setText(tr("diagnosing"))
        self.diag_hint.setText(localized("正在检测 Apple 各端点，约需十几秒…",
                                         "Checking Apple endpoints; this may take a few seconds..."))
        self._diag_thread = NetworkDiagWorker()
        self._diag_thread.done.connect(self._on_network_diag_done)
        self._diag_thread.start()

    def _on_network_diag_done(self, results):
        self.diag_btn.setEnabled(True)
        self.diag_btn.setText(tr("start_diag"))
        self.diag_hint.setText(tr("diag_hint"))
        proxy = _resolve_proxy()
        route = (localized("走代理：%s", "Proxy: %s") % proxy
                 if proxy else localized("直连（当前未使用代理）", "Direct connection (no proxy)"))
        label_names = {
            "商店配置 bag": localized("商店配置 bag", "Store configuration bag"),
            "认证端点（传统）": localized("认证端点（传统）", "Legacy sign-in endpoint"),
            "认证端点（新版）": localized("认证端点（新版）", "Native sign-in endpoint"),
            "应用查询接口": localized("应用查询接口", "App lookup API"),
        }
        lines = [route, ""]
        for item in results:
            label = label_names.get(item["label"], item["label"])
            if item["error"]:
                lines.append(localized("● %s：连接失败（%s，%dms）",
                                       "● %s: connection failed (%s, %d ms)")
                             % (label, item["error"][:60], item["ms"]))
            else:
                extra = localized("，已返回跳转地址", ", redirect received") if item.get("location") else ""
                lines.append(localized("● %s：HTTP %d（%dms）%s",
                                       "● %s: HTTP %d (%d ms)%s")
                             % (label, item["status"], item["ms"], extra))
        lines.append("")
        level, conclusion = _diag_conclusion(results)
        lines.append(conclusion)
        MacStyleMessageBox(self, title=localized("网络诊断结果", "Network check result"),
                           message="\n".join(lines),
                           icon_type="success" if level == "ok" else "warning").exec()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._drag_start = event.globalPosition().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._dragging:
            delta = event.globalPosition().toPoint() - self._drag_start
            self.move(self.pos() + delta)
            self._drag_start = event.globalPosition().toPoint()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = False
        super().mouseReleaseEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        r = self.rect()
        path.addRoundedRect(r.x() + 1, r.y() + 1, r.width() - 2, r.height() - 2, 15, 15)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor(255, 255, 255, 242)))
        painter.drawPath(path)
        border_path = QPainterPath()
        border_path.addRoundedRect(r.x() + 1, r.y() + 1, r.width() - 2, r.height() - 2, 15, 15)
        painter.setPen(QPen(QColor(0, 0, 0, 30), 0.5))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(border_path)
        super().paintEvent(event)

# ─────────────────────────────────────────────
# ─────────────────────────────────────────────
import urllib.request, urllib.parse


def _http_route_candidates():
    """"""
    try:
        values = _candidate_proxies()
    except Exception:
        values = [""]
    routes = []
    for value in values or [""]:
        value = str(value or "").strip()
        if value.lower().startswith("socks"):
            continue
        if value not in routes:
            routes.append(value)
    return routes or [""]


def _http_get_bytes(url, timeout=25):
    """"""
    last_error = None
    routes = _http_route_candidates()
    for route_index, proxy in enumerate(routes):
        for attempt in range(2):
            try:
                req = urllib.request.Request(
                    url,
                    headers={
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                      "AppleWebKit/537.36 iOSAppDownloader/1.0",
                        "Accept": "application/json,text/plain,*/*",
                        "Connection": "close",
                    })
                opener = _build_opener(proxy)
                with opener.open(req, timeout=timeout) as response:
                    data = response.read()
                if not data:
                    raise urllib.error.URLError("Apple 返回空响应")
                return data
            except (urllib.error.URLError, urllib.error.HTTPError, ssl.SSLError,
                    TimeoutError, OSError, ValueError) as exc:
                last_error = exc
                if attempt == 0:
                    time.sleep(0.35)
        if route_index + 1 < len(routes):
            time.sleep(0.45)
    if last_error is not None:
        raise last_error
    raise urllib.error.URLError("Apple 接口没有可用线路")


def _get_cached_icon(url):
    """Fetch a search result icon once and reuse it across repeated searches."""
    address = str(url or "").strip()
    if not address:
        return None
    with _ICON_CACHE_LOCK:
        cached = _ICON_CACHE.get(address)
    if cached is not None:
        return cached
    try:
        data = _http_get_bytes(address, timeout=15)
    except Exception:
        return None
    if not data:
        return None
    with _ICON_CACHE_LOCK:
        if len(_ICON_CACHE) >= _ICON_CACHE_LIMIT:
            _ICON_CACHE.pop(next(iter(_ICON_CACHE)))
        _ICON_CACHE[address] = data
    return data


def _http_get_json(url, timeout=25):
    data = _http_get_bytes(url, timeout=timeout)
    try:
        return json.loads(data.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise urllib.error.URLError("Apple 返回的搜索数据无法解析：%s" % exc)

def safe_filename(name, version, app_id):
    keep = "".join(c for c in name if c.isalnum() or c in "._-")
    return (keep + "_" + version + ".ipa") if keep else ("app_%s_%s.ipa" % (app_id, version))

def format_size(b):
    if not b:
        # Apple 的历史接口经常不公开旧 IPA 的大小，下载时会用实际文件大小补齐。
        return tr("fetch_on_download")
    b = float(b)
    if b >= 1073741824:
        return "%.2f GB" % (b / 1073741824)
    return "%.1f MB" % (b / 1048576)


class NumericTableWidgetItem(QTableWidgetItem):
    """Display text normally while sorting the underlying value numerically."""

    def __init__(self, text, number=0):
        super().__init__(str(text))
        try:
            self._sort_number = int(number)
        except Exception:
            self._sort_number = 0

    def __lt__(self, other):
        if isinstance(other, NumericTableWidgetItem):
            return self._sort_number < other._sort_number
        return super().__lt__(other)


def format_transfer_size(b):
    try:
        b = max(0, int(b or 0))
    except Exception:
        b = 0
    if b >= 1073741824:
        return "%.2f GB" % (b / 1073741824.0)
    return "%.2f MB" % (b / 1048576.0)

def format_duration(seconds):
    try:
        seconds = max(0, int(seconds or 0))
    except Exception:
        seconds = 0
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    if hours:
        return "%02d:%02d:%02d" % (hours, minutes, seconds)
    return "%02d:%02d" % (minutes, seconds)

def api_search_apps(keyword, country="cn", limit=50):
    """"""
    query = urllib.parse.urlencode({
        "term": keyword,
        "country": str(country or "cn").upper(),
        "entity": "software",
        "limit": int(limit or 50),
    })
    url = "https://itunes.apple.com/search?%s" % query
    d = _http_get_json(url, timeout=18)
    out = []
    for r in d.get("results", []):
        out.append({
            "track_name": r.get("trackName", ""),
            "bundle_id": r.get("bundleId", ""),
            "track_id": r.get("trackId", 0),
            "version": r.get("version", ""),
            "icon_100": r.get("artworkUrl100", ""),
            "icon_512": r.get("artworkUrl512", "") or r.get("artworkUrl100", ""),
            "size": r.get("fileSizeBytes", 0),
            "seller": r.get("sellerName", ""),
            "rating": r.get("averageUserRating", 0),
            "rating_count": r.get("userRatingCount", 0),
            "track_view_url": r.get("trackViewUrl", ""),
            "price": r.get("formattedPrice", "") or
                     (tr("free") if not r.get("price") else str(r.get("price"))),
            "genres": ", ".join(r.get("genres", []) or []),
            "description": (r.get("description", "") or "").replace("\n", " ").strip(),
            "release_date": (r.get("currentVersionReleaseDate", "") or "")[:19].replace("T", " "),
            "min_os": r.get("minimumOsVersion", ""),
        })
    return out

def api_fetch_history_local(app_id):
    """"""
    out = []
    for page in range(1, 61):
        try:
            url = "https://apis.bilin.eu.org/history/%s?page=%d" % (app_id, page)
            d = _http_get_json(url)
        except Exception:
            break
        if d.get("code") != 200:
            break
        rows = d.get("data") or []
        if not rows:
            break
        for it in rows:
            bv = it.get("bundle_version")
            if not bv:
                continue
            out.append({
                "version": str(bv),
                "external_id": it.get("external_identifier", 0),
                "date": (it.get("created_at", "") or "")[:19].replace("T", " "),
                "size": it.get("size", 0),
            })
        total = d.get("total")
        if total and len(out) >= total:
            break
    return out

def api_fetch_history_apple(app_id):
    """"""
    if not IPATOOL_PATH:
        raise RuntimeError("软件内部查询组件不可用，请重新下载完整的软件")
    rc, out = run_tool(["version", "list", "--app-id", str(app_id),
                        "--format", "json", "--non-interactive"], timeout=90)
    if rc != 0:
        raise RuntimeError(_friendly_auth_error(out) or "历史版本查询失败")
    rows = []
    for rec in _json_records(out):
        if not isinstance(rec, dict) or not isinstance(rec.get("versions"), list):
            continue
        for item in rec["versions"]:
            if not isinstance(item, dict):
                continue
            ext_id = str(item.get("external_version_id") or "").strip()
            if not ext_id:
                continue
            version = str(item.get("version_string") or "").strip()
            rows.append({"version": version, "external_id": ext_id,
                         "date": "", "size": 0})
        break
    if not rows:
        raise RuntimeError("没有收到有效的历史版本数据")

    # ipatool-rs 的官方 version list 是版本 ID 的权威来源，但 Apple 在该接口里
    # 通常不返回可读版本号、文件大小和日期。用公开版本资料按同一官方 ID 补齐；
    # 即使资料源暂时不可用，也绝不再把版本 ID 冒充为版本号。
    try:
        metadata_rows = api_fetch_history_local(app_id)
    except Exception:
        metadata_rows = []
    metadata_by_id = {}
    for meta in metadata_rows:
        key = str(meta.get("external_id") or "").strip()
        if key and key not in metadata_by_id:
            metadata_by_id[key] = meta
    for row in rows:
        meta = metadata_by_id.get(str(row["external_id"]))
        if not meta:
            # Keep missing metadata empty. The table renders an aligned dash;
            # it must not invent a version or place a status phrase in a data column.
            row["version"] = row.get("version") or ""
            continue
        row["version"] = str(meta.get("version") or row.get("version") or "")
        row["date"] = str(meta.get("date") or "")
        row["size"] = meta.get("size") or 0
    return rows

# ---------------------------------------------------------------- 官网会话凭证

CONFIGURATOR_UA = "Configurator/2.0 (Macintosh; OS X 10.12.6; 16G29) AppleWebKit/2603.3.8"

STORE_DOWNLOAD_PATH = "/WebObjects/MZFinance.woa/wa/volumeStoreDownloadProduct"
STORE_PURCHASE_PATH = "/WebObjects/MZBuy.woa/wa/buyProduct"

_TOKEN_COOKIE_PREFIX = ("mz_at_ssl", "mz_at0", "mt-tkn", "mz_at")
_DSID_COOKIE_NAMES = ("dssid", "dssid2")
_INFO_COOKIE_PREFIX = ("myacinfo",)
_POD_COOKIE_NAMES = ("itspod", "pod")


class StoreSession(object):
    """"""

    def __init__(self, dsid="", token="", storefront="", pod="", email="", name=""):
        self.dsid = str(dsid or "").strip()
        self.token = str(token or "").strip()
        self.storefront = str(storefront or "").strip()
        self.pod = str(pod or "").strip()
        self.email = str(email or "").strip()
        self.name = str(name or "").strip()

    @property
    def ok(self):
        return self.dsid.isdigit() and len(self.dsid) >= 6

    @property
    def label(self):
        who = self.email or self.name or "Apple ID"
        return "%s（DSID %s）" % (who, self.dsid)

    def summary(self):
        return ("账号：%s<br>DSID：%s<br>会话令牌：%s<br>商店分区：%s<br>服务节点：%s"
                % (_ht(self.email or self.name or "Apple ID"),
                   _ht(self.dsid or "-"),
                   "已获取" if self.token else "未获取",
                   _ht(self.storefront or "-"),
                   _ht(("p" + self.pod) if self.pod else "-")))


def _plist_find(node, key):
    """"""
    if isinstance(node, dict):
        if key in node:
            return node[key]
        for value in node.values():
            found = _plist_find(value, key)
            if found is not None:
                return found
    elif isinstance(node, (list, tuple)):
        for value in node:
            found = _plist_find(value, key)
            if found is not None:
                return found
    return None


def _decode_account_cookie(value):
    """"""
    try:
        import base64
        import plistlib
        raw = base64.b64decode(value + "=" * (-len(value) % 4))
        data = plistlib.loads(raw)
    except Exception:
        return "", ""
    dsid = _plist_find(data, "dsid") or _plist_find(data, "DSID")
    apple_id = _plist_find(data, "appleId") or _plist_find(data, "appleID")
    name = _plist_find(data, "fullName") or _plist_find(data, "name")
    return str(dsid or ""), str(apple_id or ""), str(name or "")


def parse_store_cookies(cookies):
    """"""
    token = ""
    dsid = ""
    pod = ""
    email = ""
    name = ""

    for item in cookies:
        try:
            cname, cvalue, _cdomain = item
        except Exception:
            continue
        low = str(cname or "").strip().lower()
        val = str(cvalue or "").strip()
        if not low or not val:
            continue

        if not token:
            for prefix in _TOKEN_COOKIE_PREFIX:
                if low == prefix:
                    token = val
                    break
                if low.startswith(prefix + "-"):
                    token = val
                    tail = low[len(prefix) + 1:]
                    if tail.isdigit() and not dsid:
                        dsid = tail
                    break

        if not dsid and low in _DSID_COOKIE_NAMES:
            if val.isdigit():
                dsid = val

        if low.startswith(_INFO_COOKIE_PREFIX):
            got_dsid, got_mail, got_name = _decode_account_cookie(val)
            if got_dsid and not dsid:
                dsid = got_dsid
            if got_mail and not email:
                email = got_mail
            if got_name and not name:
                name = got_name

        if not pod and low in _POD_COOKIE_NAMES:
            if val.isdigit():
                pod = val

    return StoreSession(dsid=dsid, token=token, pod=pod, email=email, name=name)


def _machine_guid():
    """"""
    try:
        import uuid
        node = uuid.getnode()
        if node and node != 0xFFFFFFFFFFFF:
            mac = "%012X" % node
            return mac.upper()
    except Exception:
        pass
    return "0000000000000000"


def _build_opener(proxy=""):
    """"""
    handlers = []
    value = str(proxy or "").strip()
    if value:
        handlers.append(urllib.request.ProxyHandler({"http": value, "https": value}))
    else:
        handlers.append(urllib.request.ProxyHandler({}))
    return urllib.request.build_opener(*handlers)


def _http_post_bytes(url, body, headers, proxy="", timeout=60):
    """"""
    opener = _build_opener(proxy)
    req = urllib.request.Request(url, data=body, headers=headers)
    with opener.open(req, timeout=timeout) as resp:
        return resp.read()


def _store_hosts(session):
    """"""
    hosts = []
    if session.pod and session.pod.isdigit():
        hosts.append("https://p%s-buy.itunes.apple.com" % session.pod)
    hosts.append("https://buy.itunes.apple.com")
    for index in range(1, 6):
        host = "https://p%d-buy.itunes.apple.com" % index
        if host not in hosts:
            hosts.append(host)
    return hosts


def store_purchase(session, app_id, proxy="", timeout=60):
    """"""
    guid = _machine_guid()
    body = urllib.parse.urlencode({
        "guid": guid,
        "salableAdamId": str(app_id),
        "productType": "C",
        "pricingParameters": "STDQ",
    }).encode("utf-8")
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "User-Agent": CONFIGURATOR_UA,
        "iCloud-DSID": session.dsid,
        "X-Dsid": session.dsid,
    }
    if session.token:
        headers["X-Token"] = session.token
    if session.storefront:
        headers["X-Apple-Store-Front"] = session.storefront
    last = ""
    for host in _store_hosts(session):
        url = host + STORE_PURCHASE_PATH + "?guid=" + guid
        try:
            data = _http_post_bytes(url, body, headers, proxy, timeout)
        except Exception as exc:
            last = str(exc)
            continue
        if not data:
            last = "空响应"
            continue
        return True, data
    return False, last or "无法连接 App Store 服务"


def store_download_product(session, app_id, external_version_id, proxy="", timeout=90):
    """"""
    guid = _machine_guid()
    body = urllib.parse.urlencode({
        "creditDisplay": "",
        "guid": guid,
        "salableAdamId": str(app_id),
        "appExtVrsId": str(external_version_id or "0"),
    }).encode("utf-8")
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "User-Agent": CONFIGURATOR_UA,
        "iCloud-DSID": session.dsid,
        "X-Dsid": session.dsid,
    }
    if session.token:
        headers["X-Token"] = session.token
    if session.storefront:
        headers["X-Apple-Store-Front"] = session.storefront

    errors = []
    for host in _store_hosts(session):
        url = host + STORE_DOWNLOAD_PATH + "?guid=" + guid
        try:
            data = _http_post_bytes(url, body, headers, proxy, timeout)
        except Exception as exc:
            errors.append("%s -> %s" % (host.split("//")[-1], str(exc)[:80]))
            continue
        if not data:
            errors.append("%s -> 空响应" % host.split("//")[-1])
            continue
        try:
            import plistlib
            pl = plistlib.loads(data)
        except Exception:
            errors.append("%s -> 响应不是有效数据" % host.split("//")[-1])
            continue

        failure = _plist_find(pl, "failureType")
        message = _plist_find(pl, "customerMessage")
        if failure and str(failure).strip():
            errors.append("%s -> %s" % (host.split("//")[-1], str(message or failure)[:80]))
            continue

        ipa_url = _plist_find(pl, "software-package")
        sinfs = _plist_find(pl, "sinfs") or []
        metadata = _plist_find(pl, "metadata")
        if not ipa_url:
            errors.append("%s -> 未返回下载地址" % host.split("//")[-1])
            continue
        return {
            "ipa_url": str(ipa_url),
            "sinfs": sinfs if isinstance(sinfs, (list, tuple)) else ([sinfs] if sinfs else []),
            "metadata": metadata,
            "storefront": session.storefront,
        }, None
    return None, "；".join(errors[:3]) or "未能取得下载地址"


def session_from_auth_info(out):
    """"""
    for record in _json_records(out or ""):
        if not isinstance(record, dict):
            continue
        dsid = str(record.get("directory_services_id") or "").strip()
        if not dsid or not dsid.isdigit():
            continue
        return StoreSession(
            dsid=dsid,
            token=str(record.get("password_token") or "").strip(),
            storefront=str(record.get("store_front") or "").strip(),
            pod=str(record.get("pod") or "").strip(),
            email=str(record.get("email") or "").strip(),
            name=str(record.get("name") or "").strip(),
        )
    return None


def _find_app_dir(zf):
    for info in zf.infolist():
        name = info.filename
        if not name.startswith("Payload/"):
            continue
        rest = name[len("Payload/"):]
        if "/" not in rest:
            continue
        app_name, file_name = rest.split("/", 1)
        if app_name.endswith(".app") and file_name == "Info.plist":
            return "Payload/%s/" % app_name
    return ""


def _read_plist_member(zf, path):
    try:
        with zf.open(path) as fh:
            return plistlib.loads(fh.read())
    except Exception:
        return None


def _sinf_bytes(item):
    if isinstance(item, bytes):
        return item
    if isinstance(item, dict):
        for key in ("sinf", "Sinf", "data"):
            value = item.get(key)
            if isinstance(value, bytes):
                return value
    return b""


def patch_ipa(src, dest, sinfs, metadata, email):
    """"""
    with zipfile.ZipFile(src, "r") as zin:
        app_dir = _find_app_dir(zin)
        manifest = {}
        if app_dir:
            manifest = _read_plist_member(zin, app_dir + "SC_Info/Manifest.plist") or {}
        sinf_paths = [str(x) for x in (manifest.get("SinfPaths") or [])]

        if not sinf_paths and app_dir:
            info = _read_plist_member(zin, app_dir + "Info.plist") or {}
            exe = str(info.get("CFBundleExecutable") or "").strip()
            if exe:
                sinf_paths = ["SC_Info/%s.sinf" % exe]

        with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zout:
            for info in zin.infolist():
                zi = zipfile.ZipInfo(info.filename, date_time=info.date_time)
                zi.compress_type = info.compress_type
                zi.external_attr = info.external_attr
                zi.internal_attr = info.internal_attr
                zi.create_system = info.create_system
                if info.flag_bits & 0x800:
                    zi.flag_bits |= 0x800
                try:
                    payload = zin.read(info.filename)
                except Exception:
                    payload = b""
                zout.writestr(zi, payload)

            meta = dict(metadata) if isinstance(metadata, dict) else {}
            meta["apple-id"] = email or ""
            meta["userName"] = email or ""
            try:
                buf = plistlib.dumps(meta, fmt=plistlib.FMT_BINARY)
            except Exception:
                buf = plistlib.dumps({"apple-id": email or "", "userName": email or ""},
                                      fmt=plistlib.FMT_BINARY)
            zi = zipfile.ZipInfo("iTunesMetadata.plist")
            zi.compress_type = zipfile.ZIP_STORED
            zi.external_attr = 0o644 << 16
            zout.writestr(zi, buf)

            for idx, sinf in enumerate(sinfs or []):
                data = _sinf_bytes(sinf)
                if not data:
                    continue
                if idx < len(sinf_paths):
                    path = (app_dir + sinf_paths[idx]) if app_dir else sinf_paths[idx]
                else:
                    path = (app_dir + "SC_Info/%d.sinf" % idx) if app_dir else "SC_Info/%d.sinf" % idx
                zi = zipfile.ZipInfo(path)
                zi.compress_type = zipfile.ZIP_STORED
                zi.external_attr = 0o644 << 16
                zout.writestr(zi, data)
    return True


def store_download_ipa(session, app_id, version_id, dest, proxy="",
                       progress_cb=None, timeout=120):
    """"""
    info, err = store_download_product(session, app_id, version_id, proxy, timeout)
    if not info:
        return False, err or "未能取得下载地址"

    tmp = dest + ".tmp"
    url = info["ipa_url"]
    written = [0]
    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        opener = _build_opener(proxy)
        req = urllib.request.Request(
            url, headers={"User-Agent": CONFIGURATOR_UA, "Accept": "*/*"})
        with opener.open(req, timeout=timeout) as resp:
            total = 0
            try:
                total = int(resp.headers.get("Content-Length") or 0)
            except Exception:
                total = 0
            with open(tmp, "wb") as fh:
                while True:
                    chunk = resp.read(262144)
                    if not chunk:
                        break
                    fh.write(chunk)
                    written[0] += len(chunk)
                    if progress_cb and total:
                        try:
                            progress_cb(min(99, int(written[0] * 100 / total)))
                        except Exception:
                            pass
    except Exception as exc:
        try:
            if os.path.isfile(tmp):
                os.remove(tmp)
        except Exception:
            pass
        return False, "下载 IPA 失败：%s" % str(exc)[:120]

    try:
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        patch_ipa(tmp, dest, info.get("sinfs") or [], info.get("metadata") or {},
                  session.email or "")
    except Exception as exc:
        try:
            if os.path.isfile(tmp):
                os.remove(tmp)
        except Exception:
            pass
        return False, "写入签名失败：%s" % str(exc)[:120]

    try:
        if os.path.isfile(tmp):
            os.remove(tmp)
    except Exception:
        pass
    if progress_cb:
        try:
            progress_cb(100)
        except Exception:
            pass
    return True, dest


def _no_window_flags():
    if os.name != "nt":
        return {}
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = 0
    return {"startupinfo": si, "creationflags": subprocess.CREATE_NO_WINDOW}


def _windows_system_proxy():
    if os.name != "nt":
        return ""
    try:
        import winreg
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            enabled = int(winreg.QueryValueEx(key, "ProxyEnable")[0])
            server = str(winreg.QueryValueEx(key, "ProxyServer")[0]).strip()
        if not enabled or not server:
            return ""
        if ";" in server or "=" in server:
            values = {}
            for item in server.split(";"):
                if "=" in item:
                    name, value = item.split("=", 1)
                    values[name.strip().lower()] = value.strip()
            server = values.get("https") or values.get("http") or values.get("socks") or ""
        if not server:
            return ""
        return server if "://" in server else "http://" + server
    except Exception:
        return ""


_local_proxy_cache = None


def _normalize_proxy(value):
    value = (value or "").strip().strip('"').strip("'")
    if not value:
        return ""
    return value if "://" in value else "http://" + value


def _http_proxy_for_ipatool(proxy_url):
    if not proxy_url:
        return ""
    low = proxy_url.lower()
    if low.startswith("http://") or low.startswith("https://"):
        return proxy_url
    if not low.startswith("socks"):
        return proxy_url
    # HTTP_PROXY/HTTPS_PROXY accepts an HTTP proxy URL here.  A SOCKS
    # endpoint must not be mislabeled as HTTP; doing so causes confusing
    # connection resets and was the source of several failed sign-ins.
    return ""


def _env_proxy():
    for name in ("HTTPS_PROXY", "https_proxy", "ALL_PROXY", "all_proxy",
                 "HTTP_PROXY", "http_proxy"):
        value = _normalize_proxy(os.environ.get(name) or "")
        if value:
            return value
    return ""


def _detect_local_proxy():
    global _local_proxy_cache
    if _local_proxy_cache is not None:
        return _local_proxy_cache
    found = ""
    for port in _LOCAL_PROXY_PORTS:
        sock = socket.socket()
        sock.settimeout(0.35)
        try:
            sock.connect(("127.0.0.1", port))
            found = "http://127.0.0.1:%d" % port
        except Exception:
            pass
        finally:
            try:
                sock.close()
            except Exception:
                pass
        if found:
            break
    _local_proxy_cache = found
    return found


def _resolve_proxy(use_proxy=True):
    if not use_proxy:
        return ""
    if PROXY_MODE == "direct":
        return ""
    if PROXY_MODE == "custom":
        return _normalize_proxy(PROXY_CUSTOM)
    system = _windows_system_proxy()
    if system:
        return system
    env = _env_proxy()
    if env:
        return env
    return _detect_local_proxy()


def _candidate_proxies():
    """"""
    if PROXY_MODE == "direct":
        return [""]
    if PROXY_MODE == "custom":
        value = _normalize_proxy(PROXY_CUSTOM)
        return [value] if value else [""]
    ordered = []
    for value in (_windows_system_proxy(), _env_proxy(), _detect_local_proxy()):
        if value and value not in ordered:
            ordered.append(value)
    ordered.append("")
    return ordered


_LOCAL_PROXY_PORTS = (
    7890, 7891, 7897, 7898, 7899,
    1080, 1081, 1087, 10808, 10809, 10810,
    20171, 2080, 2081, 8888, 8889, 8080, 8081, 4780,
)

_AUTO_EXIT_STATE = {"checked": False, "proxy": None, "score": 0}

_LAST_LOGIN_ROUTES = []


def _get_login_challenge_proxy():
    """Return the route that created the current Apple 2FA challenge."""
    with _LOGIN_CHALLENGE_PROXY_LOCK:
        return _LOGIN_CHALLENGE_PROXY


def _set_login_challenge_proxy(proxy):
    global _LOGIN_CHALLENGE_PROXY
    with _LOGIN_CHALLENGE_PROXY_LOCK:
        _LOGIN_CHALLENGE_PROXY = proxy or ""


def _clear_login_challenge_proxy():
    global _LOGIN_CHALLENGE_PROXY
    with _LOGIN_CHALLENGE_PROXY_LOCK:
        _LOGIN_CHALLENGE_PROXY = None


def _port_open(host, port, timeout=0.3):
    try:
        sock = socket.create_connection((host, port), timeout=timeout)
        sock.close()
        return True
    except Exception:
        return False


def _exit_candidates(max_items=8):
    ordered = [""]
    for value in _candidate_proxies():
        if value and value not in ordered:
            ordered.append(value)
    for port in _LOCAL_PROXY_PORTS:
        if len(ordered) >= max_items:
            break
        if not _port_open("127.0.0.1", port):
            continue
        for value in ("http://127.0.0.1:%d" % port, "socks5://127.0.0.1:%d" % port):
            if value not in ordered and len(ordered) < max_items:
                ordered.append(value)
    if "" not in ordered:
        if len(ordered) >= max_items:
            ordered[-1] = ""
        else:
            ordered.append("")
    return ordered


_PROBE_EMAIL = "route-probe-notreal@example.com"
_PROBE_PASSWORD = "RouteProbe12345"


def _probe_exit_score(proxy_url, attempts=2, timeout=45):
    best = 0
    for _ in range(max(1, attempts)):
        score = _probe_exit_once(proxy_url, timeout=timeout)
        if score > best:
            best = score
        if best >= 3:
            break
    return best


def _probe_exit_once(proxy_url, timeout=45):
    if not IPATOOL_PATH or not os.path.exists(IPATOOL_PATH):
        return 0
    probe_root = tempfile.mkdtemp(prefix="iOSOldApp_probe_")
    probe_home = os.path.join(probe_root, "engine_home")
    env = os.environ.copy()
    drive, home_path = os.path.splitdrive(os.path.abspath(probe_home))
    env["HOMEDRIVE"] = drive
    env["HOMEPATH"] = home_path
    env["USERPROFILE"] = probe_home
    env["HOME"] = probe_home
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
                 "http_proxy", "https_proxy", "all_proxy"):
        env.pop(name, None)
    proxy_url = _http_proxy_for_ipatool(proxy_url)
    if proxy_url:
        for name in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
            env[name] = proxy_url
    command = [IPATOOL_PATH, "--keychain-passphrase", KEYCHAIN_PASSPHRASE,
               "auth", "login", "--email", _PROBE_EMAIL,
               "--password", _PROBE_PASSWORD, "--non-interactive", "--format", "json"]
    out = ""
    try:
        r = subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True,
                           text=True, errors="replace", timeout=timeout,
                           env=env, **_no_window_flags())
        out = re.sub(r"\x1b\[[0-9;]*m", "", (r.stdout or "") + (r.stderr or "")).strip()
    except Exception:
        return 0
    finally:
        try:
            shutil.rmtree(probe_root, ignore_errors=True)
        except Exception:
            pass
    low = out.lower()
    if "something went wrong" in low:
        return 0
    if any(k in low for k in ("incorrect", "invalid", "not found", "locked",
                              "disabled", "auth-code", "verification")):
        return 3
    if _is_transient_apple_edge_error(out):
        return 0
    if '"success":true' in out.replace(" ", ""):
        return 3
    return 1


def _auto_pick_exit():
    if _AUTO_EXIT_STATE["checked"]:
        return _AUTO_EXIT_STATE["proxy"], _AUTO_EXIT_STATE["score"]
    candidates = _exit_candidates()
    scores = {}
    lock = threading.Lock()

    def _work(url):
        score = _probe_exit_score(url)
        with lock:
            scores[url] = score

    threads = []
    for url in candidates:
        t = threading.Thread(target=_work, args=(url,), daemon=True)
        t.start()
        threads.append(t)
    for t in threads:
        t.join(timeout=70)

    best, best_score = None, 0
    for url in candidates:
        score = scores.get(url, 0)
        if score > best_score:
            best, best_score = url, score
    _AUTO_EXIT_STATE["checked"] = True
    _AUTO_EXIT_STATE["proxy"] = best if best_score > 0 else None
    _AUTO_EXIT_STATE["score"] = best_score
    return _AUTO_EXIT_STATE["proxy"], best_score


def _reset_auto_exit():
    _AUTO_EXIT_STATE["checked"] = False
    _AUTO_EXIT_STATE["proxy"] = None
    _AUTO_EXIT_STATE["score"] = 0


# ─────────────────────────────────────────────
# ─────────────────────────────────────────────

def _parse_proxy_url(proxy_url):
    from urllib.parse import urlparse, unquote
    if not proxy_url or not str(proxy_url).strip():
        return None
    try:
        raw = str(proxy_url).strip()
        if "://" not in raw:
            raw = "http://" + raw
        parsed = urlparse(raw)
        scheme = (parsed.scheme or "").lower()
        host = parsed.hostname
        if not host:
            return None
        default_port = 1080 if scheme.startswith("socks") else 80
        return {
            "scheme": scheme,
            "host": host,
            "port": parsed.port or default_port,
            "user": unquote(parsed.username) if parsed.username else "",
            "pwd": unquote(parsed.password) if parsed.password else "",
        }
    except Exception:
        return None


def _socks5_connect(proxy, host, port, timeout=15):
    sock = socket.create_connection((proxy["host"], proxy["port"]), timeout=timeout)
    try:
        if proxy["user"]:
            sock.sendall(b"\x05\x02\x00\x02")
        else:
            sock.sendall(b"\x05\x01\x00")
        reply = sock.recv(2)
        if len(reply) < 2 or reply[0] != 5:
            raise IOError("SOCKS5 握手失败")
        if reply[1] == 2:
            user_bytes = proxy["user"].encode("utf-8")
            pwd_bytes = proxy["pwd"].encode("utf-8")
            sock.sendall(b"\x05" + bytes([len(user_bytes)]) + user_bytes +
                         bytes([len(pwd_bytes)]) + pwd_bytes)
            auth_reply = sock.recv(2)
            if len(auth_reply) < 2 or auth_reply[1] != 0:
                raise IOError("SOCKS5 账号密码认证失败")
        try:
            host_bytes = host.encode("idna")
        except Exception:
            host_bytes = host.encode("utf-8")
        sock.sendall(b"\x05\x01\x00\x03" + bytes([len(host_bytes)]) + host_bytes +
                     port.to_bytes(2, "big"))
        head = sock.recv(4)
        if len(head) < 4 or head[1] != 0:
            raise IOError("SOCKS5 连接被拒绝")
        if head[3] == 1:
            sock.recv(6)
        elif head[3] == 3:
            length = sock.recv(1)
            if length:
                sock.recv(length[0] + 2)
        elif head[3] == 4:
            sock.recv(18)
        return sock
    except Exception:
        try:
            sock.close()
        except Exception:
            pass
        raise


def _proxy_socket(host, port, proxy_url, timeout=15):
    proxy = _parse_proxy_url(proxy_url)
    if not proxy:
        return socket.create_connection((host, port), timeout=timeout)
    if proxy["scheme"].startswith("socks"):
        return _socks5_connect(proxy, host, port, timeout=timeout)
    sock = socket.create_connection((proxy["host"], proxy["port"]), timeout=timeout)
    try:
        request = "CONNECT %s:%d HTTP/1.1\r\nHost: %s:%d\r\n" % (host, port, host, port)
        if proxy["user"]:
            credential = base64.b64encode(
                ("%s:%s" % (proxy["user"], proxy["pwd"])).encode("utf-8")).decode()
            request += "Proxy-Authorization: Basic %s\r\n" % credential
        request += "User-Agent: ios-old-app-downloader\r\nProxy-Connection: keep-alive\r\n\r\n"
        sock.sendall(request.encode("latin1"))
        data = b""
        while b"\r\n\r\n" not in data and len(data) < 65536:
            chunk = sock.recv(4096)
            if not chunk:
                break
            data += chunk
        first_line = data.split(b"\r\n")[0].decode("latin1", "replace")
        if " 200 " not in first_line:
            raise IOError("代理拒绝连接：%s" % first_line[:70])
        return sock
    except Exception:
        try:
            sock.close()
        except Exception:
            pass
        raise


_DIAG_PLIST = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
    '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">'
    '<plist version="1.0"><dict>'
    '<key>appleId</key><string>probe@example.com</string>'
    '<key>password</key><string>probe</string>'
    '<key>attempt</key><string>1</string>'
    '<key>guid</key><string>0000000000000000000000000000000000000000</string>'
    '</dict></plist>'
)


def _diag_request(host, path, proxy_url, method="GET", body=None, timeout=15):
    sock = _proxy_socket(host, 443, proxy_url, timeout=timeout)
    try:
        context = ssl.create_default_context()
        sock = context.wrap_socket(sock, server_hostname=host)
        payload = (body or "").encode("utf-8")
        header = "%s %s HTTP/1.1\r\nHost: %s\r\n" % (method, path, host)
        header += ("User-Agent: Configurator/2.15 (Macintosh; OS X 12.6; 16G29) "
                   "AppleWebKit/2603.1.30.0.1\r\n")
        header += "Accept: */*\r\n"
        if payload:
            header += "Content-Type: application/x-www-form-urlencoded\r\n"
            header += "Content-Length: %d\r\n" % len(payload)
        header += "Connection: close\r\n\r\n"
        sock.settimeout(timeout)
        sock.sendall(header.encode("latin1") + payload)
        data = b""
        while b"\r\n\r\n" not in data and len(data) < 65536:
            chunk = sock.recv(8192)
            if not chunk:
                break
            data += chunk
        head_text = data.partition(b"\r\n\r\n")[0]
        lines = head_text.split(b"\r\n")
        status = 0
        if lines:
            parts = lines[0].split()
            if len(parts) >= 2:
                try:
                    status = int(parts[1])
                except Exception:
                    status = 0
        headers = {}
        for line in lines[1:]:
            if b":" in line:
                key, value = line.split(b":", 1)
                headers[key.strip().lower().decode("latin1", "replace")] = \
                    value.strip().decode("latin1", "replace")
        return status, headers
    finally:
        try:
            sock.close()
        except Exception:
            pass


_DIAG_TARGETS = (
    ("商店配置 bag", "init.itunes.apple.com", "/bag.xml", "GET", None),
    ("认证端点（传统）", "buy.itunes.apple.com",
     "/WebObjects/MZFinance.woa/wa/authenticate", "POST", _DIAG_PLIST),
    ("认证端点（新版）", "auth.itunes.apple.com",
     "/auth/v1/native/fast/", "POST", _DIAG_PLIST),
    ("应用查询接口", "itunes.apple.com", "/lookup?id=310633997&country=US", "GET", None),
)


def diagnose_apple_network(proxy_url=""):
    results = []
    for label, host, path, method, body in _DIAG_TARGETS:
        started = time.time()
        try:
            status, headers = _diag_request(host, path, proxy_url,
                                            method=method, body=body, timeout=15)
            results.append({
                "label": label, "host": host, "status": status,
                "ms": int((time.time() - started) * 1000),
                "location": headers.get("location", ""), "error": "",
            })
        except Exception as exc:
            results.append({
                "label": label, "host": host, "status": 0,
                "ms": int((time.time() - started) * 1000),
                "location": "", "error": str(exc),
            })
    return results


def _diag_conclusion(results):
    mapped = {}
    for item in results:
        mapped[item["label"]] = item
    bag = mapped.get("商店配置 bag")
    legacy = mapped.get("认证端点（传统）")
    native = mapped.get("认证端点（新版）")
    lookup = mapped.get("应用查询接口")

    blocked_status = (204, 301, 404, 503)
    if all(item["error"] for item in results):
        return ("blocked", localized(
            "当前网络完全无法连通 Apple 服务。\n请检查：① 代理地址与端口是否正确；② 代理软件是否已开启；③ 防火墙是否拦截。",
            "This network cannot reach Apple services.\nCheck the proxy address and port, whether the proxy is running, and whether a firewall is blocking the app."))

    if bag and not bag["error"] and bag["status"] != 200:
        return ("blocked", localized(
            "Apple 商店配置接口返回 HTTP %d，当前网络出口不被 Apple 接受。\n建议更换代理节点（优先选择美国 / 日本 / 香港等海外节点）后重新诊断。",
            "Apple's store configuration endpoint returned HTTP %d, so this network exit was not accepted.\nTry another proxy route and run the check again.") % bag["status"])

    auth_ok = False
    if legacy and not legacy["error"]:
        if legacy["status"] in (200, 302) or legacy["location"]:
            auth_ok = True
    if native and not native["error"] and native["status"] in (200, 302):
        auth_ok = True

    if auth_ok:
        detail = []
        if legacy and legacy["status"] == 302 and legacy["location"]:
            detail.append("传统认证端点已正常返回跳转地址")
        if native and native["status"] in (200, 302):
            detail.append("新版认证端点响应正常")
        suffix = ("（%s）" % "、".join(detail)) if detail else ""
        suffix_en = (" (%s)" % ", ".join(
            "legacy sign-in endpoint returned a redirect" if "传统" in item else
            "native sign-in endpoint responded normally" for item in detail)) if detail else ""
        return ("ok", localized(
            "网络检查通过，Apple 登录认证链路可用%s。\n可以直接回到主界面登录；若仍失败，多为账号本身需要验证码或条款确认。" % suffix,
            "Network check passed; Apple sign-in is reachable%s.\nReturn to the main window and sign in. If it still fails, the account may need a code or terms confirmation." % suffix_en))

    rejected = []
    for item in (legacy, native):
        if item and not item["error"] and item["status"] in blocked_status:
            rejected.append("%s HTTP %d" % (item["host"], item["status"]))
    if rejected:
        return ("blocked", localized(
            "Apple 认证服务拒绝了当前网络出口：%s。\n这正是登录报「something went wrong」/「failed to retrieve redirect location」的原因。\n\n解决办法：在上方「代理」里填入一个海外代理节点（美国 / 日本 / 新加坡等），保存后重新诊断，直到这里显示「认证端点」正常，再登录。",
            "Apple's sign-in service rejected this network exit: %s.\nThis causes errors such as \"something went wrong\" or \"failed to retrieve redirect location\".\n\nUse a working overseas proxy route, run the check again, and sign in after the endpoint passes.") % ", ".join(rejected))

    if lookup and lookup["error"]:
        return ("blocked", localized("应用查询接口无法连通（%s）。\n请更换代理节点后重新诊断。",
                                     "The app lookup API is unreachable (%s).\nTry another proxy route and run the check again.") % lookup["error"])

    return ("warning", localized("各端点响应存在异常，建议更换代理节点后重新诊断；若多次仍失败，请把诊断结果截图反馈。",
                                 "Some endpoints responded unexpectedly. Try another proxy route and run the check again; if it still fails, share a screenshot of the result."))


def _prepare_engine_home():
    """Prepare a stable HOME and seed ipatool-rs' verified SAP cache."""
    with _ENGINE_HOME_LOCK:
        os.makedirs(IPATOOL_SESSION_HOME, exist_ok=True)
        source_cache = os.path.join(IPATOOL_SEED_ROOT, ".ipatool", "cache")
        if not os.path.isdir(source_cache):
            return
        target_cache = os.path.join(IPATOOL_SESSION_HOME, ".ipatool", "cache")
        for source_dir, _dirs, filenames in os.walk(source_cache):
            relative = os.path.relpath(source_dir, source_cache)
            target_dir = target_cache if relative == "." else os.path.join(target_cache, relative)
            os.makedirs(target_dir, exist_ok=True)
            for filename in filenames:
                source = os.path.join(source_dir, filename)
                target = os.path.join(target_dir, filename)
                try:
                    same = os.path.isfile(target) and os.path.getsize(target) == os.path.getsize(source)
                except OSError:
                    same = False
                if same:
                    continue
                temporary = target + ".seed-copy"
                shutil.copy2(source, temporary)
                os.replace(temporary, target)


def _ipatool_command(args):
    """"""
    return [IPATOOL_PATH, "--keychain-passphrase", KEYCHAIN_PASSPHRASE] + list(args)


def _clear_runtime_auth(revoke=True):
    """"""
    tool = IPATOOL_PATH
    if revoke and tool and os.path.exists(tool):
        env = os.environ.copy()
        env["HOME"] = IPATOOL_SESSION_HOME
        for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
                     "http_proxy", "https_proxy", "all_proxy"):
            env.pop(name, None)
        try:
            subprocess.run(
                _ipatool_command(["auth", "revoke", "--format", "json", "--non-interactive"]),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=25,
                env=env,
                **_no_window_flags()
            )
        except Exception as exc:
            _diagnostic("auth_cleanup_exception", repr(exc))
    try:
        shutil.rmtree(IPATOOL_SESSION_HOME, ignore_errors=True)
    except Exception as exc:
        _diagnostic("auth_session_cleanup_exception", repr(exc))


atexit.register(_clear_runtime_auth)


def _ipatool_env(for_login=False, use_proxy=True, proxy=None):
    _prepare_engine_home()
    env = os.environ.copy()
    env["HOME"] = IPATOOL_SESSION_HOME
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
                 "http_proxy", "https_proxy", "all_proxy"):
        env.pop(name, None)
    env.pop("IPATOOL_AUTH_ENDPOINT", None)
    env.pop("IPATOOL_NO_PASSWORD_STORAGE", None)
    if proxy is None:
        proxy = _resolve_proxy(use_proxy)
    proxy = _http_proxy_for_ipatool(proxy)
    if proxy:
        env["HTTP_PROXY"] = proxy
        env["HTTPS_PROXY"] = proxy
        env["http_proxy"] = proxy
        env["https_proxy"] = proxy
    return env


def _json_records(text):
    """"""
    value = text or ""
    decoder = json.JSONDecoder()
    pos = 0
    while pos < len(value):
        starts = [i for i in (value.find("{", pos), value.find("[", pos)) if i >= 0]
        if not starts:
            break
        start = min(starts)
        try:
            record, end = decoder.raw_decode(value, start)
        except Exception:
            pos = start + 1
            continue
        yield record
        pos = end


def _auth_result(rc, out):
    text = (out or "").strip()
    low = text.lower()
    code_markers = (
        "2fa code is required", "2fa code required", "2fa code",
        "auth code is required", "auth code required", "auth_code_required",
        "two-factor authentication", "two factor authentication",
        "two-factor code", "two factor code", "verification code",
        "verification_code", "--auth-code", "双重认证", "两步验证",
        "验证码", "受信任设备",
    )
    needs_code = any(k in low for k in code_markers)
    success = False
    identity = ""
    for record in _json_records(text):
        if not isinstance(record, dict):
            continue
        record_text = " ".join(
            str(record.get(k, ""))
            for k in ("message", "error", "reason", "detail", "status", "code"))
        record_low = record_text.lower()
        if any(k in record_low for k in code_markers):
            needs_code = True
        if any(str(key).lower() in (
                "auth_code_required", "two_factor_required", "verification_required")
                and bool(value) for key, value in record.items()):
            needs_code = True
        if record.get("success") is True:
            success = True
            identity = str(record.get("email") or record.get("name") or "").strip()
        elif record.get("email") and (
                "password_token" in record or "directory_services_id" in record or
                (record.get("name") is not None and record.get("store_front") is not None)):
            success = True
            identity = str(record.get("email") or record.get("name") or "").strip()
    if not success and re.search(r"\bsuccess\s*[=:]\s*true\b", low):
        success = True
        match = re.search(r"[\w.+-]+@[\w.-]+", text)
        identity = match.group(0) if match else ""
    # Interactive ipatool output keeps the earlier 2FA prompt in the same
    # stream even after the submitted code succeeds. A confirmed success JSON
    # must therefore take precedence over stale prompt text.
    if rc == 0 and success:
        return True, False, identity
    return False, needs_code, identity


def _is_retryable_login_error(out):
    low = (out or "").lower()
    if _is_transient_apple_edge_error(out):
        return True
    return any(k in low for k in (
        "unexpected eof", "eof occurred", "connection reset", "connection refused",
        "connection closed", "timed out", "timeout", "network is unreachable",
        "no such host", "tls handshake", "ssl error", "failed to fetch bag",
        "failed to establish a sap signing session", "failed to retrieve redirect",
        "empty response", "empty or non-plist body", "http 408", "http 409",
        "http 425", "http 429", "http 500", "http 502", "http 503", "http 504",
    )) or not low.strip()


def _route_summary():
    try:
        routes = list(_LAST_LOGIN_ROUTES) or _candidate_proxies()
    except Exception:
        routes = [""]
    names = []
    for value in routes:
        label = value if value else localized("直连", "Direct")
        if label not in names:
            names.append(label)
    return localized("、", ", ").join(names)


def _network_blocked_tip():
    tried = len(_LAST_LOGIN_ROUTES) or 1
    return localized(
        "\n\n本软件已自动轮换「系统代理 / 本机已监听的代理端口 / 直连」共 %d 条线路依次重试，全部被 Apple 认证服务拒绝或超时。\n这属于 Apple 对当前网络环境的间歇性限制（同一条线路时好时坏），不是账号问题。\n建议：等 1～2 分钟后直接再点一次「登录」，软件会自动重新轮换线路重试；也可以改用手机热点（4G/5G）后再试。",
        "\n\nThe app automatically retried %d routes (system proxy, local proxy ports, and direct connection), but Apple rejected or timed out on all of them.\nThis is an intermittent restriction on the current network environment, not necessarily an account problem.\nWait 1–2 minutes and try again; a phone hotspot may also help.") % tried


def _friendly_auth_error(out):
    text = (out or "").strip()
    low = text.lower()
    if ("failed to retrieve redirect location" in low
            or "something went wrong" in low):
        return localized(
            "Apple 认证服务拒绝了当前网络出口（软件已自动尝试：%s）。\n这是 Apple 对大陆网络的已知限制，不是你的账号问题。%s",
            "Apple rejected the current network exit (routes tried: %s).\nThis is a known restriction affecting some mainland-China networks and is not necessarily an account problem.%s") % (_route_summary(), _network_blocked_tip())
    if _is_transient_apple_edge_error(text):
        return localized(
            "Apple 认证服务未返回有效响应，当前网络出口被限制（软件已自动尝试：%s，仍未通过）。%s",
            "Apple did not return a valid response; the current network exit may be restricted (routes tried: %s).%s") % (_route_summary(), _network_blocked_tip())
    if "failed to establish a sap signing session" in low:
        return localized("Apple 安全登录组件初始化失败，请检查网络后重新登录。",
                         "Apple's secure sign-in component failed to initialize. Check the network and try again.")
    if "not logged in" in low:
        return localized("当前尚未登录。", "You are not signed in.")
    if "login rejected" in low and "auth-code" in low:
        return localized("Apple 要求继续验证。若设备已收到验证码，请输入 6 位验证码后提交。",
                         "Apple requires additional verification. If your trusted device received a code, enter the 6-digit code and submit it.")
    messages = []
    for record in _json_records(text):
        if isinstance(record, dict):
            value = str(record.get("error") or record.get("message") or "").strip()
            if value and value not in messages:
                messages.append(value)
    if messages:
        return "\n".join(messages)[-500:]
    return text[-500:] or localized("没有收到可确认的登录结果，请重新尝试。",
                                    "No confirmable sign-in result was received. Try again.")


def _is_transient_apple_edge_error(out):
    low = (out or "").lower()
    if re.search(r"http[)\s:]*\s*(204|301|302|307|404|429|500|502|503|504)", low):
        return True
    if re.search(r"\b(204|301|302|404|500|502|503|504)\b[^\n]{0,24}(forbidden|not found|"
                 r"unavailable|no content|moved permanently|bad gateway)", low):
        return True
    return any(k in low for k in (
        "empty or non-plist body",
        "failed to retrieve redirect location",
        "authentication edge returned no account response",
        "invalid type: string \"<html>\"",
        "expected a map",
        "something went wrong"))


def _redact_engine_output(out):
    value = out or ""
    return re.sub(
        r'("(?:password|password_token|directory_services_id)"\s*:\s*)"(?:[^"\\]|\\.)*"',
        r'\1"***"', value, flags=re.IGNORECASE)


def run_tool(args, timeout=120, proxy=None):
    tool = IPATOOL_PATH
    if not tool or not os.path.exists(tool):
        return -1, "ipatool.exe not found"
    command = _ipatool_command(args)
    is_login = len(args) >= 2 and list(args[:2]) == ["auth", "login"]
    has_auth_code = is_login and "--auth-code" in args
    if proxy is not None:
        routes = [proxy]
    elif is_login:
        routes = _candidate_proxies()
        # Apple can bind a verification challenge to the network/session that
        # created it. Reuse that route first when submitting the code instead
        # of silently starting with a different proxy on every attempt.
        challenge_proxy = _get_login_challenge_proxy() if has_auth_code else None
        if challenge_proxy is not None:
            routes = [challenge_proxy] + [route for route in routes if route != challenge_proxy]
    else:
        routes = [_resolve_proxy()]
    routes = routes or [""]
    if is_login:
        _LAST_LOGIN_ROUTES[:] = routes
    with IPATOOL_PROCESS_LOCK:
        last_rc, last_out = -3, ""
        for route_index, proxy in enumerate(routes):
            try:
                r = subprocess.run(
                    command,
                    stdin=subprocess.DEVNULL,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=timeout,
                    env=_ipatool_env(for_login=is_login, proxy=proxy),
                    **_no_window_flags()
                )
            except subprocess.TimeoutExpired:
                last_rc, last_out = -2, "timeout after %ss" % timeout
                if is_login and route_index + 1 < len(routes):
                    time.sleep(0.8)
                    continue
                return last_rc, last_out
            except Exception as e:
                last_rc, last_out = -3, str(e)
                if is_login and route_index + 1 < len(routes):
                    time.sleep(0.8)
                    continue
                return last_rc, last_out
            out = re.sub(r"\x1b\[[0-9;]*m", "", (r.stdout or "") + (r.stderr or "")).strip()
            out = _redact_engine_output(out)
            last_rc, last_out = r.returncode, out
            if is_login:
                _logged, needs_code, _who = _auth_result(r.returncode, out)
                if needs_code:
                    _set_login_challenge_proxy(proxy)
                    return r.returncode, out
                if _logged:
                    _set_login_challenge_proxy(proxy)
                    return r.returncode, out
                if (_is_retryable_login_error(out)
                        and route_index + 1 < len(routes)):
                    time.sleep(1.0 + route_index * 0.5)
                    continue
                if not has_auth_code:
                    _clear_login_challenge_proxy()
            return r.returncode, out
        return last_rc, last_out or "登录请求未完成"


def check_login_status(ipatool_path=None):
    """"""
    tool = ipatool_path or IPATOOL_PATH
    if not tool or not os.path.exists(tool):
        return False, ""
    if tool != IPATOOL_PATH:
        return False, ""
    rc, out = run_tool(["auth", "info", "--format", "json"], timeout=60)
    logged, _, who = _auth_result(rc, out)
    return logged, ((who or "Apple ID") if logged else "")

# ─────────────────────────────────────────────
# ─────────────────────────────────────────────
class WorkerSignals(QObject):
    progress = pyqtSignal(int, int)
    result_line = pyqtSignal(str)
    finished = pyqtSignal()
    error = pyqtSignal(str)
    data = pyqtSignal(object)

class ToolWorker(QThread):
    done = pyqtSignal(int, str)

    def __init__(self, args, timeout=60, proxy=None):
        super().__init__()
        self.args = args
        self.timeout = timeout
        self.proxy = proxy

    def run(self):
        try:
            rc, out = run_tool(self.args, timeout=self.timeout, proxy=self.proxy)
        except Exception as exc:
            _diagnostic("tool_worker_exception", repr(exc))
            rc, out = -3, str(exc)
        self.done.emit(rc, out)


class NetworkDiagWorker(QThread):
    done = pyqtSignal(object)

    def run(self):
        try:
            results = diagnose_apple_network(_resolve_proxy())
        except Exception as exc:
            results = [{
                "label": "诊断异常", "host": "", "status": 0, "ms": 0,
                "location": "", "error": str(exc),
            }]
        self.done.emit(results)


class SearchWorker(QThread):
    def __init__(self, keyword, country="cn", limit=5):
        super().__init__()
        self.keyword = keyword
        self.country = country
        self.limit = limit
        self.signals = WorkerSignals()
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        try:
            self.signals.progress.emit(0, 1)
            apps = api_search_apps(self.keyword, self.country, limit=self.limit)
            if self._stop:
                return
            targets = [a for a in apps if a.get("icon_100")]
            for a in apps:
                a["icon_bytes"] = None
            if targets:
                with ThreadPoolExecutor(
                        max_workers=min(8, len(targets)),
                        thread_name_prefix="app-icon") as pool:
                    futures = {
                        pool.submit(_get_cached_icon, a.get("icon_100")): a
                        for a in targets
                    }
                    for future in as_completed(futures):
                        if self._stop:
                            break
                        app = futures[future]
                        try:
                            app["icon_bytes"] = future.result()
                        except Exception:
                            app["icon_bytes"] = None
            if not self._stop:
                self.signals.data.emit(apps)
        except Exception as e:
            self.signals.error.emit(str(e))
        finally:
            self.signals.finished.emit()

class HistoryWorker(QThread):
    def __init__(self, app_id, mode="local"):
        super().__init__()
        self.app_id = app_id
        self.mode = mode
        self.signals = WorkerSignals()
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        try:
            if self.mode == "apple":
                rows = api_fetch_history_apple(self.app_id)
            else:
                rows = api_fetch_history_local(self.app_id)
            if not self._stop:
                self.signals.data.emit(rows)
        except Exception as e:
            self.signals.error.emit(str(e))
        finally:
            self.signals.finished.emit()

class DownloadWorker(QThread):
    progress = pyqtSignal(str)
    progress_pct = pyqtSignal(int)
    task_update = pyqtSignal(str, object)
    finished = pyqtSignal(object)
    error = pyqtSignal(str)

    def __init__(self, email, task):
        super().__init__()
        self.email = email
        self.task = task
        self._stop = False
        self._action = ""
        self._proc = None
        self._last_activity = time.time()

    def pause(self):
        self._action = "paused"
        self._stop_process()

    def cancel(self):
        self._action = "cancelled"
        self._stop_process()

    def _stop_process(self):
        proc = self._proc
        if proc and proc.poll() is None:
            try:
                proc.terminate()
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass

    def run(self):
        q = self.task
        task_id = q["id"]
        result = {"id": task_id, "ok": False, "status": "failed", "path": q["out"],
                  "name": q.get("name", ""), "version": q.get("version", ""), "reason": ""}
        try:
            os.makedirs(os.path.dirname(q["out"]) or ".", exist_ok=True)
            existing = self._current_size(q)
            total = int(q.get("total") or 0)
            free = shutil.disk_usage(os.path.dirname(q["out"]) or ".").free
            remaining = max(0, total - existing) if total else 512 * 1024 * 1024
            reserve = max(64 * 1024 * 1024, min(256 * 1024 * 1024, int(total * 0.05))) if total else 0
            if free < remaining + reserve:
                need = remaining + reserve
                result["reason"] = localized(
                    "磁盘空间不足：当前可用 %s，本任务至少需要 %s。",
                    "Not enough disk space: %s is available, but this task needs at least %s.") % (
                        format_transfer_size(free), format_transfer_size(need))
                self.task_update.emit(task_id, {"status": "failed", "error": result["reason"]})
                self.progress.emit("[FAIL] " + result["reason"])
                self.finished.emit(result)
                return

            self.progress.emit("[START] %s %s ..." % (q.get("name", ""), q.get("version", "")))
            self.task_update.emit(task_id, {"status": "downloading", "error": ""})
            args = [
                "download",
                "--app-id", str(q["app_id"]),
                "--bundle-identifier", q["bundle"],
                "--version-id", str(q["version_id"]),
                "--output", q["out"],
                "--purchase",
                "--format", "json",
                "--non-interactive",
            ]
            status, reason = self._stream(q, args)
            result["status"] = status
            result["ok"] = status == "completed"
            result["reason"] = reason
        except Exception as e:
            result["reason"] = str(e)
            self.task_update.emit(task_id, {"status": "failed", "error": str(e)})
            self.error.emit(str(e))
        self.finished.emit(result)

    @staticmethod
    def _candidate_paths(q):
        # ipatool-rs 下载期间实际写入 .tmp；部分版本使用 .part。
        return (q["out"] + ".tmp", q["out"] + ".part", q["out"])

    def _current_size(self, q):
        for path in self._candidate_paths(q):
            try:
                if os.path.isfile(path):
                    return os.path.getsize(path)
            except OSError:
                pass
        return 0

    def _stream(self, q, args):
        env = _ipatool_env(for_login=False)
        command = _ipatool_command(args)
        proc = subprocess.Popen(command, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, env=env, text=True,
                                encoding="utf-8", errors="replace", bufsize=1,
                                **_no_window_flags())
        self._proc = proc
        self._last_activity = time.time()
        stall_timeout = 600
        monitor_stop = threading.Event()
        output_lines = []

        def _monitor_file():
            started = time.time()
            last_t = started
            last_size = self._current_size(q)
            speed = 0.0
            while not monitor_stop.wait(0.5):
                now = time.time()
                size = self._current_size(q)
                delta_t = max(0.001, now - last_t)
                if size > last_size:
                    instant = (size - last_size) / delta_t
                    speed = instant if speed <= 0 else (speed * 0.65 + instant * 0.35)
                    self._last_activity = now
                elif size < last_size:
                    speed = 0.0
                total = int(q.get("total") or 0)
                percent = min(99, int(size * 100 / total)) if total > 0 else -1
                eta = int((total - size) / speed) if total > size and speed > 1 else -1
                self.task_update.emit(q["id"], {
                    "status": "downloading", "downloaded": size, "total": total,
                    "speed": speed, "percent": percent,
                    "elapsed": int(now - started), "eta": eta,
                })
                if percent >= 0:
                    self.progress_pct.emit(percent)
                if proc.poll() is None and now - self._last_activity > stall_timeout:
                    self._action = "timeout"
                    self._stop_process()
                    self.progress.emit(localized("[TIMEOUT] 10 分钟没有收到数据，已停止本任务。",
                                                 "[TIMEOUT] No data was received for 10 minutes; this task was stopped."))
                    return
                last_t, last_size = now, size

        monitor = threading.Thread(target=_monitor_file, daemon=True)
        monitor.start()
        for raw in proc.stdout:
            piece = raw.strip()
            if piece:
                self._last_activity = time.time()
                output_lines.append(piece)
                if len(output_lines) > 80:
                    del output_lines[:20]
                m = re.search(r"(\d{1,3})\s*%", piece)
                if m:
                    self.progress_pct.emit(int(m.group(1)))
                    continue
                if not re.fullmatch(r"[\s\W]+", piece):
                    self.progress.emit(piece)
        proc.stdout.close()
        rc = proc.wait()
        monitor_stop.set()
        monitor.join(timeout=2)
        self._proc = None
        ok = rc == 0 and os.path.exists(q["out"]) and os.path.getsize(q["out"]) > 1024
        if ok:
            self.progress.emit("[OK] %s" % q["out"])
            self.progress_pct.emit(100)
            final_size = os.path.getsize(q["out"])
            self.task_update.emit(q["id"], {"status": "completed", "downloaded": final_size,
                                             "total": final_size, "speed": 0.0,
                                             "percent": 100, "eta": 0, "error": ""})
            return "completed", ""
        if self._action == "paused":
            self.task_update.emit(q["id"], {"status": "paused", "speed": 0.0})
            return "paused", ""
        if self._action == "cancelled":
            self.task_update.emit(q["id"], {"status": "cancelled", "speed": 0.0})
            return "cancelled", ""

        combined = "\n".join(output_lines)
        low = combined.lower()
        if "os error 112" in low or "存储空间不足" in combined or "磁盘空间不足" in combined:
            reason = localized("磁盘空间不足，未能写完 IPA。请更换下载目录或释放空间后继续。",
                               "There is not enough disk space to finish the IPA. Change the download folder or free space, then retry.")
        elif self._action == "timeout":
            reason = localized("下载长时间没有收到数据，请检查网络或代理后继续。",
                               "No data was received for a long time. Check the network or proxy, then retry.")
        else:
            reason = localized("下载失败（返回码 %s）。%s",
                               "Download failed (return code %s). %s") % (rc, output_lines[-1] if output_lines else "")
        self.progress.emit("[FAIL] %s %s：%s" % (q.get("name", ""), q.get("version", ""), reason))
        self.progress_pct.emit(0)
        self.task_update.emit(q["id"], {"status": "failed", "speed": 0.0, "error": reason})
        return "failed", reason

# ─────────────────────────────────────────────
# ─────────────────────────────────────────────
class TransparentMacWindow(QMainWindow):
    RESIZE_MARGIN = 7

    def __init__(self):
        super().__init__()
        self.current_app = None
        self.download_queue = []
        self.search_results = []
        self.history_rows = []
        self.history_mode = "apple"
        self._resizing = False
        self._resize_edge = None
        self._resize_start_pos = QPoint()
        self._resize_start_geom = QRect()
        self.dragging = False
        self.drag_start = QPoint()
        self.worker = None
        self._content_workers = set()
        self._search_generation = 0
        self._history_generation = 0
        self.download_monitor = None
        self._download_workers = {}
        self._download_session_ids = set()
        self._download_max_parallel = 10
        self.logged_in = False
        self._startup_login_tip = False
        self._threads = []
        self._pre_check_busy = False
        self._setup_window()
        self._setup_tray()
        self._init_ui()

    def _arm_startup_login_tip(self):
        self._startup_login_tip = True

    def _show_startup_login_tip(self):
        if not self._startup_login_tip or self.logged_in:
            return
        self._startup_login_tip = False
        MacStyleMessageBox(
            self, title=tr("startup_title"), message=startup_login_message(),
            icon_type="info", rich_message=True).exec()

    def _setup_window(self):
        self.setWindowTitle(tr("window_title"))
        self.setMinimumSize(820, 600)
        self.resize(WINDOW_WIDTH, WINDOW_HEIGHT)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowIcon(get_app_icon())
        self._first_show = True

    def showEvent(self, event):
        super().showEvent(event)
        if self._first_show:
            self._first_show = False
            QTimer.singleShot(100, self._bring_to_front)

    def _bring_to_front(self):
        self.raise_()
        self.activateWindow()

    def _setup_tray(self):
        try:
            self.tray_icon = QSystemTrayIcon(self)
            self.tray_icon.setIcon(get_app_icon())
            self.tray_icon.setToolTip(tr("tray_tip"))
            menu = QMenu()
            menu.addAction(tr("show_window"), self._show_normal)
            menu.addAction(tr("exit"), self._exit_app)
            self.tray_icon.setContextMenu(menu)
            self.tray_icon.show()
        except Exception:
            self.tray_icon = None

    def _detect_edge(self, pos):
        m = self.RESIZE_MARGIN
        parts = []
        if pos.y() < m:
            parts.append("top")
        if pos.y() > self.height() - m:
            parts.append("bottom")
        if pos.x() < m:
            parts.append("left")
        if pos.x() > self.width() - m:
            parts.append("right")
        return "_".join(parts) if parts else None

    _CURSOR_MAP = {
        "left": Qt.CursorShape.SizeHorCursor, "right": Qt.CursorShape.SizeHorCursor,
        "top": Qt.CursorShape.SizeVerCursor, "bottom": Qt.CursorShape.SizeVerCursor,
        "top_left": Qt.CursorShape.SizeFDiagCursor, "bottom_right": Qt.CursorShape.SizeFDiagCursor,
        "top_right": Qt.CursorShape.SizeBDiagCursor, "bottom_left": Qt.CursorShape.SizeBDiagCursor,
    }

    def _apply_edge_cursor(self, edge):
        if edge and edge in self._CURSOR_MAP:
            self.setCursor(self._CURSOR_MAP[edge])
        else:
            self.unsetCursor()

    def _do_resize(self, global_pos):
        delta = global_pos - self._resize_start_pos
        geom = QRect(self._resize_start_geom)
        if "left" in self._resize_edge:
            nl = geom.left() + delta.x()
            if nl > geom.right() - self.minimumWidth() + 1:
                nl = geom.right() - self.minimumWidth() + 1
            geom.setLeft(nl)
        if "right" in self._resize_edge:
            nr = geom.right() + delta.x()
            if nr < geom.left() + self.minimumWidth() - 1:
                nr = geom.left() + self.minimumWidth() - 1
            geom.setRight(nr)
        if "top" in self._resize_edge:
            nt = geom.top() + delta.y()
            if nt > geom.bottom() - self.minimumHeight() + 1:
                nt = geom.bottom() - self.minimumHeight() + 1
            geom.setTop(nt)
        if "bottom" in self._resize_edge:
            nb = geom.bottom() + delta.y()
            if nb < geom.top() + self.minimumHeight() - 1:
                nb = geom.top() + self.minimumHeight() - 1
            geom.setBottom(nb)
        self.setGeometry(geom)

    def _show_normal(self):
        self.show()
        self.raise_()
        self.activateWindow()

    def _exit_app(self):
        self._stop_content_worker()
        if self.tray_icon:
            self.tray_icon.hide()
        QApplication.quit()

    def _stop_content_worker(self):
        """Stop an active search/history worker without blocking the UI thread."""
        self._search_generation += 1
        self._history_generation += 1
        worker = self.worker
        self.worker = None
        if worker is None:
            return
        try:
            worker.stop()
        except Exception:
            pass
        try:
            worker.quit()
        except Exception:
            pass

    def _track_content_worker(self, worker):
        self._content_workers.add(worker)

        def cleanup():
            self._content_workers.discard(worker)
            worker.deleteLater()

        worker.finished.connect(cleanup)

    def closeEvent(self, event):
        dlg = MacStyleMessageBox(self, title=tr("confirm_exit_title"), message=tr("confirm_exit_message"),
                                 icon_type="question", buttons=[tr("ok"), tr("cancel")])
        if dlg.exec() == QDialog.DialogCode.Accepted:
            save_config()
            self._exit_app()
        event.ignore()

    def _init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)

        self.gradient_frame = GradientFrame()
        frame_layout = QVBoxLayout(self.gradient_frame)
        frame_layout.setContentsMargins(0, 0, 0, 0)

        title_bar = QHBoxLayout()
        title_bar.setContentsMargins(20, 15, 20, 0)
        self.app_title = QLabel(tr("app_title"))
        self.app_title.setStyleSheet("QLabel{font-size:20px;font-weight:bold;color:#333;background:transparent;}")
        title_bar.addWidget(self.app_title)
        title_bar.addStretch()
        self.login_status_lbl = QLabel(tr("not_logged"))
        self.login_status_lbl.setStyleSheet(
            "QLabel{font-size:12px;color:#666;background:rgba(255,255,255,70);"
            "border-radius:8px;padding:4px 10px;}")
        title_bar.addWidget(self.login_status_lbl)
        self.settings_btn = ControlButton("⚙", tr("settings_tip"))
        self.settings_btn.clicked.connect(self._open_settings)
        title_bar.addWidget(self.settings_btn)
        self.min_btn = ControlButton("-", tr("minimize"))
        self.min_btn.clicked.connect(self.showMinimized)
        self.close_btn = ControlButton("×", tr("close"))
        self.close_btn.clicked.connect(self.close)
        title_bar.addWidget(self.min_btn)
        title_bar.addWidget(self.close_btn)
        frame_layout.addLayout(title_bar)

        nav = QHBoxLayout()
        nav.setContentsMargins(20, 8, 20, 0)
        nav.setSpacing(8)
        self.nav_btns = []
        nav.setSpacing(14)
        for i, key in enumerate(["tab_search", "tab_history", "tab_download", "tab_install"]):
            name = tr(key)
            b = QPushButton(name)
            b.setProperty("i18n_key", key)
            b.setFixedHeight(36)
            b.setMinimumWidth(90)
            b.setCheckable(True)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.clicked.connect(lambda _checked, idx=i: self._switch_tab(idx))
            self.nav_btns.append(b)
            nav.addWidget(b)
        nav.addStretch()
        frame_layout.addLayout(nav)

        self.stack = QStackedWidget()
        self.stack.setStyleSheet("background:transparent;")
        self.stack.addWidget(self._build_search_tab())
        self.stack.addWidget(self._build_history_tab())
        self.stack.addWidget(self._build_download_tab())
        self.stack.addWidget(self._build_install_tab())
        frame_layout.addWidget(self.stack, 1)

        bottom_pad = QWidget()
        bottom_pad.setFixedHeight(10)
        bottom_pad.setStyleSheet("background:transparent;")
        frame_layout.addWidget(bottom_pad)

        main_layout.addWidget(self.gradient_frame)
        self._switch_tab(0)
        self._refresh_login_status()

    def _apply_language(self):
        """Refresh visible static labels after the language selector changes."""
        self.setWindowTitle(tr("window_title"))
        self.app_title.setText(tr("app_title"))
        self.settings_btn.setToolTip(tr("settings_tip"))
        self.min_btn.setToolTip(tr("minimize"))
        self.close_btn.setToolTip(tr("close"))
        for key, button in zip(("tab_search", "tab_history", "tab_download", "tab_install"), self.nav_btns):
            button.setText(tr(key))
        if getattr(self, "tray_icon", None) is not None:
            self.tray_icon.setToolTip(tr("tray_tip"))
            menu = self.tray_icon.contextMenu()
            if menu is not None:
                actions = menu.actions()
                if len(actions) >= 2:
                    actions[0].setText(tr("show_window"))
                    actions[1].setText(tr("exit"))
        if hasattr(self, "search_input"):
            self.search_input.setPlaceholderText(tr("search_placeholder"))
        if hasattr(self, "show_label"):
            self.show_label.setText(tr("show_label"))
        if hasattr(self, "limit_combo"):
            current = self.limit_combo.currentData() or 5
            self.limit_combo.blockSignals(True)
            self.limit_combo.clear()
            for n in [5, 10, 20, 30, 50, 100]:
                self.limit_combo.addItem(limit_name(n), n)
            idx = self.limit_combo.findData(current)
            self.limit_combo.setCurrentIndex(idx if idx >= 0 else 0)
            self.limit_combo.blockSignals(False)
        if hasattr(self, "country_combo"):
            current = self.country_combo.currentData() or "cn"
            self.country_combo.blockSignals(True)
            self.country_combo.clear()
            for code in ("cn", "hk", "mo", "tw", "us", "jp", "gb", "kr", "sg"):
                self.country_combo.addItem(region_name(code), code)
            idx = self.country_combo.findData(current)
            self.country_combo.setCurrentIndex(idx if idx >= 0 else 0)
            self.country_combo.blockSignals(False)
        if hasattr(self, "search_hint") and not self.search_results:
            self.search_hint.setText(tr("search_flow"))
        if hasattr(self, "history_mode_combo"):
            if hasattr(self, "history_mode_label"):
                self.history_mode_label.setText(tr("history_mode_label"))
            current = self.history_mode_combo.currentData() or "apple"
            self.history_mode_combo.blockSignals(True)
            self.history_mode_combo.clear()
            self.history_mode_combo.addItem(tr("official_versions"), "apple")
            self.history_mode_combo.addItem(tr("login_free_lookup"), "local")
            idx = self.history_mode_combo.findData(current)
            self.history_mode_combo.setCurrentIndex(idx if idx >= 0 else 0)
            self.history_mode_combo.blockSignals(False)
        if hasattr(self, "history_load_btn"):
            self.history_load_btn.setText(tr("load_history"))
        if hasattr(self, "history_select_all_btn"):
            self.history_select_all_btn.setText(tr("select_all"))
        if hasattr(self, "history_invert_btn"):
            self.history_invert_btn.setText(tr("invert"))
        if hasattr(self, "history_enqueue_btn"):
            self.history_enqueue_btn.setText(tr("download_selected"))
        if hasattr(self, "history_app_info") and not self.current_app:
            self.history_app_info.setText(tr("no_app_selected"))
        if hasattr(self, "history_table"):
            self.history_table.setHorizontalHeaderLabels([
                tr("select"), tr("version"), tr("version_id"), tr("size"), tr("updated")])
        if hasattr(self, "download_queue_table"):
            self.download_queue_table.setHorizontalHeaderLabels([
                tr("select"), tr("name"), tr("downloaded_total"), tr("speed"),
                tr("progress"), tr("time_remaining"), tr("actions")])
        if hasattr(self, "download_account_lbl"):
            self.download_account_lbl.setText(
                tr("account_prefix") + (getattr(self, "_last_login_who", "Apple ID")
                                         if self.logged_in else tr("not_logged")))
        if hasattr(self, "login_tip_btn"):
            self.login_tip_btn.setText(tr("login"))
        if hasattr(self, "download_queue_hint_lbl"):
            self.download_queue_hint_lbl.setText(tr("download_queue_hint"))
        if hasattr(self, "download_start_btn"):
            self.download_start_btn.setText(tr("start_all"))
        if hasattr(self, "download_clear_btn"):
            self.download_clear_btn.setText(tr("clear_finished"))
        if hasattr(self, "download_progress"):
            self.download_progress.setFormat(tr("waiting_download"))
        if hasattr(self, "download_queue_table"):
            self._refresh_download_queue()
        if hasattr(self, "install_header_lbl"):
            self.install_header_lbl.setText(tr("install_header") % IPAS_DIR)
        if hasattr(self, "install_open_dir_btn"):
            self.install_open_dir_btn.setText(tr("open_folder"))
        if hasattr(self, "install_delete_btn"):
            self.install_delete_btn.setText(tr("delete_selected"))
        if hasattr(self, "install_clear_btn"):
            self.install_clear_btn.setText(tr("clear_all"))
        if hasattr(self, "install_refresh_btn"):
            self.install_refresh_btn.setText(tr("refresh"))
        if hasattr(self, "install_tip"):
            self.install_tip.setText(tr("install_tip"))
        if hasattr(self, "install_list"):
            self._refresh_install_list()

    def _switch_tab(self, idx):
        for i, b in enumerate(self.nav_btns):
            b.setChecked(i == idx)
            b.setStyleSheet(self._nav_style(i == idx))
        self.stack.setCurrentIndex(idx)

    def _nav_style(self, active):
        if active:
            return ("QPushButton{background:rgba(0,122,255,210);color:#fff;border:none;border-radius:10px;"
                    "font-size:14px;font-weight:600;padding:6px 18px;min-width:70px;outline:none;}")
        return ("QPushButton{background:rgba(255,255,255,60);color:#333;border:1px solid rgba(255,255,255,90);"
                "border-radius:10px;font-size:14px;padding:6px 18px;min-width:70px;outline:none;}")

    # ═════════════════════════════════════════
    # ═════════════════════════════════════════
    def _open_settings(self):
        """"""
        dlg = SettingsDialog(self)
        dlg.exec()
        self._apply_language()
        self._refresh_login_status()

    def _run_tool_async(self, args, callback, timeout=60):
        w = ToolWorker(args, timeout)
        self._threads.append(w)
        _ACTIVE_TOOL_WORKERS.add(w)

        def _slot(rc, out):
            try:
                callback(rc, out)
            except Exception as exc:
                _diagnostic("main_callback_exception", repr(exc))
                try:
                    MacStyleMessageBox(self, title="软件处理异常",
                                       message="已阻止软件闪退。\n\n%s" % str(exc),
                                       icon_type="warning").exec()
                except Exception:
                    pass

        def _finished():
            if w in self._threads:
                self._threads.remove(w)
            _ACTIVE_TOOL_WORKERS.discard(w)
            w.deleteLater()

        w.done.connect(_slot)
        w.finished.connect(_finished)
        w.start()
        return w

    def _refresh_login_status(self):
        """"""
        self.login_status_lbl.setText(tr("checking"))
        self.login_status_lbl.setStyleSheet(
            "QLabel{font-size:12px;color:#888;background:rgba(255,255,255,70);"
            "border-radius:8px;padding:4px 10px;}")
        self._run_tool_async(["auth", "info", "--format", "json"], self._on_login_status, timeout=45)

    def _on_login_status(self, rc, out):
        logged, _, who = _auth_result(rc, out)
        self.logged_in = logged
        self._last_login_who = who or "Apple ID"
        if logged:
            self.login_status_lbl.setText(tr("logged_in_prefix") + self._last_login_who)
            self.login_status_lbl.setStyleSheet(
                "QLabel{font-size:12px;color:#0a7;font-weight:600;background:rgba(255,255,255,90);"
                "border-radius:8px;padding:4px 10px;}")
        else:
            self.login_status_lbl.setText(tr("not_logged"))
            self.login_status_lbl.setStyleSheet(
                "QLabel{font-size:12px;color:#c33;background:rgba(255,255,255,70);"
                "border-radius:8px;padding:4px 10px;}")
        if hasattr(self, "download_account_lbl"):
            self.download_account_lbl.setText(tr("account_prefix") + (who if logged else tr("not_logged")))
        if not logged and self._startup_login_tip:
            QTimer.singleShot(400, self._show_startup_login_tip)

    # ═════════════════════════════════════════
    # ═════════════════════════════════════════
    def _build_search_tab(self):
        w = QWidget()
        w.setStyleSheet("background:transparent;")
        layout = QVBoxLayout(w)
        layout.setContentsMargins(20, 12, 20, 12)
        layout.setSpacing(10)

        input_style = INPUT_STYLE.replace("font-size:13px", "font-size:14px")
        combo_style = COMBO_STYLE
        btn_blue = ("QPushButton{background:rgba(0,122,255,210);color:#fff;border:none;border-radius:10px;"
                   "font-size:14px;font-weight:600;padding:6px 22px;outline:none;}"
                   "QPushButton:hover{background:rgba(0,100,220,230);}"
                   "QPushButton:disabled{background:rgba(150,150,150,200);}")
        hint_style = "QLabel{color:#666;font-size:12px;background:transparent;}"
        list_style = ("QListWidget{background:rgba(255,255,255,55);border:1px solid rgba(255,255,255,100);"
                      "border-radius:12px;padding:6px;font-size:13px;color:#222;outline:none;}"
                      "QListWidget::item{padding:8px 6px;border-bottom:1px solid rgba(0,0,0,20);}"
                      "QListWidget::item:selected{background:rgba(0,122,255,60);border-radius:8px;}"
                      "QListWidget::item:hover{background:rgba(0,122,255,35);}"
                      "QScrollBar:vertical{background:transparent;width:8px;border-radius:4px;margin:0px 2px;}"
                      "QScrollBar::handle:vertical{background:rgba(130,130,130,150);border-radius:4px;min-height:32px;}"
                      "QScrollBar::handle:vertical:hover{background:rgba(100,100,100,200);}"
                      "QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{height:0px;background:none;}")

        top = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText(tr("search_placeholder"))
        self.search_input.setStyleSheet(input_style)
        self.search_input.returnPressed.connect(self._do_search)
        top.addWidget(self.search_input, 1)

        self.country_combo = QComboBox()
        for code in ("cn", "hk", "mo", "tw", "us", "jp", "gb", "kr", "sg"):
            self.country_combo.addItem(region_name(code), code)
        idx = self.country_combo.findData(COUNTRY_SAVE)
        if idx >= 0:
            self.country_combo.setCurrentIndex(idx)
        style_combo_clean(self.country_combo)
        self.country_combo.currentIndexChanged.connect(self._on_country_changed)
        top.addWidget(self.country_combo)

        self.show_label = QLabel(tr("show_label"))
        top.addWidget(self.show_label)
        self.limit_combo = QComboBox()
        for n in [5, 10, 20, 30, 50, 100]:
            self.limit_combo.addItem(limit_name(n), n)
        self.limit_combo.setCurrentIndex(0)
        style_combo_clean(self.limit_combo)
        top.addWidget(self.limit_combo)

        self.search_btn = QPushButton(tr("search"))
        self.search_btn.setFixedHeight(36)
        self.search_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.search_btn.setStyleSheet(btn_blue)
        self.search_btn.clicked.connect(self._do_search)
        top.addWidget(self.search_btn)
        layout.addLayout(top)

        self.search_hint = QLabel(tr("search_flow"))
        self.search_hint.setStyleSheet(hint_style)
        layout.addWidget(self.search_hint)

        self.search_list = QListWidget()
        self.search_list.setStyleSheet(list_style)
        self.search_list.setIconSize(QSize(48, 48))
        self.search_list.itemDoubleClicked.connect(self._on_app_double_clicked)
        self.search_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.search_list.customContextMenuRequested.connect(self._on_search_context_menu)
        layout.addWidget(self.search_list, 1)
        return w

    def _do_search(self):
        kw = self.search_input.text().strip()
        if not kw:
            MacStyleMessageBox(self, title=tr("search_empty_title"), message=tr("search_empty_message"), icon_type="warning").exec()
            return
        country = self.country_combo.currentData()
        limit = self.limit_combo.currentData() or 5
        global COUNTRY_SAVE
        COUNTRY_SAVE = country
        self.search_btn.setEnabled(False)
        self.search_hint.setText(
            tr("searching") % (kw, self.country_combo.currentText(), limit))
        self._stop_content_worker()
        generation = self._search_generation
        worker = SearchWorker(kw, country, limit)
        self.worker = worker
        self._track_content_worker(worker)
        worker.signals.data.connect(
            lambda apps, token=generation: self._on_search_data(apps, token))
        worker.signals.error.connect(
            lambda msg, token=generation: self._on_search_error(msg, token))
        worker.signals.finished.connect(
            lambda token=generation, current=worker: self._on_search_finished(token, current))
        worker.start()

    def _on_country_changed(self, index):
        """非国区搜索仍可免登录，但官方版本和下载需要对应区域账号。"""
        if index < 0:
            return
        country = self.country_combo.itemData(index)
        if not country or country == "cn":
            return
        region = self.country_combo.itemText(index)
        MacStyleMessageBox(
            self,
            title=tr("region_notice_title"),
            message=tr("region_notice_message") % region,
            icon_type="info").exec()

    def _make_app_item_widget(self, a):
        """"""
        w = QWidget()
        w.setStyleSheet("background:transparent;")
        root = QHBoxLayout(w)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(12)

        icon_lbl = QLabel()
        icon_lbl.setFixedSize(58, 58)
        icon_lbl.setStyleSheet("QLabel{background:transparent;border-radius:12px;}")
        if a.get("icon_bytes"):
            pm = QPixmap()
            if pm.loadFromData(a["icon_bytes"]):
                icon_lbl.setPixmap(pm.scaled(58, 58, Qt.AspectRatioMode.KeepAspectRatio,
                                             Qt.TransformationMode.SmoothTransformation))
        else:
            icon_lbl.setText("\U0001F4F1")
            icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            icon_lbl.setStyleSheet("QLabel{font-size:26px;background:transparent;}")
        root.addWidget(icon_lbl)

        info = QVBoxLayout()
        info.setSpacing(3)
        name_lbl = QLabel(a.get("track_name", ""))
        name_lbl.setStyleSheet("QLabel{font-size:14px;font-weight:bold;color:#222;background:transparent;}")
        info.addWidget(name_lbl)

        rating = a.get("rating", 0) or 0
        rating_count = a.get("rating_count", 0) or 0
        if rating:
            rating_txt = "\u2605 %.1f (%s)" % (rating, self._fmt_count(rating_count))
        else:
            rating_txt = tr("no_rating")
        meta_parts = [
            rating_txt,
            tr("price") % (a.get("price") or tr("free")),
            tr("version_value") % (a.get("version") or tr("not_available")),
            "%s %s" % (tr("size"), format_size(a.get("size"))),
        ]
        if a.get("seller"):
            meta_parts.append(tr("developer") % a["seller"])
        meta_lbl = QLabel("  |  ".join(meta_parts))
        meta_lbl.setStyleSheet("QLabel{font-size:12px;color:#666;background:transparent;}")
        meta_lbl.setWordWrap(True)
        info.addWidget(meta_lbl)

        desc = a.get("description", "") or ""
        if len(desc) > 110:
            desc = desc[:110] + "..."
        extra = tr("bundle") % (a.get("bundle_id") or "")
        if a.get("genres"):
            extra = tr("category") % a["genres"] + extra
        sub2 = extra + ("\n%s" % desc if desc else "")
        sub_lbl = QLabel(sub2)
        sub_lbl.setStyleSheet("QLabel{font-size:11px;color:#888;background:transparent;}")
        sub_lbl.setWordWrap(True)
        info.addWidget(sub_lbl)

        root.addLayout(info, 1)
        return w

    @staticmethod
    def _fmt_count(n):
        try:
            n = int(n)
        except Exception:
            return "0"
        if n >= 10000:
            return "%.1f 万" % (n / 10000.0)
        return str(n)

    def _on_search_data(self, apps, generation=None):
        if generation is not None and generation != self._search_generation:
            return
        self.search_results = apps
        self.search_list.clear()
        for a in apps:
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, a)
            item.setSizeHint(QSize(0, 92))
            self.search_list.addItem(item)
            self.search_list.setItemWidget(item, self._make_app_item_widget(a))
        self.search_hint.setText(tr("search_results_hint") % len(apps))

    def _on_search_finished(self, generation=None, worker=None):
        if generation is not None and generation != self._search_generation:
            return
        if worker is None or self.worker is worker:
            self.worker = None
        self.search_btn.setEnabled(True)

    def _on_search_error(self, msg, generation=None):
        if generation is not None and generation != self._search_generation:
            return
        self.search_btn.setEnabled(True)
        self.search_hint.setText(tr("search_failed") + ": " + msg)
        MacStyleMessageBox(self, title=tr("search_failed"), message=msg, icon_type="warning").exec()

    def _on_app_double_clicked(self, item):
        app = item.data(Qt.ItemDataRole.UserRole)
        if not app:
            return
        self.current_app = app
        self._switch_tab(1)
        self._load_history_for_current()

    def _on_search_context_menu(self, pos):
        item = self.search_list.itemAt(pos)
        if not item:
            return
        app = item.data(Qt.ItemDataRole.UserRole)
        menu = QMenu(self)
        act_store = menu.addAction(tr("open_store"))
        act_copy = menu.addAction(tr("copy_link"))
        act_ver = menu.addAction(tr("find_versions_local"))
        chosen = menu.exec(self.search_list.mapToGlobal(pos))
        if chosen == act_store:
            url = app.get("track_view_url", "")
            if url:
                QDesktopServices.openUrl(QUrl(url))
        elif chosen == act_copy:
            QApplication.clipboard().setText(app.get("track_view_url", ""))
            MacStyleMessageBox(self, title=tr("copied_title"),
                               message=tr("copied_message"), icon_type="success").exec()
        elif chosen == act_ver:
            self.current_app = app
            self._switch_tab(1)
            self._load_history_for_current()

    # ═════════════════════════════════════════
    # ═════════════════════════════════════════
    def _build_history_tab(self):
        w = QWidget()
        w.setStyleSheet("background:transparent;")
        layout = QVBoxLayout(w)
        layout.setContentsMargins(20, 12, 20, 12)
        layout.setSpacing(10)

        btn_gray = ("QPushButton{background:rgba(255,255,255,70);color:#333;border:1px solid rgba(255,255,255,110);"
                    "border-radius:10px;font-size:13px;font-weight:600;padding:6px 16px;}"
                    "QPushButton:hover{background:rgba(255,255,255,120);}")
        btn_blue = ("QPushButton{background:rgba(0,122,255,210);color:#fff;border:none;border-radius:10px;"
                   "font-size:13px;font-weight:600;padding:6px 18px;}"
                   "QPushButton:hover{background:rgba(0,100,220,230);}")
        combo_style = COMBO_STYLE
        table_style = ("QTableWidget{background:rgba(255,255,255,55);border:1px solid rgba(255,255,255,100);"
                       "border-radius:12px;font-size:13px;color:#222;gridline-color:rgba(0,0,0,0);}"
                       "QHeaderView::section{background:rgba(0,122,255,120);color:#fff;padding:7px 6px;border:none;"
                       "font-weight:bold;}"
                       "QHeaderView::section:horizontal{border-right:1px solid rgba(255,255,255,60);}"
                       "QTableWidget::item{padding:7px 6px;border:none;"
                       "border-bottom:1px solid rgba(0,0,0,22);}"
                       "QTableWidget::item:selected{background:rgba(0,122,255,55);}"
                       "QScrollBar:vertical{background:transparent;width:8px;border-radius:4px;margin:0px 2px;}"
                       "QScrollBar::handle:vertical{background:rgba(130,130,130,150);border-radius:4px;min-height:32px;}"
                       "QScrollBar::handle:vertical:hover{background:rgba(100,100,100,200);}"
                       "QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{height:0px;background:none;}")

        self.history_app_info = QLabel(tr("no_app_selected"))
        self.history_app_info.setStyleSheet(
            "QLabel{font-size:14px;color:#333;background:rgba(255,255,255,65);"
            "border:1px solid rgba(255,255,255,110);border-radius:10px;padding:10px 14px;font-weight:600;}"
        )
        self.history_app_info.setWordWrap(True)
        layout.addWidget(self.history_app_info)

        ctrl = QHBoxLayout()
        ctrl.setSpacing(8)
        self.history_mode_label = QLabel(tr("history_mode_label"))
        ctrl.addWidget(self.history_mode_label)
        self.history_mode_combo = QComboBox()
        self.history_mode_combo.addItem(tr("official_versions"), "apple")
        self.history_mode_combo.addItem(tr("login_free_lookup"), "local")
        style_combo_clean(self.history_mode_combo)
        self.history_mode_combo.currentIndexChanged.connect(
            lambda _i: setattr(self, "history_mode", self.history_mode_combo.currentData()))
        ctrl.addWidget(self.history_mode_combo)
        self.history_load_btn = QPushButton(tr("load_history"))
        self.history_load_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.history_load_btn.setStyleSheet(btn_blue)
        self.history_load_btn.clicked.connect(self._load_history_for_current)
        ctrl.addWidget(self.history_load_btn)
        ctrl.addStretch()
        self.history_select_all_btn = QPushButton(tr("select_all"))
        self.history_select_all_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.history_select_all_btn.setStyleSheet(btn_gray)
        self.history_select_all_btn.clicked.connect(self._history_toggle_select_all)
        ctrl.addWidget(self.history_select_all_btn)
        self.history_invert_btn = QPushButton(tr("invert"))
        self.history_invert_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.history_invert_btn.setStyleSheet(btn_gray)
        self.history_invert_btn.clicked.connect(self._history_invert_selection)
        ctrl.addWidget(self.history_invert_btn)
        self.history_enqueue_btn = QPushButton(tr("download_selected"))
        self.history_enqueue_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.history_enqueue_btn.setStyleSheet(btn_blue)
        self.history_enqueue_btn.clicked.connect(self._download_selected_versions)
        ctrl.addWidget(self.history_enqueue_btn)
        layout.addLayout(ctrl)

        self.history_table = QTableWidget(0, 5)
        self.history_table.setHorizontalHeaderLabels([
            tr("select"), tr("version"), tr("version_id"), tr("size"), tr("updated")])
        self.history_table.setStyleSheet(table_style)
        self.history_table.setSortingEnabled(True)
        self.history_table.verticalHeader().setVisible(False)
        self.history_table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.history_table.horizontalHeader().setMinimumSectionSize(50)
        self.history_table.horizontalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignCenter)
        self.history_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.history_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self.history_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self.history_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self.history_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.history_table.setColumnWidth(0, 50)
        self.history_table.setColumnWidth(1, 110)
        self.history_table.setColumnWidth(2, 135)
        self.history_table.setColumnWidth(3, 125)
        self.history_table.horizontalHeader().setStretchLastSection(True)
        self.history_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.history_table.customContextMenuRequested.connect(self._on_history_context_menu)
        self.history_table.cellDoubleClicked.connect(self._on_history_row_double_clicked)
        layout.addWidget(self.history_table, 1)
        return w

    def _load_history_for_current(self):
        if not self.current_app:
            MacStyleMessageBox(self, title=tr("choose_app_title"),
                               message=tr("choose_app_message"), icon_type="warning").exec()
            return
        app = self.current_app
        self.history_app_info.setText(
            tr("current_app") % (app["track_name"], app["bundle_id"], app["track_id"]))
        self.history_load_btn.setEnabled(False)
        self.history_table.setRowCount(0)
        self._stop_content_worker()
        generation = self._history_generation
        worker = HistoryWorker(app["track_id"], self.history_mode)
        self.worker = worker
        self._track_content_worker(worker)
        worker.signals.data.connect(
            lambda rows, token=generation: self._on_history_data(rows, token))
        worker.signals.error.connect(
            lambda msg, token=generation: self._on_history_error(msg, token))
        worker.signals.finished.connect(
            lambda token=generation, current=worker: self._on_history_finished(token, current))
        worker.start()

    def _on_history_data(self, rows, generation=None):
        if generation is not None and generation != self._history_generation:
            return
        self.history_rows = rows
        self.history_table.setSortingEnabled(False)
        self.history_table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            cb = QTableWidgetItem()
            cb.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
            cb.setCheckState(Qt.CheckState.Unchecked)
            cb.setData(Qt.ItemDataRole.UserRole, {
                "app_id": self.current_app["track_id"], "bundle": self.current_app["bundle_id"],
                "version_id": row["external_id"], "version": row["version"],
                "name": self.current_app["track_name"], "size": row.get("size") or 0,
                "date": row.get("date") or "",
            })
            self.history_table.setItem(r, 0, cb)
            version_item = QTableWidgetItem(str(row.get("version") or "—"))
            version_id = str(row.get("external_id") or "")
            version_id_item = NumericTableWidgetItem(version_id, version_id)
            size_value = row.get("size") or 0
            size_item = QTableWidgetItem(format_size(size_value) if size_value else "—")
            date_item = QTableWidgetItem(str(row.get("date") or "—"))
            for item in (version_item, version_id_item, size_item, date_item):
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.history_table.setItem(r, 1, version_item)
            self.history_table.setItem(r, 2, version_id_item)
            self.history_table.setItem(r, 3, size_item)
            self.history_table.setItem(r, 4, date_item)
        self.history_table.setSortingEnabled(True)
        self.history_table.sortItems(2, Qt.SortOrder.DescendingOrder)
        self.history_app_info.setText(
            tr("history_count") % (
                tr("current_app") % (self.current_app["track_name"],
                                      self.current_app["bundle_id"],
                                      self.current_app["track_id"]), len(rows)))

    def _on_history_finished(self, generation=None, worker=None):
        if generation is not None and generation != self._history_generation:
            return
        if worker is None or self.worker is worker:
            self.worker = None
        self.history_load_btn.setEnabled(True)

    def _on_history_error(self, msg, generation=None):
        if generation is not None and generation != self._history_generation:
            return
        self.history_load_btn.setEnabled(True)
        self.history_app_info.setText(tr("history_failed") + ": " + msg)
        MacStyleMessageBox(self, title=tr("load_failed"), message=msg, icon_type="warning").exec()

    def _history_select_all(self):
        """"""
        for r in range(self.history_table.rowCount()):
            cb = self.history_table.item(r, 0)
            if cb:
                cb.setCheckState(Qt.CheckState.Checked)
        self.history_select_all_btn.setText(tr("cancel_select_all"))

    def _history_toggle_select_all(self):
        """"""
        rows = self.history_table.rowCount()
        if rows == 0:
            return
        checked = 0
        for r in range(rows):
            cb = self.history_table.item(r, 0)
            if cb and cb.checkState() == Qt.CheckState.Checked:
                checked += 1
        if checked >= rows:
            for r in range(rows):
                cb = self.history_table.item(r, 0)
                if cb:
                    cb.setCheckState(Qt.CheckState.Unchecked)
            self.history_select_all_btn.setText(tr("select_all"))
        else:
            for r in range(rows):
                cb = self.history_table.item(r, 0)
                if cb:
                    cb.setCheckState(Qt.CheckState.Checked)
            self.history_select_all_btn.setText(tr("cancel_select_all"))

    def _history_invert_selection(self):
        """"""
        for r in range(self.history_table.rowCount()):
            cb = self.history_table.item(r, 0)
            if not cb:
                continue
            cb.setCheckState(Qt.CheckState.Unchecked
                             if cb.checkState() == Qt.CheckState.Checked
                             else Qt.CheckState.Checked)
        rows = self.history_table.rowCount()
        checked = sum(1 for r in range(rows)
                      if self.history_table.item(r, 0)
                      and self.history_table.item(r, 0).checkState() == Qt.CheckState.Checked)
        self.history_select_all_btn.setText(
            tr("cancel_select_all") if (rows and checked >= rows) else tr("select_all"))

    def _get_checked_versions(self):
        """"""
        out = []
        for r in range(self.history_table.rowCount()):
            cb = self.history_table.item(r, 0)
            if cb and cb.checkState() == Qt.CheckState.Checked:
                d = cb.data(Qt.ItemDataRole.UserRole)
                if d:
                    out.append(d)
        return out

    # ═════════════════════════════════════════
    # ═════════════════════════════════════════
    def _start_download(self, picked):
        if not IPATOOL_PATH or not os.path.exists(IPATOOL_PATH):
            MacStyleMessageBox(self, title=tr("component_error_title"),
                               message=localized("下载组件缺失，当前程序可能不完整。\n请重新下载完整的软件。",
                                                 "The download component is missing. Download the complete package again."),
                               icon_type="warning").exec()
            return
        tasks = []
        for item in picked:
            if item.get("id") and item.get("out"):
                task = item
            else:
                self._enqueue(item)
                task_id = "%s:%s" % (item["app_id"], item["version_id"])
                task = next((q for q in self.download_queue if q["id"] == task_id), None)
            if task and task.get("status") in ("queued", "failed", "cancelled"):
                task["status"] = "queued"
                task["error"] = ""
                tasks.append(task)
        self._refresh_download_queue()
        if not tasks:
            self._launch_pending_downloads(getattr(self, "_download_email", APPLE_ID_SAVE or ""))
            return
        if getattr(self, "_pre_check_busy", False):
            return
        self._pre_check_busy = True
        self._run_tool_async(["auth", "info", "--format", "json"],
                             lambda rc, out: self._on_pre_download_check(rc, out, tasks),
                             timeout=45)

    def _on_pre_download_check(self, rc, out, picked):
        global APPLE_ID_SAVE
        self._pre_check_busy = False
        logged, _, who = _auth_result(rc, out)

        if not logged:
            MacStyleMessageBox(
                self, title=tr("download_signin_title"),
                message=tr("download_signin_message"),
                icon_type="warning").exec()
            self._open_settings()
            return

        if not APPLE_ID_SAVE:
            APPLE_ID_SAVE = who or ""

        self._download_email = APPLE_ID_SAVE or who or ""
        self._download_session_ids.update(q["id"] for q in picked)
        self._launch_pending_downloads(self._download_email)

    def _launch_pending_downloads(self, email=""):
        if not email:
            return
        while len(self._download_workers) < self._download_max_parallel:
            task = next((q for q in self.download_queue if q.get("status") == "queued"
                         and q["id"] not in self._download_workers), None)
            if not task:
                break
            task["status"] = "downloading"
            task["error"] = ""
            worker = DownloadWorker(email, dict(task))
            task_id = task["id"]
            worker.progress.connect(self._download_log_line)
            worker.progress_pct.connect(self._on_download_progress)
            worker.task_update.connect(self._on_download_task_update)
            worker.error.connect(lambda m: self._download_log_line("[错误] " + m))
            worker.finished.connect(lambda result, w=worker: self._on_single_download_done(result, w))
            self._download_workers[task_id] = worker
            self._update_download_queue_row(task_id)
            worker.start()
        self._update_overall_download_progress()

    def _on_download_task_update(self, task_id, update):
        task = next((q for q in self.download_queue if q["id"] == task_id), None)
        if not task:
            return
        task.update(update or {})
        self._update_download_queue_row(task_id)
        self._update_overall_download_progress()

    def _on_single_download_done(self, result, worker):
        task_id = result.get("id", "")
        task = next((q for q in self.download_queue if q["id"] == task_id), None)
        if task:
            task["status"] = result.get("status") or ("completed" if result.get("ok") else "failed")
            task["error"] = result.get("reason") or ""
            task["speed"] = 0.0
            if task.get("_remove_when_done"):
                self._remove_partial_files(task)
        self._update_download_queue_row(task_id)
        QTimer.singleShot(80, lambda tid=task_id, w=worker: self._finalize_download_worker(tid, w))

    def _finalize_download_worker(self, task_id, worker):
        if worker.isRunning():
            QTimer.singleShot(80, lambda tid=task_id, w=worker: self._finalize_download_worker(tid, w))
            return
        if self._download_workers.get(task_id) is worker:
            self._download_workers.pop(task_id, None)
        task = next((q for q in self.download_queue if q["id"] == task_id), None)
        if task and task.pop("_remove_when_done", False):
            self.download_queue = [q for q in self.download_queue if q["id"] != task_id]
            self._download_session_ids.discard(task_id)
            self._refresh_download_queue()
        if hasattr(self, "_refresh_install_list"):
            self._refresh_install_list()
        self._launch_pending_downloads(getattr(self, "_download_email", ""))
        if not self._download_workers and not any(q.get("status") == "queued" for q in self.download_queue):
            self._show_download_summary()

    def _show_download_summary(self):
        tasks = [q for q in self.download_queue if q["id"] in self._download_session_ids]
        if not tasks or any(q.get("status") == "paused" for q in tasks):
            return
        self._download_session_ids.clear()
        ok_list = [q for q in tasks if q.get("status") == "completed"]
        fail_list = [q for q in tasks if q.get("status") == "failed"]
        if not ok_list and not fail_list:
            return
        if ok_list:
            msg = localized("下载任务已结束。\n\n", "Download tasks finished.\n\n") + "\n".join(
                "✅ %s %s" % (q["name"], q["version"]) for q in ok_list)
            if fail_list:
                msg += localized("\n\n未成功：\n", "\n\nFailed:\n") + "\n".join(
                    "❌ %s %s: %s" % (q["name"], q["version"],
                                      q.get("error") or tr("download_status_failed"))
                    for q in fail_list)
            msg += localized(
                "\n\n保存位置：\n%s\n\n安装可使用 iMazing 或爱思助手导入 IPA。\n是否现在打开文件夹？",
                "\n\nSaved to:\n%s\n\nUse iMazing or another IPA installer to import the file.\nOpen the folder now?") % IPAS_DIR
            dlg = MacStyleMessageBox(self, title=localized("下载完成", "Download complete"), message=msg,
                                     icon_type="success", buttons=[localized("是", "Yes"), localized("否", "No")])
            if dlg.exec() == QDialog.DialogCode.Accepted:
                try:
                    os.startfile(IPAS_DIR)
                except Exception:
                    QDesktopServices.openUrl(QUrl.fromLocalFile(IPAS_DIR))
        else:
            msg = localized("本次没有成功下载到 IPA。\n\n", "No IPA was downloaded successfully.\n\n") + "\n".join(
                "❌ %s %s: %s" % (q["name"], q["version"],
                                  q.get("error") or tr("download_status_failed"))
                for q in fail_list)
            MacStyleMessageBox(self, title=localized("下载未完成", "Download incomplete"),
                               message=msg, icon_type="warning").exec()

    def _download_selected_versions(self):
        """"""
        picked = self._get_checked_versions()
        if not picked:
            MacStyleMessageBox(self, title=tr("choose_app_title"),
                               message=localized("请先勾选要下载的版本（可点「全选」或双击某行）。",
                                                 "Select a version first (use Select all or double-click a row)."),
                               icon_type="info").exec()
            return
        for d in picked:
            self._enqueue(d)
        self._refresh_download_queue()
        self._switch_tab(2)
        self._download_start()

    def _add_checked_to_queue(self):
        """"""
        added = 0
        for d in self._get_checked_versions():
            if self._enqueue(d):
                added += 1
        self._refresh_download_queue()
        if added > 0:
            MacStyleMessageBox(self, title=localized("已加入", "Added"),
                               message=localized("已将 %d 个版本加入下载队列，可到「下载应用」Tab 执行下载。",
                                                 "%d version(s) were added to the download queue. Open Downloads to start.") % added,
                               icon_type="success").exec()
        else:
            MacStyleMessageBox(self, title=tr("choose_app_title"),
                               message=localized("请先勾选要下载的版本。", "Select at least one version first."),
                               icon_type="info").exec()

    def _enqueue(self, d):
        key = (str(d["app_id"]), str(d["version_id"]))
        for q in self.download_queue:
            if (str(q["app_id"]), str(q["version_id"])) == key:
                if q.get("status") in ("failed", "cancelled"):
                    q["status"] = "queued"
                    q["error"] = ""
                    return True
                return False
        out = os.path.join(IPAS_DIR, safe_filename(d["name"], d["version"], d["app_id"]))
        task_id = "%s:%s" % key
        downloaded = 0
        for path in (out + ".tmp", out + ".part", out):
            try:
                if os.path.isfile(path):
                    downloaded = os.path.getsize(path)
                    break
            except OSError:
                pass
        status = "completed" if os.path.isfile(out) and downloaded > 1024 else "queued"
        self.download_queue.append({
            "id": task_id,
            "app_id": d["app_id"], "bundle": d["bundle"], "version_id": d["version_id"],
            "version": d["version"], "name": d["name"], "out": out,
            "total": int(d.get("size") or 0), "downloaded": downloaded,
            "speed": 0.0, "percent": 100 if status == "completed" else 0,
            "elapsed": 0, "eta": -1, "status": status, "error": "",
        })
        return True

    def _on_history_row_double_clicked(self, row, _col):
        """"""
        cb = self.history_table.item(row, 0)
        if not cb:
            return
        d = cb.data(Qt.ItemDataRole.UserRole)
        if not d:
            return
        self._enqueue(d)
        self._refresh_download_queue()
        self._switch_tab(2)
        self._download_start()

    def _on_history_context_menu(self, pos):
        item = self.history_table.itemAt(pos)
        if not item:
            return
        row = item.row()
        cb = self.history_table.item(row, 0)
        d = cb.data(Qt.ItemDataRole.UserRole) if cb else None
        menu = QMenu(self)
        act_copy = menu.addAction(tr("copy_version_id"))
        act_all = menu.addAction(tr("export_version_ids"))
        chosen = menu.exec(self.history_table.mapToGlobal(pos))
        if chosen == act_copy and d:
            QApplication.clipboard().setText(str(d["version_id"]))
            MacStyleMessageBox(self, title=tr("copied_title"),
                               message=tr("version_id_copied") % d["version_id"],
                               icon_type="success").exec()
        elif chosen == act_all:
            lines = ["%s\t%s\t%s" % (r["version"], r["date"], r["external_id"]) for r in self.history_rows]
            QApplication.clipboard().setText("\n".join(lines))
            MacStyleMessageBox(self, title=tr("copied_title"),
                               message=tr("version_ids_copied") % len(lines),
                               icon_type="success").exec()

    # ═════════════════════════════════════════
    # ═════════════════════════════════════════
    def _build_download_tab(self):
        w = QWidget()
        w.setStyleSheet("background:transparent;")
        layout = QVBoxLayout(w)
        layout.setContentsMargins(20, 12, 20, 12)
        layout.setSpacing(10)

        input_style = INPUT_STYLE
        btn_blue = ("QPushButton{background:rgba(0,122,255,210);color:#fff;border:none;border-radius:10px;"
                   "font-size:14px;font-weight:600;padding:6px 22px;}"
                   "QPushButton:hover{background:rgba(0,100,220,230);}"
                   "QPushButton:disabled{background:rgba(150,150,150,200);}")
        btn_gray = ("QPushButton{background:rgba(255,255,255,70);color:#333;border:1px solid rgba(255,255,255,110);"
                   "border-radius:10px;font-size:13px;font-weight:600;padding:6px 16px;}"
                   "QPushButton:hover{background:rgba(255,255,255,120);}")
        table_style = ("QTableWidget{background:rgba(255,255,255,55);border:1px solid rgba(255,255,255,100);"
                       "border-radius:12px;font-size:12px;color:#222;gridline-color:rgba(0,0,0,18);outline:none;}"
                       "QHeaderView::section{background:rgba(255,255,255,80);color:#333;padding:7px 4px;"
                       "border:none;border-bottom:1px solid rgba(0,0,0,24);font-weight:600;}"
                       "QTableWidget::item{padding:5px 5px;border:none;border-bottom:1px solid rgba(0,0,0,20);}"
                       "QTableWidget::item:selected{background:rgba(0,122,255,35);}"
                       "QScrollBar:vertical{background:transparent;width:8px;margin:0px 2px;}"
                       "QScrollBar::handle:vertical{background:rgba(130,130,130,150);border-radius:4px;min-height:32px;}"
                       "QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{height:0px;background:none;}")
        cfg = QHBoxLayout()
        cfg.setSpacing(8)
        self.download_account_lbl = QLabel(tr("account_prefix"))
        self.download_account_lbl.setStyleSheet("QLabel{font-size:13px;color:#333;background:transparent;font-weight:600;}")
        cfg.addWidget(self.download_account_lbl)
        self.login_tip_btn = QPushButton(tr("login"))
        self.login_tip_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.login_tip_btn.setStyleSheet(btn_gray)
        self.login_tip_btn.clicked.connect(self._open_settings)
        cfg.addWidget(self.login_tip_btn)
        cfg.addStretch()
        layout.addLayout(cfg)

        self.download_queue_hint_lbl = QLabel(tr("download_queue_hint"))
        layout.addWidget(self.download_queue_hint_lbl)
        self.download_queue_table = QTableWidget(0, 7)
        self.download_queue_table.setHorizontalHeaderLabels(
            [tr("select"), tr("name"), tr("downloaded_total"), tr("speed"),
             tr("progress"), tr("time_remaining"), tr("actions")])
        self.download_queue_table.setStyleSheet(table_style)
        self.download_queue_table.setSortingEnabled(False)
        self.download_queue_table.verticalHeader().setVisible(False)
        self.download_queue_table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.download_queue_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        header = self.download_queue_table.horizontalHeader()
        header.setMinimumSectionSize(42)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(6, QHeaderView.ResizeMode.Fixed)
        self.download_queue_table.setColumnWidth(0, 46)
        self.download_queue_table.setColumnWidth(2, 180)
        self.download_queue_table.setColumnWidth(3, 92)
        self.download_queue_table.setColumnWidth(4, 180)
        self.download_queue_table.setColumnWidth(5, 118)
        self.download_queue_table.setColumnWidth(6, 132)
        layout.addWidget(self.download_queue_table, 3)

        op = QHBoxLayout()
        op.setSpacing(8)
        self.download_start_btn = QPushButton(tr("start_all"))
        self.download_start_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.download_start_btn.setStyleSheet(btn_blue)
        self.download_start_btn.clicked.connect(self._download_start)
        op.addWidget(self.download_start_btn)
        self.download_clear_btn = QPushButton(tr("clear_finished"))
        self.download_clear_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.download_clear_btn.setStyleSheet(btn_gray)
        self.download_clear_btn.clicked.connect(self._download_clear)
        op.addWidget(self.download_clear_btn)
        op.addStretch()
        layout.addLayout(op)

        self.download_progress = QProgressBar()
        self.download_progress.setRange(0, 100)
        self.download_progress.setValue(0)
        self.download_progress.setFormat(tr("waiting_download"))
        self.download_progress.setStyleSheet(
            "QProgressBar{background:rgba(0,0,0,45);border:1px solid rgba(255,255,255,120);"
            "border-radius:8px;font-size:12px;color:#fff;text-align:center;}"
            "QProgressBar::chunk{background:qlineargradient(x1:0,y1:0,x2:1,y2:0,"
            "stop:0 rgba(0,122,255,220),stop:1 rgba(50,180,255,220));border-radius:7px;}")
        layout.addWidget(self.download_progress)

        self.download_current_lbl = QLabel("")
        self.download_current_lbl.setStyleSheet(
            "QLabel{font-size:12px;color:#444;background:transparent;}")
        layout.addWidget(self.download_current_lbl)

        self._refresh_download_queue()
        return w

    def _refresh_download_queue(self):
        if not hasattr(self, "download_queue_table"):
            return
        table = self.download_queue_table
        table.setRowCount(len(self.download_queue))
        for row, task in enumerate(self.download_queue):
            select_item = QTableWidgetItem()
            select_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
            select_item.setCheckState(Qt.CheckState.Checked if task.get("selected") else Qt.CheckState.Unchecked)
            select_item.setData(Qt.ItemDataRole.UserRole, task["id"])
            select_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            table.setItem(row, 0, select_item)
            for col in (1, 2, 3, 5):
                item = QTableWidgetItem()
                item.setFlags(Qt.ItemFlag.ItemIsEnabled)
                table.setItem(row, col, item)

            bar = QProgressBar()
            bar.setRange(0, 100)
            bar.setTextVisible(True)
            bar.setStyleSheet(
                "QProgressBar{background:rgba(0,0,0,22);border:none;border-radius:3px;"
                "height:6px;text-align:center;color:#444;font-size:10px;}"
                "QProgressBar::chunk{background:qlineargradient(x1:0,y1:0,x2:1,y2:0,"
                "stop:0 #7b61ff,stop:1 #27a8ff);border-radius:3px;}")
            table.setCellWidget(row, 4, bar)

            action_box = QWidget()
            action_box.setStyleSheet("background:transparent;")
            action_layout = QHBoxLayout(action_box)
            action_layout.setContentsMargins(2, 3, 2, 3)
            action_layout.setSpacing(4)
            primary = QPushButton()
            primary.setObjectName("taskPrimary")
            primary.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            primary.setFixedSize(58, 28)
            primary.setStyleSheet(
                "QPushButton{background:rgba(255,255,255,80);border:1px solid rgba(0,0,0,25);"
                "border-radius:7px;color:#333;font-size:12px;}"
                "QPushButton:hover{background:rgba(255,255,255,150);}")
            primary.clicked.connect(lambda _checked=False, tid=task["id"]: self._download_task_pause_resume(tid))
            remove = QPushButton(tr("task_remove"))
            remove.setObjectName("taskRemove")
            remove.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            remove.setFixedSize(50, 28)
            remove.setStyleSheet(
                "QPushButton{background:transparent;border:none;color:#666;font-size:12px;}"
                "QPushButton:hover{color:#e53935;background:rgba(255,255,255,80);border-radius:7px;}")
            remove.clicked.connect(lambda _checked=False, tid=task["id"]: self._download_task_delete(tid))
            action_layout.addWidget(primary)
            action_layout.addWidget(remove)
            table.setCellWidget(row, 6, action_box)
            table.setRowHeight(row, 44)
            self._write_download_queue_row(row, task)
        self._update_overall_download_progress()

    def _download_status_text(self, status):
        return {
            "queued": tr("download_status_queued"),
            "downloading": tr("download_status_downloading"),
            "paused": tr("download_status_paused"),
            "completed": tr("download_status_completed"),
            "failed": tr("download_status_failed"),
            "cancelled": tr("download_status_cancelled"),
        }.get(status, tr("waiting_download"))

    def _write_download_queue_row(self, row, task):
        table = self.download_queue_table
        status = task.get("status", "queued")
        downloaded = int(task.get("downloaded") or 0)
        total = int(task.get("total") or 0)
        name_item = table.item(row, 1)
        if name_item:
            name_item.setText("📱 %s_%s%s" %
                              (task.get("name", ""), task.get("version", ""),
                               tr("genuine_suffix")))
            name_item.setToolTip(self._download_status_text(status))
            if task.get("error"):
                name_item.setToolTip("%s\n%s" % (self._download_status_text(status), task["error"]))
        size_item = table.item(row, 2)
        if size_item:
            size_item.setText("%s / %s" %
                              (format_transfer_size(downloaded),
                               format_transfer_size(total) if total else
                               tr("fetch_on_download")))
        speed_item = table.item(row, 3)
        if speed_item:
            speed = float(task.get("speed") or 0)
            speed_item.setText((format_transfer_size(speed) + "/s") if speed > 0 else "--")
            speed_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        bar = table.cellWidget(row, 4)
        if isinstance(bar, QProgressBar):
            percent = int(task.get("percent") if task.get("percent") is not None else -1)
            if status == "completed":
                percent = 100
            if percent < 0:
                # 未知总大小时不能使用 0,0 忙碌条，否则每行都会显示成半条假进度。
                bar.setRange(0, 100)
                bar.setValue(0)
                bar.setFormat(tr("reading_size"))
            else:
                bar.setRange(0, 100)
                bar.setValue(max(0, min(100, percent)))
                bar.setFormat("%d%%" % max(0, min(100, percent)))
        time_item = table.item(row, 5)
        if time_item:
            elapsed = format_duration(task.get("elapsed") or 0)
            eta = int(task.get("eta") if task.get("eta") is not None else -1)
            time_item.setText("%s / %s" % (elapsed, format_duration(eta) if eta >= 0 else "--:--"))
            time_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        action_box = table.cellWidget(row, 6)
        if action_box:
            primary = action_box.findChild(QPushButton, "taskPrimary")
            if primary:
                if status == "completed":
                    primary.setText(tr("task_open"))
                elif status in ("paused", "failed", "cancelled"):
                    primary.setText(tr("task_resume") if status == "paused" else tr("task_retry"))
                else:
                    primary.setText(tr("task_pause"))

    def _update_download_queue_row(self, task_id):
        if not hasattr(self, "download_queue_table"):
            return
        task = next((q for q in self.download_queue if q["id"] == task_id), None)
        if not task:
            return
        for row in range(self.download_queue_table.rowCount()):
            item = self.download_queue_table.item(row, 0)
            if item and item.data(Qt.ItemDataRole.UserRole) == task_id:
                self._write_download_queue_row(row, task)
                return

    @staticmethod
    def _remove_partial_files(task):
        for path in (task["out"] + ".tmp", task["out"] + ".part"):
            try:
                if os.path.isfile(path):
                    os.remove(path)
            except OSError:
                pass

    def _download_task_pause_resume(self, task_id):
        task = next((q for q in self.download_queue if q["id"] == task_id), None)
        if not task:
            return
        status = task.get("status")
        if status == "completed":
            try:
                os.startfile(os.path.dirname(task["out"]) or IPAS_DIR)
            except Exception:
                QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(task["out"]) or IPAS_DIR))
            return
        if status == "downloading":
            task["status"] = "paused"
            worker = self._download_workers.get(task_id)
            if worker:
                worker.pause()
            self._update_download_queue_row(task_id)
            return
        if status == "queued":
            task["status"] = "paused"
            self._update_download_queue_row(task_id)
            return
        task["status"] = "queued"
        task["error"] = ""
        self._download_session_ids.add(task_id)
        self._update_download_queue_row(task_id)
        self._start_download([task])

    def _download_task_delete(self, task_id):
        task = next((q for q in self.download_queue if q["id"] == task_id), None)
        if not task:
            return
        worker = self._download_workers.get(task_id)
        if worker:
            task["_remove_when_done"] = True
            task["status"] = "cancelled"
            worker.cancel()
            self._update_download_queue_row(task_id)
            return
        self._remove_partial_files(task)
        self.download_queue = [q for q in self.download_queue if q["id"] != task_id]
        self._download_session_ids.discard(task_id)
        self._refresh_download_queue()

    def _download_clear(self):
        keep = []
        for task in self.download_queue:
            if task["id"] in self._download_workers or task.get("status") in ("queued", "downloading", "paused"):
                keep.append(task)
            else:
                if task.get("status") != "completed":
                    self._remove_partial_files(task)
                self._download_session_ids.discard(task["id"])
        self.download_queue = keep
        self._refresh_download_queue()

    def _download_start(self):
        """"""
        if not self.download_queue:
            MacStyleMessageBox(self, title=tr("empty_queue_title"),
                               message=tr("empty_queue_message"), icon_type="warning").exec()
            return
        tasks = []
        for task in self.download_queue:
            if task.get("status") in ("paused", "failed", "cancelled"):
                task["status"] = "queued"
                task["error"] = ""
            if task.get("status") == "queued":
                tasks.append(task)
                self._download_session_ids.add(task["id"])
        if not tasks:
            self._launch_pending_downloads(getattr(self, "_download_email", ""))
            return
        self._refresh_download_queue()
        self._start_download(tasks)

    def _download_log_line(self, line):
        # 下载区只保留一行简短状态，避免展示后端原始输出造成乱码和界面过高。
        text = str(line or "").strip()
        if not text or not hasattr(self, "download_current_lbl"):
            return
        if text.startswith(("[START]", "开始下载")):
            self.download_current_lbl.setText(text.replace("[START]", "", 1).replace(" ...", "").strip())
        elif text.startswith("[OK]"):
            self.download_current_lbl.setText(tr("recent_complete"))
        elif text.startswith(("[FAIL]", "[TIMEOUT]", "[错误]", "[失败]")):
            self.download_current_lbl.setText(tr("download_failed_hint"))

    def _on_download_progress(self, value):
        self._update_overall_download_progress()

    def _update_overall_download_progress(self):
        if not hasattr(self, "download_progress"):
            return
        tasks = self.download_queue
        if not tasks:
            self.download_progress.setRange(0, 100)
            self.download_progress.setValue(0)
            self.download_progress.setFormat(tr("waiting_download"))
            if hasattr(self, "download_current_lbl"):
                self.download_current_lbl.setText("")
            return
        values = []
        for task in tasks:
            if task.get("status") == "completed":
                values.append(100)
                continue
            total = int(task.get("total") or 0)
            downloaded = int(task.get("downloaded") or 0)
            if total > 0:
                values.append(max(0, min(100, int(downloaded * 100 / total))))
                continue
            # Unknown-size tasks must not be counted as a false 0% while
            # their size is still being read.
            pct = int(task.get("percent") if task.get("percent") is not None else -1)
            if pct >= 0:
                values.append(max(0, min(100, pct)))
        overall = int(sum(values) / len(values)) if values else 0
        done = sum(1 for q in tasks if q.get("status") == "completed")
        active = sum(1 for q in tasks if q.get("status") == "downloading")
        waiting = sum(1 for q in tasks if q.get("status") == "queued")
        self.download_progress.setRange(0, 100)
        self.download_progress.setValue(overall)
        self.download_progress.setFormat(
            tr("overall_progress") % (overall, done, len(tasks)))
        if hasattr(self, "download_current_lbl"):
            self.download_current_lbl.setText(tr("active_waiting") % (active, waiting))

    def _download_finished(self):
        self.download_start_btn.setEnabled(True)
        if hasattr(self, "download_current_lbl"):
            self.download_current_lbl.setText(tr("download_closed"))
        if hasattr(self, "_refresh_install_list"):
            self._refresh_install_list()

    # ═════════════════════════════════════════
    # ═════════════════════════════════════════
    def _build_install_tab(self):
        w = QWidget()
        w.setStyleSheet("background:transparent;")
        layout = QVBoxLayout(w)
        layout.setContentsMargins(20, 12, 20, 12)
        layout.setSpacing(10)

        btn_gray = ("QPushButton{background:rgba(255,255,255,70);color:#333;border:1px solid rgba(255,255,255,110);"
                   "border-radius:10px;font-size:13px;font-weight:600;padding:6px 16px;}"
                   "QPushButton:hover{background:rgba(255,255,255,120);}")
        list_style = ("QListWidget{background:rgba(255,255,255,55);border:1px solid rgba(255,255,255,100);"
                      "border-radius:12px;padding:6px;font-size:13px;color:#222;outline:none;}"
                      "QListWidget::item{padding:6px 8px;border-bottom:1px solid rgba(0,0,0,20);}"
                      "QListWidget::item:selected{background:rgba(0,122,255,60);border-radius:8px;}"
                      "QScrollBar:vertical{background:transparent;width:8px;border-radius:4px;margin:0px 2px;}"
                      "QScrollBar::handle:vertical{background:rgba(130,130,130,150);border-radius:4px;min-height:32px;}"
                      "QScrollBar::handle:vertical:hover{background:rgba(100,100,100,200);}"
                      "QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{height:0px;background:none;}")

        head = QHBoxLayout()
        head.setSpacing(8)
        self.install_header_lbl = QLabel(tr("install_header") % IPAS_DIR)
        head.addWidget(self.install_header_lbl)
        head.addStretch()
        self.install_open_dir_btn = QPushButton(tr("open_folder"))
        self.install_open_dir_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.install_open_dir_btn.setStyleSheet(btn_gray)
        self.install_open_dir_btn.clicked.connect(self._install_open_dir)
        head.addWidget(self.install_open_dir_btn)
        self.install_delete_btn = QPushButton(tr("delete_selected"))
        self.install_delete_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.install_delete_btn.setStyleSheet(btn_gray)
        self.install_delete_btn.clicked.connect(self._install_delete_selected)
        head.addWidget(self.install_delete_btn)
        self.install_clear_btn = QPushButton(tr("clear_all"))
        self.install_clear_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.install_clear_btn.setStyleSheet(btn_gray)
        self.install_clear_btn.clicked.connect(self._install_clear_all)
        head.addWidget(self.install_clear_btn)
        self.install_refresh_btn = QPushButton(tr("refresh"))
        self.install_refresh_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.install_refresh_btn.setStyleSheet(btn_gray)
        self.install_refresh_btn.clicked.connect(self._refresh_install_list)
        head.addWidget(self.install_refresh_btn)
        layout.addLayout(head)

        self.install_list = QListWidget()
        self.install_list.setStyleSheet(list_style)
        self.install_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.install_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.install_list.customContextMenuRequested.connect(self._on_install_context_menu)
        self.install_list.itemDoubleClicked.connect(self._install_open_folder)
        layout.addWidget(self.install_list, 1)

        self.install_tip = QLabel(tr("install_tip"))
        tip = self.install_tip
        tip.setStyleSheet("QLabel{font-size:12px;color:#555;background:rgba(255,255,255,40);"
                         "border-radius:10px;padding:10px;}")
        tip.setWordWrap(True)
        layout.addWidget(tip)

        self._refresh_install_list()
        return w

    def _refresh_install_list(self):
        self.install_list.clear()
        if not os.path.isdir(IPAS_DIR):
            return
        files = []
        for fn in os.listdir(IPAS_DIR):
            if fn.lower().endswith(".ipa"):
                full = os.path.join(IPAS_DIR, fn)
                st = os.stat(full)
                files.append((fn, st.st_size, st.st_mtime))
        files.sort(key=lambda x: x[2], reverse=True)
        for fn, size, mtime in files:
            dt = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")
            item = QListWidgetItem("%s\n%s %s  |  %s" %
                                  (fn, tr("size"), format_size(size), dt))
            item.setData(Qt.ItemDataRole.UserRole, os.path.join(IPAS_DIR, fn))
            self.install_list.addItem(item)
        if not files:
            self.install_list.addItem(tr("no_downloaded_ipa"))

    def _on_install_context_menu(self, pos):
        item = self.install_list.itemAt(pos)
        if not item:
            return
        path = item.data(Qt.ItemDataRole.UserRole)
        if not path or not os.path.exists(path):
            return
        menu = QMenu(self)
        act_open = menu.addAction(tr("open_folder_context"))
        act_copy = menu.addAction(tr("copy_path"))
        act_del = menu.addAction(tr("delete"))
        chosen = menu.exec(self.install_list.mapToGlobal(pos))
        if chosen == act_open:
            self._install_open_folder(item)
        elif chosen == act_copy:
            QApplication.clipboard().setText(path)
            MacStyleMessageBox(self, title=tr("copied_title"),
                               message=tr("path_copied") % path, icon_type="success").exec()
        elif chosen == act_del:
            dlg = MacStyleMessageBox(self, title=localized("确认删除", "Confirm deletion"),
                                     message=tr("confirm_delete_one") % os.path.basename(path),
                                     icon_type="question", buttons=[tr("ok"), tr("cancel")])
            if dlg.exec() == QDialog.DialogCode.Accepted:
                try:
                    os.remove(path)
                    self._refresh_install_list()
                except Exception as e:
                    MacStyleMessageBox(self, title=tr("delete_failed"), message=str(e), icon_type="warning").exec()

    def _install_open_folder(self, item):
        path = item.data(Qt.ItemDataRole.UserRole) if item else None
        if not path:
            return
        folder = os.path.dirname(path)
        try:
            os.startfile(folder)
        except Exception:
            QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    def _install_open_dir(self):
        """"""
        try:
            os.startfile(IPAS_DIR)
        except Exception:
            QDesktopServices.openUrl(QUrl.fromLocalFile(IPAS_DIR))

    def _install_collect_selected_paths(self):
        """"""
        paths = []
        for item in self.install_list.selectedItems():
            p = item.data(Qt.ItemDataRole.UserRole)
            if p and os.path.exists(p):
                paths.append(p)
        return paths

    def _install_delete_selected(self):
        """"""
        paths = self._install_collect_selected_paths()
        if not paths:
            MacStyleMessageBox(self, title=tr("choose_app_title"), message=tr("select_packages"),
                               icon_type="info").exec()
            return
        names = "\n".join(os.path.basename(p) for p in paths)
        dlg = MacStyleMessageBox(self, title=localized("确认删除", "Confirm deletion"),
                                 message=tr("confirm_delete_many") % (len(paths), names),
                                 icon_type="question", buttons=[tr("ok"), tr("cancel")])
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        failed = []
        for p in paths:
            try:
                os.remove(p)
            except Exception as e:
                failed.append("%s：%s" % (os.path.basename(p), e))
        self._refresh_install_list()
        if failed:
            MacStyleMessageBox(self, title=tr("partial_delete_failed"),
                               message="\n".join(failed), icon_type="warning").exec()
        else:
            MacStyleMessageBox(self, title=localized("已删除", "Deleted"),
                               message=tr("deleted_packages") % len(paths),
                               icon_type="success").exec()

    def _install_clear_all(self):
        """"""
        if not os.path.isdir(IPAS_DIR):
            return
        files = [os.path.join(IPAS_DIR, f) for f in os.listdir(IPAS_DIR) if f.lower().endswith(".ipa")]
        if not files:
            MacStyleMessageBox(self, title=tr("choose_app_title"), message=tr("nothing_to_clear"),
                               icon_type="info").exec()
            return
        dlg = MacStyleMessageBox(self, title=localized("确认清空", "Confirm clear"),
                                 message=tr("confirm_clear") % (len(files), IPAS_DIR),
                                 icon_type="question", buttons=[tr("ok"), tr("cancel")])
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        failed = 0
        for p in files:
            try:
                os.remove(p)
            except Exception:
                failed += 1
        self._refresh_install_list()
        if failed:
            MacStyleMessageBox(self, title=localized("清空结果", "Clear result"),
                               message=tr("clear_result") % failed,
                               icon_type="warning").exec()
        else:
            MacStyleMessageBox(self, title=localized("已清空", "Cleared"),
                               message=tr("cleared_packages") % len(files),
                               icon_type="success").exec()

# ─────────────────────────────────────────────
# ─────────────────────────────────────────────
def main():
    try:
        _clear_runtime_auth()
        load_config()
        app = QApplication(sys.argv)
        try:
            from PyQt6.QtCore import QTranslator
            import PyQt6 as _pq
            _td = os.path.join(os.path.dirname(_pq.__file__), "Qt6", "translations")
            for _qm in ("qt_zh_CN.qm", "qtbase_zh_CN.qm"):
                _tr = QTranslator()
                if _tr.load(_qm, _td):
                    app.installTranslator(_tr)
        except Exception:
            pass
        app.setQuitOnLastWindowClosed(False)
        font = QFont()
        font.setFamily("Microsoft YaHei")
        app.setFont(font)
        app.setStyleSheet("""""")
        win = TransparentMacWindow()
        win.show()
        win.raise_()
        win.activateWindow()
        if not IPATOOL_PATH:
            QTimer.singleShot(600, lambda: MacStyleMessageBox(
                win, title="软件组件异常",
                message="内部下载组件缺失，当前程序可能不完整。\n请重新下载完整的软件。",
                icon_type="warning").exec())
        else:
            win._arm_startup_login_tip()
        sys.exit(app.exec())
    except Exception as e:
        QMessageBox.critical(None, "错误", "程序发生错误:\n%s" % e)

if __name__ == "__main__":
    try:
        main()
    except Exception as _f:
        import traceback
        _show_error("致命错误", "%s\n\n%s" % (_f, traceback.format_exc()))

