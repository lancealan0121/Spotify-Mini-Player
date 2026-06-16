"""共用樣式與設定系統：主題色、縮放、字體、動畫模式、config 載入儲存。"""
import json
import math
import os
import sys
import time
from collections import OrderedDict

import shiboken6
from PySide6.QtGui import (QColor, QFont, QFontDatabase, QGuiApplication,
                           QImage, QPainter, QPainterPath, QPixmap)
from PySide6.QtCore import (QEasingCurve, QObject, QRectF, Qt, QTimer,
                            Signal, qInstallMessageHandler)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")

SPOTIFY_GREEN = QColor("#1DB954")
TEXT_DIM = QColor(255, 255, 255, 150)

COLOR_SETTING_KEYS = (
    "font_color",
    "source_text_color",
    "topbar_icon_color",
    "number_color",
    "seek_fill_color",
    "seek_thumb_color",
    "seek_track_color",
)

CARD_W, CARD_H = 400, 148
ART_SIZE = 96
MARGIN = 18            # 卡片外圍留給陰影的透明邊

# Segoe Fluent Icons / MDL2 圖示字元
GLYPH_PLAY = "\uE768"
GLYPH_PAUSE = "\uE769"
GLYPH_PREV = "\uE892"
GLYPH_NEXT = "\uE893"
GLYPH_SHUFFLE = "\uE8B1"
GLYPH_REPEAT_ALL = "\uE8EE"
GLYPH_REPEAT_ONE = "\uE8ED"
GLYPH_PIN = "\uE718"
GLYPH_CLOSE = "\uE8BB"
GLYPH_NOTE = "\uE8D6"
GLYPH_VOLUME = "\uE767"
GLYPH_VOLUME_0 = "\uE992"
GLYPH_VOLUME_1 = "\uE993"
GLYPH_VOLUME_2 = "\uE994"
GLYPH_VOLUME_3 = "\uE995"
GLYPH_MUTE = "\uE74F"
GLYPH_SETTINGS = "\uE713"
GLYPH_CHECK = "\uE73E"
GLYPH_GLOBE = "\uE774"
GLYPH_SEARCH = "\uE721"
GLYPH_CHEVRON_DOWN = "\uE70D"
GLYPH_CHEVRON_UP = "\uE70E"

# ---------------------------------------------------------------- 設定 ----

DEFAULTS = {
    "pinned": True,
    "theme": "auto",        # auto 或 THEMES 內的 key
    "bg_opacity": 1.0,      # 0.35 ~ 1.0
    "brightness": 0.9540801010635326,     # 0.55 ~ 1.45，mini player 背景亮度
    "auto_color_strength": 1.0,  # 0.0 ~ 1.0，自動主色背景強度
    "scale": 1.7038678271081824,          # 0.8 ~ 3.0
    "settings_scale": 1.199758606299479, # 0.8 ~ 2.0
    "settings_panel_type": "normal",  # normal / categories
    "auto_keep_on_screen": True,  # 視窗超出螢幕時自動拉回可見範圍
    "settings_advanced_open": False,  # 設定面板進階區塊是否展開
    "radius": 15,           # 6 ~ 28
    "anim": "full",
    "anim_enabled": True,
    "seek_style": "wave",   # plain / wave / glow
    "seek_thumb": "always", # hover / always，進度條白色圓鈕顯示方式
    "seek_thumb_shape": "circle",  # circle / star / rect
    "seek_wave_amp": 0.7049731860774968,
    "seek_wave_speed": 0.8993361381128148,
    "seek_glow_strength": 1.0031393708391512,
    "seek_length": 1.0504252783388335,
    "seek_thumb_size": 0.595937135919813,
    "progress_time_mode": "current",
    "controls_hover": True, # 控制列只在 hover 時顯示
    "marquee_enabled": True, # 曲名 / 作者過長時跑馬燈，關閉時省略號截斷
    "title_size": 0.997494556708598,
    "artist_size": 0.997494556708598,
    "title_x_offset": -0.20591344239150544,
    "title_y_offset": -0.20591344239150544,
    "artist_x_offset": -0.20591344239150544,
    "artist_y_offset": -0.20591344239150544,
    "auto_theme": "gradient",  # solid / gradient，封面自動主題背景模式
    "art_mode": "cover",    # cover / vinyl / pulse / audio，封面區顯示模式
    "art_cover_size": 0.9245844436826636,
    "art_vinyl_size": 0.9983334355091419,
    "audio_feedback_thickness": 1.0,
    "audio_feedback_sensitivity": 1.0,
    "show_vinyl_center": True,
    "vinyl_center_size": 1.0,
    "show_tonearm": True,
    "tonearm_speed": 0.7711820866029643,
    "vinyl_spin_speed": 1.0,
    "topbar_hover": False,
    "card_preset": "standard",
    "show_cover": True,
    "cover_blur": 0.0,
    "cover_shape": "rounded",  # rounded / square / circle
    "cover_radius_strength": 0.9974260819701061,
    "cover_border": True,
    "cover_border_width": 4.5109877979370285,
    "cover_border_opacity": 0.3524865930387484,
    "show_fps": False,
    "show_btn_shuffle": True,
    "show_btn_prev": True,
    "show_btn_next": True,
    "show_btn_repeat": True,
    "control_button_size": 0.9981209175314486,
    "control_button_spacing": 0.9962418350628971,
    "font": "Arial",
    "fps": 144,             # 24 ~ 240，特效計時器更新率
    "antialias": True,      # 反鋸齒
    "show_source": True,    # 左上角來源標誌（Spotify 圖示 + 文字）
    "source": "spotify",    # spotify / browser / any 媒體來源
    "startup_enabled": False,
    "startup_show": "boot",  # boot / spotify
    "gpu": True,            # GPU 合成（QT_WIDGETS_RHI，重啟後生效）
    "shadow": True,         # 背景陰影
    "controls_align": "left",   # 控制列位置 left / center / right
    "custom_grad": ["#1db954", "#3d9be9"],   # 自訂漸層主題的兩端色
    "background_image": "",     # 自訂卡片背景圖片路徑
    "background_image_mode": "cover",  # cover / contain / stretch / tile
    "background_image_brightness": 1.0,  # 0.35 ~ 1.65，自訂背景圖亮度
    "background_image_parallax": False,  # 自訂背景圖滑鼠視差
    "background_image_parallax_strength": 1.0,  # 0.0 ~ 2.0
    "background_image_parallax_fps": 30,  # 5 ~ 60，視差更新率
    "weather_enabled": False,  # 降水效果總開關
    "weather_effect": "rain",  # rain / snow / custom，目前編輯與顯示的降水類型
    "rain_enabled": False,   # 飄雨效果
    "rain_intensity": 0.55,   # 0.0 ~ 1.0，雨量強度
    "rain_length": 1.0,      # 0.05 ~ 1.6，雨線長度
    "rain_thickness": 1.0,   # 0.3 ~ 2.6，雨線粗細
    "rain_direction": 18.0,  # -55 ~ 55，雨線飄移角度（度）
    "rain_fall_speed": 1.0,  # 0.25 ~ 2.5，雨滴下落速度
    "snow_intensity": 0.42,   # 0.0 ~ 1.0，雪量強度
    "snow_length": 0.8,       # 0.05 ~ 1.6，雪拖尾長度
    "snow_thickness": 1.0,    # 0.3 ~ 2.6，雪花大小 / 粗細
    "snow_direction": -10.0,  # -55 ~ 55，雪花飄移角度（度）
    "snow_size": 1.0,         # 0.45 ~ 2.2，雪花大小
    "snow_spin_speed": 1.0,   # 0.0 ~ 3.0，雪花旋轉速度
    "snow_fall_speed": 1.0,   # 0.25 ~ 2.5，雪花下落速度
    "custom_intensity": 0.42, # 0.0 ~ 1.0，自訂符號密度
    "custom_size": 1.0,       # 0.45 ~ 2.2，自訂符號大小
    "custom_spin_speed": 1.0, # 0.0 ~ 3.0，自訂符號旋轉速度
    "custom_fall_speed": 1.0, # 0.25 ~ 2.5，自訂符號下落速度
    "custom_symbols": "❄,❅,❆", # 逗號分隔的自訂符號
    "custom_image": "",      # 自訂飄落圖片路徑，空字串 = 使用文字符號
    "lightning_enabled": False,
    "lightning_size": 1.0,       # 0.3 ~ 2.0，閃電尺寸
    "lightning_thickness": 1.0,  # 0.4 ~ 3.0，閃電線條粗細
    "lightning_intensity": 0.55, # 0.0 ~ 2.5，閃光強度與頻率
    "lightning_duration": 0.18,  # 0.05 ~ 1.5，閃電出現到消失秒數
    "lightning_duration_random": False, # 閃電持續時間隨機
    "font_color": "",           # 曲名 / 作者文字顏色，空字串 = 預設
    "source_text_color": "",    # 左上來源文字顏色，空字串 = 預設
    "topbar_icon_color": "",    # 右上工具列圖示顏色，空字串 = 預設
    "number_color": "",         # 進度數字顏色，空字串 = 預設
    "seek_fill_color": "",      # 進度條已播放顏色，空字串 = 跟隨主題色
    "seek_thumb_color": "",     # 進度條圓鈕顏色，空字串 = 白色
    "seek_track_color": "",     # 進度條總長度底色，空字串 = 預設淡白
    "custom_themes": [],    # 使用者新增主題：{key, name, colors:[hex] / [hex, hex]}
    "held_theme": None,     # 已刪除但目前仍套用中的自訂主題快照
    "hotkey": "",           # 全域快捷鍵：顯示 / 隱藏小播放器
    "hotkey_play": "",
    "hotkey_prev": "",
    "hotkey_next": "",
    "hotkey_vol_up": "",
    "hotkey_vol_down": "",
    "language": "ja",       # zh / ja / en
}

THEMES = [
    # (key, 名稱, 規格)：None = 封面自動、"glass" = 玻璃透明、
    # "custom" = 新增自訂主題按鈕、
    # "#hex" = 單色、("#hex", "#hex") = 雙色漸層
    # 前 COLS 個（settings_ui.SwatchRow）是收合時可見的第一列
    ("auto",     "封面自動",    None),
    ("glass",    "玻璃透明",    "glass"),
    ("custom",   "新增主題",    "custom"),
    ("green",    "Spotify 綠",  "#1DB954"),
    ("blue",     "海洋藍",      "#3D9BE9"),
    ("purple",   "紫羅蘭",      "#9B5FD0"),
    ("pink",     "櫻花粉",      "#E8638C"),
    ("orange",   "暖陽橙",      "#E08A3C"),
    ("sunset",   "落日漸層",    ("#E96443", "#904E95")),
    ("aurora",   "極光漸層",    ("#36D1AC", "#3A7BD5")),
    ("neon",     "霓虹漸層",    ("#FC5C7D", "#6A82FB")),
    ("ocean",    "海淵漸層",    ("#2193B0", "#6DD5ED")),
    ("forest",   "森林漸層",    ("#11998E", "#38EF7D")),
    ("dusk",     "暮色漸層",    ("#C06C84", "#355C7D")),
]

SEEK_STYLES = [("plain", "簡約"), ("wave", "波浪"), ("glow", "流光")]
SEEK_THUMBS = [("hover", "滑過顯示"), ("always", "常駐顯示")]
SEEK_THUMB_SHAPES = [("circle", "圓形"), ("star", "星星"), ("rect", "直條")]
PROGRESS_TIME_MODES = [("current", "目前"), ("remaining", "-剩餘")]
AUTO_THEME_MODES = [("solid", "單色"), ("gradient", "漸層")]
SOURCE_MODES = [("spotify", "Spotify"), ("browser", "瀏覽器"), ("any", "全部")]
CONTROLS_ALIGN = [("left", "靠左"), ("center", "置中"), ("right", "靠右")]
CARD_PRESETS = [("mini", "超迷你"), ("standard", "標準"),
                ("wide", "寬版"), ("controls", "控制列")]
WEATHER_EFFECTS = [("rain", "雨"), ("snow", "雪"), ("custom", "自訂")]
LANGUAGES = [("zh", "中文"), ("ja", "日本語"), ("en", "English")]
SETTINGS_PANEL_TYPES = [("normal", "一般"), ("categories", "分類")]
BACKGROUND_IMAGE_MODES = [
    ("cover", "填滿裁切"),
    ("contain", "完整顯示"),
    ("stretch", "拉伸填滿"),
    ("tile", "平鋪"),
]

I18N_PATH = os.path.join(BASE_DIR, "i18n.json")


def _load_i18n() -> dict:
    """從 i18n.json 載入語言字串；缺漏的鍵以 zh 補齊。

    語言文字一律放在外部 i18n.json（不寫死在程式裡），方便直接編修/新增
    語言。檔案結構為 {"zh": {...}, "ja": {...}, "en": {...}}。
    """
    try:
        with open(I18N_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    for lang, _ in LANGUAGES:
        if not isinstance(data.get(lang), dict):
            data[lang] = {}
    base = data.get("zh", {})
    for lang in data:
        if lang == "zh":
            continue
        for key, value in base.items():
            data[lang].setdefault(key, value)
    return data


_I18N = _load_i18n()

SETTINGS = dict(DEFAULTS)

_SAFE_UI_FONT = "Arial"
_BAD_UI_FONTS = {
    "fixedsys",
    "terminal",
    "system",
    "small fonts",
    "ms sans serif",
    "ms serif",
    "8514oem",
}
_QT_MESSAGE_HANDLER_INSTALLED = False
_PREV_QT_MESSAGE_HANDLER = None


def _font_substitution_names(name: str) -> tuple[str, ...]:
    base = str(name or "").strip()
    if not base:
        return ()
    return tuple(dict.fromkeys((
        base,
        base.lower(),
        base.upper(),
        base.title(),
    )))


def _format_qt_message(mode, context, message: str) -> str:
    category = getattr(context, "category", "") or ""
    prefix = ""
    name = getattr(mode, "name", "")
    if name.endswith("DebugMsg"):
        prefix = "debug: "
    elif name.endswith("InfoMsg"):
        prefix = "info: "
    elif name.endswith("WarningMsg"):
        prefix = "warning: "
    elif name.endswith("CriticalMsg"):
        prefix = "critical: "
    elif name.endswith("FatalMsg"):
        prefix = "fatal: "
    if category and category != "default":
        return f"{category}: {message}"
    return f"{prefix}{message}" if prefix else message


def install_qt_message_filter():
    """只靜音已知的 Windows DirectWrite 點陣字警告。

    Qt 在初始化或原生控制項 fallback 時仍可能嘗試載入 Fixedsys 這類
    .fon 點陣字，DirectWrite 會印出噪音警告；其他 Qt 訊息仍照常輸出。
    """
    global _QT_MESSAGE_HANDLER_INSTALLED, _PREV_QT_MESSAGE_HANDLER
    if _QT_MESSAGE_HANDLER_INSTALLED:
        return

    def handler(mode, context, message):
        text = str(message)
        lower = text.lower()
        category = getattr(context, "category", "") or ""
        if (category == "qt.qpa.fonts"
                and "CreateFontFaceFromHDC() failed" in text
                and any(name in lower for name in _BAD_UI_FONTS)):
            return
        if _PREV_QT_MESSAGE_HANDLER is not None:
            _PREV_QT_MESSAGE_HANDLER(mode, context, message)
            return
        print(_format_qt_message(mode, context, text), file=sys.stderr)

    _PREV_QT_MESSAGE_HANDLER = qInstallMessageHandler(handler)
    _QT_MESSAGE_HANDLER_INSTALLED = True


def is_safe_ui_font(family: str) -> bool:
    name = str(family or "").strip()
    return bool(name) and not name.startswith("@") and name.lower() not in _BAD_UI_FONTS


def safe_font_family(family: str | None = None) -> str:
    name = str(family or "").strip()
    if is_safe_ui_font(name):
        return name
    if QGuiApplication.instance() is None:
        return _SAFE_UI_FONT
    fams = set(QFontDatabase.families())
    for candidate in (_SAFE_UI_FONT, "Segoe UI", "Microsoft JhengHei UI"):
        if candidate in fams:
            return candidate
    return _SAFE_UI_FONT


def install_font_substitutions():
    """全域攔截 Windows 點陣系統字體（Fixedsys/Terminal/System 等）。

    這些 .fon 點陣字沒有 TrueType outline，Qt 的 DirectWrite 後端呼叫
    `CreateFontFaceFromHDC()` 會失敗並噴 `qt.qpa.fonts` 警告，更糟的是
    某些情況會在存取空 font face 時直接崩潰（exit code 0xC0000005）。
    `safe_font_family()` 只能擋設定面板選到的字體，攔不住原生對話框、
    系統 fallback 等以 `styleHint=AnyStyle` 明確請求這些 family 的來源；
    這裡改用 Qt 全域字體替換表一次把它們導向安全 UI 字體。需在
    QApplication 建立後、任何視窗建立前呼叫。"""
    if QGuiApplication.instance() is None:
        return
    target = safe_font_family()
    for bad in _BAD_UI_FONTS:
        for name in _font_substitution_names(bad):
            QFont.insertSubstitution(name, target)


def _valid_hex(value) -> str | None:
    c = QColor(str(value))
    return c.name() if c.isValid() else None


def _builtin_theme_keys() -> set[str]:
    return {k for k, _, _ in THEMES}


def _normalize_custom_theme(entry, idx: int,
                            used: set[str] | None = None) -> dict | None:
    if not isinstance(entry, dict):
        return None
    used = used if used is not None else set()
    raw_colors = entry.get("colors")
    if not isinstance(raw_colors, (list, tuple)):
        return None
    colors = []
    for raw in raw_colors[:2]:
        c = _valid_hex(raw)
        if c is not None:
            colors.append(c)
    if not colors:
        return None

    key = str(entry.get("key", "")).strip()
    if not key.startswith("user_") or key in used or key in _builtin_theme_keys():
        n = max(1, idx)
        key = f"user_{n}"
        while key in used or key in _builtin_theme_keys():
            n += 1
            key = f"user_{n}"

    name = str(entry.get("name", "")).strip() or f"Custom {idx}"
    name = name[:32]
    return {"key": key, "name": name, "colors": colors[:2]}


def normalize_custom_themes(items) -> list[dict]:
    out: list[dict] = []
    used = set(_builtin_theme_keys())
    if not isinstance(items, list):
        return out
    for item in items:
        norm = _normalize_custom_theme(item, len(out) + 1, used)
        if norm is None:
            continue
        used.add(norm["key"])
        out.append(norm)
    return out


def custom_theme_entries() -> list[tuple[str, str, str | tuple[str, str]]]:
    entries = []
    for item in SETTINGS.get("custom_themes", []):
        colors = item.get("colors", [])
        if len(colors) >= 2:
            spec = (colors[0], colors[1])
        elif len(colors) == 1:
            spec = colors[0]
        else:
            continue
        entries.append((item["key"], item.get("name", item["key"]), spec))
    return entries


def all_themes() -> list[tuple[str, str, object]]:
    return list(THEMES) + custom_theme_entries()


def add_custom_theme(entry) -> str | None:
    items = list(SETTINGS.get("custom_themes", []))
    used = {k for k, _, _ in all_themes()}
    norm = _normalize_custom_theme(entry, len(items) + 1, used)
    if norm is None:
        return None
    items.append(norm)
    SETTINGS["custom_themes"] = normalize_custom_themes(items)
    SETTINGS["held_theme"] = None
    return norm["key"]


def _held_theme_spec():
    held = SETTINGS.get("held_theme")
    if not isinstance(held, dict):
        return None
    if held.get("key") != SETTINGS.get("theme"):
        return None
    colors = held.get("colors")
    if not isinstance(colors, (list, tuple)) or not colors:
        return None
    norm = []
    for raw in colors[:2]:
        c = _valid_hex(raw)
        if c is not None:
            norm.append(c)
    if len(norm) >= 2:
        return (norm[0], norm[1])
    if len(norm) == 1:
        return norm[0]
    return None


def remove_custom_theme(key: str) -> bool:
    key = str(key or "").strip()
    items = list(SETTINGS.get("custom_themes", []))
    kept = []
    removed = None
    for item in items:
        if item.get("key") == key:
            removed = item
        else:
            kept.append(item)
    if removed is None:
        return False
    SETTINGS["custom_themes"] = normalize_custom_themes(kept)
    if SETTINGS.get("theme") == key:
        SETTINGS["held_theme"] = {
            "key": key,
            "name": removed.get("name", key),
            "colors": list(removed.get("colors", [])),
        }
    return True


def _migrate_legacy_custom_theme():
    if SETTINGS.get("theme") != "custom":
        return
    cg = SETTINGS.get("custom_grad", DEFAULTS["custom_grad"])
    entry = {
        "key": "user_legacy_custom",
        "name": "自訂漸層",
        "colors": [str(cg[0]), str(cg[1])],
    }
    if not any(t.get("key") == entry["key"]
               for t in SETTINGS.get("custom_themes", [])):
        SETTINGS["custom_themes"] = normalize_custom_themes(
            list(SETTINGS.get("custom_themes", [])) + [entry])
    SETTINGS["theme"] = entry["key"]


def load_settings():
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        data = {}
    SETTINGS.update(DEFAULTS)
    SETTINGS.update(data)
    for key in ("vinyl_style", "cover_reflection",
                "cover_soft_shadow", "volume_hover_pin", "volume_osd",
                "edge_snap", "edge_auto_collapse", "edge_slide_expand"):
        SETTINGS.pop(key, None)
    # 防呆夾限
    SETTINGS["bg_opacity"] = min(1.0, max(0.35, float(SETTINGS["bg_opacity"])))
    SETTINGS["brightness"] = min(1.45, max(0.55, float(SETTINGS["brightness"])))
    SETTINGS["scale"] = min(3.0, max(0.8, float(SETTINGS["scale"])))
    SETTINGS["settings_scale"] = min(
        2.0, max(0.8, float(SETTINGS["settings_scale"])))
    if SETTINGS.get("settings_panel_type") not in [
            k for k, _ in SETTINGS_PANEL_TYPES]:
        SETTINGS["settings_panel_type"] = "normal"
    SETTINGS["auto_keep_on_screen"] = bool(
        SETTINGS.get("auto_keep_on_screen", True))
    SETTINGS["settings_advanced_open"] = bool(
        SETTINGS.get("settings_advanced_open", False))
    SETTINGS.pop("settings_full_positions", None)
    SETTINGS["radius"] = min(28, max(6, int(SETTINGS["radius"])))
    SETTINGS["fps"] = min(240, max(24, int(SETTINGS["fps"])))
    SETTINGS["antialias"] = bool(SETTINGS["antialias"])
    SETTINGS["show_source"] = bool(SETTINGS["show_source"])
    SETTINGS["startup_enabled"] = bool(
        SETTINGS.get("startup_enabled", False))
    if SETTINGS.get("startup_show") not in ("boot", "spotify"):
        SETTINGS["startup_show"] = "boot"
    SETTINGS["gpu"] = bool(SETTINGS["gpu"])
    SETTINGS["shadow"] = bool(SETTINGS["shadow"])
    SETTINGS["anim_enabled"] = bool(SETTINGS.get("anim_enabled", True))
    SETTINGS["controls_hover"] = bool(SETTINGS.get("controls_hover", False))
    SETTINGS["topbar_hover"] = bool(SETTINGS.get("topbar_hover", False))
    SETTINGS["background_image"] = str(
        SETTINGS.get("background_image", "") or "").strip()
    if SETTINGS.get("background_image_mode") not in [
            k for k, _ in BACKGROUND_IMAGE_MODES]:
        SETTINGS["background_image_mode"] = "cover"
    SETTINGS["background_image_brightness"] = min(1.65, max(0.35, float(
        SETTINGS.get("background_image_brightness", 1.0))))
    SETTINGS["background_image_parallax"] = bool(
        SETTINGS.get("background_image_parallax", False))
    SETTINGS["background_image_parallax_strength"] = min(2.0, max(
        0.0, float(SETTINGS.get("background_image_parallax_strength", 1.0))))
    SETTINGS["background_image_parallax_fps"] = min(60, max(
        5, int(SETTINGS.get("background_image_parallax_fps", 30))))
    if "weather_enabled" not in data:
        SETTINGS["weather_enabled"] = bool(SETTINGS.get("rain_enabled", False))
    SETTINGS["weather_enabled"] = bool(SETTINGS.get("weather_enabled", False))
    if SETTINGS.get("weather_effect") not in (k for k, _ in WEATHER_EFFECTS):
        SETTINGS["weather_effect"] = "rain"
    SETTINGS["rain_enabled"] = bool(SETTINGS.get("rain_enabled", False))
    for prefix in ("rain", "snow"):
        SETTINGS[f"{prefix}_intensity"] = min(1.0, max(
            0.0, float(SETTINGS.get(f"{prefix}_intensity",
                                    DEFAULTS[f"{prefix}_intensity"]))))
        SETTINGS[f"{prefix}_length"] = min(1.6, max(
            0.05, float(SETTINGS.get(f"{prefix}_length",
                                     DEFAULTS[f"{prefix}_length"]))))
        SETTINGS[f"{prefix}_thickness"] = min(2.6, max(
            0.3, float(SETTINGS.get(f"{prefix}_thickness",
                                    DEFAULTS[f"{prefix}_thickness"]))))
        SETTINGS[f"{prefix}_direction"] = min(55.0, max(
            -55.0, float(SETTINGS.get(f"{prefix}_direction",
                                      DEFAULTS[f"{prefix}_direction"]))))
    SETTINGS["rain_fall_speed"] = min(2.5, max(
        0.25, float(SETTINGS.get("rain_fall_speed", 1.0))))
    SETTINGS["snow_size"] = min(2.2, max(
        0.45, float(SETTINGS.get(
            "snow_size", SETTINGS.get("snow_thickness", 1.0)))))
    SETTINGS["snow_spin_speed"] = min(3.0, max(
        0.0, float(SETTINGS.get("snow_spin_speed", 1.0))))
    SETTINGS["snow_fall_speed"] = min(2.5, max(
        0.25, float(SETTINGS.get("snow_fall_speed", 1.0))))
    SETTINGS["custom_intensity"] = min(1.0, max(
        0.0, float(SETTINGS.get("custom_intensity",
                                SETTINGS.get("snow_intensity", 0.42)))))
    SETTINGS["custom_size"] = min(2.2, max(
        0.45, float(SETTINGS.get("custom_size",
                                 SETTINGS.get("snow_size", 1.0)))))
    SETTINGS["custom_spin_speed"] = min(3.0, max(
        0.0, float(SETTINGS.get("custom_spin_speed",
                                SETTINGS.get("snow_spin_speed", 1.0)))))
    SETTINGS["custom_fall_speed"] = min(2.5, max(
        0.25, float(SETTINGS.get("custom_fall_speed",
                                 SETTINGS.get("snow_fall_speed", 1.0)))))
    if "custom_symbols" not in data:
        SETTINGS["custom_symbols"] = SETTINGS.get(
            "snow_symbols", DEFAULTS["custom_symbols"])
    raw_symbols = str(
        SETTINGS.get("custom_symbols", DEFAULTS["custom_symbols"]) or ""
    ).strip()
    symbols = [s.strip()[:4] for s in raw_symbols.split(",") if s.strip()]
    SETTINGS["custom_symbols"] = (
        ",".join(symbols[:24]) if symbols else DEFAULTS["custom_symbols"])
    SETTINGS["custom_image"] = str(
        SETTINGS.get("custom_image", "") or "").strip()
    SETTINGS["lightning_enabled"] = bool(
        SETTINGS.get("lightning_enabled", False))
    SETTINGS["lightning_size"] = min(2.0, max(
        0.3, float(SETTINGS.get("lightning_size", 1.0))))
    SETTINGS["lightning_thickness"] = min(3.0, max(
        0.4, float(SETTINGS.get("lightning_thickness", 1.0))))
    SETTINGS["lightning_intensity"] = min(2.5, max(
        0.0, float(SETTINGS.get("lightning_intensity", 0.55))))
    SETTINGS["lightning_duration"] = min(1.5, max(
        0.05, float(SETTINGS.get("lightning_duration", 0.18))))
    SETTINGS["lightning_duration_random"] = bool(
        SETTINGS.get("lightning_duration_random", False))
    for key in COLOR_SETTING_KEYS:
        raw = str(SETTINGS.get(key, "") or "").strip()
        c = QColor(raw) if raw else QColor()
        SETTINGS[key] = c.name(QColor.HexRgb) if c.isValid() else ""
    SETTINGS["marquee_enabled"] = bool(
        SETTINGS.get("marquee_enabled", True))
    SETTINGS["title_size"] = min(
        1.8, max(0.6, float(SETTINGS.get("title_size", 1.0))))
    SETTINGS["artist_size"] = min(
        1.8, max(0.6, float(SETTINGS.get("artist_size", 1.0))))
    for key in ("title_x_offset", "title_y_offset",
                "artist_x_offset", "artist_y_offset"):
        SETTINGS[key] = min(80.0, max(
            -80.0, float(SETTINGS.get(key, 0.0))))
    if SETTINGS.get("art_mode") not in ("cover", "vinyl", "pulse", "audio"):
        SETTINGS["art_mode"] = "cover"
    SETTINGS["art_cover_size"] = min(
        1.4, max(0.6, float(SETTINGS.get("art_cover_size", 1.0))))
    SETTINGS["art_vinyl_size"] = min(
        1.35, max(0.7, float(SETTINGS.get("art_vinyl_size", 1.0))))
    SETTINGS["audio_feedback_thickness"] = min(
        2.5, max(0.4, float(SETTINGS.get("audio_feedback_thickness", 1.0))))
    SETTINGS["audio_feedback_sensitivity"] = min(
        3.0, max(0.2, float(SETTINGS.get("audio_feedback_sensitivity", 1.0))))
    SETTINGS["show_vinyl_center"] = bool(
        SETTINGS.get("show_vinyl_center", True))
    SETTINGS["vinyl_center_size"] = min(
        1.4, max(0.4, float(SETTINGS.get("vinyl_center_size", 1.0))))
    SETTINGS["show_tonearm"] = bool(SETTINGS.get("show_tonearm", True))
    SETTINGS["tonearm_speed"] = min(
        2.5, max(0.4, float(SETTINGS.get("tonearm_speed", 1.0))))
    SETTINGS["vinyl_spin_speed"] = min(
        2.5, max(0.4, float(SETTINGS.get("vinyl_spin_speed", 1.0))))
    SETTINGS["show_cover"] = bool(SETTINGS.get("show_cover", True))
    SETTINGS["cover_blur"] = round(min(
        14.0, max(0.0, float(SETTINGS.get("cover_blur", 0.0)))), 1)
    if SETTINGS.get("cover_shape") not in ("rounded", "square", "circle"):
        SETTINGS["cover_shape"] = "rounded"
    SETTINGS["cover_radius_strength"] = min(
        2.0, max(0.0, float(SETTINGS.get("cover_radius_strength", 1.0))))
    SETTINGS["cover_border"] = bool(SETTINGS.get("cover_border", False))
    SETTINGS["cover_border_width"] = min(
        8.0, max(1.0, float(SETTINGS.get("cover_border_width", 2.0))))
    SETTINGS["cover_border_opacity"] = min(
        1.0, max(0.0, float(SETTINGS.get("cover_border_opacity", 0.85))))
    SETTINGS["show_fps"] = bool(SETTINGS.get("show_fps", False))
    for key in ("show_btn_shuffle", "show_btn_prev",
                "show_btn_next", "show_btn_repeat"):
        SETTINGS[key] = bool(SETTINGS.get(key, True))
    SETTINGS["control_button_size"] = min(
        1.6, max(0.7, float(SETTINGS.get("control_button_size", 1.0))))
    SETTINGS["control_button_spacing"] = min(
        2.2, max(0.4, float(SETTINGS.get("control_button_spacing", 1.0))))
    SETTINGS["font"] = safe_font_family(SETTINGS.get("font"))
    SETTINGS["auto_color_strength"] = min(
        1.0, max(0.0, float(SETTINGS.get("auto_color_strength", 1.0))))
    if SETTINGS.get("card_preset") not in [k for k, _ in CARD_PRESETS]:
        SETTINGS["card_preset"] = "standard"
    SETTINGS["anim"] = "full"
    SETTINGS["hotkey"] = str(SETTINGS.get("hotkey", "")).strip()
    for key in ("hotkey_play", "hotkey_prev", "hotkey_next",
                "hotkey_vol_up", "hotkey_vol_down"):
        SETTINGS[key] = str(SETTINGS.get(key, "")).strip()
    for key in ("settings_x", "settings_y"):
        if key in SETTINGS:
            try:
                SETTINGS[key] = int(SETTINGS[key])
            except (TypeError, ValueError):
                SETTINGS.pop(key, None)
    if SETTINGS.get("language") not in [k for k, _ in LANGUAGES]:
        SETTINGS["language"] = "zh"
    if SETTINGS["seek_style"] not in [k for k, _ in SEEK_STYLES]:
        SETTINGS["seek_style"] = "wave"
    if SETTINGS.get("seek_thumb") not in [k for k, _ in SEEK_THUMBS]:
        SETTINGS["seek_thumb"] = "hover"
    if SETTINGS.get("seek_thumb_shape") not in [
            k for k, _ in SEEK_THUMB_SHAPES]:
        SETTINGS["seek_thumb_shape"] = "circle"
    if SETTINGS.get("progress_time_mode") not in [
            k for k, _ in PROGRESS_TIME_MODES]:
        SETTINGS["progress_time_mode"] = "current"
    SETTINGS["seek_wave_amp"] = min(
        2.0, max(0.0, float(SETTINGS.get("seek_wave_amp", 1.0))))
    SETTINGS["seek_wave_speed"] = min(
        2.5, max(0.25, float(SETTINGS.get("seek_wave_speed", 1.0))))
    SETTINGS["seek_glow_strength"] = min(
        2.0, max(0.0, float(SETTINGS.get("seek_glow_strength", 1.0))))
    SETTINGS["seek_length"] = min(
        1.3, max(0.2, float(SETTINGS.get("seek_length", 1.0))))
    SETTINGS["seek_thumb_size"] = min(
        1.5, max(0.2, float(SETTINGS.get("seek_thumb_size", 1.0))))
    if SETTINGS.get("auto_theme") not in [k for k, _ in AUTO_THEME_MODES]:
        SETTINGS["auto_theme"] = "solid"
    if SETTINGS["source"] not in [k for k, _ in SOURCE_MODES]:
        SETTINGS["source"] = "spotify"
    if SETTINGS["controls_align"] not in [k for k, _ in CONTROLS_ALIGN]:
        SETTINGS["controls_align"] = "center"
    SETTINGS["custom_themes"] = normalize_custom_themes(
        SETTINGS.get("custom_themes", []))
    held = SETTINGS.get("held_theme")
    if isinstance(held, dict):
        colors = held.get("colors")
        if isinstance(colors, (list, tuple)):
            norm = []
            for raw in colors[:2]:
                c = _valid_hex(raw)
                if c is not None:
                    norm.append(c)
            SETTINGS["held_theme"] = {
                "key": str(held.get("key", "")).strip(),
                "name": str(held.get("name", "")).strip(),
                "colors": norm,
            } if norm else None
        else:
            SETTINGS["held_theme"] = None
    else:
        SETTINGS["held_theme"] = None
    cg = SETTINGS.get("custom_grad")
    if (isinstance(cg, (list, tuple)) and len(cg) == 2
            and all(QColor(str(c)).isValid() for c in cg)):
        SETTINGS["custom_grad"] = [QColor(str(c)).name() for c in cg]
    else:
        SETTINGS["custom_grad"] = list(DEFAULTS["custom_grad"])
    _migrate_legacy_custom_theme()
    if (SETTINGS["theme"] not in [k for k, _, _ in all_themes()]
            and _held_theme_spec() is None):
        SETTINGS["theme"] = "auto"
    return SETTINGS


def tr(key: str) -> str:
    lang = SETTINGS.get("language", "zh")
    return _I18N.get(lang, _I18N["zh"]).get(key, _I18N["zh"].get(key, key))


def optional_setting_color(key: str) -> QColor | None:
    raw = str(SETTINGS.get(key, "") or "").strip()
    if not raw:
        return None
    c = QColor(raw)
    return c if c.isValid() else None


def setting_color(key: str, fallback, alpha: int | None = None) -> QColor:
    c = optional_setting_color(key)
    if c is None:
        c = QColor(fallback)
    if not c.isValid():
        c = QColor("#ffffff")
    if alpha is not None:
        c.setAlpha(max(0, min(255, int(alpha))))
    return c


def theme_label(key: str, fallback: str) -> str:
    return tr(f"theme_{key}") if f"theme_{key}" in _I18N["zh"] else fallback


def save_settings():
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(SETTINGS, f, ensure_ascii=False, indent=1)
    except OSError:
        pass


def theme_spec():
    """目前主題的規格欄位（None / "glass" / "#hex" / (hex, hex)）。

    舊版 "custom" 仍會解析成 SETTINGS["custom_grad"]，新自訂主題則
    直接從 SETTINGS["custom_themes"] 合併進主題列表。
    """
    for key, _, spec in all_themes():
        if key == SETTINGS["theme"]:
            if spec == "custom":
                cg = SETTINGS.get("custom_grad",
                                  DEFAULTS["custom_grad"])
                return (str(cg[0]), str(cg[1]))
            return spec
    held = _held_theme_spec()
    if held is not None:
        return held
    return None


def theme_color() -> QColor | None:
    """目前主題的固定 accent；auto / glass 回傳 None（用封面主色）。

    漸層主題的 accent 取兩端中點色，控制元件（進度條、開關）才有單一
    代表色可用。
    """
    spec = theme_spec()
    if spec is None or spec == "glass":
        return None
    if isinstance(spec, tuple):
        return blend(QColor(spec[0]), QColor(spec[1]), 0.5)
    return QColor(spec)


def theme_gradient() -> tuple[QColor, QColor] | None:
    """漸層主題的兩端色；非漸層主題回傳 None。"""
    spec = theme_spec()
    if isinstance(spec, tuple):
        return QColor(spec[0]), QColor(spec[1])
    return None


def glass_theme() -> bool:
    return theme_spec() == "glass"


def S(v: float) -> int:
    """依視窗縮放比例換算尺寸。"""
    return round(v * SETTINGS["scale"])


def Sf(v: float) -> float:
    return v * SETTINGS["scale"]


# ---- 動畫模式 ----

def anim_on() -> bool:
    return bool(SETTINGS.get("anim_enabled", True)) and SETTINGS["anim"] != "off"


def anim_full() -> bool:
    return bool(SETTINGS.get("anim_enabled", True)) and SETTINGS["anim"] == "full"


def adur(full_ms: int, simple_ms: int | None = None) -> int:
    """依動畫模式回傳動畫長度；關閉時為 0。"""
    if not SETTINGS.get("anim_enabled", True):
        return 0
    if SETTINGS["anim"] == "off":
        return 0
    if SETTINGS["anim"] == "simple":
        return simple_ms if simple_ms is not None else int(full_ms * 0.55)
    return full_ms


def fps_ms() -> int:
    """特效計時器的間隔毫秒（依 fps 設定）。"""
    return max(4, round(1000 / SETTINGS["fps"]))


def aa(p: QPainter):
    """依設定套用反鋸齒（文字反鋸齒永遠開啟）。"""
    on = SETTINGS["antialias"]
    p.setRenderHint(QPainter.Antialiasing, on)
    p.setRenderHint(QPainter.SmoothPixmapTransform, on)
    p.setRenderHint(QPainter.TextAntialiasing, True)


# ---------------------------------------------------------------- 動畫 ----

class _AnimManager(QObject):
    """全域動畫計時器：所有 Anim 共用一個 PreciseTimer（間隔 = fps 設定）。

    沒有動畫進行時計時器自動停止，不佔 CPU。
    """

    def __init__(self):
        super().__init__()
        self._active: list = []
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.PreciseTimer)
        self._timer.setInterval(fps_ms())
        self._timer.timeout.connect(self._tick)

    def set_interval(self, ms: int):
        self._timer.setInterval(ms)

    def add(self, a: "Anim"):
        if a not in self._active:
            self._active.append(a)
        if not self._timer.isActive():
            self._timer.start()

    def remove(self, a: "Anim"):
        if a in self._active:
            self._active.remove(a)
        if not self._active:
            self._timer.stop()

    def _tick(self):
        now = time.monotonic()
        for a in list(self._active):
            if not shiboken6.isValid(a):     # 宿主元件已被 deleteLater 回收
                self.remove(a)
                continue
            a._step(now)


_ANIM_MGR: _AnimManager | None = None


def _anim_mgr() -> _AnimManager:
    global _ANIM_MGR
    if _ANIM_MGR is None:
        _ANIM_MGR = _AnimManager()
    return _ANIM_MGR


def apply_anim_fps():
    """fps 設定變更時同步全域動畫計時器間隔。"""
    if _ANIM_MGR is not None:
        _ANIM_MGR.set_interval(fps_ms())


class Anim(QObject):
    """時間基準數值動畫，取代 QVariantAnimation。

    QVariantAnimation 由 Qt 內部統一計時器驅動，固定約 60fps，在 Windows
    上還受粗粒度系統計時器（~15.6ms）拖累，fps 設定完全影響不到它；改由
    共用 PreciseTimer（間隔依 fps 設定）驅動，hover/滑桿等互動動畫才能
    真正跟上高更新率。介面對齊 QVariantAnimation 的使用子集
    （stop() 在進行中會同步發 finished，與 Qt 行為一致）。
    """

    valueChanged = Signal(float)
    finished = Signal()
    Stopped, Running = 0, 2

    def __init__(self, parent=None):
        super().__init__(parent)
        self._v0, self._v1 = 0.0, 1.0
        self._dur = 0.2          # 秒
        self._curve = QEasingCurve(QEasingCurve.Linear)
        self._t0 = 0.0
        self._running = False

    def setStartValue(self, v):
        self._v0 = float(v)

    def setEndValue(self, v):
        self._v1 = float(v)

    def setDuration(self, ms: int):
        self._dur = max(1, int(ms)) / 1000.0

    def setEasingCurve(self, curve):
        self._curve = QEasingCurve(curve)

    def state(self) -> int:
        return self.Running if self._running else self.Stopped

    def start(self):
        self._t0 = time.monotonic()
        self._running = True
        _anim_mgr().add(self)
        self.valueChanged.emit(self._v0)

    def stop(self):
        if self._running:
            self._running = False
            _anim_mgr().remove(self)
            self.finished.emit()

    def _step(self, now: float):
        t = (now - self._t0) / self._dur
        if t >= 1.0:
            self._running = False
            _anim_mgr().remove(self)
            self.valueChanged.emit(self._v1)
            self.finished.emit()
            return
        e = self._curve.valueForProgress(t)
        self.valueChanged.emit(self._v0 + (self._v1 - self._v0) * e)


# ---------------------------------------------------------------- 陰影 ----

_SHADOW_CACHE: OrderedDict[tuple, QPixmap] = OrderedDict()
_SHADOW_TPL: OrderedDict[tuple, QPixmap] = OrderedDict()
_SHADOW_CAP = 12
_SHADOW_TPL_CAP = 16


def _blur_rounded(W: int, H: int, radius: float, B: int,
                  alpha: int) -> QPixmap:
    """高斯模糊產生 (W+2B)×(H+2B) 的圓角矩形陰影（裝置像素，未設 dpr）。"""
    from PySide6.QtWidgets import QGraphicsBlurEffect, QGraphicsScene
    src = QPixmap(W, H)
    src.fill(Qt.transparent)
    p = QPainter(src)
    p.setRenderHint(QPainter.Antialiasing)
    path = QPainterPath()
    path.addRoundedRect(QRectF(0, 0, W, H), radius, radius)
    p.fillPath(path, QColor(0, 0, 0, alpha))
    p.end()
    scene = QGraphicsScene()
    item = scene.addPixmap(src)
    eff = QGraphicsBlurEffect()
    eff.setBlurRadius(B)
    item.setGraphicsEffect(eff)
    out = QPixmap(W + B * 2, H + B * 2)
    out.fill(Qt.transparent)
    p = QPainter(out)
    scene.render(p, QRectF(0, 0, out.width(), out.height()),
                 QRectF(-B, -B, W + B * 2, H + B * 2))
    p.end()
    return out


def soft_shadow(w: int, h: int, radius: float, blur: int = 18,
                alpha: int = 150, dpr: float = 1.0) -> QPixmap:
    """預先模糊好的圓角矩形陰影貼圖（快取）。

    QGraphicsDropShadowEffect 掛在 widget 上會讓子元件每幀重繪都重新做
    高斯模糊，是效能殺手；改成一次性產生貼圖，paintEvent 直接 drawPixmap。
    回傳貼圖比 (w, h) 大、四周各多 blur，繪製時座標要往左上偏 blur。

    高斯模糊本身也不便宜（縮放/圓角滑桿拖曳時每個新尺寸都要重算一次會
    微卡）：圓角矩形陰影沿直邊是平移不變的，所以先做一張小模板（角落 +
    可拉伸中段），任何尺寸都用 9-宮格拼出來，模糊只在每個圓角值做一次。
    """
    key = (int(w * dpr), int(h * dpr), round(radius * dpr * 2),
           int(blur * dpr), alpha)
    pm = _SHADOW_CACHE.get(key)
    if pm is not None:
        _SHADOW_CACHE.move_to_end(key)
        return pm

    W, H, B = int(w * dpr), int(h * dpr), int(blur * dpr)
    R = radius * dpr
    OW, OH = W + B * 2, H + B * 2
    m = int(math.ceil(R)) + B * 3     # 角區尺寸（含模糊外擴的安全餘量）
    s = 2                             # 可拉伸中段寬

    if OW >= 2 * m + s and OH >= 2 * m + s:
        tkey = (round(R * 2), B, alpha)
        tpl = _SHADOW_TPL.get(tkey)
        if tpl is None:
            side = 2 * m + s - 2 * B  # 模板矩形邊長（輸出為 2m+s 見方）
            tpl = _blur_rounded(side, side, R, B, alpha)
            _SHADOW_TPL[tkey] = tpl
            while len(_SHADOW_TPL) > _SHADOW_TPL_CAP:
                _SHADOW_TPL.popitem(last=False)
        else:
            _SHADOW_TPL.move_to_end(tkey)
        T = tpl.width()
        out = QPixmap(OW, OH)
        out.fill(Qt.transparent)
        p = QPainter(out)
        # 四角原樣複製
        p.drawPixmap(0, 0, tpl, 0, 0, m, m)
        p.drawPixmap(OW - m, 0, tpl, T - m, 0, m, m)
        p.drawPixmap(0, OH - m, tpl, 0, T - m, m, m)
        p.drawPixmap(OW - m, OH - m, tpl, T - m, T - m, m, m)
        # 四邊與中心：取中段窄帶拉伸（帶內各行/列相同，拉伸不失真）
        p.drawPixmap(QRectF(m, 0, OW - 2 * m, m), tpl, QRectF(m, 0, s, m))
        p.drawPixmap(QRectF(m, OH - m, OW - 2 * m, m),
                     tpl, QRectF(m, T - m, s, m))
        p.drawPixmap(QRectF(0, m, m, OH - 2 * m), tpl, QRectF(0, m, m, s))
        p.drawPixmap(QRectF(OW - m, m, m, OH - 2 * m),
                     tpl, QRectF(T - m, m, m, s))
        p.drawPixmap(QRectF(m, m, OW - 2 * m, OH - 2 * m),
                     tpl, QRectF(m, m, s, s))
        p.end()
    else:                             # 尺寸太小放不下模板角區：直接模糊
        out = _blur_rounded(W, H, R, B, alpha)

    out.setDevicePixelRatio(dpr)
    _SHADOW_CACHE[key] = out
    while len(_SHADOW_CACHE) > _SHADOW_CAP:
        _SHADOW_CACHE.popitem(last=False)
    return out


# ---------------------------------------------------------------- 來源 ----

# token（出現在 SMTC app id 中）→ 顯示名稱、進程 exe
_SOURCE_APPS = [
    ("spotify",          "SPOTIFY", ["spotify.exe"]),
    ("msedge",           "EDGE",    ["msedge.exe"]),
    ("edge",             "EDGE",    ["msedge.exe"]),
    ("chrome",           "CHROME",  ["chrome.exe"]),
    ("firefox",          "FIREFOX", ["firefox.exe"]),
    ("mozilla",          "FIREFOX", ["firefox.exe"]),
    ("308046b0af4a39cb", "FIREFOX", ["firefox.exe"]),   # Firefox 安裝雜湊 AUMID
    ("opera",            "OPERA",   ["opera.exe"]),
    ("brave",            "BRAVE",   ["brave.exe"]),
    ("vivaldi",          "VIVALDI", ["vivaldi.exe"]),
]

BROWSER_TOKENS = [t for t, _, _ in _SOURCE_APPS if t != "spotify"]


def source_info(app_id: str) -> tuple[str, list[str], bool]:
    """由 SMTC app id 取得（顯示名稱, 進程 exe 清單, 是否為 Spotify）。"""
    low = (app_id or "").lower()
    for token, label, exes in _SOURCE_APPS:
        if token in low:
            return label, exes, token == "spotify"
    return "MEDIA", [], False


# ---------------------------------------------------------------- 字體 ----

_ICON_FAMILY = None


def icon_family() -> str:
    global _ICON_FAMILY
    if _ICON_FAMILY is None:
        fams = set(QFontDatabase.families())
        _ICON_FAMILY = next((f for f in ("Segoe Fluent Icons",
                                         "Segoe MDL2 Assets") if f in fams),
                            "Segoe UI Symbol")
    return _ICON_FAMILY


def icon_font(px: int) -> QFont:
    f = QFont(icon_family())
    f.setPixelSize(px)
    return f


def ui_font(px: int, weight=QFont.Normal) -> QFont:
    f = QFont(safe_font_family(SETTINGS.get("font")), weight=weight)
    f.setPixelSize(px)
    return f


# ---------------------------------------------------------------- 顏色 ----

def blend(a: QColor, b: QColor, t: float) -> QColor:
    """RGB 內插（含 alpha）。"""
    return QColor(round(a.red() + (b.red() - a.red()) * t),
                  round(a.green() + (b.green() - a.green()) * t),
                  round(a.blue() + (b.blue() - a.blue()) * t),
                  round(a.alpha() + (b.alpha() - a.alpha()) * t))


def fmt_time(sec: float) -> str:
    sec = max(0, int(sec))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


_DOM_CACHE: OrderedDict[int, QColor] = OrderedDict()
_GRAD_CACHE: OrderedDict[int, tuple[QColor, QColor]] = OrderedDict()


def _fit_cover_color(c: QColor) -> QColor:
    h, s, v, _ = QColor(c).getHsv()
    if h < 0:
        return QColor.fromHsv(220, 42, 176)
    s = max(s, 108) if s > 35 else s
    v = min(max(v, 145), 224)
    return QColor.fromHsv(h, s, v)


def _fallback_cover_pair(c: QColor) -> tuple[QColor, QColor]:
    base = _fit_cover_color(c)
    h, s, v, _ = base.getHsv()
    if h < 0:
        h = 220
    other = QColor.fromHsv((h + 34) % 360,
                           min(255, round(s * 0.92)),
                           max(82, round(v * 0.76)))
    return base, other


def dominant_color(img: QImage) -> QColor:
    """從封面取出最有代表性的主色，調整到適合當背景底色的明度。

    純 Python 逐像素統計不便宜，以 QImage.cacheKey() 快取：同一張封面
    （上一首/下一首來回、縮放重建卡片）不重算。
    """
    ck = img.cacheKey()
    cached = _DOM_CACHE.get(ck)
    if cached is not None:
        _DOM_CACHE.move_to_end(ck)
        return QColor(cached)
    small = img.scaled(28, 28, Qt.IgnoreAspectRatio,
                       Qt.SmoothTransformation).convertToFormat(
                           QImage.Format_RGB32)
    buckets = {}
    for y in range(small.height()):
        for x in range(small.width()):
            c = small.pixelColor(x, y)
            v = c.value()
            if v < 26:          # 接近全黑的像素不具代表性
                continue
            s = c.saturation()
            key = (c.red() >> 5, c.green() >> 5, c.blue() >> 5)
            score = (s / 255) ** 1.4 * (v / 255) + 0.02
            acc = buckets.setdefault(key, [0, 0, 0, 0, 0.0])
            acc[0] += c.red()
            acc[1] += c.green()
            acc[2] += c.blue()
            acc[3] += 1
            acc[4] += score
    if not buckets:
        result = QColor(SPOTIFY_GREEN)
    else:
        best = max(buckets.values(), key=lambda a: a[4])
        c = QColor(best[0] // best[3], best[1] // best[3], best[2] // best[3])
        h, s, v, _ = c.getHsv()
        if h < 0:               # 無色相（灰階封面）給個沉穩的藍灰
            result = QColor.fromHsv(220, 40, 180)
        else:
            s = max(s, 110) if s > 35 else s
            v = min(max(v, 150), 220)
            result = QColor.fromHsv(h, s, v)
    _DOM_CACHE[ck] = QColor(result)
    while len(_DOM_CACHE) > 16:
        _DOM_CACHE.popitem(last=False)
    return result


def cover_gradient(img: QImage) -> tuple[QColor, QColor]:
    """從封面抓兩個代表色，用於自動雙色漸層背景。"""
    ck = img.cacheKey()
    cached = _GRAD_CACHE.get(ck)
    if cached is not None:
        _GRAD_CACHE.move_to_end(ck)
        return QColor(cached[0]), QColor(cached[1])

    small = img.scaled(32, 32, Qt.IgnoreAspectRatio,
                       Qt.SmoothTransformation).convertToFormat(
                           QImage.Format_RGB32)
    buckets: dict[tuple[int, int, int], list[float]] = {}
    for y in range(small.height()):
        for x in range(small.width()):
            c = small.pixelColor(x, y)
            v = c.value()
            if v < 24:
                continue
            s = c.saturation()
            if s < 18 and v < 160:
                continue
            key = (c.red() >> 4, c.green() >> 4, c.blue() >> 4)
            score = (0.25 + (s / 255) ** 1.25) * (0.35 + v / 255)
            acc = buckets.setdefault(key, [0.0, 0.0, 0.0, 0.0, 0.0])
            acc[0] += c.red()
            acc[1] += c.green()
            acc[2] += c.blue()
            acc[3] += 1.0
            acc[4] += score

    if not buckets:
        result = _fallback_cover_pair(QColor(SPOTIFY_GREEN))
    else:
        candidates = []
        for acc in buckets.values():
            n = max(1.0, acc[3])
            color = _fit_cover_color(QColor(round(acc[0] / n),
                                            round(acc[1] / n),
                                            round(acc[2] / n)))
            candidates.append((color, acc[4]))
        candidates.sort(key=lambda item: item[1], reverse=True)
        c0, score0 = candidates[0]
        best = None
        best_score = -1.0
        for c, score in candidates[1:18]:
            dr = (c.red() - c0.red()) / 255.0
            dg = (c.green() - c0.green()) / 255.0
            db = (c.blue() - c0.blue()) / 255.0
            dist = math.sqrt(dr * dr + dg * dg + db * db)
            h0, _, _, _ = c0.getHsv()
            h1, _, _, _ = c.getHsv()
            hue = 0.0
            if h0 >= 0 and h1 >= 0:
                hue = min(abs(h0 - h1), 360 - abs(h0 - h1)) / 180.0
            pick_score = score * (0.55 + dist + hue * 0.65)
            if dist > 0.18 and pick_score > best_score:
                best = c
                best_score = pick_score
        result = (c0, best) if best is not None else _fallback_cover_pair(c0)

    _GRAD_CACHE[ck] = (QColor(result[0]), QColor(result[1]))
    while len(_GRAD_CACHE) > 16:
        _GRAD_CACHE.popitem(last=False)
    return QColor(result[0]), QColor(result[1])
