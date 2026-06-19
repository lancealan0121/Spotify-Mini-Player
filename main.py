"""Spotify Mini — 不需要 API 的桌面迷你播放器。

透過 Windows 媒體傳輸控制（SMTC）遙控 Spotify 桌面版（或瀏覽器等其他媒體來源）：
無邊框置頂小卡片、封面主色漸層背景、跑馬燈標題、可拖曳進度條、
播放/上一首/下一首/隨機/循環、音量控制、自訂設定面板、系統匣常駐。

開發用參數：
    --demo          使用假資料顯示版面（不連 Spotify）
    --panel         啟動時順便打開設定面板
    --startup       由 Windows 開機啟動項呼叫
    --startup-hide  開機先常駐，偵測到 Spotify 後再顯示
    --shot <path>   啟動 1.5 秒後截圖存檔並退出（面板開啟時加存 *_panel）
"""
import ctypes
import json
import math
import os
import random
import subprocess
import sys
import time
from urllib.parse import quote
from collections import OrderedDict
from ctypes import wintypes

from PySide6.QtCore import (QEvent, QEasingCurve, QPoint, QPointF, QRectF,
                            QSizeF, Qt, QTimer, Signal)
from PySide6.QtGui import (QColor, QCursor, QFont, QFontMetricsF, QIcon,
                           QImage, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap,
                           QRadialGradient)
from PySide6.QtWidgets import (QApplication, QFileDialog,
                               QGraphicsOpacityEffect, QLabel, QMenu,
                               QSystemTrayIcon, QWidget)

from edit_mode import (_EditGhostLayer, _EditLayoutOverlay, _EditLibrary,
                       _EditReplica)
from settings_ui import SettingsPanel, VolumePopup, fade_in, fade_out
from style import (ART_SIZE, CARD_H, CARD_W, CONFIG_PATH, FPS_MAX, FPS_MIN, GLYPH_CLOSE, GLYPH_EDIT, GLYPH_GLOBE,
                   GLYPH_NEXT, GLYPH_NOTE, GLYPH_PIN, GLYPH_PREV,
                   GLYPH_REPEAT_ALL, GLYPH_REPEAT_ONE, GLYPH_RESET, GLYPH_SETTINGS,
                   GLYPH_SHUFFLE, GLYPH_VOLUME, MARGIN, S, SETTINGS,
                   SPOTIFY_GREEN, Anim, DEFAULTS, Sf, TEXT_DIM, aa, adur,
                   anim_on, add_custom_theme, apply_anim_fps,
                   apply_settings_data, blend,
                   cover_gradient, dominant_color,
                   fmt_time, remove_custom_theme,
                   glass_theme, icon_font, install_font_substitutions,
                   install_qt_message_filter, load_settings, save_settings,
                   optional_setting_color, safe_font_family, soft_shadow, source_info,
                   theme_color, theme_gradient, tr, ui_font)
from volume import AppMasterAudioMeter, AppVolume, SystemSpectrumAnalyzer
from widgets import (ArtView, IconButton, LaunchButton, MarqueeLabel,
                     PlayButton, SeekBar)

def empty_text(mode: str) -> str:
    return tr(f"empty_{mode}") if mode in ("spotify", "browser", "any") else tr("empty_spotify")

WM_HOTKEY = 0x0312
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000

_HOTKEY_SPECIAL = {
    "SPACE": 0x20,
    "TAB": 0x09,
    "ENTER": 0x0D,
    "RETURN": 0x0D,
    "ESC": 0x1B,
    "ESCAPE": 0x1B,
    "BACKSPACE": 0x08,
    "DELETE": 0x2E,
    "DEL": 0x2E,
    "INSERT": 0x2D,
    "INS": 0x2D,
    "HOME": 0x24,
    "END": 0x23,
    "PAGEUP": 0x21,
    "PAGEDOWN": 0x22,
    "LEFT": 0x25,
    "UP": 0x26,
    "RIGHT": 0x27,
    "DOWN": 0x28,
}

_TIMER_RESOLUTION_ACTIVE = False


def _apply_timer_resolution():
    """讓 Windows 的 QTimer 在 100+ FPS 設定下不被 15.6ms 系統粒度卡住。"""
    global _TIMER_RESOLUTION_ACTIVE
    want = (sys.platform.startswith("win")
            and int(SETTINGS.get("fps", 60)) > 60)
    if want == _TIMER_RESOLUTION_ACTIVE:
        return
    try:
        if want:
            ok = ctypes.windll.winmm.timeBeginPeriod(1) == 0
            _TIMER_RESOLUTION_ACTIVE = bool(ok)
        else:
            ctypes.windll.winmm.timeEndPeriod(1)
            _TIMER_RESOLUTION_ACTIVE = False
    except Exception:
        _TIMER_RESOLUTION_ACTIVE = False


def _release_timer_resolution():
    global _TIMER_RESOLUTION_ACTIVE
    if not _TIMER_RESOLUTION_ACTIVE or not sys.platform.startswith("win"):
        _TIMER_RESOLUTION_ACTIVE = False
        return
    try:
        ctypes.windll.winmm.timeEndPeriod(1)
    finally:
        _TIMER_RESOLUTION_ACTIVE = False


def parse_hotkey(seq: str) -> tuple[int, int] | None:
    parts = [p.strip().upper() for p in str(seq or "").split("+") if p.strip()]
    if not parts:
        return None
    mods = MOD_NOREPEAT
    vk = None
    for part in parts:
        if part in ("CTRL", "CONTROL"):
            mods |= MOD_CONTROL
        elif part == "ALT":
            mods |= MOD_ALT
        elif part == "SHIFT":
            mods |= MOD_SHIFT
        elif part in ("WIN", "META", "SUPER"):
            mods |= MOD_WIN
        elif len(part) == 1 and ("A" <= part <= "Z" or "0" <= part <= "9"):
            vk = ord(part)
        elif part.startswith("F") and part[1:].isdigit():
            n = int(part[1:])
            if 1 <= n <= 24:
                vk = 0x70 + n - 1
        else:
            vk = _HOTKEY_SPECIAL.get(part)
    if vk is None:
        return None
    return mods, vk


# 官方 Spotify 圖示（spt.png：綠圓 + 鏤空波浪，畫在深色卡片上即官方深色版）
_LOGO_CACHE: dict[tuple[int, int], QPixmap] = {}
_LOGO_SRC: QImage | None = None


def spotify_logo_pixmap(d: float, dpr: float) -> QPixmap | None:
    global _LOGO_SRC
    px = max(1, round(d * dpr))
    bucket = max(1, int(round(px / 8.0) * 8))
    dpr_key = max(1, round(dpr * 100))
    key = (bucket, dpr_key)
    pm = _LOGO_CACHE.get(key)
    if pm is None:
        if _LOGO_SRC is None:
            path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "spt.png")
            img = QImage(path)
            if img.isNull():
                return None
            _LOGO_SRC = img
        pm = QPixmap.fromImage(
            _LOGO_SRC.scaled(bucket, bucket, Qt.KeepAspectRatio,
                             Qt.SmoothTransformation))
        pm.setDevicePixelRatio(dpr)
        _LOGO_CACHE[key] = pm
    return pm


def rounded_pixmap(img: QImage, size: int, radius: int, dpr: float) -> QPixmap:
    radius = max(0, min(size // 2, int(radius)))
    px = int(size * dpr)
    pm = QPixmap(px, px)
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    path = QPainterPath()
    path.addRoundedRect(QRectF(0, 0, size, size), radius, radius)
    p.setClipPath(path)
    scaled = img.scaled(px, px, Qt.KeepAspectRatioByExpanding,
                        Qt.SmoothTransformation)
    sx = max(0.0, (scaled.width() - px) / 2.0)
    sy = max(0.0, (scaled.height() - px) / 2.0)
    p.drawImage(QRectF(0, 0, size, size), scaled,
                QRectF(sx, sy, px, px))
    p.end()
    return pm


# ---------------------------------------------------------------- 卡片 ----

class _CardFade(QWidget):
    """空狀態 ↔ 內容切換時舊畫面淡出的過渡層（蓋在卡片上，不擋滑鼠）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._pm: QPixmap | None = None
        self._t = 1.0
        self._anim = Anim(self)
        self._anim.valueChanged.connect(self._on_t)
        self._anim.finished.connect(self._done)
        self.hide()

    def _on_t(self, v):
        self._t = float(v)
        self.update()

    def _done(self):
        self._pm = None
        self.hide()

    def start(self, pm: QPixmap, ms: int):
        self._anim.stop()
        self._pm = pm
        self._t = 0.0
        self.resize(self.parentWidget().size())
        self.show()
        self.raise_()
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.setDuration(ms)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.start()

    def paintEvent(self, _):
        if self._pm is None:
            return
        p = QPainter(self)
        p.setOpacity(1.0 - self._t)
        p.drawPixmap(0, 0, self._pm)


class TimeLabel(QLabel):
    """底部時間文字：seek / 回起點時快速數字內插。"""

    TEXT_STYLES = ("fade", "slide", "slide2")

    def __init__(self, text="0:00", parent=None):
        super().__init__(text, parent)
        self._sec = 0.0
        self._target = 0.0
        self._prefix = ""
        self._anim = Anim(self)
        self._anim.valueChanged.connect(self._on_value)
        self._text_t = 1.0
        self._old_text = text
        self._new_text = text
        self._text_style = "slide"
        self._text_anim = Anim(self)
        self._text_anim.valueChanged.connect(self._on_text_t)
        self._text_anim.finished.connect(self._text_done)
        self._edit_angle = 0.0

    def set_edit_angle(self, angle: float):
        angle = float(angle or 0.0)
        if abs(angle - self._edit_angle) < 0.01:
            return
        self._edit_angle = angle
        self.update()

    def _apply_edit_rotation(self, p: QPainter):
        if abs(self._edit_angle) < 0.01:
            return
        p.translate(self.width() / 2.0, self.height() / 2.0)
        p.rotate(self._edit_angle)
        p.translate(-self.width() / 2.0, -self.height() / 2.0)

    def _text_for(self, sec: float, prefix: str | None = None) -> str:
        return f"{self._prefix if prefix is None else prefix}{fmt_time(sec)}"

    def _on_value(self, v):
        self._sec = float(v)
        QLabel.setText(self, self._text_for(self._sec))

    def _on_text_t(self, v):
        self._text_t = max(0.0, min(1.0, float(v)))
        self.update()

    def _text_done(self):
        self._text_t = 1.0
        QLabel.setText(self, self._new_text)
        self.update()

    def _can_animate_digits_only(self) -> bool:
        if len(self._old_text) != len(self._new_text):
            return False
        return any(a != b and (a.isdigit() or b.isdigit())
                   for a, b in zip(self._old_text, self._new_text))

    def _animate_text_to(self, text: str, style: str = "slide") -> bool:
        old = self._new_text if self._text_anim.state() == Anim.Running else QLabel.text(self)
        if old == text:
            QLabel.setText(self, text)
            return False
        self._anim.stop()
        self._text_anim.stop()
        self._old_text = old
        self._new_text = text
        self._text_style = style if style in self.TEXT_STYLES else "fade"
        QLabel.setText(self, text)
        ms = adur(290, 180) if self._text_style == "slide2" else adur(180, 110)
        if not anim_on() or ms <= 0 or not self.isVisible():
            self._text_t = 1.0
            self.update()
            return False
        self._text_t = 0.0
        self._text_anim.setStartValue(0.0)
        self._text_anim.setEndValue(1.0)
        self._text_anim.setDuration(ms)
        self._text_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._text_anim.start()
        return True

    def set_seconds(self, sec: float, animate: bool = False,
                    prefix: str = "", text_transition: bool = False,
                    transition_style: str = "slide"):
        sec = max(0.0, float(sec))
        prefix = str(prefix or "")
        prefix_changed = prefix != self._prefix
        new_text = self._text_for(sec, prefix)
        self._prefix = prefix
        if text_transition:
            self._sec = sec
            self._target = sec
            self._animate_text_to(new_text, transition_style)
            return
        if self._text_anim.state() == Anim.Running:
            if new_text != self._new_text:
                self._new_text = new_text
                QLabel.setText(self, new_text)
                self.update()
            self._sec = sec
            self._target = sec
            return
        if animate and anim_on() and abs(sec - self._sec) > 0.35:
            self._target = sec
            self._anim.stop()
            self._anim.setStartValue(self._sec)
            self._anim.setEndValue(sec)
            self._anim.setDuration(adur(190, 100))
            self._anim.setEasingCurve(QEasingCurve.OutCubic)
            self._anim.start()
            return
        self._anim.stop()
        self._sec = sec
        self._target = sec
        if prefix_changed or QLabel.text(self) != new_text:
            QLabel.setText(self, new_text)

    def paintEvent(self, e):
        if self._text_t >= 0.999:
            if abs(self._edit_angle) < 0.01:
                super().paintEvent(e)
                return
            p = QPainter(self)
            aa(p)
            self._apply_edit_rotation(p)
            p.setFont(self.font())
            col = self.palette().color(self.foregroundRole())
            if not col.isValid():
                col = QColor(255, 255, 255, 120)
            p.setPen(col)
            p.drawText(QRectF(self.rect()),
                       self.alignment() or (Qt.AlignLeft | Qt.AlignVCenter),
                       self.text())
            return
        p = QPainter(self)
        aa(p)
        self._apply_edit_rotation(p)
        p.setFont(self.font())
        col = self.palette().color(self.foregroundRole())
        if not col.isValid():
            col = QColor(255, 255, 255, 120)
        r = QRectF(self.rect())
        dy = max(3.0, self.height() * 0.42)
        align = self.alignment() or (Qt.AlignLeft | Qt.AlignVCenter)
        t = self._text_t
        p.setPen(col)
        if self._can_animate_digits_only():
            self._paint_digit_transition(p, r, align, col, dy, t)
        elif self._text_style == "fade":
            p.setOpacity(1.0 - t)
            p.drawText(r, align, self._old_text)
            p.setOpacity(t)
            p.drawText(r, align, self._new_text)
        elif self._text_style == "slide2":
            slide_dy = dy * 1.45
            p.setOpacity(1.0 - t)
            p.drawText(r.translated(0, -slide_dy * t), align,
                       self._old_text)
            p.setOpacity(t)
            p.drawText(r.translated(0, slide_dy * (1.0 - t)), align,
                       self._new_text)
        else:
            p.setOpacity(1.0 - t)
            p.drawText(r.translated(0, -dy * t), align, self._old_text)
            p.setOpacity(t)
            p.drawText(r.translated(0, dy * (1.0 - t)), align, self._new_text)

    def _text_start_x(self, fm: QFontMetricsF, rect: QRectF, align) -> float:
        text_w = fm.horizontalAdvance(self._new_text)
        if align & Qt.AlignRight:
            return rect.right() - text_w
        if align & Qt.AlignHCenter:
            return rect.x() + (rect.width() - text_w) / 2.0
        return rect.x()

    def _paint_digit_transition(self, p: QPainter, rect: QRectF, align,
                                color: QColor, dy: float, t: float):
        fm = QFontMetricsF(p.font())
        x = self._text_start_x(fm, rect, align)
        baseline = rect.center().y() + (fm.ascent() - fm.descent()) / 2.0
        for old_ch, new_ch in zip(self._old_text, self._new_text):
            new_w = fm.horizontalAdvance(new_ch)
            if old_ch == new_ch or not (old_ch.isdigit() or new_ch.isdigit()):
                p.setOpacity(1.0)
                p.setPen(color)
                p.drawText(QPointF(x, baseline), new_ch)
                x += new_w
                continue
            old_w = fm.horizontalAdvance(old_ch)
            old_x = x + (new_w - old_w) / 2.0
            p.setPen(color)
            if self._text_style == "fade":
                p.setOpacity(1.0 - t)
                p.drawText(QPointF(old_x, baseline), old_ch)
                p.setOpacity(t)
                p.drawText(QPointF(x, baseline), new_ch)
            elif self._text_style == "slide2":
                slide_dy = dy * 1.45
                p.setOpacity(1.0 - t)
                p.drawText(QPointF(old_x, baseline - slide_dy * t), old_ch)
                p.setOpacity(t)
                p.drawText(QPointF(x, baseline + slide_dy * (1.0 - t)),
                           new_ch)
            else:
                p.setOpacity(1.0 - t)
                p.drawText(QPointF(old_x, baseline - dy * t), old_ch)
                p.setOpacity(t)
                p.drawText(QPointF(x, baseline + dy * (1.0 - t)), new_ch)
            x += new_w


class _SeekHoverTimeOverlay(QWidget):
    """進度條 hover 秒數泡泡；不接滑鼠，避免擴大 SeekBar 點擊區。"""

    def __init__(self, seek: SeekBar, parent=None):
        super().__init__(parent)
        self._seek = seek
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAutoFillBackground(False)

    def paintEvent(self, _):
        seek = self._seek
        if seek is None or seek.isHidden() or seek._dur <= 0:
            return
        t = max(0.0, min(1.0, float(seek._hover_time_t)))
        if t <= 0.001:
            return
        text = fmt_time(seek._hover_sec)
        track_h = max(1.0, float(seek.height()))
        font_px = max(7, round(track_h * 0.48))
        font = ui_font(font_px, QFont.DemiBold)
        fm = QFontMetricsF(font)
        pad_x = max(5.0, track_h * 0.22)
        pill_w = max(26.0, fm.horizontalAdvance(text) + pad_x * 2)
        pill_h = max(13.0, track_h * 0.82)
        sx = float(seek.x()) + max(0.0, min(float(seek.width()),
                                            float(seek._hover_x)))
        x = max(1.0, min(float(self.width()) - pill_w - 1.0,
                         sx - pill_w / 2.0))
        y = max(1.0, float(seek.y()) - pill_h - S(2)
                - (1.0 - t) * S(3))
        r = QRectF(x, y, pill_w, pill_h)
        p = QPainter(self)
        aa(p)
        p.setOpacity(t)
        p.setPen(QPen(QColor(255, 255, 255, 34), 1.0))
        p.setBrush(QColor(10, 10, 12, 176))
        p.drawRoundedRect(r, pill_h / 2.0, pill_h / 2.0)
        p.setFont(font)
        p.setPen(QColor(255, 255, 255, 218))
        p.drawText(r, Qt.AlignCenter, text)


class _SourceLogo(QWidget):
    """來源小圖示；獨立 widget 避免封面切換時父層局部重繪裁切。"""

    def __init__(self, spotify: bool = True, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.setAutoFillBackground(False)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self._spotify = bool(spotify)
        self._color = QColor(255, 255, 255, 170)
        self._edit_angle = 0.0

    def set_edit_angle(self, angle: float):
        angle = float(angle or 0.0)
        if abs(angle - self._edit_angle) < 0.01:
            return
        self._edit_angle = angle
        self.update()

    def _apply_edit_rotation(self, p: QPainter):
        if abs(self._edit_angle) < 0.01:
            return
        p.translate(self.width() / 2.0, self.height() / 2.0)
        p.rotate(self._edit_angle)
        p.translate(-self.width() / 2.0, -self.height() / 2.0)

    def set_spotify(self, spotify: bool):
        spotify = bool(spotify)
        if spotify == self._spotify:
            return
        self._spotify = spotify
        self.update()

    def set_color(self, color: QColor):
        self._color = QColor(color)
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        aa(p)
        self._apply_edit_rotation(p)
        d = max(1.0, min(self.width(), self.height()) - 2.0)
        r = QRectF((self.width() - d) / 2.0, (self.height() - d) / 2.0,
                   d, d)
        if not self._spotify:
            p.setFont(icon_font(max(1, round(d * 0.85))))
            p.setPen(self._color)
            p.drawText(r, Qt.AlignCenter, GLYPH_GLOBE)
            return
        pm = spotify_logo_pixmap(d, self.devicePixelRatioF())
        if pm is not None:
            p.setRenderHint(QPainter.SmoothPixmapTransform, True)
            p.drawPixmap(r, pm, QRectF(pm.rect()))
        else:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(SPOTIFY_GREEN))
            p.drawEllipse(r)


class _RotatingLabel(QLabel):
    """Simple QLabel variant used by edit mode angle controls."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._edit_angle = 0.0

    def set_edit_angle(self, angle: float):
        angle = float(angle or 0.0)
        if abs(angle - self._edit_angle) < 0.01:
            return
        self._edit_angle = angle
        self.update()

    def paintEvent(self, e):
        if abs(self._edit_angle) < 0.01:
            super().paintEvent(e)
            return
        p = QPainter(self)
        aa(p)
        p.translate(self.width() / 2.0, self.height() / 2.0)
        p.rotate(self._edit_angle)
        p.translate(-self.width() / 2.0, -self.height() / 2.0)
        p.setFont(self.font())
        col = self.palette().color(self.foregroundRole())
        if not col.isValid():
            col = QColor(255, 255, 255, 140)
        p.setPen(col)
        p.drawText(QRectF(self.rect()),
                   self.alignment() or (Qt.AlignLeft | Qt.AlignVCenter),
                   self.text())


class _WeatherLayer(QWidget):
    """卡片背景上的輕量降水層：雨線或飄雪，共用一組顯示面板控制。"""

    _FPS_CAP = 72

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.setAutoFillBackground(False)
        self._rng = random.Random()
        self._drops: list[dict] = []
        self._splashes: list[dict] = []
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.PreciseTimer)
        self._timer.timeout.connect(self._tick)
        self._last = time.monotonic()
        self._effect = "rain"
        self._intensity = 0.0
        self._length_scale = 1.0
        self._thickness_scale = 1.0
        self._size_scale = 1.0
        self._spin_speed = 1.0
        self._fall_speed = 1.0
        self._direction = 18.0
        self._snow_symbols = ("❄", "❅", "❆")
        self._snow_cache: dict[tuple[str, int, int], QPixmap] = {}
        self._custom_image_path = ""
        self._custom_image: QImage | None = None
        self._custom_image_cache: dict[tuple[str, int, int], QPixmap] = {}
        self._clip_path_cache: QPainterPath | None = None
        self._clip_path_key = None
        self._fade = 0.0
        self._active_target = False
        self._fade_anim = Anim(self)
        self._fade_anim.valueChanged.connect(self._on_fade)
        self._fade_anim.finished.connect(self._fade_done)
        self.hide()
        self.apply_settings()

    def apply_settings(self):
        old_effect = self._effect
        self._effect = str(SETTINGS.get("weather_effect", "rain"))
        if self._effect not in ("rain", "snow", "custom"):
            self._effect = "rain"
        if old_effect != self._effect:
            self._drops.clear()
            self._splashes.clear()
            self._fade = 0.0
        self._intensity = max(
            0.0, min(1.0, float(SETTINGS.get(
                f"{self._effect}_intensity", 0.55))))
        if self._effect in ("snow", "custom"):
            prefix = self._effect
            self._size_scale = max(
                0.45, min(2.2, float(SETTINGS.get(f"{prefix}_size", 1.0))))
            self._spin_speed = max(
                0.0, min(3.0, float(SETTINGS.get(
                    f"{prefix}_spin_speed", 1.0))))
            self._fall_speed = max(
                0.25, min(2.5, float(SETTINGS.get(
                    f"{prefix}_fall_speed", 1.0))))
            if self._effect == "custom":
                self._load_custom_image()
                raw_symbols = str(
                    SETTINGS.get("custom_symbols", "❄,❅,❆") or "")
                symbols = tuple(s.strip()[:4] for s in raw_symbols.split(",")
                                if s.strip())
                self._snow_symbols = (
                    symbols[:24] if symbols else ("❄", "❅", "❆"))
            else:
                self._snow_symbols = ("❄", "❅", "❆")
            self._length_scale = 0.0
            self._thickness_scale = self._size_scale
            self._direction = 0.0
        else:
            self._length_scale = max(
                0.05, min(1.6, float(SETTINGS.get("rain_length", 1.0))))
            self._thickness_scale = max(
                0.3, min(2.6, float(SETTINGS.get("rain_thickness", 1.0))))
            self._direction = max(
                -55.0, min(55.0, float(SETTINGS.get("rain_direction", 18.0))))
            self._fall_speed = max(
                0.25, min(2.5, float(SETTINGS.get("rain_fall_speed", 1.0))))
        active = (bool(SETTINGS.get("weather_enabled", False))
                  and self._intensity > 0.0005)
        self._active_target = active
        self.apply_fps()
        self._refresh_drop_settings()
        if active:
            self._sync_drop_count()
            self.show()
            self._last = time.monotonic()
            if not self._timer.isActive():
                self._timer.start()
            self._animate_fade(1.0)
        else:
            self._animate_fade(0.0)
        self.update()

    def _on_fade(self, value):
        self._fade = max(0.0, min(1.0, float(value)))
        self.update()

    def _fade_done(self):
        self._fade = 1.0 if self._active_target else 0.0
        if not self._active_target:
            self._timer.stop()
            self.hide()
        self.update()

    def _animate_fade(self, target: float):
        target = max(0.0, min(1.0, float(target)))
        if not anim_on():
            self._fade_anim.stop()
            self._fade = target
            self._fade_done()
            return
        if abs(self._fade - target) < 0.001:
            if target > 0.0:
                self.show()
            else:
                self._fade_done()
            return
        self._fade_anim.stop()
        self._fade_anim.setStartValue(self._fade)
        self._fade_anim.setEndValue(target)
        self._fade_anim.setDuration(adur(420, 260))
        self._fade_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._fade_anim.start()

    def apply_fps(self):
        fps = max(FPS_MIN, min(FPS_MAX, int(SETTINGS.get("fps", 60))))
        fps = min(self._FPS_CAP, fps)
        self._timer.setInterval(max(8, round(1000 / fps)))

    def _refresh_drop_settings(self):
        if self._effect in ("snow", "custom"):
            for d in self._drops:
                if "base_size" in d:
                    d["size"] = d["base_size"] * self._size_scale
                if "base_speed" in d:
                    d["speed"] = d["base_speed"] * self._fall_speed
                if "base_spin" in d:
                    d["spin"] = d["base_spin"] * self._spin_speed
        else:
            for d in self._drops:
                if "base_speed" in d:
                    d["speed"] = d["base_speed"] * self._fall_speed

    def _target_count(self) -> int:
        if self._intensity <= 0.0005:
            return 0
        area = max(1, self.width() * self.height())
        area_scale = max(0.6, area / float(CARD_W * CARD_H))
        density = self._intensity ** 1.55
        if self._effect in ("snow", "custom"):
            return max(1, min(140, round(
                (2 + 74 * density) * area_scale)))
        return max(1, min(260, round(
            (1 + 130 * density) * area_scale)))

    def _new_drop(self, reset: bool = False) -> dict:
        w, h = max(1, self.width()), max(1, self.height())
        depth = self._rng.random() ** 0.45
        if self._effect in ("snow", "custom"):
            base_size = (0.85 + 2.2 * depth) * max(0.85, S(1))
            size = base_size * self._size_scale
            base_speed = ((30.0 + 104.0 * depth)
                          * (0.72 + self._intensity * 0.46))
            base_spin = self._rng.uniform(-95.0, 95.0) * (0.4 + depth)
            return {
                "x": self._rng.uniform(-w * 0.12, w * 1.12),
                "y": self._rng.uniform(-h, h) if reset else self._rng.uniform(-h * 0.35, -size),
                "depth": depth,
                "base_size": base_size,
                "size": size,
                "glyph": self._rng.choice(self._snow_symbols),
                "angle": self._rng.uniform(0.0, 360.0),
                "base_spin": base_spin,
                "spin": base_spin * self._spin_speed,
                "base_speed": base_speed,
                "speed": base_speed * self._fall_speed,
                "phase": self._rng.uniform(0.0, 6.283),
            }
        length = ((5.0 + 18.0 * depth + 8.0 * self._intensity)
                  * self._length_scale * max(0.85, S(1)))
        base_speed = ((220.0 + 520.0 * depth)
                      * (0.75 + self._intensity * 0.55))
        return {
            "x": self._rng.uniform(-w * 0.15, w * 1.15),
            "y": self._rng.uniform(-h, h) if reset else self._rng.uniform(-h * 0.45, -length),
            "depth": depth,
            "len": length,
            "base_speed": base_speed,
            "speed": base_speed * self._fall_speed,
            "phase": self._rng.uniform(0.0, 6.283),
        }

    def _sync_drop_count(self):
        target = self._target_count()
        while len(self._drops) < target:
            self._drops.append(self._new_drop(reset=True))
        if len(self._drops) > target:
            del self._drops[target:]

    def _add_splash(self, x: float):
        if (self._intensity < 0.18 or self._fade < 0.25
                or self._rng.random() > 0.42 + self._intensity * 0.35):
            return
        y = self.height() - self._rng.uniform(3.0, max(4.0, self.height() * 0.13))
        for _ in range(2 + int(self._rng.random() * 3)):
            self._splashes.append({
                "x": x + self._rng.uniform(-2.0, 2.0),
                "y": y,
                "vx": self._rng.uniform(-24.0, 24.0),
                "vy": self._rng.uniform(-34.0, -12.0),
                "life": self._rng.uniform(0.16, 0.28),
                "max": 0.28,
            })
        if len(self._splashes) > 48:
            del self._splashes[:-48]

    def _tick(self):
        now = time.monotonic()
        dt = min(0.05, max(0.006, now - self._last))
        self._last = now
        if not self.isVisible():
            return
        self._sync_drop_count()
        w, h = max(1, self.width()), max(1, self.height())
        angle = math.radians(self._direction)
        if self._effect in ("snow", "custom"):
            wind = math.tan(angle) * 76.0 * (0.45 + self._intensity * 0.55)
            for d in self._drops:
                depth = d["depth"]
                d["phase"] += dt * (0.9 + depth * 1.4)
                d["angle"] = (d.get("angle", 0.0)
                              + d.get("spin", 0.0) * dt) % 360.0
                wobble = math.sin(d["phase"]) * (8.0 + 20.0 * depth)
                d["x"] += (wind * (0.35 + depth * 0.85) + wobble) * dt
                d["y"] += d["speed"] * dt
                size = d.get("size", 2.0)
                if d["y"] - size > h or d["x"] < -w * 0.22 or d["x"] > w * 1.22:
                    d.update(self._new_drop(reset=False))
                    d["x"] = self._rng.uniform(-w * 0.12, w * 1.12)
            self.update()
            return
        wind = math.tan(angle) * 430.0 * (0.35 + self._intensity * 0.65)
        for d in self._drops:
            depth = d["depth"]
            sway = 12.0 * self._intensity * (0.25 + depth)
            d["phase"] += dt * (1.1 + depth)
            d["x"] += (wind * (0.35 + depth * 0.9)
                       + sway * math.sin(d["phase"] * 1.7) * 0.18) * dt
            d["y"] += d["speed"] * dt
            if d["y"] - d["len"] > h or d["x"] > w + d["len"] * 2.4:
                self._add_splash(d["x"])
                d.update(self._new_drop(reset=False))
                d["x"] = self._rng.uniform(-w * 0.25, w * 1.02)
        alive = []
        for s in self._splashes:
            s["life"] -= dt
            if s["life"] <= 0.0:
                continue
            s["x"] += s["vx"] * dt
            s["y"] += s["vy"] * dt
            s["vy"] += 190.0 * dt
            alive.append(s)
        self._splashes = alive
        self.update()

    def resizeEvent(self, _):
        self._sync_drop_count()

    def showEvent(self, _):
        if (bool(SETTINGS.get("weather_enabled", False))
                and self._intensity > 0.001):
            self._last = time.monotonic()
            if not self._timer.isActive():
                self._timer.start()

    def hideEvent(self, _):
        self._timer.stop()

    def _load_custom_image(self) -> QImage | None:
        path = str(SETTINGS.get("custom_image", "") or "").strip()
        if path != self._custom_image_path:
            self._custom_image_path = path
            self._custom_image_cache.clear()
            self._custom_image = QImage(path) if path else None
        if self._custom_image is None or self._custom_image.isNull():
            return None
        return self._custom_image

    def _custom_image_pixmap(self, px: float) -> QPixmap | None:
        img = self._load_custom_image()
        if img is None:
            return None
        dpr = max(1.0, self.devicePixelRatioF())
        px_i = max(6, min(110, round(px)))
        dpr_i = max(1, round(dpr * 100))
        key = (self._custom_image_path, px_i, dpr_i)
        pm = self._custom_image_cache.get(key)
        if pm is not None:
            return pm
        side = max(1, round(px_i * dpr))
        pm = QPixmap.fromImage(img).scaled(
            side, side, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        pm.setDevicePixelRatio(dpr)
        if len(self._custom_image_cache) > 96:
            self._custom_image_cache.clear()
        self._custom_image_cache[key] = pm
        return pm

    def _snow_glyph_pixmap(self, glyph: str, px: float) -> QPixmap:
        dpr = max(1.0, self.devicePixelRatioF())
        px_i = max(7, min(90, round(px)))
        dpr_i = max(1, round(dpr * 100))
        key = (glyph, px_i, dpr_i)
        pm = self._snow_cache.get(key)
        if pm is not None:
            return pm
        side = max(1, round(px_i * 1.45 * dpr))
        pm = QPixmap(side, side)
        pm.setDevicePixelRatio(dpr)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        aa(p)
        p.setFont(QFont("Segoe UI Symbol", px_i, QFont.DemiBold))
        p.setPen(QColor(242, 248, 255, 230))
        logical = side / dpr
        p.drawText(QRectF(0, 0, logical, logical),
                   Qt.AlignCenter, glyph)
        p.end()
        if len(self._snow_cache) > 160:
            self._snow_cache.clear()
        self._snow_cache[key] = pm
        return pm

    def _clip_path(self) -> QPainterPath:
        radius = Sf(SETTINGS.get("radius", 15))
        key = (self.width(), self.height(), round(radius * 100))
        if self._clip_path_cache is not None and self._clip_path_key == key:
            return self._clip_path_cache
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, self.width(), self.height()),
                            radius, radius)
        self._clip_path_cache = path
        self._clip_path_key = key
        return path

    def paintEvent(self, _):
        if self._intensity <= 0.0005 or self._fade <= 0.001:
            return
        p = QPainter(self)
        aa(p)
        p.setOpacity(self._fade)
        p.setClipPath(self._clip_path())
        if self._effect in ("snow", "custom"):
            p.setRenderHint(QPainter.SmoothPixmapTransform,
                            SETTINGS["antialias"])
            fade = self._fade
            k_alpha = 0.38 + self._intensity * 0.66
            is_custom = self._effect == "custom"
            custom_pm = self._custom_image_pixmap
            glyph_pm = self._snow_glyph_pixmap
            p_save, p_restore = p.save, p.restore
            p_translate, p_rotate = p.translate, p.rotate
            p_setop, p_drawpm = p.setOpacity, p.drawPixmap
            for d in self._drops:
                depth = d["depth"]
                alpha = round((48 + depth * 106) * k_alpha)
                if alpha <= 2:
                    continue
                size = d.get("size", 2.0)
                if size < 0.5:
                    size = 0.5
                pm = None
                if is_custom:
                    pm = custom_pm(max(7.0, min(96.0, size * 5.2)))
                if pm is None:
                    pm = glyph_pm(d.get("glyph", "❄"),
                                  max(7.0, min(72.0, size * 4.2)))
                dpr = pm.devicePixelRatioF()
                if dpr < 1.0:
                    dpr = 1.0
                pw, ph = pm.width() / dpr, pm.height() / dpr
                p_save()
                p_translate(d["x"], d["y"])
                p_rotate(d.get("angle", 0.0))
                p_setop(fade * min(1.0, alpha / 210.0))
                p_drawpm(QPointF(-pw / 2.0, -ph / 2.0), pm)
                p_restore()
            return
        drift_k = math.tan(math.radians(self._direction))
        line_col = QColor(214, 232, 255)
        pen = QPen(line_col, 1.0)
        pen.setCapStyle(Qt.RoundCap)
        hi_col = QColor(255, 255, 255)
        tw = self._thickness_scale
        hi_pen = QPen(hi_col, max(0.25, 0.45 * tw))
        k_alpha = 0.42 + self._intensity * 0.72
        set_pen, draw_line = p.setPen, p.drawLine
        pen_color, pen_width = pen.setColor, pen.setWidthF
        line_alpha = line_col.setAlpha
        hi_alpha, hi_color = hi_col.setAlpha, hi_pen.setColor
        for d in self._drops:
            depth = d["depth"]
            alpha = round((26 + depth * 92) * k_alpha)
            if alpha <= 2:
                continue
            length = d["len"]
            drift = drift_k * length
            dx, dy = d["x"], d["y"]
            line_alpha(150 if alpha > 150 else alpha)
            pen_color(line_col)
            pen_width((0.45 + depth * 1.15) * tw)
            set_pen(pen)
            draw_line(QPointF(dx, dy), QPointF(dx - drift, dy - length))
            if depth > 0.62:
                ha = alpha // 2
                hi_alpha(70 if ha > 70 else ha)
                hi_color(hi_col)
                set_pen(hi_pen)
                draw_line(QPointF(dx + 0.8, dy - length * 0.1),
                          QPointF(dx - drift * 0.42, dy - length * 0.62))
        sp_col = QColor(225, 240, 255)
        sp_pen = QPen(sp_col, max(0.3, 0.75 * self._thickness_scale))
        for s in self._splashes:
            t = max(0.0, min(1.0, s["life"] / s["max"]))
            sp_col.setAlpha(round(72 * t))
            sp_pen.setColor(sp_col)
            p.setPen(sp_pen)
            p.drawLine(QPointF(s["x"], s["y"]),
                       QPointF(s["x"] - s["vx"] * 0.045,
                               s["y"] - 2.6 * t))


class _LightningLayer(QWidget):
    """短暫閃光與分支閃電，獨立於雨雪設定。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.setAutoFillBackground(False)
        self._rng = random.Random()
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.PreciseTimer)
        self._timer.timeout.connect(self._tick)
        # 等待出招期間只需偵測 _wait 歸零，用低頻計時省 CPU（閃電平均數秒
        # 一次，50ms 誤差人眼無感）；_strike() 後才切到全速畫衰減動畫。
        self._wait_interval = 50
        self._active_interval = 50
        self._last = time.monotonic()
        self._flash = 0.0
        self._screen_flash = 0.0
        self._bolt_flash = 0.0
        self._life = 0.16
        self._screen_life = 0.16
        self._bolt_life = 0.16
        self._age = 0.0
        self._wait = 1.0
        self._size = 1.0
        self._intensity = 0.0
        self._thickness = 1.0
        self._duration = 0.18
        self._duration_random = False
        self._flash_peak = 0.0
        self._bolts: list[list[QPointF]] = []
        self._clip_path_cache: QPainterPath | None = None
        self._clip_path_key = None
        self.hide()
        self.apply_settings()

    def apply_settings(self):
        self._size = max(
            0.3, min(2.0, float(SETTINGS.get("lightning_size", 1.0))))
        self._thickness = max(
            0.4, min(3.0, float(SETTINGS.get("lightning_thickness", 1.0))))
        old_intensity = self._intensity
        self._intensity = max(
            0.0, min(2.5, float(SETTINGS.get("lightning_intensity", 0.55))))
        self._duration = max(
            0.05, min(1.5, float(SETTINGS.get("lightning_duration", 0.18))))
        self._duration_random = bool(
            SETTINGS.get("lightning_random_duration",
                         SETTINGS.get("lightning_duration_random", False)))
        active = (bool(SETTINGS.get("lightning_enabled", False))
                  and self._intensity > 0.001)
        self.apply_fps()
        if active:
            self.show()
            self._last = time.monotonic()
            if abs(old_intensity - self._intensity) > 0.01 and self._flash <= 0.001:
                self._wait = self._next_wait()
            if not self._timer.isActive():
                self._wait = self._next_wait()
                self._timer.start()
        else:
            self._timer.stop()
            self._flash = 0.0
            self._screen_flash = 0.0
            self._bolt_flash = 0.0
            self._bolts.clear()
            self.hide()
        self.update()

    def apply_fps(self):
        fps = max(FPS_MIN, min(FPS_MAX, int(SETTINGS.get("fps", 60))))
        self._active_interval = (
            0 if fps >= FPS_MAX else max(8, round(1000 / fps)))
        # 閃光中（高頻衰減動畫）才全速；等待期維持低頻省 CPU
        self._timer.setInterval(self._active_interval
                                if self._flash > 0.001
                                else self._wait_interval)

    def _next_wait(self) -> float:
        chance = 0.045 + self._intensity ** 2.25
        return self._rng.uniform(1.2, 4.8) / chance

    def _strike(self):
        w, h = max(1.0, float(self.width())), max(1.0, float(self.height()))
        start = QPointF(self._rng.uniform(w * 0.14, w * 0.86),
                        -max(2.0, h * 0.03))
        end_y = h + max(2.0, h * 0.04)
        length = end_y - start.y()
        segments = max(5, round(6 + 6 * self._size))
        pts = [start]
        x = start.x()
        y = start.y()
        drift = self._rng.uniform(-0.18, 0.18) * w * self._size
        bend = self._rng.uniform(-0.16, 0.16) * w * self._size
        for i in range(1, segments + 1):
            t = i / segments
            y = start.y() + length * t
            x += (drift / segments
                  + bend * (0.5 - abs(t - 0.5)) / max(1, segments)
                  + self._rng.uniform(-w, w) * 0.030 * self._size)
            x = max(w * 0.04, min(w * 0.96, x))
            pts.append(QPointF(x, y))
        bolts = [pts]
        branch_count = max(1, round(1 + 4 * self._size * self._intensity))
        for _ in range(branch_count):
            base_idx = self._rng.randrange(1, max(2, len(pts) - 1))
            base = pts[base_idx]
            side = -1 if self._rng.random() < 0.5 else 1
            blen = length * self._rng.uniform(0.10, 0.26) * self._size
            bpts = [QPointF(base)]
            bx, by = base.x(), base.y()
            steps = self._rng.randrange(2, 5)
            for i in range(1, steps + 1):
                bx += side * blen / steps + self._rng.uniform(-8, 8) * self._size
                by += blen * 0.35 / steps + self._rng.uniform(0, 9) * self._size
                bpts.append(QPointF(bx, by))
            bolts.append(bpts)
        self._bolts = bolts
        base_life = (self._duration * self._rng.uniform(0.55, 1.85)
                     if self._duration_random else self._duration)
        self._life = base_life
        self._bolt_life = max(0.10, base_life * 2.25)
        self._screen_life = max(0.18, base_life * 4.69)
        self._age = 0.0
        self._flash_peak = 0.45 + 0.55 * self._intensity
        self._screen_flash = self._flash_peak
        self._bolt_flash = self._flash_peak
        self._flash = self._flash_peak
        self._wait = self._next_wait()
        self._timer.setInterval(self._active_interval)

    @staticmethod
    def _fade_out(t: float, hold: float = 0.08) -> float:
        if t <= hold:
            return 1.0
        u = max(0.0, min(1.0, (t - hold) / max(0.001, 1.0 - hold)))
        smooth = u * u * (3.0 - 2.0 * u)
        return max(0.0, 1.0 - smooth)

    def _tick(self):
        now = time.monotonic()
        dt = min(0.06, max(0.006, now - self._last))
        self._last = now
        if self._flash > 0.001:
            self._age += dt
            screen_t = max(0.0, min(1.0, self._age / max(0.03, self._screen_life)))
            bolt_t = max(0.0, min(1.0, self._age / max(0.03, self._bolt_life)))
            screen_fade = max(0.0, 1.0 - screen_t) ** 1.45
            self._screen_flash = max(
                0.0, self._flash_peak * screen_fade)
            self._bolt_flash = max(
                0.0, self._flash_peak * self._fade_out(bolt_t, 0.10))
            self._flash = max(self._screen_flash, self._bolt_flash)
            if self._bolt_flash <= 0.001:
                self._bolts.clear()
            if self._flash <= 0.001:
                self._timer.setInterval(self._wait_interval)
            self.update()
            return
        self._wait -= dt
        if self._wait <= 0.0:
            self._strike()
            self.update()

    def showEvent(self, _):
        if bool(SETTINGS.get("lightning_enabled", False)):
            self._last = time.monotonic()
            if not self._timer.isActive():
                self._timer.start()

    def hideEvent(self, _):
        self._timer.stop()

    def _clip_path(self) -> QPainterPath:
        radius = Sf(SETTINGS.get("radius", 15))
        key = (self.width(), self.height(), round(radius * 100))
        if self._clip_path_cache is not None and self._clip_path_key == key:
            return self._clip_path_cache
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, self.width(), self.height()),
                            radius, radius)
        self._clip_path_cache = path
        self._clip_path_key = key
        return path

    def paintEvent(self, _):
        if self._screen_flash <= 0.001 and self._bolt_flash <= 0.001:
            return
        p = QPainter(self)
        aa(p)
        p.setClipPath(self._clip_path())
        bolt_flash = self._bolt_flash
        flash = bolt_flash * (0.45 + self._intensity * 0.75)
        # 全視窗白閃直接跟隨閃電生命週期，duration 拉長時會一起延長。
        screen_flash = max(0.0, min(1.0, self._screen_flash * (
            0.65 + self._intensity * 0.25)))
        flash_alpha = max(0, min(76, round(72 * screen_flash)))
        if flash_alpha > 0:
            p.fillRect(self.rect(), QColor(255, 255, 255, flash_alpha))

        pulse = min(1.0, flash)
        if pulse > 0.002 and self._bolts:
            main_pts = self._bolts[0]
            center = main_pts[min(len(main_pts) - 1,
                                  max(0, round((len(main_pts) - 1) * 0.42)))]
            radius = max(float(self.width()), float(self.height())) * (
                0.42 + 0.10 * self._size)
            bg = QRadialGradient(center.x(), center.y(), radius)
            bg.setColorAt(0.0, QColor(255, 255, 255, round(30 * pulse)))
            bg.setColorAt(0.42, QColor(224, 238, 255, round(14 * pulse)))
            bg.setColorAt(1.0, QColor(210, 226, 255, 0))
            p.fillRect(self.rect(), bg)
        for i, pts in enumerate(self._bolts):
            if len(pts) < 2:
                continue
            path = QPainterPath(pts[0])
            for point in pts[1:]:
                path.lineTo(point)
            main = i == 0
            width = (1.15 if main else 0.72) * self._size * self._thickness
            aura_alpha = max(0, min(110, round((42 if main else 22) * flash)))
            glow_alpha = max(0, min(255, round(132 * flash)))
            core_alpha = max(0, min(255, round(238 * flash)))
            p.setPen(QPen(QColor(255, 255, 255, aura_alpha),
                          width + 8.5 * self._thickness, Qt.SolidLine,
                          Qt.RoundCap, Qt.RoundJoin))
            p.drawPath(path)
            p.setPen(QPen(QColor(232, 242, 255, glow_alpha),
                          width + 2.2 * self._thickness, Qt.SolidLine, Qt.RoundCap,
                          Qt.RoundJoin))
            p.drawPath(path)
            p.setPen(QPen(QColor(255, 255, 255, core_alpha),
                          width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            p.drawPath(path)


class _ControlSlideOverlay(QWidget):
    """控制列對齊切換時的子像素繪製層。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self._pm: QPixmap | None = None
        self._pos = QPointF()
        self._size = QSizeF()
        self._items: list[dict] = []
        self._t = 1.0
        self._opacity = 1.0
        self.hide()

    def pixmap(self) -> QPixmap | None:
        return self._pm

    def position(self) -> QPointF:
        return QPointF(self._pos)

    def start(self, pm: QPixmap, pos: QPointF):
        self._pm = QPixmap(pm)
        self._items = []
        self._t = 1.0
        self._pos = QPointF(pos)
        dpr = max(1.0, self._pm.devicePixelRatioF())
        self._size = QSizeF(self._pm.width() / dpr, self._pm.height() / dpr)
        self.show()
        self.raise_()
        self.update()

    def start_items(self, items: list[dict], opacity: float = 1.0):
        self._pm = None
        self._items = items
        self._t = 0.0
        self._opacity = max(0.0, min(1.0, float(opacity)))
        self.show()
        self.raise_()
        self.update()

    def set_position(self, pos: QPointF):
        self._pos = QPointF(pos)
        self.update()

    def set_t(self, t: float):
        self._t = max(0.0, min(1.0, float(t)))
        self.update()

    def paintEvent(self, _):
        if self._items:
            p = QPainter(self)
            p.setRenderHint(QPainter.SmoothPixmapTransform, True)
            t = self._t
            for item in self._items:
                pm = item.get("pm")
                if pm is None or pm.isNull():
                    continue
                p0 = item["from"]
                p1 = item["to"]
                pos = QPointF(p0.x() + (p1.x() - p0.x()) * t,
                              p0.y() + (p1.y() - p0.y()) * t)
                op0 = float(item.get("op0", 1.0))
                op1 = float(item.get("op1", 1.0))
                op = self._opacity * (op0 + (op1 - op0) * t)
                if op <= 0.001:
                    continue
                dpr = max(1.0, pm.devicePixelRatioF())
                size = QSizeF(pm.width() / dpr, pm.height() / dpr)
                p.save()
                p.setOpacity(op)
                p.drawPixmap(QRectF(pos, size), pm, QRectF(pm.rect()))
                p.restore()
            return
        if self._pm is None or self._pm.isNull():
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        p.setOpacity(self._opacity)
        p.drawPixmap(QRectF(self._pos, self._size), self._pm,
                     QRectF(self._pm.rect()))


class Card(QWidget):
    """播放器卡片本體：背景漸層（快取）、所有子元件、空狀態。"""

    drag_finished = Signal()
    layout_edit_changed = Signal()
    accent_changed = Signal(QColor)   # 主題色過渡的每一幀（設定面板跟著變）
    wheel_volume = Signal(int)        # 卡片上滾滾輪調音量（原始 angleDelta）

    _PRESET_METRICS = {
        "mini": (340, 124, 76),
        "standard": (CARD_W, CARD_H, ART_SIZE),
        "wide": (500, CARD_H, ART_SIZE),
        "controls": (430, 104, 68),
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.setAutoFillBackground(False)
        self.setMouseTracking(True)
        preset = SETTINGS.get("card_preset", "standard")
        base_w, base_h, base_art = self._PRESET_METRICS.get(
            preset, self._PRESET_METRICS["standard"])
        self._preset = preset
        self._base_w = base_w
        self._base_h = base_h
        self._compact = preset in ("mini", "controls")
        self._control_bar = preset == "controls"
        self._cover_enabled = (preset != "mini"
                               and bool(SETTINGS.get("show_cover", True)))
        self._art_size = S(base_art)
        self._W, self._H = self._window_size_px()
        self.setFixedSize(self._W, self._H)
        self._dom: QColor | None = None      # 封面萃取的主色
        self._cover_grad: tuple[QColor, QColor] | None = None
        self._accent = theme_color() or QColor(SPOTIFY_GREEN)
        self._art_pm: QPixmap | None = None
        self._art_img: QImage | None = None
        self._drag_off: QPoint | None = None
        self._edit_mode = False
        self._edit_drag: dict | None = None
        self._edit_filter_targets: dict[QWidget, str] = {}
        self._edit_hover_key: str | None = None
        self._edit_selected_keys: set[str] = set()
        self._edit_select_ops: dict[str, float] = {}
        self._edit_select_targets: dict[str, float] = {}
        self._edit_select_anims: dict[str, Anim] = {}
        self._edit_instance_widgets: dict[str, QWidget] = {}
        self._audio_level_provider = None
        self._art_playing = False
        self._window_resize_drag: dict | None = None
        self._edit_reset_from: dict[str, tuple[float, float]] = {}
        self._edit_reset_size_from: dict[str, tuple[float, float]] = {}
        self._edit_reset_angle_from: dict[str, float] = {}
        self._edit_reset_window_from: tuple[float, float] = (0.0, 0.0)
        self._edit_reset_hidden_keys: tuple[str, ...] = ()
        self._edit_reset_abort = False
        self._edit_reset_anim = Anim(self)
        self._edit_reset_anim.valueChanged.connect(self._on_layout_reset)
        self._edit_reset_anim.finished.connect(self._layout_reset_done)
        self._edit_overlay_op = 0.0
        self._edit_overlay_target = 0.0
        self._edit_overlay_anim = Anim(self)
        self._edit_overlay_anim.valueChanged.connect(self._on_edit_overlay_op)
        self._edit_overlay_anim.finished.connect(self._edit_overlay_done)
        self._edit_handle_ops: dict[str, float] = {}
        self._edit_handle_targets: dict[str, float] = {}
        self._edit_handle_anims: dict[str, Anim] = {}
        self._ctrl_layout_min = QPointF(0.0, 0.0)
        self._ctrl_nominal_size = (0, 0)
        self._bg: QPixmap | None = None      # 背景快取（漸層很貴，只畫一次）
        self._bg_image_layer: QPixmap | None = None
        self._bg_image_layer_key = None
        self._bg_overlay: QPixmap | None = None
        self._bg_overlay_key = None
        self._bg_clip_path_cache: QPainterPath | None = None
        self._bg_clip_path_key = None
        self._bg_image_path = ""
        self._bg_image: QImage | None = None
        self._bg_theme_key = None
        self._bg_dom: QColor | None = None
        self._bg_grad: tuple[QColor, QColor] | None = None
        self._accent = self.target_accent()
        self._bg_parallax = QPointF(0.0, 0.0)
        self._bg_parallax_from = QPointF(0.0, 0.0)
        self._bg_parallax_to = QPointF(0.0, 0.0)
        self._bg_parallax_anim = Anim(self)
        self._bg_parallax_anim.valueChanged.connect(self._on_bg_parallax)
        self._bg_parallax_factor = 0.0
        self._bg_parallax_factor_from = 0.0
        self._bg_parallax_factor_to = 0.0
        self._bg_parallax_factor_anim = Anim(self)
        self._bg_parallax_factor_anim.valueChanged.connect(
            self._on_bg_parallax_factor)
        self._bg_parallax_strength = float(SETTINGS.get(
            "background_image_parallax_strength", 1.0))
        self._bg_parallax_strength_to = self._bg_parallax_strength
        self._bg_parallax_strength_anim = Anim(self)
        self._bg_parallax_strength_anim.valueChanged.connect(
            self._on_bg_parallax_strength)
        self._bg_parallax_timer = QTimer(self)
        self._bg_parallax_timer.setTimerType(Qt.CoarseTimer)
        self._bg_parallax_timer.timeout.connect(
            self._update_bg_parallax_from_cursor)
        self._bg_parallax_drag_suspended = False
        self._empty_state = True
        self._src_spotify = True
        self._src_label = "SPOTIFY"
        self._fade: _CardFade | None = None   # 空狀態 ↔ 內容過渡層
        self._source_op = 1.0 if SETTINGS.get("show_source", True) else 0.0
        self._source_target = self._source_op
        self._source_anim = Anim(self)
        self._source_anim.valueChanged.connect(self._on_source_op)
        self._source_anim.finished.connect(self._source_done)
        self._edit_button_op = (
            1.0 if SETTINGS.get("show_edit_button", True) else 0.0)
        self._edit_button_target = self._edit_button_op
        self._edit_button_anim = Anim(self)
        self._edit_button_anim.valueChanged.connect(self._on_edit_button_op)
        self._edit_button_anim.finished.connect(self._edit_button_done)
        self._reset_button_op = 0.0
        self._reset_button_target = 0.0
        self._reset_button_anim = Anim(self)
        self._reset_button_anim.valueChanged.connect(self._on_reset_button_op)
        self._reset_button_anim.finished.connect(self._reset_button_done)
        self._ctrl_anim = Anim(self)
        self._ctrl_anim.valueChanged.connect(self._on_ctrl_move)
        self._ctrl_anim.finished.connect(self._ctrl_done)
        self._ctrl_from = QPointF()
        self._ctrl_to = QPointF()
        self._ctrl_pos = QPointF()
        self._ctrl_suppress_done = False
        self._ctrl_items: dict[QWidget, tuple[QPointF, QPointF]] = {}
        self._ctrl_final_size = (0, 0)
        self._ctrl_overlay: _ControlSlideOverlay | None = None
        self._ctrl_fade_in: set[QWidget] = set()
        self._controls_hover = False
        self._controls_op = 1.0 if not SETTINGS.get("controls_hover", False) else 0.0
        self._controls_oa = Anim(self)
        self._controls_oa.valueChanged.connect(self._on_controls_op)
        self._topbar_hover = False
        self._topbar_op = 1.0 if not SETTINGS.get("topbar_hover", False) else 0.0
        self._topbar_oa = Anim(self)
        self._topbar_oa.valueChanged.connect(self._on_topbar_op)
        self._info_focus = 0.0
        self._info_anim = Anim(self)
        self._info_anim.valueChanged.connect(self._on_info_focus)
        self._layout_anim = Anim(self)
        self._layout_anim.valueChanged.connect(self._on_cover_layout)
        self._layout_anim.finished.connect(self._cover_layout_done)
        self._layout_from: dict | None = None
        self._layout_to: dict | None = None
        self._art_size_anim = Anim(self)
        self._art_size_anim.valueChanged.connect(self._on_art_size_layout)
        self._art_size_anim.finished.connect(self._art_size_layout_done)
        self._art_size_refresh_pixmap = True
        self._art_scale_from = (self._cover_scale_setting(),
                                self._vinyl_scale_setting())
        self._art_scale_to = self._art_scale_from
        self._info_focus_timer = QTimer(self)
        self._info_focus_timer.setSingleShot(True)
        self._info_focus_timer.setInterval(1100)
        self._info_focus_timer.timeout.connect(self._start_info_focus)

        # 主題色淡化過渡：accent 與背景漸層兩端色一起逐幀內插，
        # 漸層主題之間切換（accent 中點色可能相同）背景才有過渡動畫
        self._bg1, self._bg2 = self._bg_target(self._accent)
        self._acc_from = QColor(self._accent)
        self._acc_to = QColor(self._accent)
        self._bg1_from, self._bg1_to = QColor(self._bg1), QColor(self._bg1)
        self._bg2_from, self._bg2_to = QColor(self._bg2), QColor(self._bg2)
        self._glass = 1.0 if glass_theme() else 0.0
        self._glass_from = self._glass
        self._glass_to = self._glass
        self._acc_anim = Anim(self)
        self._acc_anim.valueChanged.connect(self._on_acc_anim)
        self._custom_color_anim = Anim(self)
        self._custom_color_anim.valueChanged.connect(self._on_custom_color_anim)
        self._custom_color_anim.finished.connect(self._custom_color_done)
        self._custom_color_abort = False
        self._custom_color_from: dict[str, QColor] = {}
        self._custom_color_to: dict[str, QColor] = {}
        self._custom_colors: dict[str, QColor] = {}
        self._seek_fill_gradient: tuple[QColor, QColor] | None = None
        self._topbar_override = False
        self._topbar_override_to = False
        self._progress_pos = 0.0
        self._progress_dur = 0.0
        self._bg_fade_old: QPixmap | None = None
        self._bg_fade_new: QPixmap | None = None
        self._bg_fade_t = 1.0
        self._bg_fade_abort = False
        self._bg_fade_anim = Anim(self)
        self._bg_fade_anim.valueChanged.connect(self._on_bg_fade)
        self._bg_fade_anim.finished.connect(self._bg_fade_done)
        self._build()
        self._bg_parallax_timer.setInterval(self._bg_parallax_interval())
        self._bg_parallax_factor = (
            1.0 if self._bg_parallax_config_enabled() else 0.0)
        self._bg_parallax_factor_to = self._bg_parallax_factor
        self._bg_parallax_strength = min(2.0, max(0.0, float(
            SETTINGS.get("background_image_parallax_strength", 1.0))))
        self._bg_parallax_strength_to = self._bg_parallax_strength
        # 子元件建立時 accent 都是預設綠；初始主題色直接灌一次，
        # 否則 refresh_accent 看到目標色相同會早退，固定/漸層主題
        # 重啟後控制元件會停在預設綠
        self._apply_colors(self._accent, self._bg1, self._bg2)
        self.apply_custom_colors()
        self.set_empty(True)

    def accent(self) -> QColor:
        return QColor(self._accent)

    def target_accent(self) -> QColor:
        explicit = theme_color()
        if explicit is not None:
            return explicit
        if self._use_background_for_auto_theme():
            bg_dom, _ = self._background_theme_source()
            if bg_dom is not None:
                return bg_dom
        return self._dom or QColor(SPOTIFY_GREEN)

    def _use_background_for_auto_theme(self) -> bool:
        return (SETTINGS.get("theme") == "auto"
                and not bool(SETTINGS.get("background_image_auto_theme", True))
                and self._custom_bg_image() is not None)

    def _background_theme_source(
            self) -> tuple[QColor | None, tuple[QColor, QColor] | None]:
        img = self._custom_bg_image()
        if img is None:
            return None, None
        key = (self._bg_image_path, img.cacheKey())
        if self._bg_theme_key != key:
            self._bg_theme_key = key
            self._bg_dom = dominant_color(img)
            self._bg_grad = cover_gradient(img)
        dom = QColor(self._bg_dom) if self._bg_dom is not None else None
        grad = None
        if self._bg_grad is not None:
            grad = (QColor(self._bg_grad[0]), QColor(self._bg_grad[1]))
        return dom, grad

    def _cover_scale_setting(self) -> float:
        delta = self._art_edit_delta_scale()
        return max(0.6, min(
            1.4, float(SETTINGS.get("art_cover_size", 1.0)) + delta))

    def _vinyl_scale_setting(self) -> float:
        delta = self._art_edit_delta_scale()
        return max(0.7, min(
            1.35, float(SETTINGS.get("art_vinyl_size", 1.0)) + delta))

    def _cover_visual_size(self) -> int:
        return max(1, round(self._art_size * self._cover_scale_setting()))

    def _art_info_span(self) -> int:
        if hasattr(self, "art"):
            return self.art.layout_span()
        cover = self._cover_visual_size()
        layout = max(cover, round(self._art_size * self._vinyl_scale_setting()))
        return layout

    def _seek_bar_geometry(self, seek_y: int) -> tuple[int, int, int, int]:
        base_w = self._W - S(104)
        length = max(0.2, min(1.3, float(SETTINGS.get("seek_length", 1.0))))
        max_w = self._W - S(16)
        w = max(S(46), min(max_w, round(base_w * length)))
        x = round((self._W - w) / 2)
        return x, seek_y, w, S(18)

    def _seek_bar_top_padding(self) -> int:
        return 0

    def _source_scale(self) -> float:
        return max(0.65, min(1.8, 1.0 + self._edit_scale_delta(
            "source", 70.0)))

    def _source_font(self) -> QFont:
        f = ui_font(max(1, S(9 * self._source_scale())), QFont.DemiBold)
        f.setLetterSpacing(QFont.AbsoluteSpacing, Sf(1.6))
        return f

    def _apply_source_font(self):
        if not hasattr(self, "source"):
            return
        f = self._source_font()
        cur = self.source.font()
        if cur.pixelSize() != f.pixelSize():
            self.source.setFont(f)

    def _progress_time_scale(self, key: str) -> float:
        return max(0.65, min(1.8, 1.0 + self._edit_scale_delta(key, 58.0)))

    def _progress_time_font(self, key: str = "time_now") -> QFont:
        f = ui_font(max(1, S(10 * self._progress_time_scale(key))))
        spacing = Sf(float(SETTINGS.get("progress_time_spacing", 0.0)))
        f.setLetterSpacing(QFont.AbsoluteSpacing, spacing)
        return f

    def _progress_time_width(self, key: str = "time_now") -> int:
        scale = self._progress_time_scale(key)
        spacing = max(0.0, float(SETTINGS.get("progress_time_spacing", 0.0)))
        return max(S(24), S((42 + spacing * 5.0) * scale))

    def _layout_positions(self) -> dict:
        positions = SETTINGS.get("edit_layout_positions", {})
        if not isinstance(positions, dict):
            positions = {}
            SETTINGS["edit_layout_positions"] = positions
        return positions

    def _layout_sizes(self) -> dict:
        sizes = SETTINGS.get("edit_layout_sizes", {})
        if not isinstance(sizes, dict):
            sizes = {}
            SETTINGS["edit_layout_sizes"] = sizes
        return sizes

    def _layout_angles(self) -> dict:
        angles = SETTINGS.get("edit_layout_angles", {})
        if not isinstance(angles, dict):
            angles = {}
            SETTINGS["edit_layout_angles"] = angles
        return angles

    def _normalize_edit_angle(self, angle: float) -> float:
        return ((float(angle) + 180.0) % 360.0) - 180.0

    def _window_size_logic(self) -> tuple[float, float]:
        raw = SETTINGS.get("edit_window_size", {})
        if not isinstance(raw, dict):
            return 0.0, 0.0
        try:
            return float(raw.get("w", 0.0)), float(raw.get("h", 0.0))
        except (TypeError, ValueError):
            return 0.0, 0.0

    def _set_window_size_logic(self, w: float, h: float):
        w = min(500.0, max(-300.0, float(w)))
        h = min(400.0, max(-120.0, float(h)))
        if abs(w) < 0.01 and abs(h) < 0.01:
            SETTINGS["edit_window_size"] = {}
        else:
            SETTINGS["edit_window_size"] = {"w": w, "h": h}

    def _window_size_px(self) -> tuple[int, int]:
        w, h = self._window_size_logic()
        return (
            max(S(220), round(S(self._base_w) + Sf(w))),
            max(S(84), round(S(self._base_h) + Sf(h))),
        )

    def _edit_offset_logic(self, key: str) -> tuple[float, float]:
        raw = self._layout_positions().get(key, {})
        if not isinstance(raw, dict):
            return 0.0, 0.0
        try:
            return float(raw.get("x", 0.0)), float(raw.get("y", 0.0))
        except (TypeError, ValueError):
            return 0.0, 0.0

    def _edit_offset_px(self, key: str) -> QPointF:
        x, y = self._edit_offset_logic(key)
        return QPointF(Sf(x), Sf(y))

    def _set_edit_offset_logic(self, key: str, x: float, y: float):
        x = min(300.0, max(-300.0, float(x)))
        y = min(300.0, max(-300.0, float(y)))
        positions = self._layout_positions()
        if abs(x) < 0.01 and abs(y) < 0.01:
            positions.pop(key, None)
        else:
            positions[key] = {"x": x, "y": y}

    def _edit_size_logic(self, key: str) -> tuple[float, float]:
        raw = self._layout_sizes().get(key, {})
        if not isinstance(raw, dict):
            return 0.0, 0.0
        try:
            return float(raw.get("w", 0.0)), float(raw.get("h", 0.0))
        except (TypeError, ValueError):
            return 0.0, 0.0

    def _edit_size_px(self, key: str) -> QPointF:
        if key not in self._resizable_edit_keys():
            return QPointF(0.0, 0.0)
        w, h = self._edit_size_logic(key)
        return QPointF(Sf(w), Sf(h))

    def _set_edit_size_logic(self, key: str, w: float, h: float):
        w = min(300.0, max(-300.0, float(w)))
        h = min(300.0, max(-300.0, float(h)))
        sizes = self._layout_sizes()
        if abs(w) < 0.01 and abs(h) < 0.01:
            sizes.pop(key, None)
        else:
            sizes[key] = {"w": w, "h": h}

    def _edit_angle_logic(self, key: str) -> float:
        try:
            return self._normalize_edit_angle(
                float(self._layout_angles().get(key, 0.0)))
        except (TypeError, ValueError):
            return 0.0

    def _set_edit_angle_logic(self, key: str, angle: float):
        angle = self._normalize_edit_angle(angle)
        angles = self._layout_angles()
        if abs(angle) < 0.01:
            angles.pop(key, None)
        else:
            angles[key] = angle

    def _effective_edit_angle(self, key: str) -> float:
        angle = self._edit_angle_logic(key)
        if key.startswith("ctrl_"):
            angle += self._edit_angle_logic("controls")
        return self._normalize_edit_angle(angle)

    def edit_target_angle(self, key: str) -> float:
        return self._effective_edit_angle(key)

    def _set_widget_edit_angle(self, widget: QWidget | None, angle: float):
        if widget is None:
            return
        setter = getattr(widget, "set_edit_angle", None)
        if callable(setter):
            setter(angle)

    def _apply_edit_angle(self, key: str):
        if key == "controls":
            for ctrl_key in ("ctrl_shuffle", "ctrl_prev", "ctrl_play",
                             "ctrl_next", "ctrl_repeat"):
                self._apply_edit_angle(ctrl_key)
            return
        angle = self._effective_edit_angle(key)
        for widget in self._edit_target_widgets(key):
            self._set_widget_edit_angle(widget, angle)

    def _apply_edit_angles(self):
        for key in self.edit_target_keys():
            self._apply_edit_angle(key)

    def _art_edit_delta_scale(self) -> float:
        if "art" not in self._resizable_edit_keys():
            return 0.0
        w, h = self._edit_size_logic("art")
        return max(w, h) / max(1.0, float(self._PRESET_METRICS.get(
            self._preset, self._PRESET_METRICS["standard"])[2]))

    def _edit_scale_delta(self, key: str, base: float) -> float:
        w, h = self._edit_size_logic(key)
        if abs(w) >= abs(h):
            delta = w
        else:
            delta = h
        return delta / max(1.0, float(base))

    def _resizable_edit_keys(self) -> tuple[str, ...]:
        keys = [
            "source_logo", "source", "title", "artist", "controls",
            "ctrl_shuffle", "ctrl_prev", "ctrl_play", "ctrl_next",
            "ctrl_repeat",
            "top_edit", "top_reset", "top_volume", "top_settings",
            "top_pin", "top_close",
            "seek", "time_now", "time_total",
        ]
        if (self._cover_enabled and hasattr(self, "art")
                and not self.art.isHidden()):
            keys.insert(0, "art")
        return tuple(keys) + tuple(self._edit_instance_widgets)

    def _min_edit_size(self, key: str) -> tuple[float, float]:
        if key == "seek":
            return S(28), S(8)
        if key in ("title", "artist", "source", "time_now", "time_total"):
            return S(18), S(8)
        if key == "source_logo":
            return S(8), S(8)
        if key == "controls":
            return S(28), S(18)
        if key.startswith("ctrl_"):
            return S(12), S(12)
        if key.startswith("top_"):
            return S(10), S(10)
        if self._is_edit_instance_key(key):
            return S(12), S(12)
        if key.startswith("empty"):
            return S(16), S(10)
        return S(14), S(14)

    def _offset_rect(self, key: str, rect: QRectF) -> QRectF:
        r = QRectF(rect)
        off = self._edit_offset_px(key)
        size = self._edit_size_px(key)
        r.translate(off.x(), off.y())
        min_w, min_h = self._min_edit_size(key)
        r.setWidth(max(min_w, r.width() + size.x()))
        r.setHeight(max(min_h, r.height() + size.y()))
        return r

    def _offset_point(self, key: str, point: QPointF) -> QPointF:
        off = self._edit_offset_px(key)
        return QPointF(point.x() + off.x(), point.y() + off.y())

    def _unoffset_rect(self, key: str, rect: QRectF) -> QRectF:
        r = QRectF(rect)
        off = self._edit_offset_px(key)
        size = self._edit_size_px(key)
        r.translate(-off.x(), -off.y())
        r.setWidth(max(1.0, r.width() - size.x()))
        r.setHeight(max(1.0, r.height() - size.y()))
        return r

    def _unoffset_point(self, key: str, point: QPointF) -> QPointF:
        off = self._edit_offset_px(key)
        return QPointF(point.x() - off.x(), point.y() - off.y())

    def _offset_geometry(self, key: str, geo: tuple[int, int, int, int]):
        off = self._edit_offset_px(key)
        size = self._edit_size_px(key)
        min_w, min_h = self._min_edit_size(key)
        return (round(geo[0] + off.x()), round(geo[1] + off.y()),
                round(max(min_w, geo[2] + size.x())),
                round(max(min_h, geo[3] + size.y())))

    def _progress_time_geometries(self, seek_y: int):
        now_w = self._progress_time_width("time_now")
        total_w = self._progress_time_width("time_total")
        now_h = max(S(14), S(14 * self._progress_time_scale("time_now")))
        total_h = max(S(14), S(14 * self._progress_time_scale("time_total")))
        return (
            (S(12), seek_y + S(2), now_w, now_h),
            (self._W - S(12) - total_w, seek_y + S(2), total_w, total_h),
        )

    def apply_progress_time_spacing(self):
        if hasattr(self, "t_now") and hasattr(self, "t_total"):
            seek_y = S(self._base_h - (25 if self._compact else 30))
            now_geo, total_geo = self._progress_time_geometries(seek_y)
            self.t_now.setFont(self._progress_time_font("time_now"))
            self.t_total.setFont(self._progress_time_font("time_total"))
            self.t_now.setGeometry(*self._offset_geometry("time_now", now_geo))
            self.t_total.setGeometry(
                *self._offset_geometry("time_total", total_geo))
            self.t_now.update()
            self.t_total.update()
            self._update_edit_overlay()

    def _text_layout_rects(self, info_x: int, title_y: int,
                           artist_y: int, info_w: int):
        title_scale = max(0.6, min(
            1.8, float(SETTINGS.get("title_size", 1.0))
            + self._edit_scale_delta("title", 90.0)))
        artist_scale = max(0.6, min(
            1.8, float(SETTINGS.get("artist_size", 1.0))
            + self._edit_scale_delta("artist", 80.0)))
        self._title_px_base = max(1, S(15 * title_scale))
        self._artist_px_base = max(1, S(11 * artist_scale))
        self._title_scale_focus = 1.22
        self._artist_scale_focus = 1.17

        title_h = max(S(14), round(self._title_px_base * 1.42))
        artist_h = max(S(12), round(self._artist_px_base * 1.46))
        title_w = max(S(60), info_w)
        artist_w = max(S(60), info_w)

        title_base = QRectF(info_x, title_y, title_w, title_h)
        artist_base = QRectF(info_x, artist_y, artist_w, artist_h)
        focus_title_h = max(title_h, round(title_h * 1.28))
        focus_artist_h = max(artist_h, round(artist_h * 1.25))
        pair_h = focus_title_h + S(4) + focus_artist_h
        focus_top = round(self._H * 0.50 - pair_h / 2)

        title_focus = QRectF(title_base)
        artist_focus = QRectF(artist_base)
        title_focus.setHeight(focus_title_h)
        artist_focus.setHeight(focus_artist_h)
        title_focus.moveTop(focus_top)
        artist_focus.moveTop(focus_top + focus_title_h + S(4))
        title_canvas = QRectF(title_base).united(title_focus).adjusted(
            0, -S(4), 0, S(4))
        artist_canvas = QRectF(artist_base).united(artist_focus).adjusted(
            0, -S(4), 0, S(4))
        return (title_base, artist_base, title_focus, artist_focus,
                title_canvas, artist_canvas)

    def _control_button_scale(self) -> float:
        return max(0.7, min(
            1.6, float(SETTINGS.get("control_button_size", 1.0))
            + self._edit_scale_delta("controls", 100.0)))

    def _button_edit_scale(self, key: str, base: float = 42.0) -> float:
        return max(0.55, min(2.0, 1.0 + self._edit_scale_delta(key, base)))

    def _control_button_gap(self) -> int:
        spacing = max(0.4, min(
            2.2, float(SETTINGS.get("control_button_spacing", 1.0))))
        return max(0, S(14 * spacing))

    def _control_metric(self, glyph_px: float, diameter: float) -> tuple[int, int]:
        scale = self._control_button_scale()
        return max(1, S(glyph_px * scale)), max(1, S(diameter * scale))

    def apply_seek_length(self):
        if hasattr(self, "seek"):
            seek_y = S(self._base_h - (25 if self._compact else 30))
            self.seek.set_top_padding(self._seek_bar_top_padding())
            self.seek.setGeometry(
                *self._offset_geometry("seek", self._seek_bar_geometry(seek_y)))
            if hasattr(self, "seek_hover"):
                self.seek_hover.setGeometry(0, 0, self._W, self._H)
                self.seek_hover.raise_()
            self.seek.update()
            self._update_edit_overlay()

    def _set_progress_time_label(self, label: TimeLabel, source: str,
                                 pos: float, dur: float,
                                 animate_now: bool = False,
                                 animate_mode: bool = False):
        number_anim = bool(SETTINGS.get("progress_time_anim_enabled", True))
        text_style = str(SETTINGS.get("progress_time_anim_style", "fade"))
        if text_style not in TimeLabel.TEXT_STYLES:
            text_style = "fade"
        now_transition = animate_mode or number_anim
        now_style = text_style if number_anim else "slide"
        if source == "time_now":
            if SETTINGS.get("progress_time_mode") == "remaining" and dur > 0:
                label.set_seconds(max(0.0, dur - pos),
                                  animate=animate_now, prefix="-",
                                  text_transition=now_transition,
                                  transition_style=now_style)
            else:
                label.set_seconds(pos, animate=animate_now,
                                  text_transition=now_transition,
                                  transition_style=now_style)
        elif source == "time_total":
            label.set_seconds(dur, text_transition=number_anim,
                              transition_style=text_style)

    def _sync_progress_time_instances(self, animate_now: bool = False,
                                      animate_mode: bool = False):
        for key, widget in tuple(self._edit_instance_widgets.items()):
            if not isinstance(widget, TimeLabel):
                continue
            source = self._edit_instance_source(key)
            self._set_progress_time_label(
                widget, source, self._progress_pos, self._progress_dur,
                animate_now=animate_now, animate_mode=animate_mode)

    def set_progress_times(self, pos: float, dur: float,
                           animate_now: bool = False,
                           animate_mode: bool = False):
        pos = max(0.0, float(pos))
        dur = max(0.0, float(dur))
        self._progress_pos = pos
        self._progress_dur = dur
        self._set_progress_time_label(
            self.t_now, "time_now", pos, dur,
            animate_now=animate_now, animate_mode=animate_mode)
        self._set_progress_time_label(
            self.t_total, "time_total", pos, dur,
            animate_now=False, animate_mode=animate_mode)
        self._sync_progress_time_instances(
            animate_now=animate_now, animate_mode=animate_mode)

    def _build(self):
        W = self._W

        self.rain = _WeatherLayer(self)
        self.rain.setGeometry(0, 0, self._W, self._H)
        self.lightning = _LightningLayer(self)
        self.lightning.setGeometry(0, 0, self._W, self._H)

        # 封面
        art_x = S(12 if self._compact else 16)
        art_y = S(12 if self._compact else 16)
        self.art = ArtView(self._art_size, self._cover_radius(), self)
        self.art.move(art_x - self.art.pad, art_y - self.art.pad)
        self.art.setCursor(Qt.PointingHandCursor)
        self._art_eff = QGraphicsOpacityEffect(self.art)
        self._art_eff.setOpacity(1.0 if self._cover_enabled else 0.0)
        self.art.setGraphicsEffect(self._art_eff)
        self.art.setVisible(self._cover_enabled)
        self.art.set_border(SETTINGS.get("cover_border", False),
                            SETTINGS.get("cover_border_width", 2.0),
                            SETTINGS.get("cover_border_opacity", 0.85),
                            animate=False)
        self.art.set_mode(SETTINGS.get("art_mode", "cover"), animate=False)

        if self._cover_enabled:
            info_x = art_x + self._art_info_span() + S(10 if self._compact else 14)
        else:
            info_x = S(14 if self._compact else 18)
        right_pad = S(126 if self._control_bar else 16)
        info_w = W - info_x - right_pad
        if info_w < S(150):
            info_w = max(S(120), W - info_x - S(16))
        source_y = S(10 if self._compact else 14)
        title_y = S(26 if self._compact else 34)
        artist_y = S(46 if self._compact else 56)
        self._controls_y = Sf(78 if self._compact else 94)
        seek_y = S(self._base_h - (25 if self._compact else 30))

        # 來源標示
        logo_d = S(15)
        logo_gap = S(4)
        self.source = _RotatingLabel("SPOTIFY", self)
        self.source.setFont(self._source_font())
        self.source.setStyleSheet("color: rgba(255,255,255,110);")
        self.source.setGeometry(info_x + logo_d + logo_gap,
                                source_y,
                                S(120), S(14))
        self.source_logo = _SourceLogo(self._src_spotify, self)
        self.source_logo.setGeometry(info_x,
                                     source_y,
                                     logo_d, logo_d)
        self._source_eff = QGraphicsOpacityEffect(self.source)
        self._source_eff.setOpacity(self._source_op)
        self.source.setGraphicsEffect(self._source_eff)
        self._source_logo_eff = QGraphicsOpacityEffect(self.source_logo)
        self._source_logo_eff.setOpacity(self._source_op)
        self.source_logo.setGraphicsEffect(self._source_logo_eff)

        # 右上角：編輯、重設、音量、設定、釘選、隱藏
        self.btn_edit = IconButton(GLYPH_EDIT, S(10), S(22),
                                   checkable=True, fx="wiggle", parent=self)
        self.btn_edit.move(W - S(128), S(10))
        self.btn_edit.set_extra_opacity(self._edit_button_op)
        self.btn_edit.setVisible(self._edit_button_op > 0.001)
        self.btn_edit.setAttribute(
            Qt.WA_TransparentForMouseEvents,
            self._edit_button_op <= 0.02)
        self.btn_reset_layout = IconButton(GLYPH_RESET, S(10), S(22),
                                           fx="spin", parent=self)
        self.btn_reset_layout.move(W - S(152), S(10))
        self.btn_reset_layout.set_extra_opacity(self._reset_button_op)
        self.btn_reset_layout.setAttribute(
            Qt.WA_TransparentForMouseEvents,
            self._reset_button_op <= 0.02)
        self.btn_reset_layout.hide()
        self.btn_vol = IconButton(GLYPH_VOLUME, S(11), S(22),
                                  press_scale=0.78, release_ms=260,
                                  release_overshoot=1.7,
                                  hover_ms_factor=2.0,
                                  parent=self)
        self.btn_vol.move(W - S(104), S(10))
        self.btn_settings = IconButton(GLYPH_SETTINGS, S(11), S(22),
                                       fx="gear", parent=self)
        self.btn_settings.move(W - S(80), S(10))
        self.btn_pin = IconButton(GLYPH_PIN, S(11), S(22), checkable=True,
                                  fx="wiggle", parent=self)
        self.btn_pin.move(W - S(56), S(10))
        self.btn_close = IconButton(GLYPH_CLOSE, S(10), S(22), fx="spin",
                                    parent=self)
        self.btn_close.move(W - S(32), S(10))
        self._topbar_buttons = (self.btn_edit, self.btn_reset_layout,
                                self.btn_vol, self.btn_settings,
                                self.btn_pin, self.btn_close)
        self._topbar_edit_specs = {
            "top_edit": (self.btn_edit, 10, 22),
            "top_reset": (self.btn_reset_layout, 10, 22),
            "top_volume": (self.btn_vol, 11, 22),
            "top_settings": (self.btn_settings, 11, 22),
            "top_pin": (self.btn_pin, 11, 22),
            "top_close": (self.btn_close, 10, 22),
        }
        self._topbar_edit_base_geometries = {
            key: QRectF(btn.geometry())
            for key, (btn, _, _) in self._topbar_edit_specs.items()
        }
        self._topbar_effects = []
        for b in self._topbar_buttons:
            eff = QGraphicsOpacityEffect(b)
            eff.setOpacity(self._topbar_op)
            b.setGraphicsEffect(eff)
            self._topbar_effects.append(eff)

        # 曲名與演出者
        (self._title_base, self._artist_base,
         self._title_focus, self._artist_focus,
         self._title_canvas, self._artist_canvas) = self._text_layout_rects(
             info_x, title_y, artist_y, info_w)
        self.title = MarqueeLabel(self._title_px_base,
                                  QColor(255, 255, 255, 242),
                                  QFont.DemiBold, self)
        self.artist = MarqueeLabel(self._artist_px_base, TEXT_DIM, parent=self)
        self.title.setGeometry(round(self._title_canvas.x()),
                               round(self._title_canvas.y()),
                               round(self._title_canvas.width()),
                               round(self._title_canvas.height()))
        self.artist.setGeometry(round(self._artist_canvas.x()),
                                round(self._artist_canvas.y()),
                                round(self._artist_canvas.width()),
                                round(self._artist_canvas.height()))
        self._on_info_focus(0.0)

        # 控制列
        self.controls = QWidget(self)
        self.controls.setAttribute(Qt.WA_TranslucentBackground)
        self._controls_eff = QGraphicsOpacityEffect(self.controls)
        self._controls_eff.setOpacity(self._controls_op)
        self.controls.setGraphicsEffect(self._controls_eff)
        small_px, small_d = self._control_metric(12, 24)
        nav_px, nav_d = self._control_metric(14, 28)
        play_d = max(1, S(36 * self._control_button_scale()))
        self.btn_shuffle = IconButton(GLYPH_SHUFFLE, small_px, small_d,
                                      checkable=True, dot=True,
                                      press_scale=0.70, release_ms=285,
                                      release_overshoot=2.05,
                                      hover_ms_factor=2.0,
                                      parent=self.controls)
        self.btn_prev = IconButton(GLYPH_PREV, nav_px, nav_d,
                                   press_scale=0.78, release_ms=260,
                                   release_overshoot=1.7,
                                   hover_ms_factor=2.0,
                                   parent=self.controls)
        self.btn_play = PlayButton(play_d, self.controls)
        self.btn_next = IconButton(GLYPH_NEXT, nav_px, nav_d,
                                   press_scale=0.78, release_ms=260,
                                   release_overshoot=1.7,
                                   hover_ms_factor=2.0,
                                   parent=self.controls)
        self.btn_repeat = IconButton(GLYPH_REPEAT_ALL, small_px, small_d,
                                     checkable=True, dot=True,
                                     press_scale=0.70, release_ms=285,
                                     release_overshoot=2.05,
                                     hover_ms_factor=2.0,
                                     parent=self.controls)

        ctrls = [self.btn_shuffle, self.btn_prev, self.btn_play,
                 self.btn_next, self.btn_repeat]
        self._ctrls = ctrls
        self._control_edit_specs = {
            "ctrl_shuffle": (self.btn_shuffle, 12, 24, False),
            "ctrl_prev": (self.btn_prev, 14, 28, False),
            "ctrl_play": (self.btn_play, 0, 36, True),
            "ctrl_next": (self.btn_next, 14, 28, False),
            "ctrl_repeat": (self.btn_repeat, 12, 24, False),
        }
        self._control_edit_keys_by_button = {
            btn: key for key, (btn, _, _, _) in self._control_edit_specs.items()
        }
        self._button_keys = {
            self.btn_shuffle: "show_btn_shuffle",
            self.btn_prev: "show_btn_prev",
            self.btn_next: "show_btn_next",
            self.btn_repeat: "show_btn_repeat",
        }
        self._button_ops = {}
        self._button_anims = {}
        self._button_targets = {}
        for b in self._button_keys:
            anim = Anim(self)
            anim.valueChanged.connect(
                lambda v, btn=b: self._on_button_op(btn, v))
            anim.finished.connect(
                lambda btn=b: self._button_anim_done(btn))
            self._button_ops[b] = 1.0
            self._button_anims[b] = anim
            self._button_targets[b] = True
        self._ctrl_span = (info_x, info_w)
        self._ctrl_overlay = _ControlSlideOverlay(self)
        self._ctrl_overlay.setGeometry(0, 0, self._W, self._H)
        self.apply_button_visibility()
        self.relayout_controls()
        self._sync_controls_hover(animate=False)
        self._sync_topbar_hover(animate=False)

        # 進度列（整張卡片底部）
        self.t_now = TimeLabel("0:00", self)
        self.t_now.setFont(self._progress_time_font("time_now"))
        self.t_now.setStyleSheet("color: rgba(255,255,255,120);")
        now_geo, total_geo = self._progress_time_geometries(seek_y)
        self.t_now.setGeometry(*self._offset_geometry("time_now", now_geo))
        self.t_total = TimeLabel("0:00", self)
        self.t_total.setFont(self._progress_time_font("time_total"))
        self.t_total.setStyleSheet("color: rgba(255,255,255,120);")
        self.t_total.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.t_total.setGeometry(
            *self._offset_geometry("time_total", total_geo))
        self.seek = SeekBar(self)
        self.seek.set_top_padding(self._seek_bar_top_padding())
        self.seek.setGeometry(
            *self._offset_geometry("seek", self._seek_bar_geometry(seek_y)))
        self.seek_hover = _SeekHoverTimeOverlay(self.seek, self)
        self.seek_hover.setGeometry(0, 0, self._W, self._H)
        self.seek.set_hover_overlay(self.seek_hover)
        self.seek_hover.raise_()
        if self._control_bar:
            self.t_now.hide()
            self.t_total.hide()
            self.seek.hide()
            self.seek_hover.hide()

        self.fps_label = QLabel("0 FPS", self)
        self.fps_label.setFont(ui_font(S(9), QFont.DemiBold))
        self.fps_label.setStyleSheet(
            "background: rgba(0,0,0,120); color: rgba(255,255,255,190);"
            "border-radius: 5px; padding: 2px 6px;")
        self.fps_label.hide()
        self._fps_frames = 0
        self._fps_last = time.monotonic()
        self._fps_prev_paint: float | None = None
        self._fps_frame_ms_sum = 0.0
        self._fps_frame_ms_count = 0
        self._fps_paint_ms_sum = 0.0
        self._fps_paint_ms_count = 0
        self._fps_timer = QTimer(self)
        self._fps_timer.setInterval(500)
        self._fps_timer.timeout.connect(self._update_fps_label)
        self.apply_fps_overlay()

        # ---- 空狀態（沒偵測到媒體來源） ----
        self.empty_icon = _RotatingLabel(GLYPH_NOTE, self)
        self.empty_icon.setFont(icon_font(S(30)))
        self.empty_icon.setStyleSheet("color: rgba(255,255,255,70);")
        self.empty_icon.setAlignment(Qt.AlignCenter)
        self.empty_icon.setGeometry(*self._offset_geometry(
            "empty_icon", (0, S(14 if self._compact else 22), W, S(36))))
        self.empty_text = _RotatingLabel(empty_text("spotify"), self)
        self.empty_text.setFont(ui_font(S(12)))
        self.empty_text.setStyleSheet("color: rgba(255,255,255,140);")
        self.empty_text.setAlignment(Qt.AlignCenter)
        self.empty_text.setGeometry(*self._offset_geometry(
            "empty_text", (0, S(50 if self._compact else 62), W, S(18))))
        self.empty_btn = LaunchButton(tr("launch_spotify"), S(12), S(30), self)
        self._empty_btn_base_size = (
            self.empty_btn.width(), self.empty_btn.height())
        empty_base = ((W - self.empty_btn.width()) // 2,
                      S(74 if self._compact else 92) - self.empty_btn.pad,
                      self._empty_btn_base_size[0],
                      self._empty_btn_base_size[1])
        x, y, bw, bh = self._offset_geometry("empty_button", empty_base)
        self.empty_btn.setFixedSize(bw, bh)
        self.empty_btn.move(x, y)

        self._content = [self.art, self.source_logo, self.source,
                         self.title, self.artist, self.controls,
                         self.t_now, self.t_total, self.seek,
                         self.seek_hover]
        self._empty = [self.empty_icon, self.empty_text, self.empty_btn]
        self._edit_overlay = _EditLayoutOverlay(self)
        self._edit_overlay.setGeometry(0, 0, self._W, self._H)
        self._edit_overlay.hide()
        self._edit_ghost = _EditGhostLayer(self)
        self._edit_library = _EditLibrary(self)
        self._install_edit_target_filters()
        self._build_edit_instances()
        self._apply_cover_layout(self._cover_layout_data(self._cover_enabled))
        self._apply_edit_angles()
        self.art.setVisible(False)

    def _layout_control_rail(self):
        """控制列內部固定排列；對齊切換時只移動外層容器。"""
        gap = self._control_button_gap()
        visible = [b for b in self._ctrls if not b.isHidden()]
        if not visible:
            visible = [self.btn_play]
            self.btn_play.show()
        nominal_w = (sum(b.width() for b in visible)
                     + gap * (len(visible) - 1))
        nominal_h = max(b.height() for b in visible)
        items = []
        x = 0
        cy = nominal_h / 2
        for b in visible:
            key = self._control_edit_keys_by_button.get(b)
            off = self._edit_offset_px(key) if key else QPointF()
            bx = float(x) + off.x()
            by = cy - b.height() / 2 + off.y()
            items.append((b, bx, by))
            x += b.width() + gap
        group_angle = self._edit_angle_logic("controls")
        if abs(group_angle) >= 0.01 and items:
            min_x0 = min(bx for _, bx, _ in items)
            min_y0 = min(by for _, _, by in items)
            max_x0 = max(bx + b.width() for b, bx, _ in items)
            max_y0 = max(by + b.height() for b, _, by in items)
            cx0 = (min_x0 + max_x0) / 2.0
            cy0 = (min_y0 + max_y0) / 2.0
            rad = math.radians(group_angle)
            cos_a = math.cos(rad)
            sin_a = math.sin(rad)
            rotated = []
            for b, bx, by in items:
                bc_x = bx + b.width() / 2.0
                bc_y = by + b.height() / 2.0
                dx = bc_x - cx0
                dy = bc_y - cy0
                rc_x = cx0 + dx * cos_a - dy * sin_a
                rc_y = cy0 + dx * sin_a + dy * cos_a
                rotated.append((b, rc_x - b.width() / 2.0,
                                rc_y - b.height() / 2.0))
            items = rotated
        min_x = min((bx for _, bx, _ in items), default=0.0)
        min_y = min((by for _, _, by in items), default=0.0)
        max_x = max((bx + b.width() for b, bx, _ in items),
                    default=float(nominal_w))
        max_y = max((by + b.height() for b, _, by in items),
                    default=float(nominal_h))
        self._ctrl_layout_min = QPointF(min_x, min_y)
        self._ctrl_nominal_size = (nominal_w, nominal_h)
        self.controls.setFixedSize(max(1, round(max_x - min_x)),
                                   max(1, round(max_y - min_y)))
        for b, bx, by in items:
            b.move(round(bx - min_x), round(by - min_y))

    def _control_position(self) -> QPointF:
        """控制列容器位置（依 controls_align 設定靠左/置中/靠右）。"""
        info_x, info_w = self._ctrl_span
        total = self._ctrl_nominal_size[0] or self.controls.width()
        nominal_h = self._ctrl_nominal_size[1] or self.controls.height()
        align = SETTINGS["controls_align"]
        if align == "left":
            x = info_x
        elif align == "right":
            x = info_x + info_w - total
        else:
            x = info_x + (info_w - total) // 2
        layout_min = getattr(self, "_ctrl_layout_min", QPointF(0.0, 0.0))
        return self._offset_point(
            "controls",
            QPointF(float(x) + layout_min.x(),
                    self._controls_y - nominal_h / 2 + layout_min.y()))

    def _cover_layout_data(self, cover_enabled: bool) -> dict:
        art_x = S(12 if self._compact else 16)
        art_y = S(12 if self._compact else 16)
        art_on = QPointF(float(art_x - self.art.pad),
                         float(art_y - self.art.pad))
        art_off = QPointF(float(-self.art.width() + S(8)), art_on.y())
        if cover_enabled:
            info_x = art_x + self._art_info_span() + S(10 if self._compact else 14)
        else:
            info_x = S(14 if self._compact else 18)
        right_pad = S(126 if self._control_bar else 16)
        info_w = self._W - info_x - right_pad
        if info_w < S(150):
            info_w = max(S(120), self._W - info_x - S(16))
        source_y = S(10 if self._compact else 14)
        logo_d = S(15)
        logo_gap = S(4)
        title_y = S(26 if self._compact else 34)
        artist_y = S(46 if self._compact else 56)
        (title_base, artist_base, title_focus, artist_focus,
         title_canvas, artist_canvas) = self._text_layout_rects(
             info_x, title_y, artist_y, info_w)
        return {
            "art_pos": art_on if cover_enabled else art_off,
            "art_op": 1.0 if cover_enabled else 0.0,
            "source_rect": QRectF(info_x + logo_d + logo_gap, source_y,
                                  S(120), S(14)),
            "logo_rect": QRectF(info_x, source_y, logo_d, logo_d),
            "title_base": title_base,
            "artist_base": artist_base,
            "title_focus": title_focus,
            "artist_focus": artist_focus,
            "title_canvas": title_canvas,
            "artist_canvas": artist_canvas,
            "ctrl_span": (info_x, info_w),
        }

    def _current_layout_data(self) -> dict:
        return {
            "art_pos": self._unoffset_point("art", QPointF(self.art.pos())),
            "art_op": float(self._art_eff.opacity()),
            "source_rect": self._unoffset_rect(
                "source", QRectF(self.source.geometry())),
            "logo_rect": self._unoffset_rect(
                "source_logo", QRectF(self.source_logo.geometry())),
            "title_base": QRectF(self._title_base),
            "artist_base": QRectF(self._artist_base),
            "title_focus": QRectF(self._title_focus),
            "artist_focus": QRectF(self._artist_focus),
            "title_canvas": QRectF(self._title_canvas),
            "artist_canvas": QRectF(self._artist_canvas),
            "ctrl_span": (float(self._ctrl_span[0]), float(self._ctrl_span[1])),
        }

    def _lerp_rectf(self, a: QRectF, b: QRectF, t: float) -> QRectF:
        return QRectF(a.x() + (b.x() - a.x()) * t,
                      a.y() + (b.y() - a.y()) * t,
                      a.width() + (b.width() - a.width()) * t,
                      a.height() + (b.height() - a.height()) * t)

    def _lerp_layout_data(self, a: dict, b: dict, t: float) -> dict:
        ap, bp = a["art_pos"], b["art_pos"]
        return {
            "art_pos": QPointF(ap.x() + (bp.x() - ap.x()) * t,
                               ap.y() + (bp.y() - ap.y()) * t),
            "art_op": a["art_op"] + (b["art_op"] - a["art_op"]) * t,
            "source_rect": self._lerp_rectf(a["source_rect"],
                                            b["source_rect"], t),
            "logo_rect": self._lerp_rectf(a["logo_rect"],
                                          b["logo_rect"], t),
            "title_base": self._lerp_rectf(a["title_base"],
                                           b["title_base"], t),
            "artist_base": self._lerp_rectf(a["artist_base"],
                                            b["artist_base"], t),
            "title_focus": self._lerp_rectf(a["title_focus"],
                                            b["title_focus"], t),
            "artist_focus": self._lerp_rectf(a["artist_focus"],
                                             b["artist_focus"], t),
            "title_canvas": self._lerp_rectf(a["title_canvas"],
                                             b["title_canvas"], t),
            "artist_canvas": self._lerp_rectf(a["artist_canvas"],
                                              b["artist_canvas"], t),
            "ctrl_span": (
                a["ctrl_span"][0] + (b["ctrl_span"][0] - a["ctrl_span"][0]) * t,
                a["ctrl_span"][1] + (b["ctrl_span"][1] - a["ctrl_span"][1]) * t,
            ),
        }

    def _apply_source_layout(self, source_rect: QRectF, logo_rect: QRectF):
        sr = self._offset_rect("source", source_rect)
        self.source.setGeometry(round(sr.x()), round(sr.y()),
                                round(sr.width()), round(sr.height()))
        lr = self._offset_rect("source_logo", logo_rect)
        self.source_logo.setGeometry(round(lr.x()), round(lr.y()),
                                     round(lr.width()), round(lr.height()))
        self._apply_source_font()

    def _apply_cover_layout(self, data: dict):
        ap = self._offset_point("art", data["art_pos"])
        self.art.move(round(ap.x()), round(ap.y()))
        self._art_eff.setOpacity(max(0.0, min(1.0, float(data["art_op"]))))
        self._apply_source_layout(data["source_rect"], data["logo_rect"])
        self._title_base = QRectF(data["title_base"])
        self._artist_base = QRectF(data["artist_base"])
        self._title_focus = QRectF(data["title_focus"])
        self._artist_focus = QRectF(data["artist_focus"])
        self._title_canvas = QRectF(data["title_canvas"])
        self._artist_canvas = QRectF(data["artist_canvas"])
        self.title.set_font_px(self._title_px_base)
        self.artist.set_font_px(self._artist_px_base)
        title_canvas = self._offset_rect("title", self._title_canvas)
        artist_canvas = self._offset_rect("artist", self._artist_canvas)
        self.title.setGeometry(round(title_canvas.x()),
                               round(title_canvas.y()),
                               round(title_canvas.width()),
                               round(title_canvas.height()))
        self.artist.setGeometry(round(artist_canvas.x()),
                                round(artist_canvas.y()),
                                round(artist_canvas.width()),
                                round(artist_canvas.height()))
        self._ctrl_span = data["ctrl_span"]
        self._on_info_focus(self._info_focus)
        self._layout_control_rail()
        target = self._control_position()
        self._ctrl_to = QPointF(target)
        self._ctrl_pos = QPointF(target)
        if self._ctrl_overlay is not None:
            self._ctrl_overlay.hide()
        self.controls.move(round(target.x()), round(target.y()))
        self._update_edit_overlay()

    def layout_edit_mode(self) -> bool:
        return bool(self._edit_mode)

    def _base_edit_target_keys(self):
        return ("art", "source_logo", "source", "title", "artist", "controls",
                "ctrl_shuffle", "ctrl_prev", "ctrl_play", "ctrl_next",
                "ctrl_repeat",
                "top_edit", "top_reset", "top_volume", "top_settings",
                "top_pin", "top_close",
                "seek", "time_now", "time_total",
                "empty_icon", "empty_text", "empty_button")

    def edit_target_keys(self):
        return self._base_edit_target_keys() + tuple(self._edit_instance_widgets)

    def _is_edit_instance_key(self, key: str) -> bool:
        return isinstance(key, str) and key.startswith("inst:")

    @staticmethod
    def _edit_instance_key(iid: str) -> str:
        return f"inst:{iid}"

    def _edit_instances(self) -> list[dict]:
        raw = SETTINGS.get("edit_library_instances", [])
        if not isinstance(raw, list):
            raw = []
            SETTINGS["edit_library_instances"] = raw
        return raw

    def _edit_instance_data(self, key: str) -> dict | None:
        if not self._is_edit_instance_key(key):
            return None
        iid = key.split(":", 1)[1]
        for item in self._edit_instances():
            if isinstance(item, dict) and item.get("id") == iid:
                return item
        return None

    def _edit_instance_source(self, key: str) -> str:
        data = self._edit_instance_data(key)
        if not isinstance(data, dict):
            return ""
        return str(data.get("source", ""))

    def edit_library_rows(self) -> list[tuple[str, str, str]]:
        rows: list[tuple[str, str, str]] = [
            ("art:cover", "Elements", "Cover"),
            ("art:vinyl", "Elements", "Vinyl"),
            ("art:audio", "Elements", "Audio feedback"),
            ("art:pulse", "Elements", "Pulse cover"),
        ]
        for key in self._base_edit_target_keys():
            if key in ("art", "seek"):
                continue
            rows.append((f"new:{key}", "Elements", self.edit_label(key)))
        for key in self.hidden_edit_keys():
            rows.append((f"hidden:{key}", "Hidden", self.edit_label(key)))
        return rows

    def edit_library_default_drop_pos(self) -> QPointF:
        x = min(self.width() - S(44), S(176))
        y = min(self.height() - S(44), S(72))
        return QPointF(max(S(32), x), max(S(32), y))

    def _new_edit_instance_id(self) -> str:
        used = {
            str(item.get("id", "")) for item in self._edit_instances()
            if isinstance(item, dict)
        }
        while True:
            iid = f"{int(time.time() * 1000):x}{random.randrange(0x1000):03x}"
            if iid not in used:
                return iid

    def _instance_default_size_logic(self, row_key: str) -> float:
        if row_key.startswith("art:"):
            return 72.0
        if row_key.startswith("new:"):
            src = row_key.split(":", 1)[1]
            r = self.edit_target_rect(src)
            if r.isValid():
                scale = max(0.01, float(SETTINGS.get("scale", 1.0)))
                return max(26.0, min(150.0, max(r.width(), r.height()) / scale))
        return 64.0

    def create_edit_library_instance(self, row_key: str,
                                     drop_pos: QPointF | None = None):
        if not row_key or row_key.startswith("hidden:"):
            return
        if drop_pos is None:
            drop_pos = self.edit_library_default_drop_pos()
        scale = max(0.01, float(SETTINGS.get("scale", 1.0)))
        size_logic = self._instance_default_size_logic(row_key)
        data = {
            "id": self._new_edit_instance_id(),
            "x": max(-80.0, min(500.0, drop_pos.x() / scale - size_logic / 2)),
            "y": max(-80.0, min(400.0, drop_pos.y() / scale - size_logic / 2)),
            "size": size_logic,
        }
        if row_key.startswith("art:"):
            mode = row_key.split(":", 1)[1]
            data.update({
                "kind": "art",
                "mode": mode if mode in ("cover", "vinyl", "pulse", "audio") else "cover",
            })
        elif row_key.startswith("new:"):
            src = row_key.split(":", 1)[1]
            if src not in self._base_edit_target_keys():
                return
            data.update({"kind": "element", "source": src})
            if src in ("time_now", "time_total"):
                r = self.edit_target_rect(src)
                if r.isValid():
                    data["w"] = max(24.0, min(180.0, r.width() / scale))
                    data["h"] = max(12.0, min(80.0, r.height() / scale))
        else:
            return
        self._edit_instances().append(data)
        key = self._edit_instance_key(data["id"])
        self._create_edit_instance_widget(data)
        self._apply_edit_instance_layout(key)
        self._fade_edit_key_in(key)
        self._set_edit_selection(key, additive=False)
        self._sync_edit_library()
        self._update_edit_overlay()
        self.layout_edit_changed.emit()

    def _edit_button_source_spec(self, source: str):
        if source in getattr(self, "_control_edit_specs", {}):
            _, glyph_base, diam_base, is_play = self._control_edit_specs[source]
            if is_play:
                return {"kind": "play", "diameter": 36}
            glyph = {
                "ctrl_shuffle": GLYPH_SHUFFLE,
                "ctrl_prev": GLYPH_PREV,
                "ctrl_next": GLYPH_NEXT,
                "ctrl_repeat": GLYPH_REPEAT_ALL,
            }.get(source)
            if glyph is None:
                return None
            return {
                "kind": "icon",
                "glyph": glyph,
                "glyph_base": glyph_base,
                "diam_base": diam_base,
                "checkable": source in ("ctrl_shuffle", "ctrl_repeat"),
                "dot": source in ("ctrl_shuffle", "ctrl_repeat"),
                "fx": "",
            }
        top_specs = getattr(self, "_topbar_edit_specs", {})
        if source in top_specs:
            _, glyph_base, diam_base = top_specs[source]
            data = {
                "top_edit": (GLYPH_EDIT, True, "wiggle"),
                "top_reset": (GLYPH_RESET, False, "spin"),
                "top_volume": (GLYPH_VOLUME, False, ""),
                "top_settings": (GLYPH_SETTINGS, False, "gear"),
                "top_pin": (GLYPH_PIN, True, "wiggle"),
                "top_close": (GLYPH_CLOSE, False, "spin"),
            }.get(source)
            if data is None:
                return None
            glyph, checkable, fx = data
            return {
                "kind": "icon",
                "glyph": glyph,
                "glyph_base": glyph_base,
                "diam_base": diam_base,
                "checkable": checkable,
                "dot": False,
                "fx": fx,
                "press_scale": 0.78 if source == "top_volume" else None,
                "release_ms": 260 if source == "top_volume" else None,
                "release_overshoot": 1.7 if source == "top_volume" else None,
                "hover_ms_factor": 2.0 if source == "top_volume" else None,
            }
        return None

    def _invoke_window_method(self, name: str, *args):
        win = self.window()
        func = getattr(win, name, None)
        if callable(func):
            func(*args)

    def _invoke_window_command(self, name: str):
        win = self.window()
        func = getattr(win, "_cmd", None)
        if callable(func):
            func(name)

    def _connect_edit_instance_action(self, widget: QWidget, source: str):
        if source == "ctrl_play":
            widget.clicked.connect(
                lambda _=False: self._invoke_window_method("_toggle_play"))
        elif source == "ctrl_prev":
            widget.clicked.connect(
                lambda _=False: self._invoke_window_command("prev_track"))
        elif source == "ctrl_next":
            widget.clicked.connect(
                lambda _=False: self._invoke_window_command("next_track"))
        elif source == "ctrl_shuffle":
            widget.clicked.connect(
                lambda _=False: self._invoke_window_method("_toggle_shuffle"))
        elif source == "ctrl_repeat":
            widget.clicked.connect(
                lambda _=False: self._invoke_window_method("_cycle_repeat"))
        elif source == "top_edit":
            widget.clicked.connect(
                lambda checked=False, w=widget:
                self.set_layout_edit_mode(bool(w.isChecked())))
        elif source == "top_reset":
            widget.clicked.connect(
                lambda _=False: self.reset_layout_positions())
        elif source == "top_volume":
            widget.clicked.connect(
                lambda _=False: self._invoke_window_method("_show_volume"))
        elif source == "top_settings":
            widget.clicked.connect(
                lambda _=False: self._invoke_window_method("_toggle_panel"))
        elif source == "top_pin":
            widget.clicked.connect(
                lambda checked=False, w=widget:
                self.btn_pin.setChecked(bool(w.isChecked())))
        elif source == "top_close":
            widget.clicked.connect(
                lambda _=False: self._invoke_window_method("hide_animated"))

    def _create_edit_element_widget(self, source: str) -> QWidget | None:
        if source in ("time_now", "time_total"):
            widget = TimeLabel("0:00", self)
            widget.setAlignment(
                Qt.AlignRight | Qt.AlignVCenter
                if source == "time_total" else Qt.AlignLeft | Qt.AlignVCenter)
            self._set_progress_time_label(
                widget, source, self._progress_pos, self._progress_dur,
                animate_now=False, animate_mode=False)
            return widget
        spec = self._edit_button_source_spec(source)
        if spec is None:
            return _EditReplica(self, source, self)
        if spec["kind"] == "play":
            widget = PlayButton(S(spec["diameter"]), self)
        else:
            widget = IconButton(
                spec["glyph"], S(spec["glyph_base"]), S(spec["diam_base"]),
                checkable=bool(spec.get("checkable", False)),
                dot=bool(spec.get("dot", False)),
                fx=str(spec.get("fx", "")),
                press_scale=spec.get("press_scale"),
                release_ms=spec.get("release_ms"),
                release_overshoot=spec.get("release_overshoot"),
                hover_ms_factor=spec.get("hover_ms_factor"),
                parent=self)
            widget.set_accent(self._accent)
        self._connect_edit_instance_action(widget, source)
        return widget

    def _create_edit_instance_widget(self, data: dict) -> QWidget | None:
        iid = str(data.get("id", ""))
        if not iid:
            return None
        key = self._edit_instance_key(iid)
        old = self._edit_instance_widgets.pop(key, None)
        if old is not None:
            old.hide()
            old.deleteLater()
        kind = data.get("kind")
        if kind == "art":
            size = max(1, S(float(data.get("size", 72.0))))
            widget = ArtView(size, self._cover_radius_for_size(size), self)
            widget.set_mode(str(data.get("mode", "cover")), animate=False)
            widget.set_border(SETTINGS.get("cover_border", False),
                              SETTINGS.get("cover_border_width", 2.0),
                              SETTINGS.get("cover_border_opacity", 0.85),
                              animate=False)
            widget.set_accent(self._accent)
            widget.set_audio_level_provider(self._audio_level_provider)
            widget.set_playing(getattr(self, "_art_playing", False))
        elif kind in ("element", "replica"):
            source = str(data.get("source", ""))
            if source not in self._base_edit_target_keys():
                return None
            widget = self._create_edit_element_widget(source)
        else:
            return None
        if widget is None:
            return None
        widget.setMouseTracking(True)
        widget.installEventFilter(self)
        self._edit_filter_targets[widget] = key
        self._edit_instance_widgets[key] = widget
        widget.show()
        widget.raise_()
        if isinstance(widget, ArtView):
            self._refresh_edit_instance_art(key, animate=False)
        self._sync_edit_instance_element_states()
        return widget

    def _build_edit_instances(self):
        for widget in self._edit_instance_widgets.values():
            widget.hide()
            widget.deleteLater()
        self._edit_instance_widgets.clear()
        for data in list(self._edit_instances()):
            if isinstance(data, dict):
                self._create_edit_instance_widget(data)
        self._apply_edit_instance_layouts()

    def _apply_edit_instance_layout(self, key: str):
        data = self._edit_instance_data(key)
        widget = self._edit_instance_widgets.get(key)
        if data is None or widget is None:
            return
        try:
            base_size = float(data.get("size", 72.0))
            x = float(data.get("x", 40.0))
            y = float(data.get("y", 40.0))
        except (TypeError, ValueError):
            return
        dw, dh = self._edit_size_logic(key)
        size_logic = max(24.0, min(220.0, base_size + max(dw, dh)))
        if isinstance(widget, ArtView):
            size_px = max(1, S(size_logic))
            widget.set_base_size(size_px, self._cover_radius_for_size(size_px))
            widget.set_border(SETTINGS.get("cover_border", False),
                              SETTINGS.get("cover_border_width", 2.0),
                              SETTINGS.get("cover_border_opacity", 0.85),
                              animate=False)
            self._refresh_edit_instance_art(key, animate=False)
        elif isinstance(widget, PlayButton):
            widget.set_diameter(max(S(18), S(size_logic)))
        elif isinstance(widget, IconButton):
            source = str(data.get("source", ""))
            spec = self._edit_button_source_spec(source) or {}
            diam_base = max(1.0, float(spec.get("diam_base", 22.0)))
            glyph_base = max(1.0, float(spec.get("glyph_base", 10.0)))
            side = max(S(18), S(size_logic))
            glyph_px = max(1, round(side * glyph_base / diam_base))
            widget.set_metrics(glyph_px, side)
        elif isinstance(widget, TimeLabel):
            source = str(data.get("source", "time_now"))
            try:
                base_w = float(data.get("w", data.get("size", 42.0)))
                base_h = float(data.get("h", 14.0))
            except (TypeError, ValueError):
                base_w, base_h = 42.0, 14.0
            dw, dh = self._edit_size_logic(key)
            w = max(S(24), round(Sf(base_w + dw)))
            h = max(S(12), round(Sf(base_h + dh)))
            widget.setFixedSize(w, h)
            f = ui_font(max(1, round(h * 0.72)))
            spacing = Sf(float(SETTINGS.get("progress_time_spacing", 0.0)))
            f.setLetterSpacing(QFont.AbsoluteSpacing, spacing)
            widget.setFont(f)
            widget.setAlignment(
                Qt.AlignRight | Qt.AlignVCenter
                if source == "time_total" else Qt.AlignLeft | Qt.AlignVCenter)
            if hasattr(self, "t_now"):
                widget.setStyleSheet(self.t_now.styleSheet())
            self._set_progress_time_label(
                widget, source, self._progress_pos, self._progress_dur,
                animate_now=False, animate_mode=False)
        else:
            side = max(S(18), S(size_logic))
            widget.setFixedSize(side, side)
        off = self._edit_offset_px(key)
        widget.move(round(Sf(x) + off.x()), round(Sf(y) + off.y()))
        widget.raise_()
        if isinstance(widget, _EditReplica):
            widget._capture_items()
        self._apply_edit_angle(key)

    def _apply_edit_instance_layouts(self):
        for key in tuple(self._edit_instance_widgets):
            self._apply_edit_instance_layout(key)

    def _refresh_edit_instance_art(self, key: str, animate: bool = True):
        widget = self._edit_instance_widgets.get(key)
        if not isinstance(widget, ArtView):
            return
        radius = self._cover_radius_for_size(widget.cover_size())
        widget.set_radius(radius, animate=animate)
        if self._art_img is None or self._art_img.isNull():
            widget.set_pixmap(None, animate=animate)
            return
        pm = rounded_pixmap(
            self._art_img, widget.cover_size(),
            radius, self.devicePixelRatioF())
        widget.set_pixmap(pm, animate=animate)

    def _refresh_edit_instance_art_all(self, animate: bool = True):
        for key in tuple(self._edit_instance_widgets):
            self._refresh_edit_instance_art(key, animate=animate)

    def _art_widgets(self) -> tuple[ArtView, ...]:
        widgets: list[ArtView] = []
        if hasattr(self, "art") and isinstance(self.art, ArtView):
            widgets.append(self.art)
        widgets.extend(
            widget for widget in self._edit_instance_widgets.values()
            if isinstance(widget, ArtView)
        )
        return tuple(widgets)

    def _sync_edit_instance_element_states(self):
        for key, widget in tuple(self._edit_instance_widgets.items()):
            data = self._edit_instance_data(key)
            if not isinstance(data, dict) or data.get("kind") not in (
                    "element", "replica"):
                continue
            source = str(data.get("source", ""))
            if isinstance(widget, TimeLabel) and source in (
                    "time_now", "time_total"):
                self._set_progress_time_label(
                    widget, source, self._progress_pos, self._progress_dur,
                    animate_now=False, animate_mode=False)
            elif isinstance(widget, PlayButton) and source == "ctrl_play":
                widget.set_playing(getattr(self.btn_play, "_playing", False))
                widget.setEnabled(self.btn_play.isEnabled())
            elif isinstance(widget, IconButton):
                source_widgets = self._edit_target_widgets(source)
                original = source_widgets[0] if source_widgets else None
                if original is not None:
                    widget.setEnabled(original.isEnabled())
                widget.set_accent(self._accent)
                if source == "ctrl_shuffle":
                    widget.setChecked(self.btn_shuffle.isChecked())
                elif source == "ctrl_repeat":
                    widget.setChecked(self.btn_repeat.isChecked())
                    widget.set_glyph(getattr(self.btn_repeat, "_glyph",
                                             GLYPH_REPEAT_ALL))
                elif source == "top_pin":
                    widget.setChecked(self.btn_pin.isChecked())
                elif source == "top_edit":
                    widget.setChecked(self._edit_mode)

    def _remove_edit_instance(self, key: str, animate: bool = True):
        widget = self._edit_instance_widgets.get(key)
        if widget is None:
            return

        def done():
            w = self._edit_instance_widgets.pop(key, None)
            if w is not None:
                self._edit_filter_targets.pop(w, None)
                w.hide()
                w.deleteLater()
            iid = key.split(":", 1)[1]
            SETTINGS["edit_library_instances"] = [
                item for item in self._edit_instances()
                if not (isinstance(item, dict) and item.get("id") == iid)
            ]
            self._layout_positions().pop(key, None)
            self._layout_sizes().pop(key, None)
            self._layout_angles().pop(key, None)
            self._edit_selected_keys.discard(key)
            self._sync_edit_selection_fades()
            self._sync_edit_library()
            self._update_edit_overlay()

        if animate and hasattr(self, "_edit_ghost") and not widget.isHidden():
            self._edit_ghost.start((widget,), 1.0, 0.0, done_callback=done,
                                   animate=True, hide_source=True)
        else:
            done()

    def _text_edit_target_rect(self, key: str) -> QRectF:
        if key == "title":
            base = getattr(self, "_title_base", QRectF())
            focus = getattr(self, "_title_focus", QRectF())
        elif key == "artist":
            base = getattr(self, "_artist_base", QRectF())
            focus = getattr(self, "_artist_focus", QRectF())
        else:
            return QRectF()
        if not base.isValid():
            return QRectF()
        t = max(0.0, min(1.0, float(getattr(self, "_info_focus", 0.0))))
        rect = QRectF(
            base.x() + (focus.x() - base.x()) * t,
            base.y() + (focus.y() - base.y()) * t,
            base.width() + (focus.width() - base.width()) * t,
            base.height() + (focus.height() - base.height()) * t,
        )
        return self._offset_rect(key, rect)

    def _edit_target_widgets(self, key: str) -> tuple[QWidget, ...]:
        if self._is_edit_instance_key(key):
            widget = self._edit_instance_widgets.get(key)
            return (widget,) if widget is not None else ()
        if hasattr(self, "_control_edit_specs") and key in self._control_edit_specs:
            return (self._control_edit_specs[key][0],)
        if hasattr(self, "_topbar_edit_specs") and key in self._topbar_edit_specs:
            return (self._topbar_edit_specs[key][0],)
        if key == "source":
            return (self.source,)
        if key == "source_logo":
            return (self.source_logo,)
        if key == "controls":
            return (self.controls,)
        attr = {
            "art": "art",
            "title": "title",
            "artist": "artist",
            "seek": "seek",
            "time_now": "t_now",
            "time_total": "t_total",
            "empty_icon": "empty_icon",
            "empty_text": "empty_text",
            "empty_button": "empty_btn",
        }.get(key)
        if not attr or not hasattr(self, attr):
            return ()
        return (getattr(self, attr),)

    def edit_target_rect(self, key: str) -> QRectF:
        if key in self._hidden_edit_key_set():
            return QRectF()
        if key in ("title", "artist"):
            return self._text_edit_target_rect(key)
        rect = QRectF()
        first = True
        for widget in self._edit_target_widgets(key):
            if widget is None or widget.isHidden():
                continue
            if widget.parentWidget() is self:
                wr = QRectF(widget.geometry())
            else:
                top_left = widget.mapTo(self, QPoint(0, 0))
                wr = QRectF(QPointF(top_left), QSizeF(
                    widget.width(), widget.height()))
            rect = wr if first else rect.united(wr)
            first = False
        return rect

    def _unrotate_edit_pos(self, key: str, pos: QPointF) -> QPointF:
        angle = self.edit_target_angle(key)
        if abs(angle) < 0.01:
            return QPointF(pos)
        r = self.edit_target_rect(key)
        if not r.isValid():
            return QPointF(pos)
        c = r.center()
        rad = math.radians(-angle)
        dx = pos.x() - c.x()
        dy = pos.y() - c.y()
        return QPointF(c.x() + dx * math.cos(rad) - dy * math.sin(rad),
                       c.y() + dx * math.sin(rad) + dy * math.cos(rad))

    def edit_resize_handle_rect(self, key: str) -> QRectF:
        if key not in self._resizable_edit_keys():
            return QRectF()
        active = (self._edit_drag or {}).get("key")
        if (self._edit_hover_key != key and active != key
                and self._edit_handle_ops.get(key, 0.0) <= 0.001):
            return QRectF()
        r = self.edit_target_rect(key)
        if not r.isValid() or r.width() < 2 or r.height() < 2:
            return QRectF()
        d = S(7)
        return QRectF(r.right() - d + S(1), r.bottom() - d + S(1), d, d)

    def edit_rotate_handle_rect(self, key: str) -> QRectF:
        if key not in self.edit_target_keys():
            return QRectF()
        active = (self._edit_drag or {}).get("key")
        if (self._edit_hover_key != key and active != key
                and self._edit_handle_ops.get(key, 0.0) <= 0.001):
            return QRectF()
        r = self.edit_target_rect(key)
        if not r.isValid() or r.width() < 2 or r.height() < 2:
            return QRectF()
        d = S(16)
        return QRectF(r.right() - d * 0.45, r.top() - d * 0.55, d, d)

    def edit_resize_handle_opacity(self, key: str) -> float:
        if key not in self._resizable_edit_keys():
            return 0.0
        active = (self._edit_drag or {}).get("key")
        if active == key:
            return 1.0
        return max(0.0, min(1.0, self._edit_handle_ops.get(key, 0.0)))

    def edit_rotate_handle_opacity(self, key: str) -> float:
        if key not in self.edit_target_keys():
            return 0.0
        active = (self._edit_drag or {}).get("key")
        if active == key:
            return 1.0
        return max(0.0, min(1.0, self._edit_handle_ops.get(key, 0.0)))

    def _resize_key_at(self, pos: QPointF) -> str | None:
        for key in reversed(self._resizable_edit_keys()):
            r = self.edit_target_rect(key)
            if not r.isValid():
                continue
            d = S(10)
            hit = QRectF(r.right() - d + S(2), r.bottom() - d + S(2), d, d)
            if hit.contains(self._unrotate_edit_pos(key, pos)):
                return key
        return None

    def _rotate_key_at(self, pos: QPointF) -> str | None:
        for key in reversed(self.edit_target_keys()):
            r = self.edit_target_rect(key)
            if not r.isValid():
                continue
            d = S(18)
            hit = QRectF(r.right() - d * 0.5, r.top() - d * 0.6, d, d)
            if hit.contains(self._unrotate_edit_pos(key, pos)):
                return key
        return None

    def _target_key_at(self, pos: QPointF) -> str | None:
        for key in reversed(self.edit_target_keys()):
            if self.edit_target_rect(key).contains(pos):
                return key
        return None

    def _set_edit_hover_key(self, key: str | None):
        if key in self._hidden_edit_key_set():
            key = None
        if key == self._edit_hover_key:
            return
        self._edit_hover_key = key
        self._sync_edit_handle_fades()
        self._update_edit_overlay()

    def edit_key_selected(self, key: str) -> bool:
        return key in self._edit_selected_keys

    def edit_selection_opacity(self, key: str) -> float:
        if key in self._edit_selected_keys:
            return max(0.0, min(1.0, self._edit_select_ops.get(key, 1.0)))
        return max(0.0, min(1.0, self._edit_select_ops.get(key, 0.0)))

    def _ensure_edit_select_anim(self, key: str) -> Anim:
        anim = self._edit_select_anims.get(key)
        if anim is None:
            anim = Anim(self)
            anim.valueChanged.connect(
                lambda value, k=key: self._on_edit_select_op(k, value))
            anim.finished.connect(
                lambda k=key: self._edit_select_anim_done(k))
            self._edit_select_anims[key] = anim
        return anim

    def _on_edit_select_op(self, key: str, value):
        self._edit_select_ops[key] = max(0.0, min(1.0, float(value)))
        self._update_edit_overlay()

    def _edit_select_anim_done(self, key: str):
        if self._edit_select_targets.get(key, 0.0) <= 0.001:
            self._edit_select_ops.pop(key, None)
            self._edit_select_targets.pop(key, None)
        self._update_edit_overlay()

    def _fade_edit_selection(self, key: str, target: float,
                             animate: bool = True):
        target = 1.0 if target > 0.5 else 0.0
        if self._edit_select_targets.get(key) == target:
            return
        self._edit_select_targets[key] = target
        anim = self._ensure_edit_select_anim(key)
        anim.stop()
        start = self.edit_selection_opacity(key)
        ms = adur(130 if target > start else 170, 90)
        if (not animate or not anim_on() or ms <= 0 or not self.isVisible()):
            self._on_edit_select_op(key, target)
            self._edit_select_anim_done(key)
            return
        anim.setStartValue(start)
        anim.setEndValue(target)
        anim.setDuration(ms)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.start()

    def _sync_edit_selection_fades(self, animate: bool = True):
        keys = set(self.edit_target_keys())
        keys.update(self._edit_select_ops)
        keys.update(self._edit_select_targets)
        for key in keys:
            self._fade_edit_selection(
                key, 1.0 if key in self._edit_selected_keys else 0.0,
                animate=animate)

    def hidden_edit_keys(self) -> list[str]:
        raw = SETTINGS.get("edit_hidden_keys", [])
        if not isinstance(raw, list):
            raw = []
            SETTINGS["edit_hidden_keys"] = raw
        valid = set(self._base_edit_target_keys())
        return [k for k in raw if k in valid]

    def _hidden_edit_key_set(self) -> set[str]:
        return set(self.hidden_edit_keys())

    def edit_label(self, key: str) -> str:
        data = self._edit_instance_data(key)
        if data is not None:
            if data.get("kind") == "art":
                mode = str(data.get("mode", "cover"))
                return {
                    "cover": "Cover",
                    "vinyl": "Vinyl",
                    "pulse": "Pulse cover",
                    "audio": "Audio feedback",
                }.get(mode, "Art")
            src = str(data.get("source", ""))
            return self.edit_label(src)
        labels = {
            "art": "Cover",
            "source_logo": "Source icon",
            "source": "Source text",
            "title": "Title",
            "artist": "Artist",
            "controls": "Controls",
            "ctrl_shuffle": "Shuffle",
            "ctrl_prev": "Previous",
            "ctrl_play": "Play",
            "ctrl_next": "Next",
            "ctrl_repeat": "Repeat",
            "top_edit": "Edit",
            "top_reset": "Reset",
            "top_volume": "Volume",
            "top_settings": "Settings",
            "top_pin": "Pin",
            "top_close": "Close",
            "seek": "Seek",
            "time_now": "Time now",
            "time_total": "Time total",
            "empty_icon": "Empty icon",
            "empty_text": "Empty text",
            "empty_button": "Launch",
        }
        return labels.get(key, key)

    def _visible_edit_widgets(self, key: str) -> tuple[QWidget, ...]:
        return tuple(w for w in self._edit_target_widgets(key)
                     if w is not None and not w.isHidden()
                     and w.width() > 0 and w.height() > 0)

    def _fade_edit_key_out(self, key: str, animate: bool = True):
        widgets = self._visible_edit_widgets(key)
        if widgets and hasattr(self, "_edit_ghost"):
            self._edit_ghost.start(widgets, 1.0, 0.0, animate=animate)
            self._update_edit_overlay()
            self._sync_edit_library(animate=False)

    def _fade_edit_key_in(self, key: str, animate: bool = True):
        widgets = self._visible_edit_widgets(key)
        if not widgets or not hasattr(self, "_edit_ghost"):
            return

        def done():
            self._restore_edit_key_visibility(key)
            self._apply_edit_hidden_visibility()
            self._update_edit_overlay()
            self._sync_edit_library(animate=False)

        self._edit_ghost.start(widgets, 0.0, 1.0, done_callback=done,
                               animate=animate, hide_source=True)
        self._update_edit_overlay()
        self._sync_edit_library(animate=False)

    def _fade_edit_keys_in(self, keys: tuple[str, ...] | list[str],
                           animate: bool = True):
        keys = tuple(k for k in keys if k in self.edit_target_keys())
        if not keys or not hasattr(self, "_edit_ghost"):
            return
        for key in keys:
            self._restore_edit_key_visibility(key)
        self._apply_edit_hidden_visibility()
        widgets: list[QWidget] = []
        seen: set[QWidget] = set()
        for key in keys:
            for widget in self._visible_edit_widgets(key):
                if widget not in seen:
                    seen.add(widget)
                    widgets.append(widget)
        if not widgets:
            self._update_edit_overlay()
            self._sync_edit_library(animate=False)
            return

        def done():
            for key in keys:
                self._restore_edit_key_visibility(key)
            self._apply_edit_hidden_visibility()
            self._update_edit_overlay()
            self._sync_edit_library(animate=False)

        self._edit_ghost.start(widgets, 0.0, 1.0, done_callback=done,
                               animate=animate, hide_source=True)
        self._update_edit_overlay()
        self._sync_edit_library(animate=False)

    def _hide_edit_keys_without_setting(self, keys: tuple[str, ...] | list[str]):
        for key in keys:
            for widget in self._edit_target_widgets(key):
                if widget is not None:
                    widget.hide()

    def _set_edit_key_hidden(self, key: str, hidden: bool):
        if self._is_edit_instance_key(key):
            if hidden:
                self._remove_edit_instance(key)
            return
        keys = self.hidden_edit_keys()
        if hidden:
            if key not in keys:
                self._fade_edit_key_out(key)
                keys.append(key)
        else:
            keys = [k for k in keys if k != key]
        SETTINGS["edit_hidden_keys"] = keys
        self._edit_selected_keys.discard(key)
        self._sync_edit_selection_fades()
        if not hidden:
            self._restore_edit_key_visibility(key)
        self._apply_edit_hidden_visibility()
        self._sync_edit_library()
        self._update_edit_overlay()

    def _delete_edit_keys(self, keys: tuple[str, ...] | list[str]):
        valid = [k for k in keys if k in self.edit_target_keys()]
        if not valid and self._edit_hover_key in self.edit_target_keys():
            valid = [self._edit_hover_key]
        for key in valid:
            if self._is_edit_instance_key(key):
                self._remove_edit_instance(key)
            else:
                self._set_edit_key_hidden(key, True)
        if valid:
            self.layout_edit_changed.emit()

    def restore_hidden_edit_key(self, key: str, drop_pos: QPointF | None = None):
        if key not in self.edit_target_keys():
            return
        self._set_edit_key_hidden(key, False)
        self._apply_layout_position_offsets()
        if drop_pos is not None:
            r = self.edit_target_rect(key)
            if r.isValid():
                scale = max(0.01, float(SETTINGS.get("scale", 1.0)))
                ox, oy = self._edit_offset_logic(key)
                delta = drop_pos - r.center()
                self._set_edit_offset_logic(
                    key, ox + delta.x() / scale, oy + delta.y() / scale)
                self._apply_layout_position_offsets()
        self._fade_edit_key_in(key)
        self._set_edit_selection(key, additive=False)
        self._sync_edit_library()
        self.layout_edit_changed.emit()

    def _restore_edit_key_visibility(self, key: str):
        widgets = self._edit_target_widgets(key)
        if self._is_edit_instance_key(key):
            for w in widgets:
                w.show()
        elif key == "art":
            self.art.setVisible((not self._empty_state) and self._cover_enabled)
        elif key in ("source", "source_logo"):
            visible = (not self._empty_state
                       and bool(SETTINGS.get("show_source", True)))
            for w in widgets:
                w.setVisible(visible)
        elif key in ("title", "artist", "controls"):
            for w in widgets:
                w.setVisible(not self._empty_state)
        elif key.startswith("ctrl_"):
            self.apply_button_visibility(relayout=True, animate=False)
        elif key.startswith("top_"):
            if key == "top_edit":
                self.apply_edit_button_visible(animate=False)
            elif key == "top_reset":
                self._fade_reset_button(self._edit_mode, animate=False)
            else:
                for w in widgets:
                    w.show()
        elif key in ("seek", "time_now", "time_total"):
            for w in widgets:
                w.setVisible((not self._empty_state) and not self._control_bar)
        elif key.startswith("empty"):
            for w in widgets:
                w.setVisible(self._empty_state)

    def _apply_edit_hidden_visibility(self):
        hidden = self._hidden_edit_key_set()
        for key in self.edit_target_keys():
            if key in hidden:
                if key == "top_edit" and not self._edit_mode:
                    continue
                for widget in self._edit_target_widgets(key):
                    widget.hide()

    def _restore_all_edit_key_visibility(self):
        for key in self.edit_target_keys():
            self._restore_edit_key_visibility(key)

    def _sync_edit_library(self, animate: bool = True):
        if hasattr(self, "_edit_library"):
            self._edit_library.sync(animate=animate)

    def _set_edit_selection(self, key: str | None, additive: bool = False):
        if key is None or key not in self.edit_target_keys():
            if not additive:
                self._edit_selected_keys.clear()
            self._sync_edit_selection_fades()
            self._update_edit_overlay()
            return
        if additive:
            if key in self._edit_selected_keys:
                self._edit_selected_keys.discard(key)
            else:
                self._edit_selected_keys.add(key)
        else:
            self._edit_selected_keys = set() if key in self._edit_selected_keys else {key}
        self._sync_edit_selection_fades()
        self._update_edit_overlay()

    def _active_edit_move_keys(self, key: str) -> tuple[str, ...]:
        if key in self._edit_selected_keys:
            return tuple(k for k in self.edit_target_keys()
                         if k in self._edit_selected_keys)
        return (key,)

    def _nudge_edit_selection(self, dx: float, dy: float):
        keys = tuple(k for k in self.edit_target_keys()
                     if k in self._edit_selected_keys)
        if not keys and self._edit_hover_key is not None:
            keys = (self._edit_hover_key,)
            self._set_edit_selection(self._edit_hover_key, additive=False)
        if not keys:
            return
        scale = max(0.01, float(SETTINGS.get("scale", 1.0)))
        for key in keys:
            ox, oy = self._edit_offset_logic(key)
            self._set_edit_offset_logic(key, ox + dx / scale, oy + dy / scale)
        self._apply_layout_position_offsets()
        self.layout_edit_changed.emit()

    def _handle_edit_key_press(self, event) -> bool:
        if not self._edit_mode:
            return False
        step = 10 if event.modifiers() & Qt.ShiftModifier else 1
        key = event.key()
        if key in (Qt.Key_Delete, Qt.Key_Backspace):
            selected = tuple(k for k in self.edit_target_keys()
                             if k in self._edit_selected_keys)
            self._delete_edit_keys(selected)
        elif key == Qt.Key_Escape:
            self.set_layout_edit_mode(False)
        elif key == Qt.Key_Left:
            self._nudge_edit_selection(-step, 0)
        elif key == Qt.Key_Right:
            self._nudge_edit_selection(step, 0)
        elif key == Qt.Key_Up:
            self._nudge_edit_selection(0, -step)
        elif key == Qt.Key_Down:
            self._nudge_edit_selection(0, step)
        else:
            return False
        event.accept()
        return True

    def _window_resize_edge_at(self, pos: QPointF) -> str:
        if not self._edit_mode:
            return ""
        m = max(S(6), 6)
        x, y = pos.x(), pos.y()
        left = x <= m
        right = x >= self._W - m
        top = y <= m
        bottom = y >= self._H - m
        edge = ""
        if top:
            edge += "t"
        elif bottom:
            edge += "b"
        if left:
            edge += "l"
        elif right:
            edge += "r"
        return edge

    def _window_resize_cursor(self, edge: str):
        if edge in ("l", "r"):
            return Qt.SizeHorCursor
        if edge in ("t", "b"):
            return Qt.SizeVerCursor
        if edge in ("tl", "br"):
            return Qt.SizeFDiagCursor
        if edge in ("tr", "bl"):
            return Qt.SizeBDiagCursor
        return Qt.ArrowCursor

    def _begin_window_resize(self, edge: str, global_pos: QPoint):
        if not edge:
            return
        self._window_resize_drag = {
            "edge": edge,
            "start": QPoint(global_pos),
            "size": self._window_size_logic(),
            "win_pos": QPoint(self.window().pos()),
        }

    def _move_window_resize(self, global_pos: QPoint):
        if not self._window_resize_drag:
            return
        edge = self._window_resize_drag["edge"]
        start = self._window_resize_drag["start"]
        delta = global_pos - start
        scale = max(0.01, float(SETTINGS.get("scale", 1.0)))
        w, h = self._window_resize_drag["size"]
        dw = float(delta.x()) / scale
        dh = float(delta.y()) / scale
        move = QPoint(0, 0)
        if "l" in edge:
            w -= dw
            move.setX(delta.x())
        elif "r" in edge:
            w += dw
        if "t" in edge:
            h -= dh
            move.setY(delta.y())
        elif "b" in edge:
            h += dh
        old_size = self._window_size_px()
        self._set_window_size_logic(w, h)
        self.apply_edit_window_size()
        new_size = self._window_size_px()
        if move != QPoint(0, 0):
            win = self.window()
            base = self._window_resize_drag["win_pos"]
            actual = QPoint(
                move.x() if new_size[0] != old_size[0] else 0,
                move.y() if new_size[1] != old_size[1] else 0,
            )
            win.move(base + actual)

    def _edit_handle_target_key(self) -> str | None:
        active = (self._edit_drag or {}).get("key")
        if active in self.edit_target_keys():
            return active
        if self._edit_hover_key in self.edit_target_keys():
            return self._edit_hover_key
        return None

    def _ensure_edit_handle_anim(self, key: str) -> Anim:
        anim = self._edit_handle_anims.get(key)
        if anim is None:
            anim = Anim(self)
            anim.valueChanged.connect(
                lambda value, k=key: self._on_edit_handle_op(k, value))
            anim.finished.connect(
                lambda k=key: self._edit_handle_anim_done(k))
            self._edit_handle_anims[key] = anim
        return anim

    def _on_edit_handle_op(self, key: str, value):
        op = max(0.0, min(1.0, float(value)))
        self._edit_handle_ops[key] = op
        self._update_edit_overlay()

    def _edit_handle_anim_done(self, key: str):
        if self._edit_handle_targets.get(key, 0.0) <= 0.001:
            self._edit_handle_ops.pop(key, None)
            self._edit_handle_targets.pop(key, None)
        self._update_edit_overlay()

    def _fade_edit_handle(self, key: str, target: float,
                          animate: bool = True):
        target = 1.0 if target > 0.5 else 0.0
        if self._edit_handle_targets.get(key) == target:
            return
        self._edit_handle_targets[key] = target
        anim = self._ensure_edit_handle_anim(key)
        anim.stop()
        start = max(0.0, min(1.0, self._edit_handle_ops.get(key, 0.0)))
        ms = adur(120 if target > start else 150, 80)
        if (not animate or not anim_on() or ms <= 0 or not self.isVisible()):
            self._on_edit_handle_op(key, target)
            self._edit_handle_anim_done(key)
            return
        anim.setStartValue(start)
        anim.setEndValue(target)
        anim.setDuration(ms)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.start()

    def _sync_edit_handle_fades(self, animate: bool = True):
        target = self._edit_handle_target_key()
        keys = set(self.edit_target_keys())
        keys.update(self._edit_handle_ops)
        keys.update(self._edit_handle_targets)
        for key in keys:
            self._fade_edit_handle(
                key, 1.0 if key == target else 0.0, animate)

    def _update_edit_hover_from_global(self, global_pos: QPoint | None = None):
        if not self._edit_mode or self._edit_drag is not None:
            return
        if global_pos is None:
            global_pos = QCursor.pos()
        pos = QPointF(self.mapFromGlobal(global_pos))
        if not self.rect().contains(pos.toPoint()):
            self._set_edit_hover_key(None)
            return
        self._set_edit_hover_key(self._target_key_at(pos))

    def _install_edit_target_filters(self):
        mapping = {
            self.art: "art",
            self.source_logo: "source_logo",
            self.source: "source",
            self.title: "title",
            self.artist: "artist",
            self.controls: "controls",
            self.btn_shuffle: "ctrl_shuffle",
            self.btn_prev: "ctrl_prev",
            self.btn_play: "ctrl_play",
            self.btn_next: "ctrl_next",
            self.btn_repeat: "ctrl_repeat",
            self.btn_edit: "top_edit",
            self.btn_reset_layout: "top_reset",
            self.btn_vol: "top_volume",
            self.btn_settings: "top_settings",
            self.btn_pin: "top_pin",
            self.btn_close: "top_close",
            self.seek: "seek",
            self.t_now: "time_now",
            self.t_total: "time_total",
            self.empty_icon: "empty_icon",
            self.empty_text: "empty_text",
            self.empty_btn: "empty_button",
        }
        self._edit_filter_targets.clear()
        for widget, key in mapping.items():
            widget.setMouseTracking(True)
            widget.installEventFilter(self)
            self._edit_filter_targets[widget] = key

    def _set_edit_cursors(self):
        for widget in self._edit_filter_targets:
            if self._edit_mode:
                widget.setCursor(Qt.SizeAllCursor)
            elif widget in (self.art, self.title, self.artist):
                widget.setCursor(Qt.PointingHandCursor)
            else:
                widget.unsetCursor()

    def _update_edit_overlay(self):
        if not hasattr(self, "_edit_overlay"):
            return
        self._edit_overlay.setGeometry(0, 0, self._W, self._H)
        if self._edit_overlay_op > 0.001:
            self._edit_overlay.raise_()
            self._edit_overlay.update()

    def edit_overlay_opacity(self) -> float:
        return self._edit_overlay_op

    def _on_edit_overlay_op(self, value):
        self._edit_overlay_op = max(0.0, min(1.0, float(value)))
        if self._edit_overlay_op > 0.001:
            self._edit_overlay.show()
            self._edit_overlay.raise_()
        self._edit_overlay.update()

    def _edit_overlay_done(self):
        if self._edit_overlay_target <= 0.001:
            self._edit_overlay.hide()
        else:
            self._edit_overlay.show()
            self._edit_overlay.raise_()
        self._edit_overlay.update()

    def _fade_edit_overlay(self, visible: bool, animate: bool = True):
        target = 1.0 if visible else 0.0
        self._edit_overlay_target = target
        self._edit_overlay_anim.stop()
        if visible or self._edit_overlay_op > 0.001:
            self._edit_overlay.show()
            self._edit_overlay.raise_()
        ms = adur(180 if visible else 150, 100)
        if (not animate or not anim_on() or ms <= 0 or not self.isVisible()):
            self._on_edit_overlay_op(target)
            self._edit_overlay_done()
            return
        self._edit_overlay_anim.setStartValue(self._edit_overlay_op)
        self._edit_overlay_anim.setEndValue(target)
        self._edit_overlay_anim.setDuration(ms)
        self._edit_overlay_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._edit_overlay_anim.start()

    def _on_reset_button_op(self, value):
        self._reset_button_op = max(0.0, min(1.0, float(value)))
        if self._reset_button_op > 0.001:
            self.btn_reset_layout.show()
        self.btn_reset_layout.set_extra_opacity(self._reset_button_op)
        self.btn_reset_layout.setAttribute(
            Qt.WA_TransparentForMouseEvents,
            self._reset_button_op <= 0.02)
        self._apply_edit_hidden_visibility()
        self.update()

    def _reset_button_done(self):
        if self._reset_button_target <= 0.001:
            self.btn_reset_layout.hide()
            self.btn_reset_layout.setAttribute(
                Qt.WA_TransparentForMouseEvents, True)
        else:
            self.btn_reset_layout.show()
            self.btn_reset_layout.setAttribute(
                Qt.WA_TransparentForMouseEvents, False)
        self.update()

    def _fade_reset_button(self, visible: bool, animate: bool = True):
        target = 1.0 if visible else 0.0
        self._reset_button_target = target
        self._reset_button_anim.stop()
        if visible or self._reset_button_op > 0.001:
            self.btn_reset_layout.show()
            self.btn_reset_layout.raise_()
        ms = adur(180 if visible else 150, 100)
        if (not animate or not anim_on() or ms <= 0 or not self.isVisible()):
            self._on_reset_button_op(target)
            self._reset_button_done()
            return
        self._reset_button_anim.setStartValue(self._reset_button_op)
        self._reset_button_anim.setEndValue(target)
        self._reset_button_anim.setDuration(ms)
        self._reset_button_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._reset_button_anim.start()

    def set_layout_edit_mode(self, enabled: bool):
        enabled = bool(enabled)
        if enabled == self._edit_mode:
            return
        self._edit_mode = enabled
        self._edit_drag = None
        self._fade_reset_button(enabled, animate=True)
        if self.btn_edit.isChecked() != enabled:
            self.btn_edit.setChecked(enabled)
        self._set_edit_cursors()
        if enabled:
            self.setFocus(Qt.MouseFocusReason)
            self._sync_controls_hover(True, animate=False)
            self._sync_topbar_hover(True, animate=False)
            self._fade_edit_overlay(True, animate=True)
            self._update_edit_hover_from_global()
            self._apply_edit_hidden_visibility()
            self._sync_edit_library()
            self._update_edit_overlay()
        else:
            self._set_edit_hover_key(None)
            self._sync_edit_handle_fades()
            self._fade_edit_overlay(False, animate=True)
            self._sync_controls_hover(self.underMouse(), animate=True)
            self._sync_topbar_hover(self.underMouse(), animate=True)
            self._restore_edit_key_visibility("top_edit")
            self._apply_edit_hidden_visibility()
            self._sync_edit_library()
        self._sync_edit_instance_element_states()

    def _apply_empty_layout_positions(self):
        if not hasattr(self, "empty_icon"):
            return
        W = self._W
        self.empty_icon.setGeometry(*self._offset_geometry(
            "empty_icon", (0, S(14 if self._compact else 22), W, S(36))))
        self.empty_text.setGeometry(*self._offset_geometry(
            "empty_text", (0, S(50 if self._compact else 62), W, S(18))))
        base_w, base_h = getattr(
            self, "_empty_btn_base_size",
            (self.empty_btn.width(), self.empty_btn.height()))
        base = ((W - base_w) // 2,
                S(74 if self._compact else 92) - self.empty_btn.pad,
                base_w, base_h)
        x, y, bw, bh = self._offset_geometry("empty_button", base)
        self.empty_btn.setFixedSize(bw, bh)
        self.empty_btn.move(x, y)

    def _apply_layout_position_offsets(self):
        if hasattr(self, "art"):
            self._set_art_scales_for_layout(
                self._cover_scale_setting(), self._vinyl_scale_setting())
        self._apply_topbar_edit_layout()
        self._apply_cover_layout(self._cover_layout_data(self._cover_enabled))
        self.apply_control_button_layout(animate=False)
        self.apply_seek_length()
        self.apply_progress_time_spacing()
        self._apply_empty_layout_positions()
        self._apply_edit_instance_layouts()
        self._apply_edit_angles()
        self._update_edit_overlay()

    def apply_edit_window_size(self):
        new_w, new_h = self._window_size_px()
        if new_w == self._W and new_h == self._H:
            return
        self._W, self._H = new_w, new_h
        self.setFixedSize(self._W, self._H)
        for layer in (getattr(self, "rain", None),
                      getattr(self, "lightning", None),
                      getattr(self, "seek_hover", None),
                      getattr(self, "_ctrl_overlay", None),
                      getattr(self, "_edit_overlay", None)):
            if layer is not None:
                layer.setGeometry(0, 0, self._W, self._H)
        self.invalidate_bg()
        self._apply_layout_position_offsets()
        self._sync_edit_library(animate=False)
        win = self.window()
        if hasattr(win, "_sync_size_to_card"):
            win._sync_size_to_card()
        self.update()

    def _current_layout_position_snapshot(self) -> dict[str, tuple[float, float]]:
        snap = {}
        for key, value in self._layout_positions().items():
            if not isinstance(value, dict):
                continue
            try:
                x = float(value.get("x", 0.0))
                y = float(value.get("y", 0.0))
            except (TypeError, ValueError):
                continue
            if abs(x) >= 0.01 or abs(y) >= 0.01:
                snap[key] = (x, y)
        return snap

    def _current_layout_size_snapshot(self) -> dict[str, tuple[float, float]]:
        snap = {}
        for key, value in self._layout_sizes().items():
            if not isinstance(value, dict):
                continue
            try:
                w = float(value.get("w", 0.0))
                h = float(value.get("h", 0.0))
            except (TypeError, ValueError):
                continue
            if abs(w) >= 0.01 or abs(h) >= 0.01:
                snap[key] = (w, h)
        return snap

    def _current_layout_angle_snapshot(self) -> dict[str, float]:
        snap = {}
        for key, value in self._layout_angles().items():
            try:
                angle = self._normalize_edit_angle(float(value))
            except (TypeError, ValueError):
                continue
            if abs(angle) >= 0.01:
                snap[key] = angle
        return snap

    def _clear_edit_layout_settings(self):
        SETTINGS["edit_layout_positions"] = {}
        SETTINGS["edit_layout_sizes"] = {}
        SETTINGS["edit_layout_angles"] = {}
        SETTINGS["edit_window_size"] = {}
        SETTINGS["edit_hidden_keys"] = []
        SETTINGS["edit_library_pos"] = {}
        SETTINGS["edit_library_collapsed"] = False
        SETTINGS["edit_library_instances"] = []
        for key, widget in list(self._edit_instance_widgets.items()):
            self._edit_filter_targets.pop(widget, None)
            widget.hide()
            widget.deleteLater()
            self._edit_selected_keys.discard(key)
        self._edit_instance_widgets.clear()
        self._sync_edit_selection_fades()

    def reset_layout_positions(self, animate: bool = True):
        start = self._current_layout_position_snapshot()
        size_start = self._current_layout_size_snapshot()
        angle_start = self._current_layout_angle_snapshot()
        win_start = self._window_size_logic()
        has_win = abs(win_start[0]) >= 0.01 or abs(win_start[1]) >= 0.01
        hidden_start = tuple(self.hidden_edit_keys())
        self._edit_drag = None
        self._window_resize_drag = None
        if self._edit_reset_anim.state() == Anim.Running:
            self._edit_reset_abort = True
            self._edit_reset_anim.stop()
            self._edit_reset_abort = False
        if not start and not size_start and not angle_start and not has_win:
            self._clear_edit_layout_settings()
            self._apply_layout_position_offsets()
            if hidden_start:
                self._fade_edit_keys_in(hidden_start, animate=animate)
            else:
                self._restore_all_edit_key_visibility()
            self._apply_edit_hidden_visibility()
            self._sync_edit_library()
            self.layout_edit_changed.emit()
            return
        self._edit_reset_from = start
        self._edit_reset_size_from = size_start
        self._edit_reset_angle_from = angle_start
        self._edit_reset_window_from = win_start
        self._edit_reset_hidden_keys = hidden_start
        ms = adur(280, 160)
        if (not animate or not anim_on() or ms <= 0 or not self.isVisible()):
            self._clear_edit_layout_settings()
            self.apply_edit_window_size()
            self._apply_layout_position_offsets()
            if hidden_start:
                self._fade_edit_keys_in(hidden_start, animate=False)
            else:
                self._restore_all_edit_key_visibility()
            self._apply_edit_hidden_visibility()
            self._sync_edit_library()
            self.layout_edit_changed.emit()
            return
        self._edit_reset_anim.setStartValue(0.0)
        self._edit_reset_anim.setEndValue(1.0)
        self._edit_reset_anim.setDuration(ms)
        self._edit_reset_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._edit_reset_anim.start()

    def _on_layout_reset(self, value):
        t = max(0.0, min(1.0, float(value)))
        self._clear_edit_layout_settings()
        self._restore_all_edit_key_visibility()
        if self._edit_reset_hidden_keys:
            self._hide_edit_keys_without_setting(self._edit_reset_hidden_keys)
        remain = 1.0 - t
        for key, (x, y) in self._edit_reset_from.items():
            self._set_edit_offset_logic(key, x * remain, y * remain)
        for key, (w, h) in self._edit_reset_size_from.items():
            self._set_edit_size_logic(key, w * remain, h * remain)
        for key, angle in self._edit_reset_angle_from.items():
            self._set_edit_angle_logic(key, angle * remain)
        ww, wh = self._edit_reset_window_from
        self._set_window_size_logic(ww * remain, wh * remain)
        self.apply_edit_window_size()
        self._apply_layout_position_offsets()

    def _layout_reset_done(self):
        if self._edit_reset_abort:
            return
        self._clear_edit_layout_settings()
        hidden = self._edit_reset_hidden_keys
        self._edit_reset_from = {}
        self._edit_reset_size_from = {}
        self._edit_reset_angle_from = {}
        self._edit_reset_window_from = (0.0, 0.0)
        self._edit_reset_hidden_keys = ()
        self.apply_edit_window_size()
        self._apply_layout_position_offsets()
        self._refresh_art_pixmap()
        if hidden:
            self._fade_edit_keys_in(hidden, animate=True)
        else:
            self._restore_all_edit_key_visibility()
        self.layout_edit_changed.emit()

    def _begin_edit_drag(self, key: str, global_pos: QPoint,
                         additive: bool = False):
        if self._edit_reset_anim.state() == Anim.Running:
            self._edit_reset_abort = True
            self._edit_reset_anim.stop()
            self._edit_reset_abort = False
        was_selected = key in self._edit_selected_keys
        if additive:
            self._set_edit_selection(key, additive=True)
        elif key not in self._edit_selected_keys:
            self._set_edit_selection(key, additive=False)
        keys = self._active_edit_move_keys(key)
        scale = max(0.01, float(SETTINGS.get("scale", 1.0)))
        self._edit_drag = {
            "mode": "move",
            "key": key,
            "keys": keys,
            "start": QPoint(global_pos),
            "moved": False,
            "was_selected": was_selected,
            "offsets": {k: self._edit_offset_logic(k) for k in keys},
            "scale": scale,
            "geometries": {
                widget: QRectF(widget.geometry())
                for k in keys
                for widget in self._edit_target_widgets(k)
            },
        }
        self._sync_edit_handle_fades()

    def _begin_edit_resize(self, key: str, global_pos: QPoint):
        if key not in self._resizable_edit_keys():
            self._edit_drag = None
            return
        if self._edit_reset_anim.state() == Anim.Running:
            self._edit_reset_abort = True
            self._edit_reset_anim.stop()
            self._edit_reset_abort = False
        scale = max(0.01, float(SETTINGS.get("scale", 1.0)))
        sw, sh = self._edit_size_logic(key)
        rect = self.edit_target_rect(key)
        if not rect.isValid():
            return
        self._set_edit_selection(key, additive=False)
        self._edit_drag = {
            "mode": "resize",
            "key": key,
            "start": QPoint(global_pos),
            "size": (sw, sh),
            "scale": scale,
            "rect": QRectF(rect),
            "art_delta": self._edit_size_logic("art"),
            "source_rect": self._unoffset_rect(
                "source", QRectF(self.source.geometry()))
                if key in ("source", "source_logo") else QRectF(),
            "logo_rect": self._unoffset_rect(
                "source_logo", QRectF(self.source_logo.geometry()))
                if key in ("source", "source_logo") else QRectF(),
        }
        self._sync_edit_handle_fades()

    def _begin_edit_rotate(self, key: str, global_pos: QPoint):
        if key not in self.edit_target_keys():
            self._edit_drag = None
            return
        if self._edit_reset_anim.state() == Anim.Running:
            self._edit_reset_abort = True
            self._edit_reset_anim.stop()
            self._edit_reset_abort = False
        rect = self.edit_target_rect(key)
        if not rect.isValid():
            return
        center = self.mapToGlobal(rect.center().toPoint())
        dx = global_pos.x() - center.x()
        dy = global_pos.y() - center.y()
        start_vec = math.degrees(math.atan2(dy, dx))
        self._set_edit_selection(key, additive=False)
        self._edit_drag = {
            "mode": "rotate",
            "key": key,
            "start": QPoint(global_pos),
            "center": QPoint(center),
            "vec": start_vec,
            "angle": self._edit_angle_logic(key),
            "moved": False,
        }
        self._sync_edit_handle_fades()

    def _move_edit_drag(self, global_pos: QPoint):
        if not self._edit_drag:
            return
        if self._edit_drag.get("mode") == "resize":
            self._move_edit_resize(global_pos)
            return
        if self._edit_drag.get("mode") == "rotate":
            self._move_edit_rotate(global_pos)
            return
        start = self._edit_drag["start"]
        delta = global_pos - start
        if abs(delta.x()) + abs(delta.y()) > S(3):
            self._edit_drag["moved"] = True
        scale = float(self._edit_drag["scale"])
        keys = self._edit_drag.get("keys") or (self._edit_drag["key"],)
        for key in keys:
            ox, oy = self._edit_drag["offsets"].get(
                key, self._edit_offset_logic(key))
            self._set_edit_offset_logic(
                key, ox + delta.x() / scale, oy + delta.y() / scale)
        for widget, rect in self._edit_drag["geometries"].items():
            widget.setGeometry(round(rect.x() + delta.x()),
                               round(rect.y() + delta.y()),
                               round(rect.width()), round(rect.height()))
        if "controls" in keys:
            self._ctrl_pos = QPointF(self.controls.pos())
            self._ctrl_to = QPointF(self.controls.pos())
        if any(str(k).startswith("ctrl_") for k in keys):
            self.apply_control_button_layout(animate=False)
        self._update_edit_overlay()

    def _move_edit_resize(self, global_pos: QPoint):
        if not self._edit_drag:
            return
        key = self._edit_drag["key"]
        start = self._edit_drag["start"]
        delta = global_pos - start
        scale = float(self._edit_drag["scale"])
        rect = self._edit_drag["rect"]
        min_w, min_h = self._min_edit_size(key)
        dx = max(min_w - rect.width(), float(delta.x()))
        dy = max(min_h - rect.height(), float(delta.y()))
        sw, sh = self._edit_drag["size"]
        if key == "art":
            # Keep the cover resize square and let ArtView recompute its own pad.
            d = max(dx, dy)
            aw, ah = self._edit_drag["art_delta"]
            logical = d / scale
            self._set_edit_size_logic("art", aw + logical, ah + logical)
            self.apply_art_size_layout(animate=False, refresh_pixmap=False)
        elif key in ("source", "source_logo"):
            d = max(dx, dy)
            self._set_edit_size_logic(
                key, sw + d / scale, sh + d / scale)
            self._apply_source_layout(
                self._edit_drag["source_rect"],
                self._edit_drag["logo_rect"])
        else:
            self._set_edit_size_logic(
                key, sw + dx / scale, sh + dy / scale)
            if key == "controls":
                self.apply_control_button_layout(animate=False)
            elif key.startswith("ctrl_"):
                self.apply_control_button_layout(animate=False)
            elif key.startswith("top_"):
                self._apply_topbar_edit_layout()
            elif key in ("title", "artist"):
                self._apply_cover_layout(
                    self._cover_layout_data(self._cover_enabled))
            elif key == "seek":
                self.apply_seek_length()
            elif key in ("time_now", "time_total"):
                self.apply_progress_time_spacing()
            elif key.startswith("empty"):
                self._apply_empty_layout_positions()
                self._update_edit_overlay()
            elif self._is_edit_instance_key(key):
                self._apply_edit_instance_layout(key)
        self._update_edit_overlay()

    def _move_edit_rotate(self, global_pos: QPoint):
        if not self._edit_drag:
            return
        key = self._edit_drag["key"]
        center = self._edit_drag["center"]
        dx = global_pos.x() - center.x()
        dy = global_pos.y() - center.y()
        if abs(dx) + abs(dy) <= 1:
            return
        cur_vec = math.degrees(math.atan2(dy, dx))
        delta = self._normalize_edit_angle(cur_vec - self._edit_drag["vec"])
        if abs(delta) > 1.0:
            self._edit_drag["moved"] = True
        angle = self._edit_drag["angle"] + delta
        self._set_edit_angle_logic(key, angle)
        if key == "controls":
            self.apply_control_button_layout(animate=False)
        else:
            self._apply_edit_angle(key)
        self._update_edit_overlay()

    def eventFilter(self, obj, event):
        if self._edit_mode and obj in self._edit_filter_targets:
            et = event.type()
            if et == QEvent.KeyPress and self._handle_edit_key_press(event):
                return True
            if et == QEvent.MouseButtonPress and event.button() == Qt.RightButton:
                key = self._edit_filter_targets[obj]
                self._set_edit_selection(key, additive=False)
                event.accept()
                return True
            if et == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
                pos = self.mapFromGlobal(event.globalPosition().toPoint())
                rotate_key = self._rotate_key_at(QPointF(pos))
                resize_key = self._resize_key_at(QPointF(pos))
                if rotate_key is not None:
                    self._begin_edit_rotate(
                        rotate_key, event.globalPosition().toPoint())
                elif resize_key is not None:
                    self._begin_edit_resize(
                        resize_key, event.globalPosition().toPoint())
                else:
                    self._begin_edit_drag(
                        self._edit_filter_targets[obj],
                        event.globalPosition().toPoint(),
                        bool(event.modifiers() & Qt.ShiftModifier))
                event.accept()
                return True
            if et == QEvent.MouseMove and self._edit_drag is not None:
                if event.buttons() & Qt.LeftButton:
                    self._move_edit_drag(event.globalPosition().toPoint())
                    event.accept()
                    return True
            if et == QEvent.MouseMove and self._edit_drag is None:
                gpos = event.globalPosition().toPoint()
                pos = QPointF(self.mapFromGlobal(gpos))
                self._update_edit_hover_from_global(gpos)
                if self._rotate_key_at(pos) is not None:
                    obj.setCursor(Qt.CrossCursor)
                elif self._resize_key_at(pos) is not None:
                    obj.setCursor(Qt.SizeFDiagCursor)
                else:
                    obj.setCursor(Qt.SizeAllCursor)
            if et == QEvent.Enter and self._edit_drag is None:
                self._update_edit_hover_from_global(QCursor.pos())
            if et == QEvent.Leave and self._edit_drag is None:
                self._update_edit_hover_from_global(QCursor.pos())
            if et == QEvent.MouseButtonRelease and self._edit_drag is not None:
                if event.button() == Qt.LeftButton:
                    drag_key = self._edit_drag.get("key")
                    moved = bool(self._edit_drag.get("moved"))
                    mode = self._edit_drag.get("mode")
                    was_selected = bool(self._edit_drag.get("was_selected"))
                    self._move_edit_drag(event.globalPosition().toPoint())
                    if self._edit_drag.get("mode") == "resize":
                        key = self._edit_drag.get("key")
                        if key == "art":
                            self.apply_art_size_layout(
                                animate=False, refresh_pixmap=True)
                            self._refresh_art_pixmap()
                    self._edit_drag = None
                    self._sync_edit_handle_fades()
                    self.layout_edit_changed.emit()
                    if mode == "move" and not moved:
                        source_key = self._edit_instance_source(drag_key)
                        action_key = source_key or drag_key
                        if action_key in ("top_edit", "top_reset"):
                            if was_selected:
                                if action_key == "top_edit":
                                    self.set_layout_edit_mode(False)
                                else:
                                    self.reset_layout_positions()
                        elif was_selected:
                            self._set_edit_selection(drag_key, additive=False)
                    event.accept()
                    return True
        return super().eventFilter(obj, event)

    def apply_text_layout(self):
        if hasattr(self, "title") and hasattr(self, "artist"):
            self._apply_cover_layout(self._cover_layout_data(self._cover_enabled))
            self.update()

    def apply_control_button_layout(self, animate: bool = True):
        if not hasattr(self, "btn_play"):
            return
        small_px, small_d = self._control_metric(12, 24)
        nav_px, nav_d = self._control_metric(14, 28)
        play_d = max(1, S(36 * self._control_button_scale()))
        for key, (btn, glyph_base, diam_base, is_play) in (
                self._control_edit_specs.items()):
            ind = self._button_edit_scale(key)
            if is_play:
                btn.set_diameter(max(1, round(play_d * ind)))
            elif diam_base == 24:
                btn.set_metrics(max(1, round(small_px * ind)),
                                max(1, round(small_d * ind)))
            else:
                btn.set_metrics(max(1, round(nav_px * ind)),
                                max(1, round(nav_d * ind)))
        self.relayout_controls(animate=animate)
        self.update()

    def _apply_topbar_edit_layout(self):
        if not hasattr(self, "_topbar_edit_specs"):
            return
        self.btn_edit.move(self._W - S(128), S(10))
        self.btn_reset_layout.move(self._W - S(152), S(10))
        base_geos = {
            "top_edit": QRectF(self._W - S(128), S(10), S(22), S(22)),
            "top_reset": QRectF(self._W - S(152), S(10), S(22), S(22)),
            "top_volume": QRectF(self._W - S(104), S(10), S(22), S(22)),
            "top_settings": QRectF(self._W - S(80), S(10), S(22), S(22)),
            "top_pin": QRectF(self._W - S(56), S(10), S(22), S(22)),
            "top_close": QRectF(self._W - S(32), S(10), S(22), S(22)),
        }
        for key, (btn, glyph_base, diam_base) in self._topbar_edit_specs.items():
            scale = self._button_edit_scale(key, 34.0)
            glyph_px = max(1, S(glyph_base * scale))
            diam = max(1, S(diam_base * scale))
            btn.set_metrics(glyph_px, diam)
            base = base_geos.get(key)
            if base is None:
                continue
            off = self._edit_offset_px(key)
            btn.move(round(base.x() + off.x()), round(base.y() + off.y()))

    def _on_cover_layout(self, v):
        if self._layout_from is None or self._layout_to is None:
            return
        t = max(0.0, min(1.0, float(v)))
        self._apply_cover_layout(
            self._lerp_layout_data(self._layout_from, self._layout_to, t))

    def _cover_layout_done(self):
        if self._layout_to is not None:
            self._apply_cover_layout(self._layout_to)
        if not self._cover_enabled:
            self.art.hide()
        elif not self._empty_state:
            self.art.show()
        self._layout_from = None
        self._layout_to = None

    def set_cover_enabled(self, enabled: bool, animate: bool = True):
        enabled = bool(enabled) and self._preset != "mini"
        if enabled == self._cover_enabled and self._layout_anim.state() != Anim.Running:
            return
        self._layout_anim.stop()
        self._cover_enabled = enabled
        if self._ctrl_overlay is not None:
            self._ctrl_overlay.hide()
        self._ctrl_suppress_done = True
        self._ctrl_anim.stop()
        self._ctrl_suppress_done = False
        if enabled and not self._empty_state:
            self.art.show()
        self._layout_from = self._current_layout_data()
        self._layout_to = self._cover_layout_data(enabled)
        ms = adur(300, 170)
        if (not animate or not anim_on() or ms <= 0 or not self.isVisible()
                or self._empty_state):
            self._apply_cover_layout(self._layout_to)
            self._cover_layout_done()
            return
        self._layout_anim.setStartValue(0.0)
        self._layout_anim.setEndValue(1.0)
        self._layout_anim.setDuration(ms)
        self._layout_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._layout_anim.start()

    def _on_ctrl_move(self, v):
        t = max(0.0, min(1.0, float(v)))
        p0, p1 = self._ctrl_from, self._ctrl_to
        self._ctrl_pos = QPointF(
            p0.x() + (p1.x() - p0.x()) * t,
            p0.y() + (p1.y() - p0.y()) * t)
        self.controls.move(round(self._ctrl_pos.x()),
                           round(self._ctrl_pos.y()))
        for btn, (b0, b1) in self._ctrl_items.items():
            btn.move(round(b0.x() + (b1.x() - b0.x()) * t),
                     round(b0.y() + (b1.y() - b0.y()) * t))
        for btn in self._ctrl_fade_in:
            self._on_button_op(btn, t)

    def _ctrl_done(self):
        if self._ctrl_suppress_done:
            return
        target = self._ctrl_to
        if self._ctrl_final_size[0] > 0 and self._ctrl_final_size[1] > 0:
            self.controls.setFixedSize(*self._ctrl_final_size)
        self.controls.move(round(target.x()), round(target.y()))
        self._ctrl_pos = QPointF(target)
        for btn, (_, b1) in self._ctrl_items.items():
            btn.move(round(b1.x()), round(b1.y()))
        self._ctrl_items.clear()
        for btn in list(self._ctrl_fade_in):
            self._on_button_op(btn, 1.0)
            btn.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        self._ctrl_fade_in.clear()
        self.controls.setVisible(not self._empty_state)

    def relayout_controls(self, animate: bool = False,
                          fade_in_buttons=None):
        """控制列按鈕排列（依 controls_align 設定靠左/置中/靠右）。"""
        fade_in_buttons = set(fade_in_buttons or [])
        if self._ctrl_anim.state() == Anim.Running:
            self._ctrl_suppress_done = True
            self._ctrl_anim.stop()
            self._ctrl_suppress_done = False

        old_pos = QPointF(self.controls.pos())
        old_size = (self.controls.width(), self.controls.height())
        old_visible = [b for b in self._ctrls
                       if not b.isHidden() and b not in fade_in_buttons]
        old_rel = {b: QPointF(b.pos()) for b in old_visible}
        old_abs = {
            b: QPointF(old_pos.x() + old_rel[b].x(),
                       old_pos.y() + old_rel[b].y())
            for b in old_visible
        }
        self._layout_control_rail()
        target = self._control_position()
        final_size = (self.controls.width(), self.controls.height())

        new_visible = [b for b in self._ctrls if not b.isHidden()]
        new_rel = {b: QPointF(b.pos()) for b in new_visible}
        new_abs = {
            b: QPointF(target.x() + new_rel[b].x(),
                       target.y() + new_rel[b].y())
            for b in new_visible
        }
        moved = any(
            b not in old_abs
            or abs(old_abs[b].x() - new_abs[b].x()) > 0.5
            or abs(old_abs[b].y() - new_abs[b].y()) > 0.5
            for b in new_visible
        )

        if (animate and anim_on() and self.isVisible()
                and not self._empty_state
                and (moved or fade_in_buttons)):
            self._ctrl_items = {}
            for btn in new_visible:
                self._ctrl_items[btn] = (old_rel.get(btn, new_rel[btn]),
                                         new_rel[btn])
            self._ctrl_fade_in = set(fade_in_buttons)
            for btn in self._ctrl_fade_in:
                self._on_button_op(btn, 0.0)
                btn.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            self._ctrl_from = QPointF(old_pos)
            self._ctrl_to = QPointF(target)
            self._ctrl_pos = QPointF(old_pos)
            self._ctrl_final_size = final_size
            self.controls.setFixedSize(max(old_size[0], final_size[0]),
                                       max(old_size[1], final_size[1]))
            self.controls.move(round(old_pos.x()), round(old_pos.y()))
            for btn, (p0, _) in self._ctrl_items.items():
                btn.move(round(p0.x()), round(p0.y()))
            self.controls.show()
            if self._ctrl_overlay is not None:
                self._ctrl_overlay.hide()
            self._ctrl_anim.setStartValue(0.0)
            self._ctrl_anim.setEndValue(1.0)
            self._ctrl_anim.setDuration(adur(280, 170))
            self._ctrl_anim.setEasingCurve(QEasingCurve.OutCubic)
            self._ctrl_anim.start()
            return
        self._ctrl_suppress_done = True
        self._ctrl_anim.stop()
        self._ctrl_suppress_done = False
        for btn in fade_in_buttons:
            self._on_button_op(btn, 1.0)
            btn.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        self._ctrl_items.clear()
        self._ctrl_fade_in.clear()
        self._ctrl_final_size = final_size
        self._ctrl_to = QPointF(target)
        self._ctrl_pos = QPointF(target)
        if self._ctrl_overlay is not None:
            self._ctrl_overlay.hide()
        self.controls.move(round(target.x()), round(target.y()))
        self.controls.setVisible(not self._empty_state)
        self._sync_controls_hover(animate=False)

    def _on_controls_op(self, v):
        self._controls_op = max(0.0, min(1.0, float(v)))
        if (self._controls_eff is None
                or self.controls.graphicsEffect() is not self._controls_eff):
            self._controls_eff = QGraphicsOpacityEffect(self.controls)
            self.controls.setGraphicsEffect(self._controls_eff)
        self._controls_eff.setOpacity(self._controls_op)
        self.controls.setAttribute(
            Qt.WA_TransparentForMouseEvents,
            self._controls_op <= 0.02)
        self.update()

    def _on_topbar_op(self, v):
        self._topbar_op = max(0.0, min(1.0, float(v)))
        for eff in self._topbar_effects:
            eff.setOpacity(self._topbar_op)
        block = self._topbar_op <= 0.02
        for b in self._topbar_buttons:
            b.setAttribute(Qt.WA_TransparentForMouseEvents, block)
        self.update()

    def _sync_topbar_hover(self, hover: bool | None = None,
                           animate: bool = True):
        if hover is not None:
            self._topbar_hover = bool(hover)
        target = 1.0
        if (not self._edit_mode and SETTINGS.get("topbar_hover", False)
                and not self._topbar_hover):
            target = 0.0
        self._topbar_oa.stop()
        ms = adur(160 if target > self._topbar_op else 200, 100)
        if not animate or not anim_on() or ms <= 0 or not self.isVisible():
            self._on_topbar_op(target)
            return
        self._topbar_oa.setStartValue(self._topbar_op)
        self._topbar_oa.setEndValue(target)
        self._topbar_oa.setDuration(ms)
        self._topbar_oa.setEasingCurve(QEasingCurve.OutCubic)
        self._topbar_oa.start()

    def _on_info_focus(self, v):
        self._info_focus = max(0.0, min(1.0, float(v)))

        def lerp_rect(a, b):
            t = self._info_focus
            return QRectF(a.x() + (b.x() - a.x()) * t,
                          a.y() + (b.y() - a.y()) * t,
                          a.width() + (b.width() - a.width()) * t,
                          a.height() + (b.height() - a.height()) * t)

        tr = lerp_rect(QRectF(self._title_base), self._title_focus)
        ar = lerp_rect(QRectF(self._artist_base), self._artist_focus)
        self.title.set_visual_frame(
            y=tr.y() - self._title_canvas.y(), height=tr.height(),
            scale=1.0 + (self._title_scale_focus - 1.0) * self._info_focus)
        self.artist.set_visual_frame(
            y=ar.y() - self._artist_canvas.y(), height=ar.height(),
            scale=1.0 + (self._artist_scale_focus - 1.0) * self._info_focus)

    def _animate_info_focus(self, target: float, animate: bool = True):
        self._info_anim.stop()
        ms = adur(320, 190)
        if not animate or not anim_on() or ms <= 0 or not self.isVisible():
            self._on_info_focus(target)
            return
        self._info_anim.setStartValue(self._info_focus)
        self._info_anim.setEndValue(target)
        self._info_anim.setDuration(ms)
        self._info_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._info_anim.start()

    def _start_info_focus(self):
        if (not self._empty_state and SETTINGS.get("controls_hover", False)
                and not self._controls_hover):
            self._animate_info_focus(1.0, animate=True)

    def _sync_info_focus(self, animate: bool = True):
        target = 1.0 if (not self._empty_state
                         and SETTINGS.get("controls_hover", False)
                         and not self._controls_hover) else 0.0
        if target > 0.5 and animate and anim_on() and self.isVisible():
            self._info_focus_timer.start()
            return
        self._info_focus_timer.stop()
        self._animate_info_focus(target, animate=animate)

    def _sync_controls_hover(self, hover: bool | None = None,
                             animate: bool = True):
        if hover is not None:
            self._controls_hover = bool(hover)
        if self._empty_state:
            target = 0.0
        elif self._edit_mode:
            target = 1.0
        elif SETTINGS.get("controls_hover", False):
            target = 1.0 if self._controls_hover else 0.0
        else:
            target = 1.0
        self._sync_info_focus(animate=animate)
        replay_play_hover = (target > self._controls_op + 0.01
                             and SETTINGS.get("controls_hover", False)
                             and animate and anim_on())
        self.controls.setVisible(not self._empty_state)
        if replay_play_hover and hasattr(self.btn_play, "replay_hover_animation"):
            self.btn_play.replay_hover_animation()
        self._controls_oa.stop()
        ms = adur(170 if target > self._controls_op else 210, 100)
        if not animate or not anim_on() or ms <= 0 or not self.isVisible():
            self._on_controls_op(target)
            return
        self._controls_oa.setStartValue(self._controls_op)
        self._controls_oa.setEndValue(target)
        self._controls_oa.setDuration(ms)
        self._controls_oa.setEasingCurve(QEasingCurve.OutCubic)
        self._controls_oa.start()

    def apply_button_visibility(self, relayout: bool = False,
                                animate: bool = True):
        self.btn_play.setVisible(True)
        needs_relayout = False
        fade_in = []
        for btn, key in self._button_keys.items():
            target = bool(SETTINGS.get(key, True))
            action = self._set_control_button_visible(btn, target, animate)
            if action:
                needs_relayout = True
            if action == "show":
                fade_in.append(btn)
        if relayout or needs_relayout:
            self.relayout_controls(animate=animate,
                                   fade_in_buttons=fade_in)
        self._apply_edit_hidden_visibility()

    def _on_button_op(self, btn: QWidget, v):
        op = max(0.0, min(1.0, float(v)))
        self._button_ops[btn] = op
        if hasattr(btn, "set_extra_opacity"):
            btn.set_extra_opacity(op)
        else:
            btn.update()

    def _button_anim_done(self, btn: QWidget):
        target = bool(self._button_targets.get(btn, True))
        if not target:
            btn.hide()
            self.relayout_controls(animate=True)
        btn.setAttribute(Qt.WA_TransparentForMouseEvents, not target)

    def _set_control_button_visible(self, btn: QWidget, target: bool,
                                    animate: bool = True):
        self._button_targets[btn] = target
        anim = self._button_anims.get(btn)
        if anim is not None:
            anim.stop()
        cur = self._button_ops.get(btn, 1.0 if btn.isVisible() else 0.0)
        if target:
            if btn.isVisible() and cur >= 0.999:
                btn.setAttribute(Qt.WA_TransparentForMouseEvents, False)
                return False
            btn.show()
            self._on_button_op(btn, 0.0 if animate else 1.0)
            btn.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            if (animate and anim_on() and self.isVisible()
                    and anim is not None):
                return "show"
        if (not animate or not anim_on() or not self.isVisible()
                or anim is None):
            self._on_button_op(btn, 1.0 if target else 0.0)
            btn.setVisible(target)
            btn.setAttribute(Qt.WA_TransparentForMouseEvents, not target)
            return True
        if not target and (btn.isHidden() or cur <= 0.001):
            btn.hide()
            btn.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            return False
        anim.setStartValue(cur)
        anim.setEndValue(1.0 if target else 0.0)
        anim.setDuration(adur(180 if target else 150, 95))
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.start()
        return False

    def set_empty(self, empty: bool, animate: bool = False):
        ms = adur(380, 200)
        do_fade = (animate and ms > 0 and self.isVisible()
                   and empty != self._empty_state)
        if do_fade:
            old_pm = self.grab()     # 切換前的畫面，蓋在上面淡出
        self._empty_state = empty
        for w in self._content:
            w.setVisible(not empty)
        self.art.setVisible((not empty) and self._cover_enabled)
        if not empty and self._control_bar:
            self.t_now.hide()
            self.t_total.hide()
            self.seek.hide()
        if empty and self._ctrl_overlay is not None:
            self._ctrl_suppress_done = True
            self._ctrl_anim.stop()
            self._ctrl_suppress_done = False
            self._ctrl_overlay.hide()
        for w in self._empty:
            w.setVisible(empty)
        self.update_source_visible()
        self.refresh_empty_text()
        self._sync_controls_hover(animate=animate)
        # 右上角按鈕永遠顯示；筆可關閉，重設只在編輯模式顯示
        for b in self._topbar_buttons:
            if b is self.btn_edit:
                b.setVisible(self._edit_button_target > 0.001
                             or self._edit_button_op > 0.001)
            else:
                b.setVisible(
                    b is not self.btn_reset_layout
                    or self._reset_button_target > 0.001
                    or self._reset_button_op > 0.001)
            b.raise_()
        self.fps_label.raise_()
        self._apply_edit_hidden_visibility()
        self._sync_edit_library()
        self._sync_edit_instance_element_states()
        if empty:
            self._dom = None
            self.refresh_accent()
        if do_fade:
            if self._fade is None:
                self._fade = _CardFade(self)
            self._fade.start(old_pm, ms)
        self.update()

    def refresh_empty_text(self):
        mode = SETTINGS["source"]
        self.empty_text.setText(empty_text(mode))
        self.empty_btn.setVisible(self._empty_state and mode != "browser")

    def update_source_visible(self):
        target = 1.0 if (not self._empty_state
                         and SETTINGS["show_source"]) else 0.0
        ms = adur(190, 110)
        # stop() 會同步發 finished；先保留顯示狀態，避免淡出前被隱藏。
        self._source_target = 1.0
        self._source_anim.stop()
        self._source_target = target
        if not anim_on() or ms <= 0 or not self.isVisible():
            self._on_source_op(target)
            self._source_done()
            return
        if target > 0:
            self.source_logo.show()
            self.source.show()
        self._source_anim.setStartValue(self._source_op)
        self._source_anim.setEndValue(target)
        self._source_anim.setDuration(ms)
        self._source_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._source_anim.start()

    def _on_source_op(self, v):
        self._source_op = float(v)
        self._source_eff.setOpacity(self._source_op)
        self._source_logo_eff.setOpacity(self._source_op)
        self.update()

    def _source_done(self):
        if self._source_target <= 0.001:
            self.source_logo.hide()
            self.source.hide()
        else:
            self.source_logo.show()
            self.source.show()
        self._apply_edit_hidden_visibility()
        self.update()

    def set_source(self, app_id: str):
        label, _, is_sp = source_info(app_id or "spotify")
        if label != self._src_label or is_sp != self._src_spotify:
            self._src_label = label
            self._src_spotify = is_sp
            self.source_logo.set_spotify(is_sp)
            self.source.setText(label)
            self.update()

    def visual_state(self) -> dict:
        return {
            "source_op": self._source_op,
            "source_target": self._source_target,
            "seek": self.seek.visual_state(),
        }

    def restore_visual_state(self, state: dict | None):
        if not state:
            return
        self._source_target = 1.0
        self._source_anim.stop()
        self._source_op = max(0.0, min(1.0, float(
            state.get("source_op", self._source_op))))
        self._source_target = max(0.0, min(1.0, float(
            state.get("source_target", self._source_target))))
        self._source_eff.setOpacity(self._source_op)
        self._source_logo_eff.setOpacity(self._source_op)
        if self._source_op > 0.001 or self._source_target > 0.001:
            self.source_logo.show()
            self.source.show()
        else:
            self.source_logo.hide()
            self.source.hide()
        self.seek.restore_visual_state(state.get("seek"))
        self.update()

    # ---- 主題色（含淡化過渡） ----

    @staticmethod
    def _auto_gradient(accent: QColor) -> tuple[QColor, QColor]:
        h, s, v, _ = QColor(accent).getHsv()
        if h < 0:
            h = 132
        c0 = QColor.fromHsv(h, min(255, round(s * 1.05)),
                            min(255, round(v * 1.12)))
        c1 = QColor.fromHsv((h + 34) % 360, min(255, round(s * 0.92)),
                            max(72, round(v * 0.78)))
        return c0, c1

    def _control_gradient(self, accent: QColor):
        pair = theme_gradient()
        if pair:
            return pair
        if (SETTINGS.get("theme") == "auto"
                and SETTINGS.get("auto_theme") == "gradient"):
            if self._use_background_for_auto_theme():
                _, bg_grad = self._background_theme_source()
                return bg_grad or Card._auto_gradient(accent)
            return self._cover_grad or Card._auto_gradient(accent)
        return None

    def _bg_target(self, accent: QColor) -> tuple[QColor, QColor]:
        """背景漸層兩端的目標色（已壓暗、尚未乘透明度）。"""
        strength = min(1.0, max(0.0, float(
            SETTINGS.get("auto_color_strength", 1.0))))
        neutral1, neutral2 = QColor(15, 15, 19), QColor(13, 13, 17)
        pair = theme_gradient()
        if pair:                 # 漸層主題：雙色斜向，壓暗保文字可讀
            c0 = blend(pair[0], neutral1, 0.42)
            c1 = blend(pair[1], neutral2, 0.50)
            return blend(neutral1, c0, strength), blend(neutral2, c1, strength)
        if (SETTINGS.get("theme") == "auto"
                and SETTINGS.get("auto_theme") == "gradient"):
            if self._use_background_for_auto_theme():
                _, bg_grad = self._background_theme_source()
                c0, c1 = bg_grad or Card._auto_gradient(accent)
            else:
                c0, c1 = self._cover_grad or Card._auto_gradient(accent)
            c0 = blend(c0, neutral1, 0.42)
            c1 = blend(c1, neutral2, 0.50)
            return blend(neutral1, c0, strength), blend(neutral2, c1, strength)
        c0 = blend(accent, neutral1, 0.70)
        return blend(neutral1, c0, strength), neutral2

    @staticmethod
    def _bright(c: QColor) -> QColor:
        b = float(SETTINGS.get("brightness", 1.0))
        out = QColor(
            min(255, max(0, round(c.red() * b))),
            min(255, max(0, round(c.green() * b))),
            min(255, max(0, round(c.blue() * b))),
            c.alpha())
        return out

    def _on_acc_anim(self, v):
        t = float(v)
        self._glass = self._glass_from + (self._glass_to - self._glass_from) * t
        self._apply_colors(blend(self._acc_from, self._acc_to, t),
                           blend(self._bg1_from, self._bg1_to, t),
                           blend(self._bg2_from, self._bg2_to, t))

    def _apply_colors(self, acc: QColor, bg1: QColor, bg2: QColor):
        self._accent = QColor(acc)
        self._bg1, self._bg2 = QColor(bg1), QColor(bg2)
        for widget in self._art_widgets():
            widget.set_accent(acc)
        self.seek.set_accent(acc)
        self.btn_shuffle.set_accent(acc)
        self.btn_repeat.set_accent(acc)
        self.empty_btn.set_theme(acc, self._control_gradient(acc))
        self._sync_edit_instance_element_states()
        if hasattr(self, "_custom_colors"):
            self.apply_custom_colors(animate=False)
        self._bg = None
        self.update()
        self.accent_changed.emit(QColor(acc))

    @staticmethod
    def _css_color(c: QColor) -> str:
        return f"rgba({c.red()},{c.green()},{c.blue()},{c.alpha()})"

    @staticmethod
    def _with_alpha(c: QColor, alpha: int) -> QColor:
        out = QColor(c)
        out.setAlpha(max(0, min(255, int(alpha))))
        return out

    def _custom_color_targets(self) -> tuple[dict[str, QColor], bool]:
        text = optional_setting_color("font_color")
        if text is None:
            title_col = QColor(255, 255, 255, 242)
            artist_col = QColor(TEXT_DIM)
            empty_icon_col = QColor(255, 255, 255, 70)
            empty_text_col = QColor(255, 255, 255, 140)
        else:
            title_col = self._with_alpha(text, 242)
            artist_col = self._with_alpha(text, 170)
            empty_icon_col = self._with_alpha(text, 82)
            empty_text_col = self._with_alpha(text, 160)

        source_col = optional_setting_color("source_text_color")
        if source_col is None:
            source_col = QColor(255, 255, 255, 110)
        else:
            source_col = self._with_alpha(source_col, 190)

        number_col = optional_setting_color("number_color")
        if number_col is None:
            number_col = QColor(255, 255, 255, 120)
        else:
            number_col = self._with_alpha(number_col, 205)

        topbar_raw = optional_setting_color("topbar_icon_color")
        topbar_override = topbar_raw is not None
        topbar_col = (QColor(topbar_raw) if topbar_raw is not None
                      else QColor(255, 255, 255, 245))

        seek_fill = optional_setting_color("seek_fill_color")
        if seek_fill is None:
            seek_fill = QColor(self._accent)
        else:
            seek_fill = self._with_alpha(seek_fill, 230)
        seek_thumb = optional_setting_color("seek_thumb_color")
        seek_thumb = QColor(255, 255, 255) if seek_thumb is None else QColor(seek_thumb)
        seek_track = optional_setting_color("seek_track_color")
        if seek_track is None:
            seek_track = QColor(255, 255, 255, 36)
        else:
            seek_track = self._with_alpha(seek_track, 110)

        return {
            "title": title_col,
            "artist": artist_col,
            "empty_icon": empty_icon_col,
            "empty_text": empty_text_col,
            "source": source_col,
            "number": number_col,
            "topbar": topbar_col,
            "seek_fill": seek_fill,
            "seek_thumb": seek_thumb,
            "seek_track": seek_track,
        }, topbar_override

    @staticmethod
    def _gradient_key(pair: tuple[QColor, QColor] | None):
        if pair is None:
            return None
        return tuple((c.red(), c.green(), c.blue(), c.alpha())
                     for c in pair)

    def _seek_fill_gradient_target(self) -> tuple[QColor, QColor] | None:
        if optional_setting_color("seek_fill_color") is not None:
            return None
        pair = self._control_gradient(self._accent)
        if pair is None:
            return None
        return QColor(pair[0]), QColor(pair[1])

    def _set_custom_color_frame(self, colors: dict[str, QColor],
                                topbar_override: bool,
                                force_topbar_override: bool = False):
        self.title.set_color(colors["title"])
        self.artist.set_color(colors["artist"])
        self.empty_icon.setStyleSheet(
            f"color: {self._css_color(colors['empty_icon'])};")
        self.empty_text.setStyleSheet(
            f"color: {self._css_color(colors['empty_text'])};")
        self.source.setStyleSheet(f"color: {self._css_color(colors['source'])};")
        self.source_logo.set_color(colors["source"])

        qss = f"color: {self._css_color(colors['number'])};"
        self.t_now.setStyleSheet(qss)
        self.t_total.setStyleSheet(qss)
        for widget in self._edit_instance_widgets.values():
            if isinstance(widget, TimeLabel):
                widget.setStyleSheet(qss)

        topbar_col = (colors["topbar"] if (topbar_override
                      or force_topbar_override) else None)
        for b in self._topbar_buttons:
            b.set_color_override(topbar_col)

        seek_grad = self._seek_fill_gradient_target()
        self.seek.set_custom_colors(colors["seek_fill"],
                                    colors["seek_thumb"],
                                    colors["seek_track"],
                                    seek_grad)
        self._custom_colors = {k: QColor(v) for k, v in colors.items()}
        self._seek_fill_gradient = (
            None if seek_grad is None
            else (QColor(seek_grad[0]), QColor(seek_grad[1])))
        self._topbar_override = bool(topbar_override)
        self.update()

    def _on_custom_color_anim(self, value):
        t = max(0.0, min(1.0, float(value)))
        colors = {
            key: blend(self._custom_color_from[key],
                       self._custom_color_to[key], t)
            for key in self._custom_color_to
        }
        self._set_custom_color_frame(
            colors, self._topbar_override_to,
            force_topbar_override=t < 0.999)

    def _custom_color_done(self):
        if self._custom_color_abort:
            return
        if self._custom_color_to:
            self._set_custom_color_frame(
                self._custom_color_to, self._topbar_override_to)

    def apply_custom_colors(self, animate: bool = True):
        target, topbar_override = self._custom_color_targets()
        target_seek_grad = self._seek_fill_gradient_target()
        if not self._custom_colors:
            self._set_custom_color_frame(target, topbar_override)
            return
        same_colors = all(self._custom_colors.get(k) == v
                          for k, v in target.items())
        same_seek_grad = (self._gradient_key(self._seek_fill_gradient)
                          == self._gradient_key(target_seek_grad))
        if (same_colors and same_seek_grad
                and self._topbar_override == topbar_override):
            return
        self._custom_color_abort = True
        self._custom_color_anim.stop()
        self._custom_color_abort = False
        ms = adur(260, 150)
        if not animate or not anim_on() or ms <= 0 or not self.isVisible():
            self._set_custom_color_frame(target, topbar_override)
            return
        self._custom_color_from = {
            key: QColor(self._custom_colors.get(key, value))
            for key, value in target.items()
        }
        self._custom_color_to = {key: QColor(value)
                                 for key, value in target.items()}
        self._topbar_override_to = bool(topbar_override)
        self._custom_color_anim.setStartValue(0.0)
        self._custom_color_anim.setEndValue(1.0)
        self._custom_color_anim.setDuration(ms)
        self._custom_color_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._custom_color_anim.start()

    def refresh_accent(self, animate=True):
        t_acc = self.target_accent()
        t_bg1, t_bg2 = self._bg_target(t_acc)
        t_glass = 1.0 if glass_theme() else 0.0
        if (t_acc == self._accent and t_bg1 == self._bg1
                and t_bg2 == self._bg2 and abs(t_glass - self._glass) < 1e-6):
            return
        ms = adur(420, 220)
        if not animate or ms <= 0 or not self.isVisible():
            self._acc_anim.stop()
            self._glass = t_glass
            self._apply_colors(t_acc, t_bg1, t_bg2)
            return
        self._acc_from = QColor(self._accent)
        self._acc_to = QColor(t_acc)
        self._bg1_from, self._bg1_to = QColor(self._bg1), QColor(t_bg1)
        self._bg2_from, self._bg2_to = QColor(self._bg2), QColor(t_bg2)
        self._glass_from, self._glass_to = self._glass, t_glass
        self._acc_anim.stop()
        self._acc_anim.setStartValue(0.0)
        self._acc_anim.setEndValue(1.0)
        self._acc_anim.setDuration(ms)
        self._acc_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._acc_anim.start()

    def invalidate_bg(self):
        self._bg = None
        self._bg_image_layer = None
        self._bg_image_layer_key = None
        self._bg_overlay = None
        self._bg_overlay_key = None
        self._bg_clip_path_cache = None
        self._bg_clip_path_key = None
        self.update()

    def _bg_parallax_config_enabled(self) -> bool:
        return (bool(SETTINGS.get("background_image_parallax", False))
                and float(SETTINGS.get(
                    "background_image_parallax_strength", 1.0)) > 0.001
                and self._custom_bg_image() is not None)

    def _bg_parallax_drawing_enabled(self) -> bool:
        return (self._custom_bg_image() is not None
                and self._bg_parallax_factor > 0.001)

    def _bg_parallax_fps(self) -> int:
        return max(5, min(60, int(SETTINGS.get(
            "background_image_parallax_fps", 30))))

    def _bg_parallax_interval(self) -> int:
        return max(16, round(1000 / self._bg_parallax_fps()))

    def _bg_parallax_shift(self) -> tuple[float, float, float]:
        if self._bg_parallax_factor <= 0.001:
            return 0.0, 0.0, 0.0
        strength = min(2.0, max(0.0, float(self._bg_parallax_strength)))
        max_shift = min(self._W, self._H) * 0.045 * strength
        max_shift *= self._bg_parallax_factor
        dx = -self._bg_parallax.x() * max_shift
        dy = -self._bg_parallax.y() * max_shift
        return dx, dy, max_shift + 2.0 * self._bg_parallax_factor

    def _on_bg_parallax_factor(self, value):
        self._bg_parallax_factor = max(0.0, min(1.0, float(value)))
        self._bg = None
        self._bg_image_layer = None
        self._bg_image_layer_key = None
        self.update()

    def _on_bg_parallax_strength(self, value):
        self._bg_parallax_strength = max(0.0, min(2.0, float(value)))
        if self._bg_parallax_factor > 0.001:
            self._bg = None
            self._bg_image_layer = None
            self._bg_image_layer_key = None
            self.update()

    def _animate_bg_parallax_factor(self, target: float,
                                    animate: bool = True):
        target = max(0.0, min(1.0, float(target)))
        if abs(target - self._bg_parallax_factor_to) < 0.001:
            return
        self._bg_parallax_factor_to = target
        self._bg_parallax_factor_anim.stop()
        ms = adur(260, 150)
        if (not animate or not anim_on() or ms <= 0
                or not self.isVisible()):
            self._on_bg_parallax_factor(target)
            return
        self._bg_parallax_factor_anim.setStartValue(self._bg_parallax_factor)
        self._bg_parallax_factor_anim.setEndValue(target)
        self._bg_parallax_factor_anim.setDuration(ms)
        self._bg_parallax_factor_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._bg_parallax_factor_anim.start()

    def _animate_bg_parallax_strength(self, target: float,
                                      animate: bool = True):
        target = max(0.0, min(2.0, float(target)))
        if abs(target - self._bg_parallax_strength_to) < 0.001:
            return
        self._bg_parallax_strength_to = target
        self._bg_parallax_strength_anim.stop()
        ms = adur(550, 325)
        if (not animate or not anim_on() or ms <= 0
                or not self.isVisible()):
            self._on_bg_parallax_strength(target)
            return
        self._bg_parallax_strength_anim.setStartValue(
            self._bg_parallax_strength)
        self._bg_parallax_strength_anim.setEndValue(target)
        self._bg_parallax_strength_anim.setDuration(ms)
        self._bg_parallax_strength_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._bg_parallax_strength_anim.start()

    def _on_bg_parallax(self, value):
        t = max(0.0, min(1.0, float(value)))
        x = (self._bg_parallax_from.x()
             + (self._bg_parallax_to.x() - self._bg_parallax_from.x()) * t)
        y = (self._bg_parallax_from.y()
             + (self._bg_parallax_to.y() - self._bg_parallax_from.y()) * t)
        self._bg_parallax = QPointF(x, y)
        if self._bg_parallax_drawing_enabled():
            self.update()

    def _set_bg_parallax(self, value: QPointF, force: bool = False):
        x = max(-1.0, min(1.0, float(value.x())))
        y = max(-1.0, min(1.0, float(value.y())))
        x = round(x, 2)
        y = round(y, 2)
        target = QPointF(x, y)
        if (not force and abs(x - self._bg_parallax_to.x()) < 0.01
                and abs(y - self._bg_parallax_to.y()) < 0.01):
            return
        self._bg_parallax_to = target
        self._bg_parallax_anim.stop()
        if not force:
            return
        self._bg_parallax = QPointF(target)
        if self._bg_parallax_drawing_enabled():
            self.invalidate_bg()

    def _advance_bg_parallax(self) -> bool:
        dx = self._bg_parallax_to.x() - self._bg_parallax.x()
        dy = self._bg_parallax_to.y() - self._bg_parallax.y()
        if abs(dx) < 0.002 and abs(dy) < 0.002:
            if (self._bg_parallax.x() != self._bg_parallax_to.x()
                    or self._bg_parallax.y() != self._bg_parallax_to.y()):
                self._bg_parallax = QPointF(self._bg_parallax_to)
                if self._bg_parallax_drawing_enabled():
                    self.update()
            return False
        fps = self._bg_parallax_fps()
        alpha = max(0.04, min(0.152, 1.0 - math.exp(-1.0 / (fps * 0.275))))
        self._bg_parallax = QPointF(
            self._bg_parallax.x() + dx * alpha,
            self._bg_parallax.y() + dy * alpha)
        if self._bg_parallax_drawing_enabled():
            self.update()
        return True

    def _update_bg_parallax_from_cursor(self):
        if (self._bg_parallax_drag_suspended
                or not self._bg_parallax_config_enabled()):
            self._bg_parallax_timer.stop()
            return
        pos = self.mapFromGlobal(QCursor.pos())
        inside = self.rect().contains(pos)
        if inside:
            cx = self._W / 2.0
            cy = self._H / 2.0
            self._set_bg_parallax(QPointF(
                (pos.x() - cx) / max(1.0, cx),
                (pos.y() - cy) / max(1.0, cy)))
        else:
            self._set_bg_parallax(QPointF(0.0, 0.0))
        moving = self._advance_bg_parallax()
        if not inside and not moving:
            self._bg_parallax_timer.stop()

    def _sync_bg_parallax_timer(self):
        self._bg_parallax_timer.setInterval(self._bg_parallax_interval())
        self._animate_bg_parallax_strength(float(SETTINGS.get(
            "background_image_parallax_strength", 1.0)))
        self._animate_bg_parallax_factor(
            1.0 if self._bg_parallax_config_enabled() else 0.0)
        if (self._bg_parallax_config_enabled() and self.underMouse()
                and not self._bg_parallax_drag_suspended):
            if not self._bg_parallax_timer.isActive():
                self._bg_parallax_timer.start()
            self._update_bg_parallax_from_cursor()
        else:
            self._set_bg_parallax(QPointF(0.0, 0.0))
            if self._bg_parallax_config_enabled():
                if not self._bg_parallax_timer.isActive():
                    self._bg_parallax_timer.start()
            else:
                self._bg_parallax_timer.stop()
                self._set_bg_parallax(QPointF(0.0, 0.0), force=True)

    def _on_bg_fade(self, value):
        self._bg_fade_t = max(0.0, min(1.0, float(value)))
        self.update()

    def _bg_fade_done(self):
        if self._bg_fade_abort:
            return
        self._bg_fade_old = None
        self._bg_fade_new = None
        self._bg_fade_t = 1.0
        self.update()

    def transition_background(self, old_pm: QPixmap | None,
                              animate: bool = True):
        self._bg_fade_abort = True
        self._bg_fade_anim.stop()
        self._bg_fade_abort = False
        self._bg = None
        new_pm = QPixmap(self._bg_pixmap())
        if old_pm is None or old_pm.isNull():
            self._bg_fade_old = None
            self._bg_fade_new = None
            self._bg_fade_t = 1.0
            self.update()
            return
        ms = adur(300, 170)
        if not animate or not anim_on() or ms <= 0 or not self.isVisible():
            self._bg_fade_old = None
            self._bg_fade_new = None
            self._bg_fade_t = 1.0
            self.update()
            return
        self._bg_fade_old = QPixmap(old_pm)
        self._bg_fade_new = new_pm
        self._bg_fade_t = 0.0
        self._bg_fade_anim.setStartValue(0.0)
        self._bg_fade_anim.setEndValue(1.0)
        self._bg_fade_anim.setDuration(ms)
        self._bg_fade_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._bg_fade_anim.start()

    def apply_cover_border(self, animate: bool = True):
        for widget in self._art_widgets():
            widget.set_border(
                bool(SETTINGS.get("cover_border", False)),
                float(SETTINGS.get("cover_border_width", 2.0)),
                float(SETTINGS.get("cover_border_opacity", 0.85)),
                animate=animate)

    def _cover_radius_for_size(self, cover_size: int) -> int:
        shape = SETTINGS.get("cover_shape", "rounded")
        if shape == "square":
            return 0
        if shape == "circle":
            return max(1, int(cover_size)) // 2
        strength = max(0.0, min(
            2.0, float(SETTINGS.get("cover_radius_strength", 1.0))))
        return round(S(8 if self._compact else 10)
                     * max(1, int(cover_size)) / max(1, self._art_size)
                     * strength)

    def _cover_radius(self) -> int:
        return self._cover_radius_for_size(self._cover_visual_size())

    def apply_cover_shape(self, animate: bool = True):
        radius = self._cover_radius()
        self.art.set_radius(radius, animate=animate)
        if self._art_img is not None:
            dpr = self.devicePixelRatioF()
            self._art_pm = rounded_pixmap(self._art_img, self._cover_visual_size(),
                                          radius, dpr)
            self.art.set_pixmap(self._art_pm, animate=animate)
        else:
            self.art.update()
        self._refresh_edit_instance_art_all(animate=animate)

    def _set_art_scales_for_layout(self, cover_scale: float,
                                   vinyl_scale: float):
        self.art.set_scales(cover_scale, vinyl_scale)
        self.art.set_radius(
            self._cover_radius_for_size(self.art.cover_size()),
            animate=False)
        self._apply_cover_layout(self._cover_layout_data(self._cover_enabled))

    def _on_art_size_layout(self, v):
        t = max(0.0, min(1.0, float(v)))
        c0, v0 = self._art_scale_from
        c1, v1 = self._art_scale_to
        self._set_art_scales_for_layout(c0 + (c1 - c0) * t,
                                        v0 + (v1 - v0) * t)

    def _art_size_layout_done(self):
        c1, v1 = self._art_scale_to
        self._set_art_scales_for_layout(c1, v1)
        if self._art_size_refresh_pixmap:
            self._refresh_art_pixmap()
        self._art_size_refresh_pixmap = True
        self.update()

    def _refresh_art_pixmap(self):
        if self._art_img is None:
            return
        dpr = self.devicePixelRatioF()
        radius = self._cover_radius()
        self._art_pm = rounded_pixmap(
            self._art_img, self._cover_visual_size(), radius, dpr)
        self.art.set_radius(radius, animate=False)
        self.art.set_pixmap(self._art_pm, animate=False)
        self._refresh_edit_instance_art_all(animate=False)

    def apply_cover_blur(self, radius: float):
        for widget in self._art_widgets():
            widget.set_blur(radius)

    def apply_audio_feedback_shape(self):
        for widget in self._art_widgets():
            widget.audio_shape_changed()

    def apply_audio_feedback_settings(self):
        for widget in self._art_widgets():
            widget.apply_audio_feedback_settings()

    def apply_art_motion_settings(self):
        for widget in self._art_widgets():
            widget.apply_motion_settings()

    def apply_tonearm_visible(self, visible: bool, animate: bool = True):
        for widget in self._art_widgets():
            widget.set_tonearm_visible(visible, animate=animate)

    def apply_vinyl_center_settings(self, animate: bool = True):
        for widget in self._art_widgets():
            widget.apply_vinyl_center_settings(animate=animate)

    def apply_art_size_layout(self, animate: bool = True,
                              refresh_pixmap: bool = True):
        if not hasattr(self, "art"):
            return
        if self._art_size_anim.state() == Anim.Running:
            self._art_size_anim.stop()
        self._art_size_refresh_pixmap = bool(refresh_pixmap)
        target = (self._cover_scale_setting(), self._vinyl_scale_setting())
        current = (float(self.art._cover_scale), float(self.art._vinyl_scale))
        if (abs(current[0] - target[0]) < 0.0001
                and abs(current[1] - target[1]) < 0.0001):
            self._art_size_refresh_pixmap = True
            return
        ms = adur(260, 150)
        if (not animate or not anim_on() or ms <= 0 or not self.isVisible()):
            self._art_scale_to = target
            self._art_size_layout_done()
            return
        self._art_scale_from = current
        self._art_scale_to = target
        self._art_size_anim.setStartValue(0.0)
        self._art_size_anim.setEndValue(1.0)
        self._art_size_anim.setDuration(ms)
        self._art_size_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._art_size_anim.start()

    def apply_fps(self):
        for widget in self._art_widgets():
            widget.apply_fps()
        self.seek.apply_fps()
        self.title.apply_fps()
        self.artist.apply_fps()
        self.rain.apply_fps()
        self.lightning.apply_fps()
        self.apply_fps_overlay()
        self._sync_bg_parallax_timer()

    def apply_rain_settings(self):
        self.rain.apply_settings()

    def apply_lightning_settings(self):
        self.lightning.apply_settings()

    def apply_marquee_setting(self):
        enabled = bool(SETTINGS.get("marquee_enabled", True))
        edge_fade = bool(SETTINGS.get("marquee_edge_fade", True))
        self.title.set_marquee_enabled(enabled)
        self.artist.set_marquee_enabled(enabled)
        self.title.set_marquee_edge_fade(edge_fade)
        self.artist.set_marquee_edge_fade(edge_fade)

    def apply_fps_overlay(self):
        show = bool(SETTINGS.get("show_fps", False))
        self.fps_label.setVisible(show)
        self.fps_label.raise_()
        if show:
            self._fps_frames = 0
            self._fps_last = time.monotonic()
            self._fps_prev_paint = None
            self._fps_frame_ms_sum = 0.0
            self._fps_frame_ms_count = 0
            self._fps_paint_ms_sum = 0.0
            self._fps_paint_ms_count = 0
            if not self._fps_timer.isActive():
                self._fps_timer.start()
        else:
            self._fps_timer.stop()

    def _update_fps_label(self):
        now = time.monotonic()
        dt = max(0.001, now - self._fps_last)
        fps = self._fps_frames / dt
        frame_ms = (self._fps_frame_ms_sum / self._fps_frame_ms_count
                    if self._fps_frame_ms_count else 0.0)
        paint_ms = (self._fps_paint_ms_sum / self._fps_paint_ms_count
                    if self._fps_paint_ms_count else 0.0)
        self._fps_frames = 0
        self._fps_last = now
        self._fps_frame_ms_sum = 0.0
        self._fps_frame_ms_count = 0
        self._fps_paint_ms_sum = 0.0
        self._fps_paint_ms_count = 0
        self.fps_label.setText(
            f"{fps:.0f} FPS  frame {frame_ms:.1f}ms  paint {paint_ms:.1f}ms")
        self.fps_label.adjustSize()
        self.fps_label.move(14, 4)
        self.fps_label.raise_()

    def apply_language(self, animate: bool = True):
        old_pm = None
        ms = adur(220, 120)
        if animate and ms > 0 and self.isVisible():
            old_pm = self.grab()
        self.refresh_empty_text()
        self.empty_btn.set_texts(tr("launch_spotify"), tr("launching"))
        self._empty_btn_base_size = (
            self.empty_btn.width(), self.empty_btn.height())
        base = ((self._W - self._empty_btn_base_size[0]) // 2,
                S(74 if self._compact else 92) - self.empty_btn.pad,
                self._empty_btn_base_size[0],
                self._empty_btn_base_size[1])
        x, y, bw, bh = self._offset_geometry("empty_button", base)
        self.empty_btn.setFixedSize(bw, bh)
        self.empty_btn.move(x, y)
        self._update_edit_overlay()
        if old_pm is not None:
            if self._fade is None:
                self._fade = _CardFade(self)
            self._fade.start(old_pm, ms)
        self.update()

    def _on_edit_button_op(self, value):
        self._edit_button_op = max(0.0, min(1.0, float(value)))
        if self._edit_button_op > 0.001:
            self.btn_edit.show()
        self.btn_edit.set_extra_opacity(self._edit_button_op)
        self.btn_edit.setAttribute(
            Qt.WA_TransparentForMouseEvents,
            self._edit_button_op <= 0.02)
        self._apply_edit_hidden_visibility()
        self.update()

    def _edit_button_done(self):
        if self._edit_button_target <= 0.001:
            self.btn_edit.hide()
            self.btn_edit.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        else:
            self.btn_edit.show()
            self.btn_edit.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        self.update()

    def apply_edit_button_visible(self, animate: bool = True):
        visible = bool(SETTINGS.get("show_edit_button", True))
        if not visible and self._edit_mode:
            self.set_layout_edit_mode(False)
        target = 1.0 if visible else 0.0
        self._edit_button_target = target
        self._edit_button_anim.stop()
        if visible or self._edit_button_op > 0.001:
            self.btn_edit.show()
            self.btn_edit.raise_()
        ms = adur(180 if visible else 160, 100)
        if (not animate or not anim_on() or ms <= 0 or not self.isVisible()):
            self._on_edit_button_op(target)
            self._edit_button_done()
        else:
            self._edit_button_anim.setStartValue(self._edit_button_op)
            self._edit_button_anim.setEndValue(target)
            self._edit_button_anim.setDuration(ms)
            self._edit_button_anim.setEasingCurve(QEasingCurve.OutCubic)
            self._edit_button_anim.start()
        if self._edit_mode:
            self._fade_reset_button(True, animate=animate)
        else:
            self._fade_reset_button(False, animate=animate)
        for b in self._topbar_buttons:
            b.raise_()
        self.update()

    def set_audio_level_provider(self, provider):
        self._audio_level_provider = provider
        for widget in self._art_widgets():
            widget.set_audio_level_provider(provider)

    def set_art_playing(self, playing: bool):
        self._art_playing = bool(playing)
        for widget in self._art_widgets():
            widget.set_playing(self._art_playing)

    def set_art(self, img: QImage | None, animate=True):
        if img is None or img.isNull():
            self._art_img = None
            self._art_pm = None
            self._dom = None
            self._cover_grad = None
        else:
            self._art_img = QImage(img)
            dpr = self.devicePixelRatioF()
            self._art_pm = rounded_pixmap(
                img, self._cover_visual_size(), self._cover_radius(), dpr)
            self._dom = dominant_color(img)
            self._cover_grad = cover_gradient(img)
        self.refresh_accent(animate=animate)
        self.art.set_pixmap(self._art_pm, animate=animate)
        self._refresh_edit_instance_art_all(animate=animate)
        self.update()

    # ---- 繪製 ----

    def _custom_bg_image(self) -> QImage | None:
        path = str(SETTINGS.get("background_image", "") or "").strip()
        if path != self._bg_image_path:
            self._bg_image_path = path
            self._bg_image = QImage(path) if path else None
            self._bg_theme_key = None
            self._bg_dom = None
            self._bg_grad = None
        if self._bg_image is None or self._bg_image.isNull():
            return None
        return self._bg_image

    def _draw_custom_bg_image(self, p: QPainter, clip: QPainterPath,
                              opacity: float) -> bool:
        img = self._custom_bg_image()
        if img is None:
            return False
        iw, ih = img.width(), img.height()
        if iw <= 0 or ih <= 0:
            return False
        mode = str(SETTINGS.get("background_image_mode", "cover"))
        p.save()
        p.setClipPath(clip)
        p.setOpacity(max(0.0, min(1.0, opacity)))
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        target = QRectF(0, 0, self._W, self._H)
        drawn_rect = QRectF(target)
        dx, dy, extra = self._bg_parallax_shift()
        draw_target = target.adjusted(-extra, -extra, extra, extra)
        draw_target.translate(dx, dy)
        if mode == "tile":
            p.drawTiledPixmap(target, QPixmap.fromImage(img),
                              QPointF(dx, dy))
        elif mode == "stretch":
            drawn_rect = QRectF(draw_target)
            p.drawImage(draw_target, img, QRectF(0, 0, iw, ih))
        elif mode == "contain":
            scale = min(draw_target.width() / iw, draw_target.height() / ih)
            tw, th = iw * scale, ih * scale
            tr = QRectF(draw_target.center().x() - tw / 2.0,
                        draw_target.center().y() - th / 2.0, tw, th)
            drawn_rect = QRectF(tr)
            p.drawImage(tr, img, QRectF(0, 0, iw, ih))
        else:
            target_ratio = draw_target.width() / max(1.0, draw_target.height())
            src_ratio = iw / max(1, ih)
            if src_ratio > target_ratio:
                sw = ih * target_ratio
                sx = (iw - sw) / 2.0
                src = QRectF(sx, 0, sw, ih)
            else:
                sh = iw / target_ratio
                sy = (ih - sh) / 2.0
                src = QRectF(0, sy, iw, sh)
            drawn_rect = QRectF(draw_target)
            p.drawImage(draw_target, img, src)
        brightness = min(1.65, max(0.35, float(
            SETTINGS.get("background_image_brightness", 1.0))))
        if brightness < 0.999 or brightness > 1.001:
            p.setCompositionMode(QPainter.CompositionMode_SourceAtop)
            if brightness < 0.999:
                p.fillRect(drawn_rect, QColor(
                    0, 0, 0, round(255 * (1.0 - brightness))))
            else:
                p.fillRect(drawn_rect, QColor(
                    255, 255, 255,
                    round(255 * ((brightness - 1.0) / brightness))))
            p.setCompositionMode(QPainter.CompositionMode_SourceOver)
        p.restore()
        return True

    def _bg_scale(self) -> float:
        ss = 2 if SETTINGS["antialias"] else 1
        return self.devicePixelRatioF() * ss

    def _bg_clip_path(self) -> QPainterPath:
        radius = Sf(SETTINGS["radius"])
        key = (self._W, self._H, round(radius * 100))
        if self._bg_clip_path_cache is not None and self._bg_clip_path_key == key:
            return self._bg_clip_path_cache
        ext = 0.6
        path = QPainterPath()
        path.addRoundedRect(QRectF(-ext, -ext, self._W + ext * 2,
                                   self._H + ext * 2),
                            radius + ext, radius + ext)
        self._bg_clip_path_cache = path
        self._bg_clip_path_key = key
        return path

    @staticmethod
    def _qcolor_key(c: QColor) -> tuple[int, int, int, int]:
        return c.red(), c.green(), c.blue(), c.alpha()

    def _bg_image_pixmap(self, extra: float) -> QPixmap | None:
        img = self._custom_bg_image()
        if img is None:
            return None
        iw, ih = img.width(), img.height()
        if iw <= 0 or ih <= 0:
            return None
        scale = self._bg_scale()
        mode = str(SETTINGS.get("background_image_mode", "cover"))
        brightness = min(1.65, max(0.35, float(
            SETTINGS.get("background_image_brightness", 1.0))))
        extra_px = round(max(0.0, extra) * scale)
        key = (self._bg_image_path, img.cacheKey(), self._W, self._H,
               round(scale * 1000), SETTINGS["antialias"], mode,
               round(brightness * 1000), extra_px)
        if self._bg_image_layer is not None and self._bg_image_layer_key == key:
            return self._bg_image_layer

        logical_extra = extra_px / max(1.0, scale)
        logical = QRectF(0, 0, self._W + logical_extra * 2,
                         self._H + logical_extra * 2)
        pm = QPixmap(max(1, round(logical.width() * scale)),
                     max(1, round(logical.height() * scale)))
        pm.setDevicePixelRatio(scale)
        pm.fill(Qt.transparent)

        p = QPainter(pm)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        drawn_rect = QRectF(logical)
        if mode == "tile":
            p.drawTiledPixmap(logical, QPixmap.fromImage(img), QPointF(0, 0))
        elif mode == "stretch":
            p.drawImage(logical, img, QRectF(0, 0, iw, ih))
        elif mode == "contain":
            img_scale = min(logical.width() / iw, logical.height() / ih)
            tw, th = iw * img_scale, ih * img_scale
            tr = QRectF(logical.center().x() - tw / 2.0,
                        logical.center().y() - th / 2.0, tw, th)
            drawn_rect = QRectF(tr)
            p.drawImage(tr, img, QRectF(0, 0, iw, ih))
        else:
            target_ratio = logical.width() / max(1.0, logical.height())
            src_ratio = iw / max(1, ih)
            if src_ratio > target_ratio:
                sw = ih * target_ratio
                sx = (iw - sw) / 2.0
                src = QRectF(sx, 0, sw, ih)
            else:
                sh = iw / target_ratio
                sy = (ih - sh) / 2.0
                src = QRectF(0, sy, iw, sh)
            p.drawImage(logical, img, src)
        if brightness < 0.999 or brightness > 1.001:
            p.setCompositionMode(QPainter.CompositionMode_SourceAtop)
            if brightness < 0.999:
                p.fillRect(drawn_rect, QColor(
                    0, 0, 0, round(255 * (1.0 - brightness))))
            else:
                p.fillRect(drawn_rect, QColor(
                    255, 255, 255,
                    round(255 * ((brightness - 1.0) / brightness))))
            p.setCompositionMode(QPainter.CompositionMode_SourceOver)
        p.end()

        self._bg_image_layer = pm
        self._bg_image_layer_key = key
        return pm

    def _bg_overlay_pixmap(self, has_bg_image: bool) -> QPixmap:
        scale = self._bg_scale()
        op = SETTINGS["bg_opacity"]
        radius = Sf(SETTINGS["radius"])
        glass = min(1.0, max(0.0, self._glass))
        solid = 1.0 - glass
        key = (self._W, self._H, round(scale * 1000), SETTINGS["antialias"],
               round(radius * 100), round(op * 1000),
               round(float(SETTINGS.get("brightness", 1.0)) * 1000),
               round(glass * 1000), has_bg_image,
               self._qcolor_key(self._bg1), self._qcolor_key(self._bg2),
               self._qcolor_key(self._accent))
        if self._bg_overlay is not None and self._bg_overlay_key == key:
            return self._bg_overlay

        pm = QPixmap(max(1, int(self._W * scale)),
                     max(1, int(self._H * scale)))
        pm.setDevicePixelRatio(scale)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        aa(p)
        path = self._bg_clip_path()
        brect = QRectF(0, 0, self._W, self._H).adjusted(0.5, 0.5, -0.5, -0.5)
        brad = max(0.0, radius - 0.5)
        border_path = QPainterPath()
        border_path.addRoundedRect(brect, brad, brad)
        overlay_factor = 0.55 if has_bg_image else 1.0
        if has_bg_image:
            p.fillPath(path, self._bright(QColor(0, 0, 0, int(82 * op))))

        if solid > 0.001:
            g = QLinearGradient(0, 0, self._W, self._H)
            c1 = self._bright(QColor(self._bg1))
            c2 = self._bright(QColor(self._bg2))
            c1.setAlpha(int(255 * op * solid * overlay_factor))
            c2.setAlpha(int(255 * op * solid * overlay_factor))
            g.setColorAt(0.0, c1)
            g.setColorAt(1.0, c2)
            p.fillPath(path, g)

        if glass > 0.001:
            p.fillPath(path, self._bright(QColor(
                24, 26, 33, int(72 * op * glass * overlay_factor))))
            g = QLinearGradient(0, 0, self._W, self._H)
            g.setColorAt(0.0, self._bright(QColor(
                255, 255, 255, int(34 * op * glass * overlay_factor))))
            g.setColorAt(0.45, self._bright(QColor(
                255, 255, 255, int(9 * op * glass * overlay_factor))))
            g.setColorAt(1.0, self._bright(QColor(
                255, 255, 255, int(20 * op * glass * overlay_factor))))
            p.fillPath(path, g)

        glow = QRadialGradient(Sf(96), Sf(26), Sf(300))
        gc = self._bright(QColor(self._accent))
        gc.setAlpha(int((42 * solid + 26 * glass) * op
                        * (0.75 if has_bg_image else 1.0)))
        glow.setColorAt(0.0, gc)
        gc2 = self._bright(QColor(self._accent))
        gc2.setAlpha(0)
        glow.setColorAt(1.0, gc2)
        p.fillPath(path, glow)

        border_a = round(max(12, int(20 * op)) * solid
                         + int(38 + 52 * op) * glass)
        p.setPen(QPen(self._bright(QColor(255, 255, 255, border_a)), 1))
        p.setBrush(Qt.NoBrush)
        p.drawPath(border_path)
        p.end()
        self._bg_overlay = pm
        self._bg_overlay_key = key
        return pm

    def _paint_dynamic_bg(self, p: QPainter) -> bool:
        if self._bg_parallax_factor <= 0.001:
            return False
        dx, dy, extra = self._bg_parallax_shift()
        layer = self._bg_image_pixmap(extra)
        if layer is None:
            return False
        overlay = self._bg_overlay_pixmap(True)
        scale = self._bg_scale()
        extra_px = round(max(0.0, extra) * scale)
        logical_extra = extra_px / max(1.0, scale)
        p.save()
        p.setClipPath(self._bg_clip_path())
        p.setOpacity(max(0.0, min(1.0, SETTINGS["bg_opacity"])))
        dpr = max(1.0, layer.devicePixelRatioF())
        logical_w = layer.width() / dpr
        logical_h = layer.height() / dpr
        p.drawPixmap(QRectF(-logical_extra + dx, -logical_extra + dy,
                            logical_w, logical_h),
                     layer, QRectF(layer.rect()))
        p.restore()
        p.drawPixmap(0, 0, overlay)
        return True

    def _bg_pixmap(self) -> QPixmap:
        if self._bg is not None:
            return self._bg
        scale = self._bg_scale()
        pm = QPixmap(max(1, int(self._W * scale)),
                     max(1, int(self._H * scale)))
        pm.setDevicePixelRatio(scale)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        aa(p)
        radius = Sf(SETTINGS["radius"])
        # 填充路徑外擴 ext：圓角弧線/四邊的「卡片內側」coverage 全滿，抗鋸齒
        # 半透明過渡推到最外緣（被 pixmap 邊界裁），消除邊緣透出底色的透明感
        ext = 0.6
        path = QPainterPath()
        path.addRoundedRect(QRectF(-ext, -ext, self._W + ext * 2,
                                   self._H + ext * 2),
                            radius + ext, radius + ext)
        # 邊框內縮 0.5px 畫在像素中心，1px 描邊不被裁
        brect = QRectF(0, 0, self._W, self._H).adjusted(0.5, 0.5, -0.5, -0.5)
        brad = max(0.0, radius - 0.5)
        border_path = QPainterPath()
        border_path.addRoundedRect(brect, brad, brad)
        op = SETTINGS["bg_opacity"]
        has_bg_image = self._draw_custom_bg_image(p, path, op)
        overlay_factor = 0.55 if has_bg_image else 1.0
        if has_bg_image:
            p.fillPath(path, self._bright(QColor(0, 0, 0, int(82 * op))))

        glass = min(1.0, max(0.0, self._glass))
        solid = 1.0 - glass
        if solid > 0.001:
            # 背景漸層兩端色由 _apply_colors 維護（過渡動畫逐幀內插）
            g = QLinearGradient(0, 0, self._W, self._H)
            c1 = self._bright(QColor(self._bg1))
            c2 = self._bright(QColor(self._bg2))
            c1.setAlpha(int(255 * op * solid * overlay_factor))
            c2.setAlpha(int(255 * op * solid * overlay_factor))
            g.setColorAt(0.0, c1)
            g.setColorAt(1.0, c2)
            p.fillPath(path, g)

        if glass > 0.001:
            # 玻璃透明：煙燻玻璃底 + 斜向白色高光，與一般漸層層做透明度內插
            p.fillPath(path, self._bright(QColor(24, 26, 33,
                                                 int(72 * op * glass
                                                     * overlay_factor))))
            g = QLinearGradient(0, 0, self._W, self._H)
            g.setColorAt(0.0, self._bright(QColor(255, 255, 255,
                                                  int(34 * op * glass
                                                      * overlay_factor))))
            g.setColorAt(0.45, self._bright(QColor(255, 255, 255,
                                                   int(9 * op * glass
                                                       * overlay_factor))))
            g.setColorAt(1.0, self._bright(QColor(255, 255, 255,
                                                  int(20 * op * glass
                                                      * overlay_factor))))
            p.fillPath(path, g)

        glow = QRadialGradient(Sf(96), Sf(26), Sf(300))
        gc = self._bright(QColor(self._accent))
        gc.setAlpha(int((42 * solid + 26 * glass) * op
                        * (0.75 if has_bg_image else 1.0)))
        glow.setColorAt(0.0, gc)
        gc2 = self._bright(QColor(self._accent))
        gc2.setAlpha(0)
        glow.setColorAt(1.0, gc2)
        p.fillPath(path, glow)

        border_a = round(max(12, int(20 * op)) * solid
                         + int(38 + 52 * op) * glass)
        p.setPen(QPen(self._bright(QColor(255, 255, 255, border_a)), 1))
        p.setBrush(Qt.NoBrush)
        p.drawPath(border_path)
        p.end()
        self._bg = pm
        return pm

    def paintEvent(self, _):
        show_metrics = bool(SETTINGS.get("show_fps", False))
        paint_start = time.perf_counter() if show_metrics else 0.0
        if show_metrics:
            if self._fps_prev_paint is not None:
                self._fps_frame_ms_sum += (
                    paint_start - self._fps_prev_paint) * 1000.0
                self._fps_frame_ms_count += 1
            self._fps_prev_paint = paint_start
        p = QPainter(self)
        aa(p)
        if (self._bg_fade_old is not None and self._bg_fade_new is not None
                and self._bg_fade_t < 0.999):
            p.setOpacity(1.0 - self._bg_fade_t)
            p.drawPixmap(0, 0, self._bg_fade_old)
            p.setOpacity(self._bg_fade_t)
            p.drawPixmap(0, 0, self._bg_fade_new)
            p.setOpacity(1.0)
        else:
            if not self._paint_dynamic_bg(p):
                p.drawPixmap(0, 0, self._bg_pixmap())

        if show_metrics:
            self._fps_frames += 1
            self._fps_paint_ms_sum += (
                time.perf_counter() - paint_start) * 1000.0
            self._fps_paint_ms_count += 1

    # ---- 拖曳整個視窗 ----
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            if self._edit_mode:
                edge = self._window_resize_edge_at(e.position())
                if edge:
                    self._begin_window_resize(
                        edge, e.globalPosition().toPoint())
                    e.accept()
                    return
                rotate_key = self._rotate_key_at(e.position())
                if rotate_key is not None:
                    self._begin_edit_rotate(
                        rotate_key, e.globalPosition().toPoint())
                    e.accept()
                    return
                resize_key = self._resize_key_at(e.position())
                if resize_key is not None:
                    self._begin_edit_resize(
                        resize_key, e.globalPosition().toPoint())
                    e.accept()
                    return
                target_key = self._target_key_at(e.position())
                if target_key is None:
                    self._set_edit_selection(None, additive=False)
            win = self.window()
            if hasattr(win, "_stop_keep_on_screen_anim"):
                win._stop_keep_on_screen_anim()
            self._drag_off = (e.globalPosition().toPoint()
                              - win.frameGeometry().topLeft())
            if self._bg_parallax_timer.isActive():
                self._bg_parallax_drag_suspended = True
                self._bg_parallax_timer.stop()

    def mouseMoveEvent(self, e):
        if self._window_resize_drag is not None and e.buttons() & Qt.LeftButton:
            self._move_window_resize(e.globalPosition().toPoint())
            e.accept()
            return
        if self._edit_drag is not None and e.buttons() & Qt.LeftButton:
            self._move_edit_drag(e.globalPosition().toPoint())
            e.accept()
            return
        if self._edit_mode:
            self._update_edit_hover_from_global(e.globalPosition().toPoint())
            edge = self._window_resize_edge_at(e.position())
            if edge:
                self.setCursor(self._window_resize_cursor(edge))
            elif self._rotate_key_at(e.position()) is not None:
                self.setCursor(Qt.CrossCursor)
            elif self._resize_key_at(e.position()) is not None:
                self.setCursor(Qt.SizeFDiagCursor)
            else:
                self.unsetCursor()
        if self._drag_off is not None and e.buttons() & Qt.LeftButton:
            self.window().move(e.globalPosition().toPoint() - self._drag_off)

    def mouseReleaseEvent(self, e):
        if self._window_resize_drag is not None and e.button() == Qt.LeftButton:
            self._move_window_resize(e.globalPosition().toPoint())
            self._window_resize_drag = None
            self.layout_edit_changed.emit()
            e.accept()
            return
        if self._edit_drag is not None and e.button() == Qt.LeftButton:
            self._move_edit_drag(e.globalPosition().toPoint())
            if self._edit_drag.get("mode") == "resize":
                key = self._edit_drag.get("key")
                if key == "art":
                    self.apply_art_size_layout(
                        animate=False, refresh_pixmap=True)
                    self._refresh_art_pixmap()
            self._edit_drag = None
            self._sync_edit_handle_fades()
            self.layout_edit_changed.emit()
            e.accept()
            return
        if self._drag_off is not None:
            self._drag_off = None
            self._bg_parallax_drag_suspended = False
            self._sync_bg_parallax_timer()
            self.drag_finished.emit()

    def wheelEvent(self, e):
        d = e.angleDelta().y()
        if d:
            self.wheel_volume.emit(d)
        e.accept()

    def keyPressEvent(self, e):
        if self._handle_edit_key_press(e):
            return
        super().keyPressEvent(e)

    def enterEvent(self, e):
        self._sync_bg_parallax_timer()
        self._sync_controls_hover(True)
        self._sync_topbar_hover(True)
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._set_edit_hover_key(None)
        self._bg_parallax_drag_suspended = False
        self._set_bg_parallax(QPointF(0.0, 0.0))
        if self._bg_parallax_config_enabled():
            self._bg_parallax_timer.setInterval(self._bg_parallax_interval())
            if not self._bg_parallax_timer.isActive():
                self._bg_parallax_timer.start()
        else:
            self._bg_parallax_timer.stop()
            self._set_bg_parallax(QPointF(0.0, 0.0), force=True)
        self._sync_controls_hover(False)
        self._sync_topbar_hover(False)
        super().leaveEvent(e)


# ------------------------------------------------------- 縮放過渡動畫 ----

class _ZoomOverlay(QWidget):
    """卡片重建（縮放/字體）時的縮放 + 交叉淡化過渡層。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self._old: QPixmap | None = None
        self._new: QPixmap | None = None
        self._r0 = QRectF()
        self._r1 = QRectF()
        self._t = 0.0
        self._buf: QPixmap | None = None    # 離屏合成緩衝（重用）
        self._buf2: QPixmap | None = None   # 舊圖權重緩衝（重用）
        self.hide()

    def setup(self, old_pm: QPixmap, r0, new_pm: QPixmap, r1):
        self._old, self._new = old_pm, new_pm
        self._r0, self._r1 = QRectF(r0), QRectF(r1)
        self._t = 0.0
        dpr = self.devicePixelRatioF()
        bw = int(max(self._r0.width(), self._r1.width()) * dpr) + 2
        bh = int(max(self._r0.height(), self._r1.height()) * dpr) + 2
        if (self._buf is None or self._buf.width() < bw
                or self._buf.height() < bh):
            self._buf = QPixmap(bw, bh)
            self._buf2 = QPixmap(bw, bh)
        self.update()

    def set_t(self, t: float):
        self._t = float(t)
        self.update()

    def cur_rect(self) -> QRectF:
        t = self._t
        return QRectF(
            self._r0.x() + (self._r1.x() - self._r0.x()) * t,
            self._r0.y() + (self._r1.y() - self._r0.y()) * t,
            self._r0.width() + (self._r1.width() - self._r0.width()) * t,
            self._r0.height() + (self._r1.height() - self._r0.height()) * t)

    def _clip_radius(self, w: float) -> float:
        """過渡矩形目前的圓角（依寬度比例內插，端點正好是新舊卡片圓角）。"""
        if self._r1.width() <= 0:
            return Sf(SETTINGS["radius"])
        return Sf(SETTINGS["radius"]) * w / self._r1.width()

    def _compose(self, rect: QRectF) -> tuple[QPixmap, float, float]:
        """目前過渡畫面：buf = 新圖×t + 舊圖×(1−t)（真正的線性插值）。

        直接把舊圖以 opacity 蓋在新圖上，半透明背景時過渡中的合成 alpha
        會比穩定狀態高（卡片瞬間變得更不透明、顏色偏深）；反過來兩張都乘
        opacity 疊畫，中途整體 alpha 又會下沉（t + (1-t)² < 1），背後黑色
        陰影透出來造成變暗閃爍。另外 Qt 的 CompositionMode_Plus 在 painter
        opacity ≠ 1 時走 const-alpha 內插路徑，alpha 不是線性相加（實測
        中點 224→183，畫面像加了亮度）；所以把權重各自烘進兩個緩衝
        （Over 到透明底是精確的 src×opacity），最後用 opacity = 1 的
        Plus 做純相加，全程誤差只剩 ±1 取整、alpha 與端點一致。
        回傳（緩衝, 實際使用的寬, 高）——緩衝比需要的大，只能取局部。
        """
        dpr = self.devicePixelRatioF()
        bw = max(1.0, rect.width() * dpr)
        bh = max(1.0, rect.height() * dpr)
        if (self._buf is None or self._buf.width() < bw
                or self._buf.height() < bh):
            self._buf = QPixmap(int(bw) + 2, int(bh) + 2)
            self._buf2 = QPixmap(int(bw) + 2, int(bh) + 2)
        t = self._t
        target = QRectF(0, 0, bw, bh)
        self._buf.fill(Qt.transparent)
        p = QPainter(self._buf)
        aa(p)
        if self._new is not None and t > 0.0:
            p.setOpacity(t)
            p.drawPixmap(target, self._new, QRectF(self._new.rect()))
        if self._old is not None and t < 1.0:
            if t <= 0.0:                     # 端點不需要第二個緩衝
                p.setOpacity(1.0)
                p.drawPixmap(target, self._old, QRectF(self._old.rect()))
            else:
                self._buf2.fill(Qt.transparent)
                p2 = QPainter(self._buf2)
                aa(p2)
                p2.setOpacity(1.0 - t)
                p2.drawPixmap(target, self._old, QRectF(self._old.rect()))
                p2.end()
                p.setOpacity(1.0)
                p.setCompositionMode(QPainter.CompositionMode_Plus)
                p.drawPixmap(0, 0, self._buf2)   # opacity=1 → 純相加
        p.end()
        return self._buf, bw, bh

    def composite(self) -> QPixmap:
        """目前畫面的合成影像（重建動畫被打斷時當作新的起點）。"""
        rect = self.cur_rect()
        pm, bw, bh = self._compose(rect)
        out = pm.copy(0, 0, int(bw), int(bh))   # 緩衝會重用，須複製
        out.setDevicePixelRatio(self.devicePixelRatioF())
        return out

    def paintEvent(self, _):
        p = QPainter(self)
        aa(p)
        rect = self.cur_rect()
        # 依過渡矩形內插圓角裁切：新舊圖縮放後的圓角縫隙、grab 邊緣殘留
        # 一律切掉，不會在圓角四周露出黑塊
        rad = self._clip_radius(rect.width())
        clip = QPainterPath()
        clip.addRoundedRect(rect, rad, rad)
        p.setClipPath(clip)
        pm, bw, bh = self._compose(rect)
        p.drawPixmap(rect, pm, QRectF(0, 0, bw, bh))


# ---------------------------------------------------------------- 視窗 ----

INSTANCE_KEY = "spotify_mini.single"


def acquire_single_instance(on_show):
    """單一實例偵測：已有實例在跑就通知它現身並回傳 None，否則建立監聽。"""
    from PySide6.QtNetwork import QLocalServer, QLocalSocket
    probe = QLocalSocket()
    probe.connectToServer(INSTANCE_KEY)
    if probe.waitForConnected(250):          # 連得上 → 已有實例
        probe.write(b"show")
        probe.flush()
        probe.waitForBytesWritten(250)
        probe.disconnectFromServer()
        return None
    QLocalServer.removeServer(INSTANCE_KEY)  # 清掉異常結束殘留的具名管道
    server = QLocalServer()
    if not server.listen(INSTANCE_KEY):
        return server                        # 監聽失敗就放行，不擋啟動

    def _incoming():
        conn = server.nextPendingConnection()
        if conn is not None:
            conn.deleteLater()
        on_show()

    server.newConnection.connect(_incoming)
    return server


def make_tray_icon(accent: QColor) -> QIcon:
    pm = QPixmap(64, 64)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    path = QPainterPath()
    path.addRoundedRect(QRectF(2, 2, 60, 60), 14, 14)
    p.fillPath(path, QColor(21, 21, 26))
    p.setFont(icon_font(34))
    p.setPen(accent)
    p.drawText(pm.rect(), Qt.AlignCenter, GLYPH_NOTE)
    p.end()
    return QIcon(pm)


def launch_spotify():
    exe = os.path.expandvars(r"%APPDATA%\Spotify\Spotify.exe")
    try:
        if os.path.exists(exe):
            subprocess.Popen([exe, "--minimized"])
        else:
            os.startfile("spotify:")
    except OSError:
        pass


def _startup_command() -> str:
    if getattr(sys, "frozen", False):
        args = [sys.executable]
    else:
        args = [sys.executable, os.path.abspath(sys.argv[0])]
    args.append("--startup")
    if SETTINGS.get("startup_show") == "spotify":
        args.append("--startup-hide")
    return subprocess.list2cmdline(args)


def sync_startup_entry():
    if not sys.platform.startswith("win"):
        return
    try:
        import winreg
        path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path, 0,
                            winreg.KEY_SET_VALUE) as key:
            if SETTINGS.get("startup_enabled", False):
                winreg.SetValueEx(key, "SpotifyMini", 0, winreg.REG_SZ,
                                  _startup_command())
            else:
                try:
                    winreg.DeleteValue(key, "SpotifyMini")
                except FileNotFoundError:
                    pass
    except OSError:
        pass


def _find_hwnd(exe_names: list[str]):
    """找出指定進程的主視窗 HWND（有標題的頂層視窗）。"""
    if not exe_names:
        return None
    targets = tuple(n.lower() for n in exe_names)
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    found = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def cb(hwnd, _):
        if user32.GetWindowTextLengthW(hwnd) <= 0:
            return True
        pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        h = kernel32.OpenProcess(0x1000, False, pid.value)
        if h:
            buf = ctypes.create_unicode_buffer(260)
            size = ctypes.c_ulong(260)
            ok = kernel32.QueryFullProcessImageNameW(h, 0, buf,
                                                     ctypes.byref(size))
            kernel32.CloseHandle(h)
            if ok and buf.value.lower().endswith(targets):
                found.append(hwnd)
                return False
        return True

    user32.EnumWindows(cb, 0)
    return found[0] if found else None


def focus_app(app_id: str):
    """把媒體來源視窗帶到前景；Spotify 找不到時用協定啟動。"""
    _, exes, is_spotify = source_info(app_id or "spotify")
    hwnd = _find_hwnd(exes)
    if hwnd:
        user32 = ctypes.windll.user32
        user32.ShowWindow(hwnd, 9)          # SW_RESTORE
        user32.SetForegroundWindow(hwnd)
    elif is_spotify:
        try:
            os.startfile("spotify:")
        except OSError:
            pass


class PlayerWindow(QWidget):
    def __init__(self, demo=False, startup_wait=False):
        super().__init__()
        self.demo = demo
        self._startup_wait_show = bool(startup_wait)
        self.state = None

        # 顯示位置（內插 + 防回溯）
        self._dpos = 0.0
        self._dkey = None
        self._dlast = time.monotonic()
        self._art_img: QImage | None = None
        # 封面 bytes → 解碼後 QImage 的 LRU：上一首/下一首來回切時不重新
        # 解碼；同一物件重用也讓 dominant_color 以 cacheKey 快取命中
        self._art_cache: OrderedDict[bytes, QImage] = OrderedDict()
        self._panel: SettingsPanel | None = None
        self._vol_pop: VolumePopup | None = None   # 保持參照避免被 GC 回收
        self._volume = AppVolume()
        self._audio_meter = AppMasterAudioMeter()
        self._spectrum = SystemSpectrumAnalyzer()
        self._app_id = "spotify"
        self._vol_checked_at = 0.0   # 滾輪調音量的 session 列舉節流
        self._vol_ok = False
        self._vol_session_key = ""
        self._audio_meter_checked_at = 0.0
        self._audio_meter_ok = False
        self._vol_preheated = False
        self._open_drag = None
        hotkey_base = 0x53504D   # "SPM"
        self._hotkey_ids = {
            "hotkey": hotkey_base,
            "hotkey_play": hotkey_base + 1,
            "hotkey_prev": hotkey_base + 2,
            "hotkey_next": hotkey_base + 3,
            "hotkey_vol_up": hotkey_base + 4,
            "hotkey_vol_down": hotkey_base + 5,
        }
        self._hotkey_actions = {
            self._hotkey_ids["hotkey"]: "toggle_visible",
            self._hotkey_ids["hotkey_play"]: "play",
            self._hotkey_ids["hotkey_prev"]: "prev",
            self._hotkey_ids["hotkey_next"]: "next",
            self._hotkey_ids["hotkey_vol_up"]: "vol_up",
            self._hotkey_ids["hotkey_vol_down"]: "vol_down",
        }
        self._hotkey_registered: set[int] = set()
        self._quitting = False
        # 樂觀更新待確認：點按鈕先改 UI，輪詢值要嘛跟上要嘛逾時才放行
        # （SMTC 指令到 Spotify 真正生效會慢個一兩拍，期間舊值會把
        #  按鈕彈回去）
        self._pending: dict[str, tuple] = {}
        # seek 同理：輪詢值在來源真正套用前還是舊位置，擋下避免進度跳回
        self._seek_pending: tuple | None = None   # (目標秒, 逾時, 下達時刻)
        self._source_switch_pending = False
        self._source_switch_target = ""
        self._source_switch_until = 0.0
        self._source_switch_seek: tuple[float, float] | None = None

        # 「啟動 Spotify」逾時還原（啟動失敗/太久時把轉圈按鈕還原）
        self._launch_watch = QTimer(self)
        self._launch_watch.setSingleShot(True)
        self._launch_watch.setInterval(20000)
        self._launch_watch.timeout.connect(self._launch_timeout)
        self._source_switch_timer = QTimer(self)
        self._source_switch_timer.setSingleShot(True)
        self._source_switch_timer.timeout.connect(self._source_switch_timeout)
        self._vol_hover_timer = QTimer(self)
        self._vol_hover_timer.setSingleShot(True)
        self._vol_hover_timer.setInterval(1000)
        self._vol_hover_timer.timeout.connect(self._show_volume_from_hover)

        self.setWindowTitle("Spotify Mini")
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.setAutoFillBackground(False)
        flags = Qt.FramelessWindowHint | Qt.Tool
        if SETTINGS.get("pinned", True):
            flags |= Qt.WindowStaysOnTopHint
        self.setWindowFlags(flags)

        # 卡片重建（縮放/字體 hotswap）：併合多次變更 + 縮放過渡動畫
        self._rebuild_timer = QTimer(self)
        self._rebuild_timer.setSingleShot(True)
        self._rebuild_timer.setInterval(60)
        self._rebuild_timer.timeout.connect(self._do_rebuild)
        self._overlay: _ZoomOverlay | None = None
        self._zoom_restart = False
        self._zoom_anim = Anim(self)
        self._zoom_anim.valueChanged.connect(self._on_zoom)
        self._zoom_anim.finished.connect(self._zoom_done)
        self._final_size = None
        self._shadow_op = 1.0 if SETTINGS.get("shadow", True) else 0.0
        self._shadow_anim = Anim(self)
        self._shadow_anim.valueChanged.connect(self._on_shadow_op)
        self._keep_pos_anim = Anim(self)
        self._keep_pos_anim.valueChanged.connect(self._on_keep_pos_anim)
        self._keep_from_pos = QPoint()
        self._keep_to_pos = QPoint()

        self.card: Card | None = None
        # 系統匣圖示跟著主題色：accent 過渡每幀 emit，去抖後只重畫一次
        self._tray_timer = QTimer(self)
        self._tray_timer.setSingleShot(True)
        self._tray_timer.setInterval(200)
        self._tray_timer.timeout.connect(
            lambda: self.tray.setIcon(make_tray_icon(self.card.accent())))
        self._build_card()
        self._place()
        app = QApplication.instance()
        if app is not None:
            app.screenAdded.connect(
                lambda *_: QTimer.singleShot(0, self._keep_on_screen))
            app.screenRemoved.connect(
                lambda *_: QTimer.singleShot(0, self._keep_on_screen))
        self._tray()
        self._register_hotkeys()

        # 設定寫檔防抖（滑桿拖曳時每幀都 emit，不能每次都碰磁碟）
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(600)
        self._save_timer.timeout.connect(save_settings)

        # 進度條內插更新（50ms，讓填滿條平滑前進）
        self._tick_timer = QTimer(self)
        self._tick_timer.setInterval(50)
        self._tick_timer.timeout.connect(self._tick)
        self._tick_timer.start()
        if demo:
            self._demo_fill()
        else:
            from media import MediaBridge
            self.bridge = MediaBridge(self)
            self.bridge.state_changed.connect(self.on_state)
            self.bridge.art_changed.connect(self.on_art)
            self.bridge.art_missing.connect(lambda: self._set_art(None))
            self.bridge.start()
        QTimer.singleShot(800, self._prewarm_volume_popup)

    # ---- 卡片建立 / 重建（縮放、字體變更時） ----
    def _build_card(self, resize_window: bool = True):
        old = self.card
        visual = old.visual_state() if old is not None else None
        self.card = Card(self)
        self.card.move(MARGIN, MARGIN)
        if resize_window:
            self.setFixedSize(self.card.width() + MARGIN * 2,
                              self.card.height() + MARGIN * 2)
        self._wire()
        if old is not None:
            old.hide()
            old.deleteLater()
            self.card.show()
        # 還原目前狀態
        if self.state and self.state.found:
            self.card.set_empty(False)
            self._apply_state(self.state, animate=False)
            self.card.set_source(self.state.app_id)
            if self._art_img is not None:
                self.card.set_art(self._art_img, animate=False)
            self.card.restore_visual_state(visual)
            self._tick()
        elif visual is not None:
            self.card.restore_visual_state(visual)

    def _sync_size_to_card(self):
        if self.card is None:
            return
        self.setFixedSize(self.card.width() + MARGIN * 2,
                          self.card.height() + MARGIN * 2)

    def moveEvent(self, e):
        super().moveEvent(e)
        if self.card is not None and self.card.layout_edit_mode():
            self.card._sync_edit_library(animate=False)

    def showEvent(self, e):
        super().showEvent(e)
        if self.card is not None and self.card.layout_edit_mode():
            self.card._sync_edit_library(animate=False)

    def hideEvent(self, e):
        if (self.card is not None
                and hasattr(self.card, "_edit_library")):
            self.card._edit_library.hide()
        super().hideEvent(e)

    def _request_rebuild(self):
        self._rebuild_timer.start()

    def _do_rebuild(self):
        if (self.card is None or not anim_on() or not self.isVisible()):
            self._build_card()
            self.repaint()
            return
        # 取得目前畫面當動畫起點（動畫進行中則取合成影像）
        if self._zoom_anim.state() == Anim.Running:
            self._zoom_restart = True       # stop() 會同步發 finished
            self._zoom_anim.stop()
            self._zoom_restart = False
            r0 = self._overlay.cur_rect().toRect()
            old_pm = self._overlay.composite()
        else:
            old_pm = self.card.grab()
            r0 = self.card.geometry()
        old_size = QSizeF(self.size())

        self._build_card(resize_window=False)
        new_pm = self.card.grab()
        r1 = self.card.geometry()
        self._final_size = (self.card.width() + MARGIN * 2,
                            self.card.height() + MARGIN * 2)
        # 動畫期間視窗撐到兩者較大者，結束才縮回，避免裁切與殘影
        self.setFixedSize(max(self._final_size[0], round(old_size.width())),
                          max(self._final_size[1], round(old_size.height())))

        if self._overlay is None:
            self._overlay = _ZoomOverlay(self)
        self._overlay.setGeometry(self.rect())
        self._overlay.setup(old_pm, r0, new_pm, r1)
        self._overlay.show()
        self._overlay.raise_()
        self.card.hide()
        # 視窗剛撐大的區域在下一輪事件迴圈才會畫到，會閃一格黑/空白；
        # 先同步畫一次把第一幀補上
        self.repaint()

        self._zoom_anim.setStartValue(0.0)
        self._zoom_anim.setEndValue(1.0)
        self._zoom_anim.setDuration(adur(260, 140))
        self._zoom_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._zoom_anim.start()

    def _on_zoom(self, v):
        if self._overlay is not None:
            self._overlay.set_t(float(v))

    def _zoom_done(self):
        if self._zoom_restart:
            return
        if self._overlay is not None:
            self._overlay.hide()
        if self.card is not None:
            self.card.show()
        if self._final_size:
            self.setFixedSize(*self._final_size)
            self._keep_on_screen()
        self.repaint()      # 透明視窗縮小後強制重繪，清掉殘影

    def _on_shadow_op(self, value):
        self._shadow_op = max(0.0, min(1.0, float(value)))
        self.update()

    def _set_shadow_visible(self, visible: bool, animate: bool = True):
        target = 1.0 if visible else 0.0
        self._shadow_anim.stop()
        ms = adur(220 if target > self._shadow_op else 180, 120)
        if (not animate or not anim_on() or ms <= 0 or not self.isVisible()):
            self._on_shadow_op(target)
            return
        self._shadow_anim.setStartValue(self._shadow_op)
        self._shadow_anim.setEndValue(target)
        self._shadow_anim.setDuration(ms)
        self._shadow_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._shadow_anim.start()

    def paintEvent(self, _):
        # 卡片陰影：預先模糊好的貼圖（掛 QGraphicsDropShadowEffect 會讓
        # 波浪進度條/跑馬燈每幀重繪都重新模糊整張卡片，是卡頓主因）
        if self.card is None or self._shadow_op <= 0.001:
            return
        p = QPainter(self)
        p.setOpacity(self._shadow_op)
        blur = 15
        sh = soft_shadow(self.card.width(), self.card.height(),
                         Sf(SETTINGS["radius"]), blur=blur, alpha=150,
                         dpr=self.devicePixelRatioF())
        if self._overlay is not None and self._overlay.isVisible():
            r = self._overlay.cur_rect()
            fx = r.width() / max(1.0, float(self.card.width()))
            fy = r.height() / max(1.0, float(self.card.height()))
            target = QRectF(r.x() - blur * fx, r.y() - blur * fy + 5,
                            r.width() + blur * 2 * fx,
                            r.height() + blur * 2 * fy)
            p.setRenderHint(QPainter.SmoothPixmapTransform, True)
            p.drawPixmap(target, sh, QRectF(sh.rect()))
        else:
            g = self.card.geometry()
            p.drawPixmap(g.x() - blur, g.y() - blur + 5, sh)

    # ---- 設定 ----
    def _save_cfg(self):
        self._keep_on_screen()
        pos = (self._keep_to_pos if self._keep_pos_anim.state() == Anim.Running
               else self.pos())
        SETTINGS["x"], SETTINGS["y"] = pos.x(), pos.y()
        SETTINGS["pinned"] = self.card.btn_pin.isChecked()
        save_settings()

    def apply_setting(self, key: str, value):
        old_value = SETTINGS.get(key)
        if key == "settings_reset":
            self._reset_settings()
            return
        if key == "settings_import":
            self._import_settings()
            return
        if key == "settings_export":
            self._export_settings()
            return
        if key == "settings_open_file":
            self._open_settings_file_location()
            return
        if key == "custom_theme_add":
            add_custom_theme(value)
            self._save_timer.start()
            return
        if key == "custom_theme_delete":
            remove_custom_theme(str(value))
            self.card.refresh_accent()
            self.card.invalidate_bg()
            self._save_timer.start()
            return
        bg_old = None
        bg_can_animate = False
        bg_transition_keys = ("background_image", "background_image_mode")
        if key in bg_transition_keys and self.card is not None:
            current_bg_image = SETTINGS.get("background_image", "")
            target_bg_image = (value if key == "background_image"
                               else current_bg_image)
            bg_can_animate = bool(str(current_bg_image or "").strip()
                                  or str(target_bg_image or "").strip())
            if bg_can_animate:
                bg_old = QPixmap(self.card._bg_pixmap())
        if key == "font":
            value = safe_font_family(value)
            app = QApplication.instance()
            if app is not None:
                app.setFont(QFont(value))
        seek_transition_keys = {
            "seek_thumb_shape", "seek_thumb_size", "seek_fill_color",
            "seek_thumb_color", "seek_track_color",
        }
        seek_visual_transition = (
            key in seek_transition_keys and self.card is not None
            and hasattr(self.card, "seek"))
        if seek_visual_transition:
            self.card.seek.begin_visual_transition()
        SETTINGS[key] = value
        self._save_timer.start()         # 防抖寫檔（拖曳滑桿時每幀都會進來）
        if key in ("scale", "font"):
            self._request_rebuild()
        elif key in ("art_cover_size", "art_vinyl_size"):
            self.card.apply_art_size_layout(animate=True)
        elif key == "settings_scale":
            if self._panel is not None:
                self._panel.rebuild_for_scale()
        elif key == "settings_panel_type":
            if self._panel is not None:
                self._panel.rebuild_for_panel_type()
        elif key == "auto_keep_on_screen":
            if bool(value):
                self._keep_on_screen()
                if self._panel is not None and self._panel.isVisible():
                    self._panel._keep_on_screen()
        elif key in self._hotkey_ids:
            self._register_hotkey(str(value), key)
        elif key == "theme":
            # 卡片淡化過渡會逐幀 emit accent_changed，設定面板跟著漸變；
            # 玻璃/漸層主題可能 accent 沒變但底色變了，背景一律重畫
            self.card.refresh_accent()
            self.card.invalidate_bg()
        elif key in ("custom_grad", "auto_theme"):
            # 自訂/自動漸層換色：跟主題切換一樣走淡化過渡
            self.card.refresh_accent()
            self.card.invalidate_bg()
            if self._panel is not None and self._panel.isVisible():
                self._panel.set_accent(self.card.accent(), force=True)
        elif key == "background_image_auto_theme":
            self.card.refresh_accent()
            if self._panel is not None and self._panel.isVisible():
                self._panel.set_accent(self.card.target_accent(), force=True)
        elif key in bg_transition_keys:
            if key == "background_image":
                bg_drives_auto = (
                    SETTINGS.get("theme") == "auto"
                    and not bool(SETTINGS.get(
                        "background_image_auto_theme", True)))
                self.card.refresh_accent(animate=not bg_drives_auto)
                if self._panel is not None and self._panel.isVisible():
                    self._panel.set_accent(self.card.target_accent(), force=True)
            self.card.transition_background(bg_old, animate=bg_can_animate)
            self.card._sync_bg_parallax_timer()
        elif key in ("background_image_parallax",
                     "background_image_parallax_strength",
                     "background_image_parallax_fps"):
            self.card.invalidate_bg()
            self.card._sync_bg_parallax_timer()
        elif key == "weather_effect":
            self.card.apply_rain_settings()
            if self._panel is not None:
                self._panel.sync_weather_controls()
        elif (key in ("weather_enabled", "rain_enabled")
              or key.startswith("rain_") or key.startswith("snow_")
              or key.startswith("custom_")):
            self.card.apply_rain_settings()
        elif key in ("lightning_enabled", "lightning_size",
                     "lightning_thickness",
                     "lightning_intensity", "lightning_duration",
                     "lightning_random_duration",
                     "lightning_duration_random"):
            self.card.apply_lightning_settings()
        elif key in ("radius", "bg_opacity", "brightness",
                     "background_image_brightness", "antialias"):
            self.card.invalidate_bg()
            self.update()                # 陰影貼圖依圓角快取，重畫視窗
        elif key in ("font_color", "source_text_color",
                     "topbar_icon_color", "number_color",
                     "seek_fill_color", "seek_thumb_color",
                     "seek_track_color"):
            self.card.apply_custom_colors()
        elif key == "shadow":
            self._set_shadow_visible(bool(value), animate=True)
            if self._panel is not None:
                self._panel.set_shadow_visible(bool(value), animate=True)
        elif key == "seek_style":
            self.card.seek.style_changed()
        elif key in ("seek_wave_amp", "seek_wave_speed",
                     "seek_glow_strength"):
            self.card.seek.style_changed()
        elif key == "seek_length":
            self.card.apply_seek_length()
        elif key == "seek_thumb":
            # 圓鈕顯示模式（hover/always）：只重新同步圓鈕可見度動畫，
            # 不走整幀交叉淡化（避免新舊圓鈕重疊的幽靈圖層）
            self.card.seek.thumb_mode_changed()
        elif key in ("seek_thumb_shape", "seek_thumb_size"):
            self.card.seek.style_changed()
        elif key in ("progress_time_mode", "progress_time_anim_enabled",
                     "progress_time_anim_style"):
            dur = self.state.duration if self.state is not None else self.card.seek._dur
            self.card.set_progress_times(self._dpos, dur, animate_mode=True)
        elif key == "progress_time_spacing":
            self.card.apply_progress_time_spacing()
        elif key == "seek_hover_time":
            self.card.seek.hover_time_setting_changed()
        elif key == "auto_color_strength":
            self.card.refresh_accent()
            self.card.invalidate_bg()
            if self._panel is not None and self._panel.isVisible():
                self._panel.set_accent(self.card.accent(), force=True)
        elif key == "controls_hover":
            self.card._sync_controls_hover(animate=True)
        elif key == "topbar_hover":
            self.card._sync_topbar_hover(animate=True)
        elif key in ("title_size", "artist_size"):
            self.card.apply_text_layout()
        elif key in ("control_button_size", "control_button_spacing"):
            self.card.apply_control_button_layout(animate=True)
        elif key in ("show_btn_shuffle", "show_btn_prev",
                     "show_btn_next", "show_btn_repeat"):
            self.card.apply_button_visibility(relayout=True, animate=True)
        elif key == "show_edit_button":
            self.card.apply_edit_button_visible()
        elif key == "show_fps":
            self.card.apply_fps_overlay()
            if self._panel is not None:
                self._panel.apply_fps_overlay()
        elif key in ("marquee_enabled", "marquee_edge_fade"):
            self.card.apply_marquee_setting()
        elif key == "anim_enabled":
            apply_anim_fps()
            self.card.update()
            if self._panel is not None:
                self._panel.update()
        elif key == "show_cover":
            self.card.set_cover_enabled(bool(value), animate=True)
        elif key == "art_mode":
            self.card.art.set_mode(str(value), animate=True)
            # 離開音訊模式就停掉 WASAPI loopback 擷取執行緒——它原本只在
            # 結束程式時才關，切回封面/黑膠後仍整個 session 持續擷取系統音訊、
            # 每幾毫秒寫一次環形緩衝，純浪費 CPU。再次進 audio 由 bars() lazy
            # 重啟（stop() 不設 _failed，可正常復活）。
            if str(value) != "audio":
                self._spectrum.stop()
        elif key == "audio_feedback_shape":
            self.card.apply_audio_feedback_shape()
        elif key in ("audio_feedback_thickness", "audio_feedback_sensitivity",
                     "audio_feedback_spin", "audio_feedback_spin_speed",
                     "audio_cover_pulse", "audio_cover_pulse_strength"):
            self.card.apply_audio_feedback_settings()
        elif key in ("cover_shape", "cover_radius_strength"):
            self.card.apply_cover_shape(animate=True)
        elif key == "cover_blur":
            self.card.apply_cover_blur(float(value))
        elif key in ("tonearm_speed", "vinyl_spin_speed"):
            self.card.apply_art_motion_settings()
        elif key == "show_tonearm":
            self.card.apply_tonearm_visible(bool(value), animate=True)
        elif key in ("show_vinyl_center", "vinyl_center_size"):
            self.card.apply_vinyl_center_settings(animate=True)
        elif key in ("cover_border", "cover_border_width",
                     "cover_border_opacity"):
            self.card.apply_cover_border(animate=True)
        elif key == "card_preset":
            self._request_rebuild()
        elif key == "fps":
            self.card.apply_fps()
            _apply_timer_resolution()
            apply_anim_fps()             # 互動動畫共用計時器跟著換檔
            if self._panel is not None:
                self._panel.apply_fps_overlay()
        elif key == "controls_align":
            self.card.relayout_controls(animate=True)
        elif key == "language":
            self.card.apply_language(animate=True)
            if self._panel is not None:
                self._panel.request_language_rebuild()
            self._sync_tray_text()
        elif key == "show_source":
            self.card.update_source_visible()
        elif key == "source":
            if old_value != value:
                self._begin_source_switch(str(value))
            self.card.refresh_empty_text()
            if hasattr(self, "bridge"):
                self.bridge.poke()
        elif key in ("startup_enabled", "startup_show"):
            sync_startup_entry()
        if seek_visual_transition:
            self.card.seek.commit_visual_transition()
        # gpu：重啟後生效（啟動時設定 QT_WIDGETS_RHI）

    def _reset_settings(self):
        custom_themes = list(SETTINGS.get("custom_themes", []))
        x, y = self.x(), self.y()
        sx, sy = SETTINGS.get("settings_x"), SETTINGS.get("settings_y")
        SETTINGS.clear()
        SETTINGS.update(DEFAULTS)
        SETTINGS["custom_themes"] = custom_themes
        SETTINGS["edit_layout_positions"] = {}
        SETTINGS["edit_layout_sizes"] = {}
        SETTINGS["edit_layout_angles"] = {}
        SETTINGS["edit_window_size"] = {}
        SETTINGS["edit_hidden_keys"] = []
        SETTINGS["edit_library_pos"] = {}
        SETTINGS["edit_library_collapsed"] = False
        SETTINGS["edit_library_instances"] = []
        SETTINGS["x"], SETTINGS["y"] = x, y
        if sx is not None and sy is not None:
            SETTINGS["settings_x"], SETTINGS["settings_y"] = sx, sy
        self._save_timer.stop()
        save_settings()
        sync_startup_entry()
        self._unregister_hotkey()
        self._register_hotkeys()
        apply_anim_fps()
        _apply_timer_resolution()
        self._set_shadow_visible(bool(SETTINGS.get("shadow", True)),
                                 animate=False)
        self._request_rebuild()
        if self._panel is not None:
            self._panel.rebuild_for_scale()
            if self.card is not None:
                self._panel.set_accent(self.card.accent(), force=True)
        if hasattr(self, "bridge"):
            self.bridge.poke()

    def _place(self):
        if "x" in SETTINGS and "y" in SETTINGS:
            self.move(SETTINGS["x"], SETTINGS["y"])
        else:
            scr = QApplication.primaryScreen().availableGeometry()
            self.move(scr.right() - self.width() - 16,
                      scr.bottom() - self.height() - 16)
        self._keep_on_screen()

    def _screen_geometry_for_window(self):
        rect = self.frameGeometry()
        center = rect.center()
        scr = QApplication.screenAt(center)
        if scr is not None:
            return scr.availableGeometry()
        screens = QApplication.screens()
        if not screens:
            return QApplication.primaryScreen().availableGeometry()

        def dist2(screen):
            c = screen.availableGeometry().center()
            dx = center.x() - c.x()
            dy = center.y() - c.y()
            return dx * dx + dy * dy

        return min(screens, key=dist2).availableGeometry()

    def _keep_on_screen(self):
        if not SETTINGS.get("auto_keep_on_screen", True):
            return
        geo = self._screen_geometry_for_window()
        if self.width() >= geo.width():
            x = geo.left()
        else:
            x = min(max(self.x(), geo.left()),
                    geo.right() + 1 - self.width())
        if self.height() >= geo.height():
            y = geo.top()
        else:
            y = min(max(self.y(), geo.top()),
                    geo.bottom() + 1 - self.height())
        if x != self.x() or y != self.y():
            self._move_to_screen_pos(QPoint(x, y), animate=True)

    def _move_to_screen_pos(self, pos: QPoint, animate: bool = True):
        if self.pos() == pos:
            return
        ms = adur(230, 130)
        if (not animate or not self.isVisible() or not anim_on()
                or ms <= 0):
            self._stop_keep_on_screen_anim()
            self.move(pos)
            return
        if self._keep_pos_anim.state() == Anim.Running:
            self._stop_keep_on_screen_anim()
        self._keep_from_pos = QPoint(self.pos())
        self._keep_to_pos = QPoint(pos)
        self._keep_pos_anim.setStartValue(0.0)
        self._keep_pos_anim.setEndValue(1.0)
        self._keep_pos_anim.setDuration(ms)
        self._keep_pos_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._keep_pos_anim.start()

    def _on_keep_pos_anim(self, value):
        t = max(0.0, min(1.0, float(value)))
        x = round(self._keep_from_pos.x()
                  + (self._keep_to_pos.x() - self._keep_from_pos.x()) * t)
        y = round(self._keep_from_pos.y()
                  + (self._keep_to_pos.y() - self._keep_from_pos.y()) * t)
        self.move(x, y)

    def _stop_keep_on_screen_anim(self):
        if self._keep_pos_anim.state() == Anim.Running:
            self._keep_pos_anim.stop()

    # ---- 接線 ----
    def _wire(self):
        c = self.card
        c.btn_pin.setChecked(SETTINGS.get("pinned", True))
        c.btn_pin.toggled.connect(self._set_pinned)
        c.btn_close.clicked.connect(self.hide_animated)
        c.btn_edit.toggled.connect(c.set_layout_edit_mode)
        c.btn_reset_layout.clicked.connect(lambda: c.reset_layout_positions())
        c.btn_vol.clicked.connect(self._show_volume)
        c.btn_vol.installEventFilter(self)
        c.btn_settings.clicked.connect(self._toggle_panel)
        c.btn_play.clicked.connect(self._toggle_play)
        c.btn_next.clicked.connect(lambda: self._cmd("next_track"))
        c.btn_prev.clicked.connect(lambda: self._cmd("prev_track"))
        c.btn_shuffle.clicked.connect(self._toggle_shuffle)
        c.btn_repeat.clicked.connect(self._cycle_repeat)
        c.seek.seeked.connect(self._seek_to)
        c.seek.previewed.connect(self._preview_seek_time)
        c.set_audio_level_provider(self._read_audio_peak)
        c.empty_btn.clicked.connect(self._launch_spotify)
        c.title.setCursor(Qt.PointingHandCursor)
        c.artist.setCursor(Qt.PointingHandCursor)
        self._bind_open_or_drag(c.art, "track")
        self._bind_open_or_drag(c.title, "track")
        self._bind_open_or_drag(c.artist, "artist")
        c.wheel_volume.connect(self._wheel_volume)
        c.drag_finished.connect(self._save_cfg)
        c.layout_edit_changed.connect(lambda: self._save_timer.start())
        c.accent_changed.connect(self._sync_panel_accent)
        c.accent_changed.connect(lambda _: self._tray_timer.start())
        c.setContextMenuPolicy(Qt.CustomContextMenu)
        c.customContextMenuRequested.connect(self._menu)

    def _sync_panel_accent(self, color: QColor):
        if self._panel is not None and self._panel.isVisible():
            self._panel.set_accent(color)

    def _preview_seek_time(self, sec: float):
        dur = self.card.seek._dur if self.card is not None else 0.0
        self.card.set_progress_times(sec, dur, animate_now=True)

    def _bind_open_or_drag(self, widget: QWidget, kind: str):
        def press(e):
            if e.button() != Qt.LeftButton:
                return
            self._stop_keep_on_screen_anim()
            gp = e.globalPosition().toPoint()
            self._open_drag = {
                "widget": widget,
                "kind": kind,
                "start": gp,
                "off": gp - self.frameGeometry().topLeft(),
                "dragging": False,
            }
            e.accept()

        def move(e):
            st = self._open_drag
            if not st or st.get("widget") is not widget:
                return
            if not (e.buttons() & Qt.LeftButton):
                return
            gp = e.globalPosition().toPoint()
            if not st["dragging"]:
                delta = gp - st["start"]
                if delta.manhattanLength() < QApplication.startDragDistance():
                    e.accept()
                    return
                st["dragging"] = True
            self.move(gp - st["off"])
            e.accept()

        def release(e):
            st = self._open_drag
            if e.button() != Qt.LeftButton or not st or st.get("widget") is not widget:
                return
            self._open_drag = None
            if st["dragging"]:
                self._save_cfg()
            elif widget.rect().contains(e.position().toPoint()):
                self._open_current_source(st["kind"])
            e.accept()

        widget.mousePressEvent = press
        widget.mouseMoveEvent = move
        widget.mouseReleaseEvent = release

    def _open_current_source(self, kind: str = "track"):
        st = self.state
        if not st or not st.found:
            focus_app(self._app_id)
            return
        _, _, is_spotify = source_info(st.app_id or self._app_id)
        if is_spotify:
            query = st.artist if kind == "artist" else " ".join(
                p for p in (st.title, st.artist) if p)
            if query.strip():
                try:
                    os.startfile("spotify:search:" + quote(query.strip()))
                    return
                except OSError:
                    pass
        focus_app(st.app_id or self._app_id)

    def _set_pinned(self, pinned: bool):
        pos = self.pos()
        self.setWindowFlag(Qt.WindowStaysOnTopHint, pinned)
        self.move(pos)
        self.show()
        self.card._sync_edit_instance_element_states()
        self._save_cfg()

    def _menu(self, pos):
        menu = QMenu(self)
        menu.setStyleSheet(
            "QMenu { background: #1c1c22; color: #e8e8ee;"
            " border: 1px solid rgba(255,255,255,28); border-radius: 8px;"
            " padding: 4px; font: 12px 'Segoe UI'; }"
            "QMenu::item { padding: 6px 24px; border-radius: 5px; }"
            "QMenu::item:selected { background: rgba(255,255,255,22); }")
        act_pin = menu.addAction(tr("pin"))
        act_pin.setCheckable(True)
        act_pin.setChecked(self.card.btn_pin.isChecked())
        act_pin.toggled.connect(self.card.btn_pin.setChecked)
        menu.addAction(tr("settings"), self._toggle_panel)
        menu.addAction(tr("hide_to_tray"), self.hide_animated)
        menu.addSeparator()
        menu.addAction(tr("exit"), self.quit_animated)
        menu.exec(self.card.mapToGlobal(pos))

    # ---- 顯示 / 隱藏動畫 ----
    def _bring_to_front(self):
        if self.isMinimized():
            self.showNormal()
        else:
            self.show()
        self.raise_()
        self.activateWindow()
        if sys.platform.startswith("win"):
            try:
                hwnd = int(self.winId())
                user32 = ctypes.windll.user32
                user32.ShowWindow(hwnd, 9)   # SW_RESTORE
                user32.SetForegroundWindow(hwnd)
            except Exception:
                pass

    def show_animated(self):
        if self.isMinimized():
            self.setWindowOpacity(1.0)
            self._bring_to_front()
            return
        if self.isVisible():
            self._bring_to_front()
            return
        fade_in(self, slide=14)
        QTimer.singleShot(0, self._bring_to_front)
        QTimer.singleShot(80, self._bring_to_front)

    def hide_animated(self):
        if not self.isVisible():
            return
        fade_out(self, self.hide, slide=14)

    def quit_animated(self):
        app = QApplication.instance()
        if app is None or self._quitting:
            return
        self._quitting = True
        panel_closing = self._panel is not None and self._panel.isVisible()
        delay = adur(180, 100) if panel_closing else 0
        if panel_closing:
            self._panel.animated_close()
        if not self.isVisible():
            if delay > 0:
                QTimer.singleShot(delay, app.quit)
            else:
                app.quit()
            return
        fade_out(self, app.quit, slide=14)

    # ---- 系統匣 ----
    def _tray(self):
        self.tray = QSystemTrayIcon(make_tray_icon(self.card.accent()), self)
        menu = QMenu()
        self._tray_toggle_act = menu.addAction("", self._toggle_visible)
        self._tray_settings_act = menu.addAction("", self._toggle_panel)
        menu.addSeparator()
        self._tray_exit_act = menu.addAction("", self.quit_animated)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.show()
        self._tray_menu = menu   # 防止被回收
        self._sync_tray_text()

    def _sync_tray_text(self):
        if not hasattr(self, "tray"):
            return
        if hasattr(self, "_tray_toggle_act"):
            self._tray_toggle_act.setText(tr("tray_toggle"))
            self._tray_settings_act.setText(tr("settings"))
            self._tray_exit_act.setText(tr("exit"))

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.Trigger:
            self._toggle_visible()
        elif reason == QSystemTrayIcon.DoubleClick:
            self.show_animated()

    def _toggle_visible(self):
        if self.isVisible() and not self.isMinimized():
            self.hide_animated()
        else:
            self.show_animated()

    def _unregister_hotkey(self, key: str | None = None):
        if not sys.platform.startswith("win"):
            self._hotkey_registered.clear()
            return
        if key is None:
            ids = list(self._hotkey_registered)
        else:
            hid = self._hotkey_ids.get(key)
            ids = [hid] if hid in self._hotkey_registered else []
        if not ids:
            return
        for hid in ids:
            try:
                ctypes.windll.user32.UnregisterHotKey(int(self.winId()), hid)
            finally:
                self._hotkey_registered.discard(hid)

    def _register_hotkey(self, seq: str, key: str = "hotkey"):
        self._unregister_hotkey(key)
        hid = self._hotkey_ids.get(key)
        if hid is None:
            return
        parsed = parse_hotkey(seq)
        if parsed is None or not sys.platform.startswith("win"):
            return
        mods, vk = parsed
        ok = ctypes.windll.user32.RegisterHotKey(
            int(self.winId()), hid, mods, vk)
        if ok:
            self._hotkey_registered.add(hid)

    def _register_hotkeys(self):
        for key in self._hotkey_ids:
            self._register_hotkey(str(SETTINGS.get(key, "")), key)

    def _run_hotkey_action(self, action: str):
        if action == "toggle_visible":
            self._toggle_visible()
        elif action == "play":
            self._toggle_play()
        elif action == "prev":
            self._cmd("prev_track")
        elif action == "next":
            self._cmd("next_track")
        elif action == "vol_up":
            self._wheel_volume(120)
        elif action == "vol_down":
            self._wheel_volume(-120)

    def eventFilter(self, obj, event):
        if self.card is not None and obj is self.card.btn_vol:
            typ = event.type()
            if typ == QEvent.Enter:
                self._vol_hover_timer.start()
            elif typ in (QEvent.Leave, QEvent.MouseButtonPress):
                self._vol_hover_timer.stop()
        return super().eventFilter(obj, event)

    def nativeEvent(self, event_type, message):
        if event_type == "windows_generic_MSG":
            try:
                msg = wintypes.MSG.from_address(int(message))
            except (TypeError, ValueError):
                msg = wintypes.MSG.from_address(message.__int__())
            if msg.message == WM_HOTKEY:
                action = self._hotkey_actions.get(int(msg.wParam))
                if action is not None:
                    self._run_hotkey_action(action)
                    return True, 0
        return super().nativeEvent(event_type, message)

    # ---- 設定面板 ----
    def _create_settings_panel(self) -> SettingsPanel:
        self._panel = SettingsPanel(self.card.target_accent())
        self._panel.setting_changed.connect(self.apply_setting)
        self._panel.position_committed.connect(
            lambda _=None: self._save_panel_pos())
        self._panel.closed.connect(self._save_panel_pos)
        return self._panel

    def _toggle_panel(self):
        if self._panel is not None and self._panel.isVisible():
            self._panel.animated_close()
            return
        if self._panel is not None:
            self._panel.deleteLater()
        panel = self._create_settings_panel()
        if "settings_x" in SETTINGS and "settings_y" in SETTINGS:
            pos = QPoint(int(SETTINGS["settings_x"]),
                         int(SETTINGS["settings_y"]))
        else:
            scr = QApplication.primaryScreen().availableGeometry()
            x = self.x() - self._panel.width() + MARGIN
            if x < scr.left():
                x = self.x() + self.width() - MARGIN
            y = min(self.y(), scr.bottom() - self._panel.height() + MARGIN)
            pos = QPoint(max(scr.left(), x), max(scr.top(), y))
        panel.open_at(pos)

    def _save_panel_pos(self):
        if self._panel is None:
            return
        SETTINGS["settings_x"] = self._panel.x()
        SETTINGS["settings_y"] = self._panel.y()
        self._save_timer.start()

    def _settings_dialog_dir(self) -> str:
        folder = os.path.dirname(CONFIG_PATH)
        return folder if os.path.isdir(folder) else os.getcwd()

    def _notify_settings_file(self, key: str, warning: bool = False):
        if not hasattr(self, "tray"):
            return
        icon = (QSystemTrayIcon.Warning if warning
                else QSystemTrayIcon.Information)
        self.tray.showMessage("Spotify Mini", tr(key), icon, 2600)

    def _export_settings(self):
        self._save_timer.stop()
        save_settings()
        default = os.path.join(self._settings_dialog_dir(),
                               "spotify_mini_settings.json")
        parent = self._panel if self._panel is not None else self
        path, _ = QFileDialog.getSaveFileName(
            parent, tr("settings_export"), default,
            "JSON (*.json);;All Files (*.*)")
        if not path:
            return
        if not os.path.splitext(path)[1]:
            path += ".json"
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(SETTINGS, f, ensure_ascii=False, indent=1)
        except OSError:
            self._notify_settings_file("settings_export_failed", warning=True)
            return
        self._notify_settings_file("settings_export_done")

    def _import_settings(self):
        parent = self._panel if self._panel is not None else self
        path, _ = QFileDialog.getOpenFileName(
            parent, tr("settings_import"), self._settings_dialog_dir(),
            "JSON (*.json);;All Files (*.*)")
        if not path:
            return
        try:
            with open(path, encoding="utf-8-sig") as f:
                data = json.load(f)
            if isinstance(data, dict) and isinstance(data.get("settings"), dict):
                data = data["settings"]
            if not isinstance(data, dict):
                raise ValueError("settings JSON must be an object")
        except (OSError, json.JSONDecodeError, ValueError):
            self._notify_settings_file("settings_import_failed", warning=True)
            return

        old_settings = dict(SETTINGS)
        try:
            self._apply_imported_settings(data)
        except Exception:
            apply_settings_data(old_settings)
            save_settings()
            self._request_rebuild()
            self._notify_settings_file("settings_import_failed", warning=True)
            return
        self._notify_settings_file("settings_import_done")

    def _apply_imported_settings(self, data: dict):
        panel_was_visible = self._panel is not None and self._panel.isVisible()
        panel_pos = QPoint(self._panel.pos()) if panel_was_visible else None

        self._save_timer.stop()
        apply_settings_data(data)
        old_panel = self._panel
        self._panel = None
        if old_panel is not None:
            old_panel.hide()
            old_panel.deleteLater()
        app = QApplication.instance()
        if app is not None:
            app.setFont(QFont(safe_font_family(SETTINGS.get("font"))))
        save_settings()
        sync_startup_entry()
        self._unregister_hotkey()
        self._register_hotkeys()
        self._pending.clear()
        self._seek_pending = None
        self._cancel_source_switch()
        if SETTINGS.get("art_mode") != "audio":
            self._spectrum.stop()
        apply_anim_fps()
        _apply_timer_resolution()

        was_visible = self.isVisible()
        pos = self.pos()
        self.setWindowFlag(Qt.WindowStaysOnTopHint,
                           bool(SETTINGS.get("pinned", True)))
        self.move(pos)
        if was_visible:
            self.show()
        self._set_shadow_visible(bool(SETTINGS.get("shadow", True)),
                                 animate=False)
        self._rebuild_timer.stop()
        self._build_card()
        self._place()
        if hasattr(self, "tray"):
            self.tray.setIcon(make_tray_icon(self.card.accent()))
            self._sync_tray_text()
        if hasattr(self, "bridge"):
            self.bridge.poke()
        if panel_was_visible:
            panel = self._create_settings_panel()
            panel.open_at(panel_pos if panel_pos is not None else self.pos())

    def _open_settings_file_location(self):
        self._save_timer.stop()
        save_settings()
        folder = os.path.dirname(CONFIG_PATH)
        try:
            if sys.platform.startswith("win"):
                subprocess.Popen(["explorer.exe", "/select,",
                                  os.path.normpath(CONFIG_PATH)])
            elif sys.platform == "darwin":
                subprocess.Popen(["open", "-R", CONFIG_PATH])
            else:
                subprocess.Popen(["xdg-open", folder])
        except OSError:
            try:
                if hasattr(os, "startfile"):
                    os.startfile(folder)
                else:
                    raise OSError
            except OSError:
                self._notify_settings_file(
                    "settings_open_file_failed", warning=True)

    # ---- 音量 ----
    def _clear_volume_popup(self, pop=None):
        if pop is None or self._vol_pop is pop:
            self._vol_pop = None

    def _read_volume_state(self, force: bool = False):
        if self.demo:
            return 0.7, False
        _, exes, _ = source_info(self._app_id or "spotify")
        key = "|".join(sorted(n.lower() for n in exes))
        now = time.monotonic()
        stale = now - self._vol_checked_at > 12.0
        if force or key != self._vol_session_key or stale or not self._vol_ok:
            self._vol_ok = self._volume.refresh(exes)
            self._vol_checked_at = now
            self._vol_session_key = key
        val = self._volume.get() if self._vol_ok else None
        muted = self._volume.get_mute() if self._vol_ok else False
        return val, muted

    def _read_audio_peak(self):
        if self.demo:
            phase = time.monotonic() * 3.0
            return [
                max(0.0, min(1.0, 0.35 + 0.32 * math.sin(phase + i * 0.31)))
                for i in range(64)
            ]
        bars = self._spectrum.bars()
        if bars is not None:
            return bars
        now = time.monotonic()
        stale = now - self._audio_meter_checked_at > 5.0
        if stale or not self._audio_meter_ok:
            self._audio_meter_ok = self._audio_meter.refresh()
            self._audio_meter_checked_at = now
        if not self._audio_meter_ok:
            return None
        return self._audio_meter.peak()

    def _prewarm_volume_popup(self):
        if self._vol_preheated or self.card is None:
            return
        self._vol_preheated = True
        try:
            val, muted = self._read_volume_state(force=True)
            pop = VolumePopup(self.card.accent(), val, muted, self)
            pop.ensurePolished()
            pm = QPixmap(pop.size())
            pm.fill(Qt.transparent)
            p = QPainter(pm)
            try:
                pop.render(p, QPoint(0, 0))
            finally:
                p.end()
            pop.deleteLater()
        except Exception:
            pass

    def _show_volume(self):
        self._vol_hover_timer.stop()
        self._show_volume_popup(toggle=True)

    def _show_volume_from_hover(self):
        if self.card is None or not self.card.btn_vol.underMouse():
            return
        self._show_volume_popup(toggle=False)

    def _show_volume_popup(self, toggle: bool):
        if self._vol_pop is not None:
            try:
                if self._vol_pop.isVisible():
                    if toggle:
                        self._vol_pop.dismiss()
                    return
            except RuntimeError:
                pass
            self._vol_pop = None

        val, muted = self._read_volume_state()
        pop = VolumePopup(self.card.accent(), val, muted)
        if not self.demo:
            pop.vol_changed.connect(self._volume.set)
            pop.mute_toggled.connect(self._volume.set_mute)
        self._vol_pop = pop      # 沒有這個參照，彈窗會被 GC 回收導致崩潰
        pop.destroyed.connect(lambda _=None, p=pop: self._clear_volume_popup(p))
        # 主題色過渡時彈窗跟著漸變（彈窗銷毀時 Qt 會自動斷線）
        self.card.accent_changed.connect(pop.set_accent)
        btn = self.card.btn_vol
        g = btn.mapToGlobal(QPoint(btn.width() // 2, 0))
        # 彈出在卡片上緣之外，避免蓋住主介面
        card_top = self.card.mapToGlobal(QPoint(0, 0)).y()
        pop.popup_at(g.x(), min(g.y(), card_top) - 4)

    def _wheel_volume(self, delta: int):
        """卡片上滾滾輪直接調整來源音量（每格 4%，支援觸控板細刻度）。"""
        if self.demo:
            return
        now = time.monotonic()
        if now - self._vol_checked_at > 1.0:    # 列舉 session 不便宜，節流
            _, exes, _ = source_info(self._app_id or "spotify")
            self._vol_ok = self._volume.refresh(exes)
            self._vol_checked_at = now
        if not self._vol_ok:
            return
        cur = self._volume.get()
        if cur is None:
            return
        if delta > 0 and self._volume.get_mute():
            self._volume.set_mute(False)        # 調大音量順手解除靜音
        new_val = min(1.0, max(0.0, cur + 0.04 * delta / 120.0))
        self._volume.set(new_val)

    # ---- 指令 ----
    def _cmd(self, name):
        if not self.demo and hasattr(self, "bridge"):
            getattr(self.bridge, name)()

    def _launch_spotify(self):
        launch_spotify()
        self.card.empty_btn.set_busy(True)   # 轉圈直到偵測到媒體或逾時
        self._launch_watch.start()

    def _launch_timeout(self):
        if self.card is not None:
            self.card.empty_btn.set_busy(False)

    def _toggle_play(self):
        if self.state and self.state.found:
            now = time.monotonic()
            self.state.position = self._dpos     # 樂觀更新
            self.state.read_at = now
            self.state.playing = not self.state.playing
            self.card.btn_play.set_playing(self.state.playing)
            self.card.seek.set_playing(self.state.playing)
            self.card.set_art_playing(self.state.playing)
            self.card._sync_edit_instance_element_states()
        self._cmd("toggle_play")

    def _toggle_shuffle(self):
        if self.state and self.state.shuffle is not None:
            new = not self.state.shuffle
            self.state.shuffle = new
            self._pending["shuffle"] = (new, time.monotonic() + 3.0)
            self.card.btn_shuffle.setChecked(new)
            self.card._sync_edit_instance_element_states()
            if not self.demo:
                self.bridge.set_shuffle(new)

    def _cycle_repeat(self):
        if self.state and self.state.repeat is not None:
            nxt = {0: 2, 2: 1, 1: 0}[self.state.repeat]
            self.state.repeat = nxt
            self._pending["repeat"] = (nxt, time.monotonic() + 3.0)
            self._apply_repeat(nxt)
            if not self.demo:
                self.bridge.set_repeat(nxt)

    def _resolve_pending(self, key: str, polled):
        """輪詢值與樂觀更新值的仲裁：跟上或逾時前都信自己的。"""
        pend = self._pending.get(key)
        if pend is None:
            return polled
        val, until = pend
        if polled == val or time.monotonic() > until:
            del self._pending[key]
            return polled
        return val

    def _apply_repeat(self, mode):
        b = self.card.btn_repeat
        b.setChecked(mode in (1, 2))
        b.set_glyph(GLYPH_REPEAT_ONE if mode == 1 else GLYPH_REPEAT_ALL)
        self.card._sync_edit_instance_element_states()

    def _seek_to(self, sec: float):
        if self.state:
            now = time.monotonic()
            self.state.position = sec
            self.state.read_at = now
            self._dpos = sec
            self._seek_pending = (sec, now + 3.0, now)
            dur = self.card.seek._dur if self.card is not None else 0.0
            self.card.set_progress_times(sec, dur, animate_now=True)
        if not self.demo and hasattr(self, "bridge"):
            self.bridge.seek(sec)

    def _seek_ok(self, st, raw: float, now: float) -> bool:
        """seek 後輪詢值仲裁：來源跟上目標或逾時前，不讓位置跳回舊值。"""
        if self._seek_pending is None:
            return True
        target, until, issued = self._seek_pending
        if st.read_at <= issued + 0.05:   # 還是 seek 當下的本地狀態
            return True
        if now > until or abs(raw - target) < 2.5:
            self._seek_pending = None     # 來源已跟上（或放棄等待）
            return True
        return False

    def _state_is_spotify(self, st) -> bool:
        if st is None or not st.found:
            return False
        _, _, is_spotify = source_info(st.app_id or "")
        return is_spotify

    def _state_matches_source(self, st, mode: str) -> bool:
        if st is None or not st.found:
            return False
        if mode == "any":
            return True
        is_spotify = self._state_is_spotify(st)
        if mode == "spotify":
            return is_spotify
        if mode == "browser":
            return not is_spotify
        return True

    def _begin_source_switch(self, target: str):
        st = self.state
        if (st is None or not st.found
                or self._state_matches_source(st, target)):
            self._cancel_source_switch()
            return
        old_dur = self.card.seek._dur or st.duration
        old_pos = self._dpos if old_dur > 0 else st.position
        self._source_switch_seek = (float(old_pos), float(old_dur))
        self._source_switch_target = str(target)
        self._source_switch_pending = True
        self._source_switch_until = time.monotonic() + 1.6
        self._source_switch_timer.start(1600)

    def _cancel_source_switch(self):
        self._source_switch_pending = False
        self._source_switch_target = ""
        self._source_switch_until = 0.0
        self._source_switch_seek = None
        self._source_switch_timer.stop()

    def _source_switch_timeout(self):
        if not self._source_switch_pending:
            return
        target = self._source_switch_target
        self._cancel_source_switch()
        if (SETTINGS.get("source") == target and self.state is not None
                and self.state.found
                and not self._state_matches_source(self.state, target)):
            from media import TrackState
            self.on_state(TrackState())

    # ---- 狀態更新 ----
    def on_state(self, st):
        seek_transition = None
        if self._source_switch_pending:
            target = self._source_switch_target
            if not st.found:
                if time.monotonic() < self._source_switch_until:
                    return
                self._cancel_source_switch()
            elif SETTINGS.get("source") == target:
                if not self._state_matches_source(st, target):
                    if time.monotonic() < self._source_switch_until:
                        return
                    self._cancel_source_switch()
                    from media import TrackState
                    st = TrackState()
                else:
                    seek_transition = self._source_switch_seek
                    self._cancel_source_switch()
            else:
                self._cancel_source_switch()
        first = self.state is None or self.state.found != st.found
        self.state = st
        c = self.card
        if not st.found:
            if first:
                c.set_empty(True, animate=True)
            return
        self._app_id = st.app_id or self._app_id
        if self._startup_wait_show and not self.isVisible():
            self._startup_wait_show = False
            QTimer.singleShot(0, self.show_animated)
        if first:
            self._launch_watch.stop()
            c.empty_btn.set_busy(False)
            c.set_empty(False, animate=True)
        c.set_source(st.app_id)
        self._apply_state(st, animate=not first)
        self._tick()
        if seek_transition is not None:
            old_pos, old_dur = seek_transition
            c.seek.animate_from_ratio(old_pos, old_dur,
                                      self._dpos, st.duration)

    def _apply_state(self, st, animate: bool = True):
        c = self.card
        st.shuffle = self._resolve_pending("shuffle", st.shuffle)
        st.repeat = self._resolve_pending("repeat", st.repeat)
        c.title.setText(st.title or tr("unknown_title"), animate=animate)
        c.artist.setText(st.artist or "", animate=animate)
        c.btn_play.set_playing(st.playing)
        c.set_art_playing(st.playing)
        c.btn_prev.setEnabled(st.can_prev)
        c.btn_next.setEnabled(st.can_next)
        c.btn_shuffle.setEnabled(st.shuffle is not None)
        c.btn_shuffle.setChecked(bool(st.shuffle))
        c.btn_repeat.setEnabled(st.repeat is not None)
        self._apply_repeat(st.repeat or 0)
        c.seek.set_seek_enabled(st.can_seek and st.duration > 0)
        c.seek.set_playing(st.playing)
        c._sync_edit_instance_element_states()

    def on_art(self, data: bytes):
        img = self._art_cache.get(data)
        if img is None:
            img = QImage.fromData(data)
            if not img.isNull():
                self._art_cache[data] = img
                while len(self._art_cache) > 12:
                    self._art_cache.popitem(last=False)
        else:
            self._art_cache.move_to_end(data)
        self._set_art(None if img.isNull() else img)

    def _set_art(self, img: QImage | None):
        self._art_img = img
        self.card.set_art(img)

    def _tick(self):
        st = self.state
        if not st or not st.found:
            return
        now = time.monotonic()
        dt = max(0.0, now - self._dlast)
        raw = st.position + ((now - st.read_at) if st.playing else 0.0)
        if st.duration > 0:
            raw = min(raw, st.duration)
        reset_to_start = False

        # 防回溯：播放中以自己的時鐘前進，輪詢值只做大幅修正
        if self._dkey != st.key:
            old_pos = self._dpos
            old_dur = self.card.seek._dur
            self._dkey = st.key
            self._dpos = raw
            self._seek_pending = None
            if (old_dur > 0 and old_pos >= old_dur * 0.88
                    and raw <= max(3.0, st.duration * 0.04)):
                self.card.seek.animate_reset_to_start(old_pos, old_dur)
                self.card.set_progress_times(0.0, st.duration,
                                             animate_now=True)
                reset_to_start = True
        elif not st.playing:
            if self._seek_ok(st, raw, now):
                if (st.duration > 0 and self._dpos >= st.duration * 0.96
                        and raw <= max(2.0, st.duration * 0.02)):
                    self.card.seek.animate_reset_to_start(self._dpos,
                                                          st.duration)
                    self.card.set_progress_times(0.0, st.duration,
                                                 animate_now=True)
                    reset_to_start = True
                self._dpos = raw
        else:
            self._dpos += dt
            diff = raw - self._dpos
            if abs(diff) > 2.5:          # 真正的跳轉（手動 seek 等）
                if self._seek_ok(st, raw, now):
                    if (st.duration > 0 and self._dpos >= st.duration * 0.96
                            and raw <= max(2.0, st.duration * 0.02)):
                        self.card.seek.animate_reset_to_start(self._dpos,
                                                              st.duration)
                        self.card.set_progress_times(0.0, st.duration,
                                                     animate_now=True)
                        reset_to_start = True
                    self._dpos = raw
            else:
                if (self._seek_pending is not None
                        and st.read_at > self._seek_pending[2] + 0.05):
                    self._seek_pending = None    # 來源已跟上 seek 目標
                if diff > 0:             # 只往前緩慢校正，不回退
                    self._dpos += diff * min(1.0, dt * 1.5)
            if st.duration > 0:
                self._dpos = min(self._dpos, st.duration)
        self._dlast = now

        if not self.card.seek.is_dragging():
            self.card.seek.set_data(self._dpos, st.duration)
            self.card.set_progress_times(
                0.0 if reset_to_start else self._dpos,
                st.duration,
                animate_now=reset_to_start)

    # ---- demo 假資料 ----
    def _demo_fill(self):
        from media import TrackState
        st = TrackState(found=True, title="夜に駆ける - YOASOBI 熱門精選長標題測試",
                        artist="YOASOBI", album="THE BOOK", playing=True,
                        app_id="Spotify.exe",
                        position=83.0, duration=261.0,
                        read_at=time.monotonic(), can_seek=True,
                        shuffle=True, repeat=2)
        img = QImage(300, 300, QImage.Format_RGB32)
        p = QPainter(img)
        g = QLinearGradient(0, 0, 300, 300)
        g.setColorAt(0.0, QColor("#e84d8a"))
        g.setColorAt(0.5, QColor("#b24dd1"))
        g.setColorAt(1.0, QColor("#2b1d4f"))
        p.fillRect(img.rect(), g)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 60))
        p.drawEllipse(150, 40, 180, 180)
        p.setBrush(QColor(255, 255, 255, 30))
        p.drawEllipse(-40, 160, 200, 200)
        p.end()
        self.on_state(st)
        self._set_art(img)

    def closeEvent(self, e):
        self._spectrum.stop()
        self._unregister_hotkey()
        self._save_cfg()
        e.accept()


def main():
    install_qt_message_filter()
    argv = sys.argv[1:]
    demo = "--demo" in argv
    shot = None
    if "--shot" in argv:
        shot = argv[argv.index("--shot") + 1]

    load_settings()
    sync_startup_entry()
    if SETTINGS.get("gpu", False):
        # Qt 6.4+：widget 視窗改用 RHI（D3D11）GPU 合成
        os.environ.setdefault("QT_WIDGETS_RHI", "1")

    app = QApplication(sys.argv)
    install_font_substitutions()
    app.setFont(QFont(safe_font_family(SETTINGS.get("font"))))
    app.setQuitOnLastWindowClosed(False)

    # 單一實例：已有實例在跑就通知它現身，然後直接退出（demo 不檢查）
    holder: dict = {}

    def show_existing():
        w = holder.get("win")
        if w is not None:
            w.show_animated()

    server = None
    if not demo:
        server = acquire_single_instance(show_existing)
        if server is None:
            sys.exit(0)

    _apply_timer_resolution()
    startup_wait = (not demo and not shot and "--panel" not in argv
                    and ("--startup-hide" in argv
                         or ("--startup" in argv
                             and SETTINGS.get("startup_show") == "spotify")))
    win = PlayerWindow(demo=demo, startup_wait=startup_wait)
    holder["win"] = win
    win._single_server = server    # 保持參照，監聽跟著視窗活著
    app.aboutToQuit.connect(win._save_cfg)
    app.aboutToQuit.connect(win._unregister_hotkey)
    app.aboutToQuit.connect(win._spectrum.stop)
    app.aboutToQuit.connect(_release_timer_resolution)
    if not startup_wait:
        fade_in(win, slide=14)

    if "--panel" in argv:
        QTimer.singleShot(300, win._toggle_panel)

    if shot:
        def grab():
            win.grab().save(shot)
            if win._panel is not None and win._panel.isVisible():
                base, ext = os.path.splitext(shot)
                win._panel.grab().save(base + "_panel" + ext)
            app.quit()
        QTimer.singleShot(1500, grab)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
