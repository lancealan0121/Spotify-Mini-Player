"""自訂設定面板與音量彈窗：全部自繪控制項，不用內建外觀。"""
import os
import time

from PySide6.QtCore import (QEvent, QEasingCurve, QPoint, QPointF, QRect,
                            QRectF, QSize, Qt, QTimer,
                            QVariantAnimation, Signal)
from PySide6.QtGui import (QColor, QConicalGradient, QFont, QFontDatabase,
                           QFontMetricsF, QIcon, QLinearGradient, QPainter,
                           QPainterPath, QPen, QPixmap)
from PySide6.QtWidgets import (QApplication, QDialog,
                               QFileDialog,
                               QGraphicsOpacityEffect, QHBoxLayout, QLabel,
                               QLineEdit, QSizePolicy, QVBoxLayout, QWidget)

from style import (AUTO_THEME_MODES, BACKGROUND_IMAGE_MODES, CARD_PRESETS,
                   CONTROLS_ALIGN,
                   GLYPH_CHECK, GLYPH_CHEVRON_DOWN,
                   GLYPH_CLOSE, GLYPH_MUTE, GLYPH_SEARCH, GLYPH_SETTINGS,
                   GLYPH_VOLUME, LANGUAGES, PROGRESS_TIME_MODES,
                   SEEK_STYLES, SETTINGS,
                   SEEK_THUMBS, SETTINGS_PANEL_TYPES, SOURCE_MODES,
                   WEATHER_EFFECTS, Anim, aa,
                   adur, all_themes, anim_on, blend, icon_font,
                   is_safe_ui_font, safe_font_family, soft_shadow,
                   theme_color, theme_gradient, theme_label, tr, ui_font)
from widgets import IconButton

PANEL_W_BASE = 376
PM_BASE = 18              # 陰影留邊


def panel_scale() -> float:
    return float(SETTINGS.get("settings_scale", 1.0))


def panel_px(v: float) -> int:
    return max(1, round(v * panel_scale()))


def panel_f(v: float) -> float:
    return float(v) * panel_scale()


def panel_font(px: int, weight=QFont.Normal) -> QFont:
    f = ui_font(panel_px(px), weight)
    f.setHintingPreference(QFont.PreferNoHinting)
    return f


def panel_icon_font(px: int) -> QFont:
    f = icon_font(panel_px(px))
    f.setHintingPreference(QFont.PreferNoHinting)
    return f


def ensure_safe_app_font():
    app = QApplication.instance()
    if app is None:
        return
    f = QFont(app.font())
    family = safe_font_family(SETTINGS.get("font") or f.family())
    if f.family() != family:
        f.setFamily(family)
        app.setFont(f)


def glyph_icon(glyph: str, px: int, color: QColor) -> QIcon:
    scr = QApplication.primaryScreen()
    dpr = scr.devicePixelRatio() if scr is not None else 1.0
    side = max(1, round(px * dpr))
    pm = QPixmap(side, side)
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    aa(p)
    p.setFont(icon_font(px))
    p.setPen(color)
    p.drawText(QRectF(0, 0, px, px), Qt.AlignCenter, glyph)
    p.end()
    return QIcon(pm)


def panel_w() -> int:
    return panel_px(PANEL_W_BASE)


def panel_margin() -> int:
    return panel_px(PM_BASE)


def source_options():
    return [(k, tr(f"source_{k}")) for k, _ in SOURCE_MODES]


def startup_show_options():
    return [("boot", tr("startup_show_boot")),
            ("spotify", tr("startup_show_spotify"))]


def settings_panel_type_options():
    return [(k, tr(f"settings_panel_{k}"))
            for k, _ in SETTINGS_PANEL_TYPES]


PANEL_CATEGORY_KEYS = (
    "section_general",
    "section_appearance",
    "section_text",
    "section_cover",
    "section_controls",
    "section_buttons",
    "section_performance",
    "section_hotkeys",
)


def panel_category_options():
    return [(k, tr(k)) for k in PANEL_CATEGORY_KEYS]


def seek_options():
    return [(k, tr(f"seek_{k}")) for k, _ in SEEK_STYLES]


def seek_thumb_options():
    return [(k, tr(f"seek_thumb_{k}")) for k, _ in SEEK_THUMBS]


def progress_time_options():
    return [(k, tr(f"progress_time_{k}")) for k, _ in PROGRESS_TIME_MODES]


def auto_theme_options():
    return [(k, tr(f"auto_theme_{k}")) for k, _ in AUTO_THEME_MODES]


def background_image_mode_options():
    return [(k, tr(f"bg_image_{k}")) for k, _ in BACKGROUND_IMAGE_MODES]


def weather_effect_options():
    return [(k, tr(f"weather_{k}")) for k, _ in WEATHER_EFFECTS]


def art_mode_options():
    return [("cover", tr("art_cover")),
            ("vinyl", tr("art_vinyl")),
            ("pulse", tr("art_pulse")),
            ("audio", tr("art_audio"))]


def cover_shape_options():
    return [
        ("rounded", tr("cover_shape_rounded")),
        ("square", tr("cover_shape_square")),
        ("circle", tr("cover_shape_circle")),
    ]


def align_options():
    return [(k, tr(f"align_{k}")) for k, _ in CONTROLS_ALIGN]


def card_preset_options():
    return [(k, tr(f"card_{k}")) for k, _ in CARD_PRESETS]


def _with_alpha(c: QColor, alpha: int) -> QColor:
    out = QColor(c)
    out.setAlpha(alpha)
    return out


_PANEL_GRADIENT: tuple[QColor, QColor] | None = None


def _auto_pair(accent: QColor) -> tuple[QColor, QColor]:
    h, s, v, _ = QColor(accent).getHsv()
    if h < 0:
        h = 132
    c0 = QColor.fromHsv(h, min(255, round(s * 1.05)),
                        min(255, round(v * 1.12)))
    c1 = QColor.fromHsv((h + 34) % 360, min(255, round(s * 0.92)),
                        max(72, round(v * 0.78)))
    return c0, c1


def _solid_pair(accent: QColor) -> tuple[QColor, QColor]:
    return QColor(accent).lighter(125), QColor(accent)


def _set_panel_gradient(pair: tuple[QColor, QColor] | None):
    global _PANEL_GRADIENT
    if pair is None:
        _PANEL_GRADIENT = None
    else:
        _PANEL_GRADIENT = (QColor(pair[0]), QColor(pair[1]))


def _panel_target_pair(accent: QColor) -> tuple[QColor, QColor]:
    pair = theme_gradient()
    if pair is not None:
        return QColor(pair[0]), QColor(pair[1])
    if (SETTINGS.get("theme") == "auto"
            and SETTINGS.get("auto_theme") == "gradient"):
        return _auto_pair(accent)
    return _solid_pair(accent)


def _panel_pair_mode() -> str:
    if theme_gradient() is not None:
        return "explicit"
    if (SETTINGS.get("theme") == "auto"
            and SETTINGS.get("auto_theme") == "gradient"):
        return "auto_gradient"
    return "solid"


def _theme_gradient_brush(rect: QRectF, alpha: int = 255,
                          hover: float = 0.0,
                          lighten: int = 112):
    pair = _PANEL_GRADIENT or theme_gradient()
    if not pair:
        return None
    c0, c1 = QColor(pair[0]), QColor(pair[1])
    c0 = c0.lighter(108)
    c1 = c1.lighter(108)
    if hover > 0:
        c0 = blend(c0, c0.lighter(lighten), hover)
        c1 = blend(c1, c1.lighter(lighten), hover)
    alpha = min(255, round(alpha * 1.18))
    c0.setAlpha(alpha)
    c1.setAlpha(alpha)
    g = QLinearGradient(rect.topLeft(), rect.topRight())
    g.setColorAt(0.0, c0)
    g.setColorAt(1.0, c1)
    return g


def _draw_centered_text(p: QPainter, rect: QRectF, text: str, font: QFont):
    """用字形實際 bounding box 置中，避免圖示字元視覺偏移。"""
    fm = QFontMetricsF(font)
    br = fm.tightBoundingRect(text)
    x = rect.center().x() - br.x() - br.width() / 2
    y = rect.center().y() - br.y() - br.height() / 2
    p.setFont(font)
    p.drawText(QPointF(x, y), text)


def fade_in(win: QWidget, slide: int = 10):
    """視窗淡入 + 微上移動畫。"""
    ms = adur(220, 120)
    if ms <= 0:
        win.setWindowOpacity(1.0)
        win.show()
        return
    end = win.pos()
    win.setWindowOpacity(0.0)
    win.move(end.x(), end.y() + slide)
    win.show()
    anim = QVariantAnimation(win)
    anim.setDuration(ms)
    anim.setEasingCurve(QEasingCurve.OutCubic)
    anim.setStartValue(0.0)
    anim.setEndValue(1.0)

    def step(v):
        win.setWindowOpacity(float(v))
        win.move(end.x(), round(end.y() + slide * (1 - float(v))))
    anim.valueChanged.connect(step)
    anim.start(QVariantAnimation.DeleteWhenStopped)


def fade_out(win: QWidget, on_done, slide: int = 10):
    ms = adur(170, 100)
    if ms <= 0:
        on_done()
        return
    start = win.pos()
    anim = QVariantAnimation(win)
    anim.setDuration(ms)
    anim.setEasingCurve(QEasingCurve.InCubic)
    anim.setStartValue(1.0)
    anim.setEndValue(0.0)

    def step(v):
        win.setWindowOpacity(float(v))
        win.move(start.x(), round(start.y() + slide * (1 - float(v))))

    def done():
        on_done()
        win.move(start)
        win.setWindowOpacity(1.0)
    anim.valueChanged.connect(step)
    anim.finished.connect(done)
    anim.start(QVariantAnimation.DeleteWhenStopped)


# ------------------------------------------------------------ 控制項 ----

class PanelSlider(QWidget):
    """自繪橫向滑桿：把手 hover 漸大、點擊/滾輪滑移動畫、右側數值文字。"""

    changed = Signal(float)
    PAD = 9.0            # 左側留邊，避免把手在 0% 時被裁切

    def __init__(self, mn: float, mx: float, val: float, fmt=None,
                 live=True, accent=None, parent=None,
                 step: float | None = None):
        super().__init__(parent)
        self._mn, self._mx = mn, mx
        self._step = float(step) if step and step > 0 else None
        self._val = self._quantize(val)
        self._disp = self._val       # 畫面顯示值（動畫滑移）
        self._fmt = fmt or (lambda v: f"{v:.0f}")
        self._live = live
        self._accent = QColor(accent) if accent else QColor("#1DB954")
        self._drag = False
        self._hover = 0.0            # hover 進度 0~1（把手放大）
        self.setFixedHeight(panel_px(30))
        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)

        self._va = Anim(self)                    # 顯示值滑移
        self._va.valueChanged.connect(self._on_disp)
        self._ha = Anim(self)                    # 把手 hover
        self._ha.valueChanged.connect(self._on_hover)

    def set_accent(self, c: QColor):
        self._accent = QColor(c)
        self.update()

    def value(self) -> float:
        return self._val

    def set_value(self, value: float, animate: bool = False):
        value = self._quantize(value)
        self._val = value
        self._va.stop()
        self._disp = value
        self.update()

    def _track_w(self) -> float:
        return self.width() - panel_f(52.0) - panel_f(self.PAD)  # 右側留給數值

    def _quantize(self, v: float) -> float:
        v = min(self._mx, max(self._mn, float(v)))
        if self._step is None:
            return v
        steps = round((v - self._mn) / self._step)
        q = round(self._mn + steps * self._step, 6)
        return min(self._mx, max(self._mn, q))

    def _val_from_x(self, x: float) -> float:
        pad = panel_f(self.PAD)
        r = min(1.0, max(0.0, (x - pad) / max(1.0, self._track_w())))
        return self._quantize(self._mn + (self._mx - self._mn) * r)

    # ---- 顯示值動畫 ----

    def _on_disp(self, v):
        self._disp = float(v)
        if self._live:
            self.changed.emit(self._quantize(self._disp))
        self.update()

    def _slide_to(self, v: float, ms: int):
        v = self._quantize(v)
        self._val = v
        if not anim_on() or ms <= 0:
            self._va.stop()
            moved = abs(v - self._disp) > 1e-9
            self._disp = v
            if self._live and moved:
                self.changed.emit(v)
            self.update()
            return
        self._va.stop()
        self._va.setStartValue(self._disp)
        self._va.setEndValue(v)
        self._va.setDuration(ms)
        self._va.setEasingCurve(QEasingCurve.OutCubic)
        self._va.start()

    def _on_hover(self, v):
        self._hover = float(v)
        self.update()

    def _hover_to(self, on: bool):
        self._ha.stop()
        if not anim_on():
            self._hover = 1.0 if on else 0.0
            self.update()
            return
        self._ha.setStartValue(self._hover)
        self._ha.setEndValue(1.0 if on else 0.0)
        self._ha.setDuration(adur(140, 90))
        self._ha.setEasingCurve(QEasingCurve.OutCubic)
        self._ha.start()

    # ---- 滑鼠 ----

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag = True
            self._slide_to(self._val_from_x(e.position().x()),
                           adur(180, 100))

    def mouseMoveEvent(self, e):
        if self._drag:
            # 拖曳直接跟手不做滑移動畫（動畫只留給點擊與滾輪跳轉）
            self._slide_to(self._val_from_x(e.position().x()), 0)

    def mouseReleaseEvent(self, e):
        if self._drag:
            self._drag = False
            if not self._live:
                self.changed.emit(self._val)

    def enterEvent(self, e):
        self._hover_to(True)

    def leaveEvent(self, e):
        self._hover_to(False)

    def wheelEvent(self, e):
        step = self._step or (self._mx - self._mn) / 40.0
        d = step if e.angleDelta().y() > 0 else -step
        self._slide_to(self._val + d, adur(150, 90))
        if not self._live:
            self.changed.emit(self._val)

    def paintEvent(self, _):
        p = QPainter(self)
        aa(p)
        pad = panel_f(self.PAD)
        w = self._track_w()
        cy = self.height() / 2
        ratio = ((self._disp - self._mn) / (self._mx - self._mn)
                 if self._mx > self._mn else 0.0)
        ratio = min(1.0, max(0.0, ratio))
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 34))
        p.drawRoundedRect(QRectF(pad, cy - panel_f(2), w, panel_f(4)),
                          panel_f(2), panel_f(2))
        fill = QRectF(pad, cy - panel_f(2), max(panel_f(4.0), w * ratio),
                      panel_f(4))
        g = _theme_gradient_brush(QRectF(pad, 0, w, self.height()))
        if g is None:
            g = QLinearGradient(pad, 0, pad + w, 0)
            g.setColorAt(0.0, self._accent.lighter(125))
            g.setColorAt(1.0, self._accent)
        p.setBrush(g)
        p.drawRoundedRect(
            fill,
            panel_f(2), panel_f(2))
        r = (panel_f(5.5) + panel_f(0.9) * self._hover
             + (panel_f(0.4) if self._drag else 0.0))
        cx = pad + w * ratio
        p.setBrush(QColor(0, 0, 0, 70))
        p.drawEllipse(QPointF(cx, cy + panel_f(0.8)), r, r)
        p.setBrush(QColor(255, 255, 255))
        p.drawEllipse(QPointF(cx, cy), r, r)
        p.setFont(panel_font(11))
        p.setPen(QColor(255, 255, 255, 188))
        p.drawText(QRectF(pad + w + panel_f(8), 0, panel_f(44), self.height()),
                   Qt.AlignVCenter | Qt.AlignRight, self._fmt(self._val))


class Toggle(QWidget):
    """自繪開關：圓鈕滑動 + 軌道顏色漸變動畫。"""

    changed = Signal(bool)
    W, H = 40, 22

    def __init__(self, checked: bool, accent=None, parent=None):
        super().__init__(parent)
        self._on = bool(checked)
        self._t = 1.0 if self._on else 0.0
        self._hover = 0.0
        self._accent = QColor(accent) if accent else QColor("#1DB954")
        self._anim = Anim(self)
        self._anim.valueChanged.connect(self._on_anim)
        self._ha = Anim(self)
        self._ha.valueChanged.connect(self._on_hover)
        self.setFixedSize(panel_px(self.W), panel_px(self.H))
        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)

    def set_accent(self, c: QColor):
        self._accent = QColor(c)
        self.update()

    def is_checked(self) -> bool:
        return self._on

    def _on_anim(self, v):
        self._t = float(v)
        self.update()

    def _on_hover(self, v):
        self._hover = float(v)
        self.update()

    def _hover_to(self, on: bool):
        self._ha.stop()
        target = 1.0 if on else 0.0
        ms = adur(150 if on else 190, 90)
        if not anim_on() or ms <= 0:
            self._hover = target
            self.update()
            return
        self._ha.setStartValue(self._hover)
        self._ha.setEndValue(target)
        self._ha.setDuration(ms)
        self._ha.setEasingCurve(QEasingCurve.OutCubic)
        self._ha.start()

    def enterEvent(self, e):
        self._hover_to(True)

    def leaveEvent(self, e):
        self._hover_to(False)

    def mousePressEvent(self, e):
        if e.button() != Qt.LeftButton:
            return
        self._on = not self._on
        ms = adur(200, 110)
        self._anim.stop()
        if ms <= 0:
            self._t = 1.0 if self._on else 0.0
            self.update()
        else:
            self._anim.setStartValue(self._t)
            self._anim.setEndValue(1.0 if self._on else 0.0)
            self._anim.setDuration(ms)
            self._anim.setEasingCurve(QEasingCurve.OutCubic)
            self._anim.start()
        self.changed.emit(self._on)

    def paintEvent(self, _):
        p = QPainter(self)
        aa(p)
        w, h = self.width(), self.height()
        track_off = QColor(255, 255, 255, 36)
        t = self._t
        p.setPen(Qt.NoPen)
        grad = _theme_gradient_brush(QRectF(0, 0, w, h), alpha=200)
        if grad is not None:
            p.setBrush(track_off)
            p.drawRoundedRect(QRectF(0, 0, w, h), h / 2, h / 2)
            if t > 0.001:
                p.setOpacity(t)
                p.setBrush(grad)
                p.drawRoundedRect(QRectF(0, 0, w, h), h / 2, h / 2)
                p.setOpacity(1.0)
        else:
            track_on = QColor(self._accent)
            track_on.setAlpha(200)
            col = QColor(round(track_off.red() + (track_on.red() - track_off.red()) * t),
                         round(track_off.green() + (track_on.green() - track_off.green()) * t),
                         round(track_off.blue() + (track_on.blue() - track_off.blue()) * t),
                         round(track_off.alpha() + (track_on.alpha() - track_off.alpha()) * t))
            p.setBrush(col)
            p.drawRoundedRect(QRectF(0, 0, w, h), h / 2, h / 2)
        r = h / 2 - panel_f(3.5) + panel_f(0.9) * self._hover
        cx = h / 2 + (w - h) * t
        p.setBrush(QColor(0, 0, 0, 60))
        p.drawEllipse(QPointF(cx, h / 2 + panel_f(0.8)), r, r)
        p.setBrush(QColor(255, 255, 255, 235 + round(20 * t)))
        p.drawEllipse(QPointF(cx, h / 2), r, r)


class Segmented(QWidget):
    """自繪分段切換，滑動指示塊有動畫。"""

    changing = Signal(str)
    changed = Signal(str)

    def __init__(self, options, current: str, accent=None, parent=None):
        super().__init__(parent)
        self._opts = list(options)          # [(key, label)]
        keys = [k for k, _ in self._opts]
        self._idx = keys.index(current) if current in keys else 0
        self._ind = float(self._idx)        # 指示塊動畫位置
        self._accent = QColor(accent) if accent else QColor("#1DB954")
        self._anim = Anim(self)
        self._anim.valueChanged.connect(self._on_anim)
        self.setFixedHeight(panel_px(30))
        self.setCursor(Qt.PointingHandCursor)

    def set_accent(self, c: QColor):
        self._accent = QColor(c)
        self.update()

    def set_options(self, options, current: str | None = None):
        cur_key = current if current is not None else self._opts[self._idx][0]
        self._opts = list(options)
        keys = [k for k, _ in self._opts]
        idx = keys.index(cur_key) if cur_key in keys else 0
        self._idx = idx
        if self._anim.state() != Anim.Running:
            self._ind = float(idx)
        self.update()

    def _on_anim(self, v):
        self._ind = float(v)
        self.update()

    def _select(self, idx: int):
        if idx == self._idx:
            return
        self.changing.emit(self._opts[idx][0])
        self._idx = idx
        ms = adur(240, 120)
        if ms <= 0:
            self._ind = float(idx)
            self.update()
        else:
            self._anim.stop()
            self._anim.setStartValue(self._ind)
            self._anim.setEndValue(float(idx))
            self._anim.setDuration(ms)
            self._anim.setEasingCurve(QEasingCurve.OutCubic)
            self._anim.start()
        self.changed.emit(self._opts[idx][0])

    def mousePressEvent(self, e):
        cell = self.width() / len(self._opts)
        self._select(min(len(self._opts) - 1,
                         max(0, int(e.position().x() / cell))))

    def paintEvent(self, _):
        p = QPainter(self)
        aa(p)
        w, h = self.width(), self.height()
        cell = w / len(self._opts)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 18))
        p.drawRoundedRect(QRectF(0, 0, w, h), panel_f(9), panel_f(9))
        ind_rect = QRectF(self._ind * cell + panel_f(2.5), panel_f(2.5),
                          cell - panel_f(5), h - panel_f(5))
        grad = _theme_gradient_brush(ind_rect, alpha=96)
        if grad is not None:
            p.setBrush(grad)
        else:
            ind = QColor(self._accent)
            ind.setAlpha(82)
            p.setBrush(ind)
        p.drawRoundedRect(ind_rect, panel_f(7), panel_f(7))
        p.setFont(panel_font(12))
        for i, (_, label) in enumerate(self._opts):
            sel = (i == self._idx)
            p.setPen(QColor(255, 255, 255, 238 if sel else 170))
            p.drawText(QRectF(i * cell, 0, cell, h), Qt.AlignCenter, label)


class KeyBindButton(QWidget):
    """全域快捷鍵綁定：點擊後按下組合鍵，Esc/Backspace/Delete 清除。"""

    changed = Signal(str)

    _SPECIAL = {
        Qt.Key_Space: "Space",
        Qt.Key_Tab: "Tab",
        Qt.Key_Return: "Enter",
        Qt.Key_Enter: "Enter",
        Qt.Key_Escape: "Esc",
        Qt.Key_Backspace: "Backspace",
        Qt.Key_Delete: "Delete",
        Qt.Key_Insert: "Insert",
        Qt.Key_Home: "Home",
        Qt.Key_End: "End",
        Qt.Key_PageUp: "PageUp",
        Qt.Key_PageDown: "PageDown",
        Qt.Key_Left: "Left",
        Qt.Key_Right: "Right",
        Qt.Key_Up: "Up",
        Qt.Key_Down: "Down",
    }
    _MOD_KEYS = {
        Qt.Key_Control, Qt.Key_Shift, Qt.Key_Alt, Qt.Key_Meta,
        Qt.Key_AltGr,
    }

    def __init__(self, current: str, accent=None, parent=None):
        super().__init__(parent)
        self._key = str(current or "").strip()
        self._accent = QColor(accent) if accent else QColor("#1DB954")
        self._capturing = False
        self._hover = 0.0
        self._capture = 0.0
        self._ha = Anim(self)
        self._ha.valueChanged.connect(self._on_hover)
        self._ca = Anim(self)
        self._ca.valueChanged.connect(self._on_capture)
        self.setFixedHeight(panel_px(30))
        self.setMinimumWidth(panel_px(154))
        self.setFocusPolicy(Qt.StrongFocus)
        self.setCursor(Qt.PointingHandCursor)

    def set_accent(self, c: QColor):
        self._accent = QColor(c)
        self.update()

    def _set_key(self, value: str):
        value = value.strip()
        self._capturing = False
        self._capture_to(False)
        if value != self._key:
            self._key = value
            self.changed.emit(value)
        self.clearFocus()
        self.update()

    def _on_hover(self, v):
        self._hover = float(v)
        self.update()

    def _on_capture(self, v):
        self._capture = float(v)
        self.update()

    def _anim_to(self, anim: Anim, cur: float, target: float, ms: int):
        anim.stop()
        if not anim_on() or ms <= 0:
            anim.valueChanged.emit(target)
            return
        anim.setStartValue(cur)
        anim.setEndValue(target)
        anim.setDuration(ms)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.start()

    def _hover_to(self, on: bool):
        self._anim_to(self._ha, self._hover, 1.0 if on else 0.0,
                      adur(150 if on else 180, 90))

    def _capture_to(self, on: bool):
        self._anim_to(self._ca, self._capture, 1.0 if on else 0.0,
                      adur(190 if on else 160, 100))

    def _key_name(self, key: int) -> str:
        if Qt.Key_A <= key <= Qt.Key_Z:
            return chr(ord("A") + key - Qt.Key_A)
        if Qt.Key_0 <= key <= Qt.Key_9:
            return chr(ord("0") + key - Qt.Key_0)
        if Qt.Key_F1 <= key <= Qt.Key_F24:
            return f"F{key - Qt.Key_F1 + 1}"
        return self._SPECIAL.get(key, "")

    def mousePressEvent(self, e):
        if e.button() != Qt.LeftButton:
            return
        self._capturing = True
        self._capture_to(True)
        self.setFocus(Qt.MouseFocusReason)
        self.update()

    def keyPressEvent(self, e):
        key = e.key()
        mods = e.modifiers()
        if key in (Qt.Key_Escape, Qt.Key_Backspace, Qt.Key_Delete) and not mods:
            self._set_key("")
            return
        if key in self._MOD_KEYS:
            return
        name = self._key_name(key)
        if not name:
            return
        parts = []
        if mods & Qt.ControlModifier:
            parts.append("Ctrl")
        if mods & Qt.AltModifier:
            parts.append("Alt")
        if mods & Qt.ShiftModifier:
            parts.append("Shift")
        if mods & Qt.MetaModifier:
            parts.append("Win")
        is_function_key = name.startswith("F") and name[1:].isdigit()
        if not parts and not is_function_key:
            return
        self._set_key("+".join(parts + [name]))

    def focusOutEvent(self, e):
        self._capturing = False
        self._capture_to(False)
        self.update()

    def enterEvent(self, e):
        self._hover_to(True)

    def leaveEvent(self, e):
        self._hover_to(False)

    def paintEvent(self, _):
        p = QPainter(self)
        aa(p)
        w, h = self.width(), self.height()
        bg_alpha = round(16 + 10 * self._hover + 18 * self._capture)
        bg = QColor(255, 255, 255, bg_alpha)
        grad = None
        if self._capture > 0.001:
            bg = QColor(self._accent)
            bg.setAlpha(round(18 + 34 * self._capture))
            grad = _theme_gradient_brush(
                QRectF(0, 0, w, h), alpha=round(64 * self._capture))
        p.setPen(QPen(QColor(255, 255, 255, 42), 1))
        p.setBrush(bg)
        p.drawRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1),
                          panel_f(9), panel_f(9))
        if grad is not None:
            p.setPen(Qt.NoPen)
            p.setBrush(grad)
            p.drawRoundedRect(QRectF(1.0, 1.0, w - 2, h - 2),
                              panel_f(8), panel_f(8))
        text = tr("press_hotkey") if self._capturing else (self._key or tr("unset"))
        p.setFont(panel_font(12))
        p.setPen(QColor(255, 255, 255,
                        round(130 + 100 * max(self._capture, bool(self._key)))))
        p.drawText(QRectF(panel_f(10), 0, w - panel_f(20), h),
                   Qt.AlignCenter, text)


class PanelButton(QWidget):
    """設定面板用文字按鈕：hover/press 與主題 accent 同步。"""

    clicked = Signal()

    def __init__(self, text: str, primary=False, accent=None, parent=None):
        super().__init__(parent)
        self._text = text
        self._primary = bool(primary)
        self._accent = QColor(accent) if accent else QColor("#1DB954")
        self._hover = 0.0
        self._press = 1.0
        self._chevron_enabled = False
        self._chevron_t = 0.0
        self._ha = Anim(self)
        self._ha.valueChanged.connect(self._on_hover)
        self._pa = Anim(self)
        self._pa.valueChanged.connect(self._on_press)
        self._ca = Anim(self)
        self._ca.valueChanged.connect(self._on_chevron)
        self.setFixedHeight(panel_px(30))
        self.setMinimumWidth(panel_px(86))
        self.setCursor(Qt.PointingHandCursor)

    def set_accent(self, c: QColor):
        self._accent = QColor(c)
        self.update()

    def set_text(self, text: str):
        if text == self._text:
            return
        self._text = text
        self.update()

    def set_chevron(self, open_: bool, animate: bool = True):
        self._chevron_enabled = True
        target = 1.0 if open_ else 0.0
        self._ca.stop()
        ms = adur(180, 100)
        if (not animate or not anim_on() or ms <= 0
                or not self.isVisible()):
            self._chevron_t = target
            self.update()
            return
        self._ca.setStartValue(self._chevron_t)
        self._ca.setEndValue(target)
        self._ca.setDuration(ms)
        self._ca.setEasingCurve(QEasingCurve.OutCubic)
        self._ca.start()

    def _on_hover(self, v):
        self._hover = float(v)
        self.update()

    def _on_press(self, v):
        self._press = float(v)
        self.update()

    def _on_chevron(self, v):
        self._chevron_t = float(v)
        self.update()

    def _anim(self, anim: Anim, cur: float, to: float, ms: int):
        anim.stop()
        if not anim_on() or ms <= 0:
            anim.valueChanged.emit(to)
            return
        anim.setStartValue(cur)
        anim.setEndValue(to)
        anim.setDuration(ms)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.start()

    def enterEvent(self, e):
        self._anim(self._ha, self._hover, 1.0, adur(150, 90))

    def leaveEvent(self, e):
        self._anim(self._ha, self._hover, 0.0, adur(180, 100))

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._anim(self._pa, self._press, 0.96, adur(70, 50))

    def mouseReleaseEvent(self, e):
        self._anim(self._pa, self._press, 1.0, adur(150, 90))
        if self.rect().contains(e.position().toPoint()):
            self.clicked.emit()

    def paintEvent(self, _):
        p = QPainter(self)
        aa(p)
        c = self.rect().center()
        p.translate(c.x(), c.y())
        p.scale(self._press, self._press)
        p.translate(-c.x(), -c.y())
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(QColor(255, 255, 255, 44), 1))
        if self._primary:
            grad = _theme_gradient_brush(r, hover=self._hover)
            if grad is not None:
                p.setBrush(grad)
            else:
                p.setBrush(blend(self._accent, self._accent.lighter(118),
                                 self._hover))
        else:
            p.setBrush(QColor(255, 255, 255, 24 + round(16 * self._hover)))
        p.drawRoundedRect(r, panel_f(9), panel_f(9))
        p.setFont(panel_font(12, QFont.DemiBold if self._primary
                             else QFont.Normal))
        p.setPen(QColor(255, 255, 255, 235 if self._primary else 180))
        text_rect = QRectF(r)
        if self._chevron_enabled:
            text_rect.adjust(panel_f(10), 0, -panel_f(28), 0)
        p.drawText(text_rect, Qt.AlignCenter, self._text)
        if self._chevron_enabled:
            ar = QRectF(r.right() - panel_f(27), r.y(),
                        panel_f(22), r.height())
            center = ar.center()
            p.setFont(panel_icon_font(9))
            p.setPen(QColor(255, 255, 255,
                            190 + round(45 * self._hover)))
            p.save()
            p.translate(center)
            p.rotate(-90.0 + 90.0 * self._chevron_t)
            p.translate(-center)
            p.drawText(ar, Qt.AlignCenter, GLYPH_CHEVRON_DOWN)
            p.restore()


class ColorSlot(QWidget):
    clicked = Signal()

    def __init__(self, label: str, color: QColor, accent: QColor,
                 parent=None):
        super().__init__(parent)
        self._label = label
        self._color = QColor(color)
        self._accent = QColor(accent)
        self._selected = False
        self._sel = 0.0
        self._sa = Anim(self)
        self._sa.valueChanged.connect(self._on_sel)
        self._available = True
        self._avail = 1.0
        self._ava = Anim(self)
        self._ava.valueChanged.connect(self._on_available)
        self.setFixedHeight(panel_px(36))
        self.setCursor(Qt.PointingHandCursor)

    def set_color(self, c: QColor):
        self._color = QColor(c)
        self.update()

    def set_selected(self, on: bool):
        self._selected = bool(on)
        self._sa.stop()
        target = 1.0 if self._selected else 0.0
        ms = adur(180, 100)
        if not anim_on() or ms <= 0:
            self._sel = target
            self.update()
            return
        self._sa.setStartValue(self._sel)
        self._sa.setEndValue(target)
        self._sa.setDuration(ms)
        self._sa.setEasingCurve(QEasingCurve.OutCubic)
        self._sa.start()

    def _on_sel(self, v):
        self._sel = float(v)
        self.update()

    def _on_available(self, v):
        self._avail = float(v)
        self.update()

    def set_available(self, on: bool, animate: bool = True):
        self._available = bool(on)
        self.setCursor(Qt.PointingHandCursor if self._available
                       else Qt.ArrowCursor)
        target = 1.0 if self._available else 0.0
        if (self._ava.state() != Anim.Running
                and abs(self._avail - target) < 0.001):
            self._avail = target
            self.update()
            return
        self._ava.stop()
        ms = adur(210, 120) if animate else 0
        if not anim_on() or ms <= 0:
            self._avail = target
            self.update()
            return
        self._ava.setStartValue(self._avail)
        self._ava.setEndValue(target)
        self._ava.setDuration(ms)
        self._ava.setEasingCurve(QEasingCurve.OutCubic)
        self._ava.start()

    def set_accent(self, c: QColor):
        self._accent = QColor(c)
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and self._available:
            self.clicked.emit()

    def paintEvent(self, _):
        p = QPainter(self)
        aa(p)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        alpha = 12 + round(16 * self._avail)
        p.setBrush(QColor(255, 255, 255, alpha))
        pen = QPen(QColor(255, 255, 255, 42), 1)
        if self._sel > 0.001:
            col = blend(QColor(255, 255, 255, 42),
                        self._accent.lighter(125), self._sel)
            pen = QPen(col, 1 + 0.5 * self._sel)
        p.setPen(pen)
        p.drawRoundedRect(r, panel_f(9), panel_f(9))
        sw = QRectF(panel_f(9), panel_f(8), panel_f(20), panel_f(20))
        p.setPen(QPen(QColor(255, 255, 255, 80), 1))
        p.setBrush(_with_alpha(self._color, 120 + round(110 * self._avail)))
        p.drawEllipse(sw)
        p.setFont(panel_font(11))
        p.setPen(QColor(255, 255, 255, 90 + round(120 * self._avail)))
        p.drawText(QRectF(panel_f(36), 0, self.width() - panel_f(42),
                          self.height()), Qt.AlignVCenter | Qt.AlignLeft,
                   self._label)


class SectionLabel(QLabel):
    clicked = Signal()

    def __init__(self, title: str, collapsed: bool = False, parent=None):
        super().__init__(parent)
        self._title = title
        self._collapsed = bool(collapsed)
        self._arrow_t = 0.0 if self._collapsed else 1.0
        self._arrow_anim = Anim(self)
        self._arrow_anim.valueChanged.connect(self._on_arrow_anim)
        self.setCursor(Qt.PointingHandCursor)
        self.setText("")
        self._refresh()

    def set_title(self, title: str):
        self._title = title
        self._refresh()

    def set_collapsed(self, collapsed: bool, animate: bool = True):
        collapsed = bool(collapsed)
        if collapsed == self._collapsed:
            return
        self._collapsed = collapsed
        target = 0.0 if self._collapsed else 1.0
        self._arrow_anim.stop()
        ms = adur(170, 100)
        if not animate or not anim_on() or ms <= 0 or not self.isVisible():
            self._arrow_t = target
            self._refresh()
            return
        self._arrow_anim.setStartValue(self._arrow_t)
        self._arrow_anim.setEndValue(target)
        self._arrow_anim.setDuration(ms)
        self._arrow_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._arrow_anim.start()
        self._refresh()

    def _on_arrow_anim(self, v):
        self._arrow_t = float(v)
        self.update()

    def _refresh(self):
        self.updateGeometry()
        self.update()

    def sizeHint(self):
        fm = QFontMetricsF(self.font())
        return QSize(round(panel_f(18) + fm.horizontalAdvance(self._title)),
                     max(panel_px(19), round(fm.height() + panel_f(4))))

    def minimumSizeHint(self):
        return self.sizeHint()

    def paintEvent(self, _):
        p = QPainter(self)
        aa(p)
        p.setPen(QColor(255, 255, 255, 225))
        arrow_rect = QRectF(0, 0, panel_f(16), self.height())
        c = arrow_rect.center()
        p.save()
        p.translate(c)
        p.rotate(-90.0 + 90.0 * self._arrow_t)
        p.translate(-c)
        p.setFont(panel_icon_font(9))
        p.drawText(arrow_rect, Qt.AlignCenter, GLYPH_CHEVRON_DOWN)
        p.restore()
        p.setFont(self.font())
        text_rect = QRectF(panel_f(18), 0,
                           max(1.0, self.width() - panel_f(18)),
                           self.height())
        p.drawText(text_rect, Qt.AlignVCenter | Qt.AlignLeft, self._title)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked.emit()
            e.accept()
            return
        super().mousePressEvent(e)


class ThemePreview(QWidget):
    def __init__(self, colors, gradient: bool | None = None, parent=None):
        super().__init__(parent)
        self._colors = self._normalize(colors)
        has_gradient = len(colors) >= 2 if gradient is None else bool(gradient)
        self._grad = 1.0 if has_gradient else 0.0
        self._ga = Anim(self)
        self._ga.valueChanged.connect(self._on_grad)
        self.setFixedHeight(panel_px(38))

    def _normalize(self, colors):
        if not colors:
            return [QColor("#1DB954"), QColor("#1DB954")]
        c0 = QColor(colors[0])
        c1 = QColor(colors[1]) if len(colors) >= 2 else QColor(colors[0])
        return [c0, c1]

    def _on_grad(self, v):
        self._grad = float(v)
        self.update()

    def set_gradient_enabled(self, on: bool, animate: bool = True):
        target = 1.0 if on else 0.0
        if (self._ga.state() != Anim.Running
                and abs(self._grad - target) < 0.001):
            self._grad = target
            self.update()
            return
        self._ga.stop()
        ms = adur(210, 120) if animate else 0
        if not anim_on() or ms <= 0:
            self._grad = target
            self.update()
            return
        self._ga.setStartValue(self._grad)
        self._ga.setEndValue(target)
        self._ga.setDuration(ms)
        self._ga.setEasingCurve(QEasingCurve.OutCubic)
        self._ga.start()

    def set_colors(self, colors, gradient: bool | None = None):
        self._colors = self._normalize(colors)
        if gradient is not None:
            self.set_gradient_enabled(gradient)
        else:
            self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        aa(p)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(Qt.NoPen)
        p.setBrush(self._colors[0])
        p.drawRoundedRect(r, panel_f(10), panel_f(10))
        if self._grad > 0.001:
            g = QLinearGradient(r.topLeft(), r.topRight())
            g.setColorAt(0.0, self._colors[0])
            g.setColorAt(1.0, self._colors[1])
            p.setOpacity(self._grad)
            p.setBrush(g)
            p.drawRoundedRect(r, panel_f(10), panel_f(10))
            p.setOpacity(1.0)
        p.setPen(QPen(QColor(255, 255, 255, 44), 1))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(r, panel_f(10), panel_f(10))


class CustomThemeDialog(QDialog):
    """內建自訂主題視窗：單色 / 漸層、HSV 拉桿、即時預覽。"""

    def __init__(self, accent: QColor, parent=None):
        ensure_safe_app_font()
        super().__init__(parent)
        self.setFont(panel_font(12))
        self.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint
                            | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self._accent = QColor(accent)
        alt = blend(self._accent, QColor("#ffffff"), 0.28)
        self._colors = [QColor(self._accent), alt]
        self._mode = "gradient"
        self._active = 0
        self._entry = None
        self._updating = False
        self._sync_serial = 0
        self._drag_off = None
        self._closing = False
        self._opened = False
        self._win_anim = None
        self.setWindowOpacity(0.0)
        self.setFixedSize(panel_px(330), panel_px(392))

        lay = QVBoxLayout(self)
        lay.setContentsMargins(panel_px(18), panel_px(14),
                               panel_px(18), panel_px(16))
        lay.setSpacing(panel_px(10))

        head = QHBoxLayout()
        title = QLabel(tr("custom_theme_title"))
        title.setFont(panel_font(14, QFont.DemiBold))
        title.setStyleSheet("color: rgba(255,255,255,235);")
        head.addWidget(title)
        head.addStretch(1)
        close = IconButton(GLYPH_CLOSE, panel_px(10), panel_px(24),
                           fx="spin")
        close.clicked.connect(self.reject)
        head.addWidget(close)
        lay.addLayout(head)

        self.name = QLineEdit(tr("custom_theme_default"))
        self.name.setFixedHeight(panel_px(30))
        self.name.setStyleSheet(
            "QLineEdit { background: rgba(255,255,255,16);"
            " color: #ececf2; border: 1px solid rgba(255,255,255,36);"
            f" border-radius: {panel_px(9)}px;"
            f" padding: 0 {panel_px(10)}px;"
            f" font: {panel_px(12)}px 'Segoe UI'; }}"
            "QLineEdit:focus { border-color: rgba(255,255,255,80); }")
        lay.addWidget(self.name)

        self.mode = Segmented(
            [("single", tr("custom_single")),
             ("gradient", tr("custom_gradient"))],
            self._mode, accent=self._accent)
        self.mode.changed.connect(self._set_mode)
        lay.addWidget(self.mode)

        slots = QHBoxLayout()
        slots.setSpacing(panel_px(8))
        self.slot0 = ColorSlot(tr("custom_color_a"), self._colors[0],
                               self._accent)
        self.slot1 = ColorSlot(tr("custom_color_b"), self._colors[1],
                               self._accent)
        self.slot0.clicked.connect(lambda: self._set_active(0))
        self.slot1.clicked.connect(lambda: self._set_active(1))
        slots.addWidget(self.slot0, 1)
        slots.addWidget(self.slot1, 1)
        lay.addLayout(slots)

        self.preview = ThemePreview(self._colors, gradient=True)
        lay.addWidget(self.preview)

        self.sl_h = PanelSlider(0, 359, 0,
                                fmt=lambda v: f"{v:.0f}",
                                accent=self._accent)
        self.sl_s = PanelSlider(0, 100, 0,
                                fmt=lambda v: f"{v:.0f}%",
                                accent=self._accent)
        self.sl_v = PanelSlider(0, 100, 0,
                                fmt=lambda v: f"{v:.0f}%",
                                accent=self._accent)
        lay.addWidget(self._labeled_slider(tr("custom_hue"), self.sl_h))
        lay.addWidget(self._labeled_slider(tr("custom_saturation"), self.sl_s))
        lay.addWidget(self._labeled_slider(tr("custom_value"), self.sl_v))
        for sl in (self.sl_h, self.sl_s, self.sl_v):
            sl.changed.connect(self._sliders_changed)

        foot = QHBoxLayout()
        foot.addStretch(1)
        cancel = PanelButton(tr("custom_cancel"), accent=self._accent)
        add = PanelButton(tr("custom_add"), primary=True, accent=self._accent)
        cancel.clicked.connect(self.reject)
        add.clicked.connect(self._accept)
        foot.addWidget(cancel)
        foot.addWidget(add)
        lay.addLayout(foot)

        self._set_active(0, animate=False)
        self._set_mode(self._mode)

    def _labeled_slider(self, text: str, slider: PanelSlider) -> QWidget:
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(panel_px(10))
        lab = QLabel(text)
        lab.setFixedWidth(panel_px(64))
        lab.setFont(panel_font(12))
        lab.setStyleSheet("color: rgba(255,255,255,185);")
        h.addWidget(lab)
        h.addWidget(slider, 1)
        return w

    def _visible_colors(self):
        if self._mode == "single":
            return [self._colors[0]]
        return self._colors

    def _set_mode(self, mode: str):
        self._mode = mode
        is_gradient = mode == "gradient"
        self.slot1.set_available(is_gradient)
        if mode == "single" and self._active == 1:
            self._set_active(0)
        self._refresh_preview()

    def _set_active(self, idx: int, animate: bool = True):
        if idx == 1 and self._mode == "single":
            idx = 0
        self._active = idx
        self.slot0.set_selected(idx == 0)
        self.slot1.set_selected(idx == 1)
        self._sync_sliders(animate=animate)

    def _sync_sliders(self, animate: bool = False):
        c = QColor(self._colors[self._active])
        h, s, v, _ = c.getHsv()
        if h < 0:
            h = 0
        ms = adur(190, 110) if animate else 0
        self._sync_serial += 1
        serial = self._sync_serial
        self._updating = True
        self.sl_h._slide_to(float(h), ms)
        self.sl_s._slide_to(float(s) / 2.55, ms)
        self.sl_v._slide_to(float(v) / 2.55, ms)
        if ms > 0:
            QTimer.singleShot(ms + 24, lambda s=serial: self._finish_sync(s))
        else:
            self._updating = False

    def _finish_sync(self, serial: int):
        if serial == self._sync_serial:
            self._updating = False

    def _sliders_changed(self, _):
        if self._updating:
            return
        h = round(self.sl_h.value())
        s = round(self.sl_s.value() * 2.55)
        v = round(self.sl_v.value() * 2.55)
        self._colors[self._active] = QColor.fromHsv(h, s, v)
        self._refresh_preview()

    def _refresh_preview(self):
        self.slot0.set_color(self._colors[0])
        self.slot1.set_color(self._colors[1])
        self.preview.set_colors(self._colors, gradient=self._mode == "gradient")

    def _accept(self):
        name = self.name.text().strip() or tr("custom_theme_default")
        colors = [c.name() for c in self._visible_colors()]
        self._entry = {
            "key": f"user_{int(time.time() * 1000):x}",
            "name": name[:32],
            "colors": colors,
        }
        self.accept()

    def entry(self):
        return self._entry

    def _window_anim(self, start: float, end: float, done=None):
        ms = adur(180, 100)
        if not anim_on() or ms <= 0:
            self.setWindowOpacity(end)
            if done:
                done()
            return
        base = self.pos()
        slide = panel_px(8)
        # 先停掉上一個（淡入）動畫，避免兩個動畫同時改 opacity/pos 打架
        if self._win_anim is not None:
            self._win_anim.stop()
        anim = QVariantAnimation(self)
        self._win_anim = anim
        anim.setDuration(ms)
        anim.setEasingCurve(QEasingCurve.OutCubic if end > start
                            else QEasingCurve.InCubic)
        anim.setStartValue(start)
        anim.setEndValue(end)

        def step(v):
            t = float(v)
            self.setWindowOpacity(t)
            off = (1.0 - t) * slide
            self.move(base.x(), round(base.y() + off))

        def finish():
            final_y = base.y() if end >= start else base.y() + slide
            self.move(base.x(), round(final_y))
            self.setWindowOpacity(end)
            if done:
                done()

        anim.valueChanged.connect(step)
        anim.finished.connect(finish)
        # 不用 DeleteWhenStopped：其 pending deleteLater 會與 dialog（parent）
        # 析構競爭，dialog 關閉後（或面板重建連帶銷毀）約 1~2 秒觸發
        # use-after-free（exit 0xC0000409）。改由 parent 管理生命週期，
        # 動畫物件隨 dialog 一起析構，不留懸空 timer。
        anim.start()

    def showEvent(self, e):
        super().showEvent(e)
        if not self._opened:
            self._opened = True
            self.setWindowOpacity(0.0)
            self._window_anim(0.0, 1.0)

    def accept(self):
        if self._closing:
            return
        self._closing = True
        self._window_anim(1.0, 0.0, lambda: QDialog.accept(self))

    def reject(self):
        if self._closing:
            return
        self._closing = True
        self._window_anim(1.0, 0.0, lambda: QDialog.reject(self))

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag_off = (e.globalPosition().toPoint()
                              - self.frameGeometry().topLeft())

    def mouseMoveEvent(self, e):
        if self._drag_off is not None and e.buttons() & Qt.LeftButton:
            self.move(e.globalPosition().toPoint() - self._drag_off)

    def mouseReleaseEvent(self, e):
        self._drag_off = None

    def paintEvent(self, _):
        p = QPainter(self)
        aa(p)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(rect, panel_f(16), panel_f(16))
        p.fillPath(path, QColor(21, 21, 27, 250))
        p.setPen(QPen(QColor(255, 255, 255, 28), 1))
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)


def _place_dialog_near_host(dlg: QWidget, host: QWidget | None):
    if host is None:
        return
    scr = QApplication.screenAt(host.frameGeometry().center())
    geo = (scr.availableGeometry() if scr is not None
           else QApplication.primaryScreen().availableGeometry())
    hg = host.frameGeometry()
    gap = panel_px(12)
    x = hg.right() + gap
    if x + dlg.width() > geo.right():
        x = hg.left() - dlg.width() - gap
    x = min(max(geo.left(), x), geo.right() - dlg.width())
    y = min(max(geo.top(), hg.top() + panel_px(6)),
            geo.bottom() - dlg.height())
    dlg.move(x, y)


class ColorEditDialog(QDialog):
    """單一顏色選擇視窗：沿用面板的 HSV 滑桿與預覽。"""

    def __init__(self, title: str, current: str, fallback, accent: QColor,
                 parent=None):
        ensure_safe_app_font()
        super().__init__(parent)
        self.setFont(panel_font(12))
        self.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint
                            | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self._accent = QColor(accent)
        c = QColor(str(current or ""))
        self._color = c if c.isValid() else QColor(fallback)
        if not self._color.isValid():
            self._color = QColor("#ffffff")
        self._result: str | None = None
        self._updating = False
        self._sync_serial = 0
        self._drag_off = None
        self._closing = False
        self._opened = False
        self._win_anim = None
        self.setWindowOpacity(0.0)
        self.setFixedSize(panel_px(310), panel_px(306))

        lay = QVBoxLayout(self)
        lay.setContentsMargins(panel_px(18), panel_px(14),
                               panel_px(18), panel_px(16))
        lay.setSpacing(panel_px(10))

        head = QHBoxLayout()
        title_lab = QLabel(title or tr("choose_color"))
        title_lab.setFont(panel_font(14, QFont.DemiBold))
        title_lab.setStyleSheet("color: rgba(255,255,255,235);")
        head.addWidget(title_lab)
        head.addStretch(1)
        close = IconButton(GLYPH_CLOSE, panel_px(10), panel_px(24),
                           fx="spin")
        close.clicked.connect(self.reject)
        head.addWidget(close)
        lay.addLayout(head)

        self.preview = ThemePreview([self._color], gradient=False)
        lay.addWidget(self.preview)

        self.sl_h = PanelSlider(0, 359, 0,
                                fmt=lambda v: f"{v:.0f}",
                                accent=self._accent)
        self.sl_s = PanelSlider(0, 100, 0,
                                fmt=lambda v: f"{v:.0f}%",
                                accent=self._accent)
        self.sl_v = PanelSlider(0, 100, 0,
                                fmt=lambda v: f"{v:.0f}%",
                                accent=self._accent)
        lay.addWidget(self._labeled_slider(tr("custom_hue"), self.sl_h))
        lay.addWidget(self._labeled_slider(tr("custom_saturation"), self.sl_s))
        lay.addWidget(self._labeled_slider(tr("custom_value"), self.sl_v))
        for sl in (self.sl_h, self.sl_s, self.sl_v):
            sl.changed.connect(self._sliders_changed)

        foot = QHBoxLayout()
        reset = PanelButton(tr("color_reset"), accent=self._accent)
        cancel = PanelButton(tr("custom_cancel"), accent=self._accent)
        apply = PanelButton(tr("color_apply"), primary=True,
                            accent=self._accent)
        reset.clicked.connect(self._reset)
        cancel.clicked.connect(self.reject)
        apply.clicked.connect(self._accept)
        foot.addWidget(reset)
        foot.addStretch(1)
        foot.addWidget(cancel)
        foot.addWidget(apply)
        lay.addLayout(foot)

        self._sync_sliders()

    def _labeled_slider(self, text: str, slider: PanelSlider) -> QWidget:
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(panel_px(10))
        lab = QLabel(text)
        lab.setFixedWidth(panel_px(64))
        lab.setFont(panel_font(12))
        lab.setStyleSheet("color: rgba(255,255,255,185);")
        h.addWidget(lab)
        h.addWidget(slider, 1)
        return w

    def _sync_sliders(self):
        h, s, v, _ = self._color.getHsv()
        if h < 0:
            h = 0
        self._sync_serial += 1
        serial = self._sync_serial
        self._updating = True
        self.sl_h._slide_to(float(h), 0)
        self.sl_s._slide_to(float(s) / 2.55, 0)
        self.sl_v._slide_to(float(v) / 2.55, 0)
        QTimer.singleShot(0, lambda s=serial: self._finish_sync(s))

    def _finish_sync(self, serial: int):
        if serial == self._sync_serial:
            self._updating = False

    def _sliders_changed(self, _):
        if self._updating:
            return
        h = round(self.sl_h.value())
        s = round(self.sl_s.value() * 2.55)
        v = round(self.sl_v.value() * 2.55)
        self._color = QColor.fromHsv(h, s, v)
        self.preview.set_colors([self._color], gradient=False)

    def _reset(self):
        self._result = ""
        self.accept()

    def _accept(self):
        self._result = self._color.name(QColor.HexRgb)
        self.accept()

    def result_color(self) -> str:
        return "" if self._result is None else self._result

    def _window_anim(self, start: float, end: float, done=None):
        ms = adur(180, 100)
        if not anim_on() or ms <= 0:
            self.setWindowOpacity(end)
            if done:
                done()
            return
        base = self.pos()
        slide = panel_px(8)
        # 先停掉上一個（淡入）動畫，避免兩個動畫同時改 opacity/pos 打架
        if self._win_anim is not None:
            self._win_anim.stop()
        anim = QVariantAnimation(self)
        self._win_anim = anim
        anim.setDuration(ms)
        anim.setEasingCurve(QEasingCurve.OutCubic if end > start
                            else QEasingCurve.InCubic)
        anim.setStartValue(start)
        anim.setEndValue(end)

        def step(v):
            t = float(v)
            self.setWindowOpacity(t)
            off = (1.0 - t) * slide
            self.move(base.x(), round(base.y() + off))

        def finish():
            final_y = base.y() if end >= start else base.y() + slide
            self.move(base.x(), round(final_y))
            self.setWindowOpacity(end)
            if done:
                done()

        anim.valueChanged.connect(step)
        anim.finished.connect(finish)
        # 不用 DeleteWhenStopped：其 pending deleteLater 會與 dialog（parent）
        # 析構競爭，dialog 關閉後（或面板重建連帶銷毀）約 1~2 秒觸發
        # use-after-free（exit 0xC0000409）。改由 parent 管理生命週期，
        # 動畫物件隨 dialog 一起析構，不留懸空 timer。
        anim.start()

    def showEvent(self, e):
        super().showEvent(e)
        if not self._opened:
            self._opened = True
            self.setWindowOpacity(0.0)
            self._window_anim(0.0, 1.0)

    def accept(self):
        if self._closing:
            return
        self._closing = True
        self._window_anim(1.0, 0.0, lambda: QDialog.accept(self))

    def reject(self):
        if self._closing:
            return
        self._closing = True
        self._window_anim(1.0, 0.0, lambda: QDialog.reject(self))

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag_off = (e.globalPosition().toPoint()
                              - self.frameGeometry().topLeft())

    def mouseMoveEvent(self, e):
        if self._drag_off is not None and e.buttons() & Qt.LeftButton:
            self.move(e.globalPosition().toPoint() - self._drag_off)

    def mouseReleaseEvent(self, e):
        self._drag_off = None

    def paintEvent(self, _):
        p = QPainter(self)
        aa(p)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(rect, panel_f(16), panel_f(16))
        p.fillPath(path, QColor(21, 21, 27, 250))
        p.setPen(QPen(QColor(255, 255, 255, 28), 1))
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)


class ColorValueButton(QWidget):
    changed = Signal(str)

    def __init__(self, value: str, fallback="#ffffff", title_key="choose_color",
                 accent=None, parent=None):
        super().__init__(parent)
        self._value = self._normalize(value)
        self._fallback_from_accent = str(fallback).lower() == "accent"
        self._fallback = (QColor(accent) if self._fallback_from_accent
                          else QColor(fallback))
        if not self._fallback.isValid():
            self._fallback = QColor("#ffffff")
        self._title_key = title_key
        self._accent = QColor(accent) if accent else QColor("#1DB954")
        self._hover = 0.0
        self._press = 1.0
        self._ha = Anim(self)
        self._ha.valueChanged.connect(self._on_hover)
        self._pa = Anim(self)
        self._pa.valueChanged.connect(self._on_press)
        self.setFixedHeight(panel_px(30))
        self.setMinimumWidth(panel_px(138))
        self.setCursor(Qt.PointingHandCursor)

    def _normalize(self, value: str) -> str:
        c = QColor(str(value or "").strip())
        return c.name(QColor.HexRgb) if c.isValid() else ""

    def value(self) -> str:
        return self._value

    def set_value(self, value: str):
        value = self._normalize(value)
        if value == self._value:
            return
        self._value = value
        self.update()

    def set_accent(self, c: QColor):
        self._accent = QColor(c)
        if self._fallback_from_accent:
            self._fallback = QColor(c)
        self.update()

    def _display_color(self) -> QColor:
        c = QColor(self._value) if self._value else QColor(self._fallback)
        if not c.isValid():
            c = QColor("#ffffff")
        return c

    def _on_hover(self, v):
        self._hover = float(v)
        self.update()

    def _on_press(self, v):
        self._press = float(v)
        self.update()

    def _anim_to(self, anim: Anim, cur: float, target: float, ms: int):
        anim.stop()
        if not anim_on() or ms <= 0:
            anim.valueChanged.emit(target)
            return
        anim.setStartValue(cur)
        anim.setEndValue(target)
        anim.setDuration(ms)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.start()

    def enterEvent(self, e):
        self._anim_to(self._ha, self._hover, 1.0, adur(150, 90))

    def leaveEvent(self, e):
        self._anim_to(self._ha, self._hover, 0.0, adur(180, 100))

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._anim_to(self._pa, self._press, 0.96, adur(70, 50))

    def mouseReleaseEvent(self, e):
        self._anim_to(self._pa, self._press, 1.0, adur(150, 90))
        if not self.rect().contains(e.position().toPoint()):
            return
        dlg = ColorEditDialog(tr(self._title_key), self._value,
                              self._fallback, self._accent, self.window())
        _place_dialog_near_host(dlg, self.window())
        if dlg.exec() == QDialog.Accepted:
            value = dlg.result_color()
            self.set_value(value)
            self.changed.emit(self._value)

    def paintEvent(self, _):
        p = QPainter(self)
        aa(p)
        c = self.rect().center()
        p.translate(c.x(), c.y())
        p.scale(self._press, self._press)
        p.translate(-c.x(), -c.y())
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(QColor(255, 255, 255, 40 + round(28 * self._hover)), 1))
        p.setBrush(QColor(255, 255, 255, 18 + round(12 * self._hover)))
        p.drawRoundedRect(r, panel_f(9), panel_f(9))
        sw = QRectF(panel_f(9), panel_f(7), panel_f(16), panel_f(16))
        sw_col = self._display_color()
        if not self._value:
            sw_col.setAlpha(135)
        p.setPen(QPen(QColor(255, 255, 255, 82), 1))
        p.setBrush(sw_col)
        p.drawEllipse(sw)
        if not self._value:
            p.setPen(QPen(QColor(20, 20, 24, 170), 1.4))
            p.drawLine(sw.bottomLeft() + QPointF(2, -1),
                       sw.topRight() + QPointF(-2, 1))
        txt = self._value.upper() if self._value else tr("unset")
        p.setFont(panel_font(11, QFont.DemiBold if self._value else QFont.Normal))
        p.setPen(QColor(255, 255, 255, 218 if self._value else 150))
        p.drawText(QRectF(panel_f(33), 0,
                          self.width() - panel_f(42), self.height()),
                   Qt.AlignVCenter | Qt.AlignLeft, txt)


class _PathDisplay(QWidget):
    def __init__(self, path: str, parent=None):
        super().__init__(parent)
        self._path = str(path or "")
        self.setFixedHeight(panel_px(30))
        self.setMinimumWidth(panel_px(78))

    def set_path(self, path: str):
        self._path = str(path or "")
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        aa(p)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(QColor(255, 255, 255, 38), 1))
        p.setBrush(QColor(255, 255, 255, 16))
        p.drawRoundedRect(r, panel_f(9), panel_f(9))
        text = os.path.basename(self._path) if self._path else tr("unset")
        p.setFont(panel_font(11))
        p.setPen(QColor(255, 255, 255, 205 if self._path else 145))
        fm = QFontMetricsF(p.font())
        avail = max(1, self.width() - panel_px(18))
        text = fm.elidedText(text, Qt.ElideMiddle, avail)
        p.drawText(r.adjusted(panel_f(9), 0, -panel_f(9), 0),
                   Qt.AlignVCenter | Qt.AlignLeft, text)


class ImagePathPicker(QWidget):
    changed = Signal(str)

    def __init__(self, value: str, accent=None, parent=None,
                 title_key: str = "background_image"):
        super().__init__(parent)
        self._value = str(value or "")
        self._accent = QColor(accent) if accent else QColor("#1DB954")
        self._title_key = title_key
        self.setFixedHeight(panel_px(30))
        self.setMinimumWidth(panel_px(210))
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(panel_px(6))
        self.display = _PathDisplay(self._value)
        self.btn_choose = PanelButton(tr("choose_image"), accent=self._accent)
        self.btn_clear = PanelButton(tr("clear_image"), accent=self._accent)
        self.btn_choose.setFixedWidth(panel_px(58))
        self.btn_clear.setFixedWidth(panel_px(52))
        lay.addWidget(self.display, 1)
        lay.addWidget(self.btn_choose)
        lay.addWidget(self.btn_clear)
        self.btn_choose.clicked.connect(self._choose)
        self.btn_clear.clicked.connect(self._clear)

    def value(self) -> str:
        return self._value

    def set_value(self, value: str):
        value = str(value or "")
        if value == self._value:
            return
        self._value = value
        self.display.set_path(value)

    def set_accent(self, c: QColor):
        self._accent = QColor(c)
        self.btn_choose.set_accent(c)
        self.btn_clear.set_accent(c)

    def refresh_language(self):
        self.btn_choose.set_text(tr("choose_image"))
        self.btn_clear.set_text(tr("clear_image"))
        self.display.update()

    def _choose(self):
        start = self._value if self._value else os.path.expanduser("~")
        if os.path.isfile(start):
            start = os.path.dirname(start)
        path, _ = QFileDialog.getOpenFileName(
            self, tr(self._title_key), start,
            "Images (*.png *.jpg *.jpeg *.bmp *.webp);;All Files (*)")
        if not path:
            return
        self.set_value(path)
        self.changed.emit(self._value)

    def _clear(self):
        if not self._value:
            return
        self.set_value("")
        self.changed.emit("")


class SwatchRow(QWidget):
    """主題色票（多列）：auto 彩虹圓、glass 玻璃圓、單色圓、漸層圓。

    收合時只顯示第一列，右側小箭頭展開其餘列；展開/收合會改變自身高度，
    發 size_changed 讓設定面板跟著伸縮。
    """

    changed = Signal(str)
    custom_added = Signal(dict)     # 新增自訂主題：{key, name, colors}
    custom_deleted = Signal(str)    # 刪除使用者自訂主題 key
    size_changed = Signal()
    D = 22
    GAP = 10
    PAD = 8        # 左右內距，避免選取圓環被裁切
    COLS = 6       # 每列色票數（第一列 = 收合時可見的主題）
    ROW_H = 34

    @classmethod
    def row_h(cls) -> int:
        return panel_px(cls.ROW_H)

    def __init__(self, current: str, parent=None, expanded: bool | None = None):
        super().__init__(parent)
        self._themes = all_themes()
        self._keys = [k for k, _, _ in self._themes]
        self._current = current if current in self._keys else "auto"
        self._hover = -1        # 色票索引；-2 = 展開鈕；-1 = 無
        self._hover_levels = [0.0 for _ in self._keys]
        self._hover_starts = list(self._hover_levels)
        self._hover_targets = list(self._hover_levels)
        self._appear_key = ""
        self._appear = 1.0
        self._aa = Anim(self)
        self._aa.valueChanged.connect(self._on_appear)
        self._aa.finished.connect(self._appear_done)
        self._remove_key = ""
        self._remove_t = 0.0
        self._ra = Anim(self)
        self._ra.valueChanged.connect(self._on_remove)
        self._ra.finished.connect(self._remove_done)
        self._sel_pos = float(self._keys.index(self._current)
                              if self._current in self._keys else -1)
        self._sel_from = self._sel_pos
        self._sel_to = self._sel_pos
        self._sel_t = 1.0
        self._sa = Anim(self)
        self._sa.valueChanged.connect(self._on_select)
        self._sa.finished.connect(self._select_done)
        # 目前主題在隱藏列時直接展開，選取狀態才看得到
        self._expanded = (self._keys.index(self._current) >= self.COLS
                          if expanded is None else bool(expanded))
        self._show_all = self._expanded   # 伸縮動畫中仍要畫出全部列
        self._ea = Anim(self)             # 展開/收合高度動畫
        self._ea.valueChanged.connect(self._on_h)
        self._ea.finished.connect(self._expand_done)
        self._arrow_t = 1.0 if self._expanded else 0.0
        self._arrow_anim = Anim(self)
        self._arrow_anim.valueChanged.connect(self._on_arrow_anim)
        self._ha = Anim(self)             # 色票 hover 放大動畫
        self._ha.valueChanged.connect(self._on_hover_anim)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(self.row_h() * self._rows())

    def _reload_themes(self, current: str | None = None, reveal=False,
                       appear: str | None = None, keep_missing=False):
        self._themes = all_themes()
        self._keys = [k for k, _, _ in self._themes]
        if current in self._keys:
            self._current = current
        elif self._current not in self._keys and not keep_missing:
            self._current = "auto"
        self._hover = -1
        self._hover_levels = [0.0 for _ in self._keys]
        self._hover_starts = list(self._hover_levels)
        self._hover_targets = list(self._hover_levels)
        if reveal and self._current in self._keys:
            self._expanded = self._keys.index(self._current) >= self.COLS
            self._show_all = self._expanded
            self._arrow_t = 1.0 if self._expanded else 0.0
        self._sel_pos = float(self._keys.index(self._current)
                              if self._current in self._keys else -1)
        self._sel_from = self._sel_pos
        self._sel_to = self._sel_pos
        self._sel_t = 1.0
        self.setFixedHeight(self.row_h() * self._rows())
        self.size_changed.emit()
        if appear in self._keys:
            self._start_appear(appear)
        self.update()

    def _is_user_theme(self, idx: int) -> bool:
        return (0 <= idx < len(self._keys)
                and self._keys[idx].startswith("user_"))

    def _on_appear(self, v):
        self._appear = float(v)
        self.update()

    def _appear_done(self):
        self._appear = 1.0
        self._appear_key = ""
        self.update()

    def _start_appear(self, key: str):
        self._aa.stop()
        self._appear_key = key
        self._appear = 0.0
        ms = adur(220, 120)
        if not anim_on() or ms <= 0:
            self._appear_done()
            return
        self._aa.setStartValue(0.0)
        self._aa.setEndValue(1.0)
        self._aa.setDuration(ms)
        self._aa.setEasingCurve(QEasingCurve.OutCubic)
        self._aa.start()

    def _on_remove(self, v):
        self._remove_t = float(v)
        self.update()

    def _remove_done(self):
        key = self._remove_key
        self._remove_key = ""
        self._remove_t = 0.0
        if not key:
            self.update()
            return
        keep = key == self._current
        self.custom_deleted.emit(key)
        self._reload_themes(self._current, keep_missing=keep)

    def _delete_current(self):
        if self._current not in self._keys:
            return
        idx = self._keys.index(self._current)
        if not self._is_user_theme(idx) or self._remove_key:
            return
        self._ra.stop()
        self._remove_key = self._current
        self._remove_t = 0.0
        ms = adur(190, 110)
        if not anim_on() or ms <= 0:
            self._remove_t = 1.0
            self._remove_done()
            return
        self._ra.setStartValue(0.0)
        self._ra.setEndValue(1.0)
        self._ra.setDuration(ms)
        self._ra.setEasingCurve(QEasingCurve.InCubic)
        self._ra.start()

    def _on_select(self, v):
        self._sel_t = float(v)
        self._sel_pos = self._sel_from + (self._sel_to - self._sel_from) * self._sel_t
        self.update()

    def _select_done(self):
        self._sel_t = 1.0
        self._sel_pos = self._sel_to
        self.update()

    def _animate_selection_to(self, idx: int):
        self._sa.stop()
        if idx < 0:
            self._sel_pos = -1.0
            self._sel_from = self._sel_to = -1.0
            self._sel_t = 1.0
            self.update()
            return
        had_from = self._sel_pos >= 0
        self._sel_from = self._sel_pos if had_from else float(idx)
        self._sel_to = float(idx)
        self._sel_t = 0.0
        ms = adur(230, 130)
        if (not anim_on() or ms <= 0
                or (had_from and self._sel_from == self._sel_to)):
            self._select_done()
            return
        self._sa.setStartValue(0.0)
        self._sa.setEndValue(1.0)
        self._sa.setDuration(ms)
        self._sa.setEasingCurve(QEasingCurve.OutCubic)
        self._sa.start()

    def _set_current(self, key: str, animate=True):
        if key not in self._keys:
            return
        old = self._current
        self._current = key
        idx = self._keys.index(key)
        if animate and old != key:
            self._animate_selection_to(idx)
        else:
            self._sel_pos = self._sel_from = self._sel_to = float(idx)
            self._sel_t = 1.0
            self.update()

    def _center_lerp(self, a: float, b: float, t: float) -> QPointF:
        if a < 0 or b < 0:
            return QPointF()
        c0 = self._center(max(0, min(len(self._keys) - 1, int(round(a)))))
        c1 = self._center(max(0, min(len(self._keys) - 1, int(round(b)))))
        return QPointF(c0.x() + (c1.x() - c0.x()) * t,
                       c0.y() + (c1.y() - c0.y()) * t)

    def _draw_check(self, p: QPainter, center: QPointF, alpha: float):
        if alpha <= 0.01:
            return
        d = panel_f(self.D)
        font = panel_icon_font(11)
        font.setWeight(QFont.Bold)
        p.setOpacity(alpha)
        p.setPen(QColor(255, 255, 255, 245))
        rect = QRectF(center.x() - d / 2, center.y() - d / 2 + panel_f(1.1),
                      d, d)
        _draw_centered_text(p, rect, GLYPH_CHECK, font)
        p.setOpacity(1.0)

    def _draw_selection_ring(self, p: QPainter, center: QPointF,
                             grow: float, alpha: float):
        if alpha <= 0.01:
            return
        grow = max(0.0, min(1.0, grow))
        d = panel_f(self.D)
        radius = (d / 2 + panel_f(2.2)) * (0.76 + 0.24 * grow)
        p.setOpacity(alpha)
        p.setPen(QPen(QColor(255, 255, 255, 230), 2))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(center, radius, radius)
        p.setOpacity(1.0)

    def is_expanded(self) -> bool:
        return self._expanded

    def _rows(self) -> int:
        if not self._expanded:
            return 1
        return (len(self._keys) + self.COLS - 1) // self.COLS

    def _visible(self) -> int:
        return len(self._keys) if self._show_all else self.COLS

    def _on_h(self, v):
        h = round(float(v))
        if h == self.height():
            self.update()
            return
        self.setFixedHeight(h)
        self.size_changed.emit()   # 面板每幀跟著伸縮

    def _expand_done(self):
        self._show_all = self._expanded
        self.size_changed.emit()
        self.update()

    def _on_arrow_anim(self, v):
        self._arrow_t = float(v)
        self.update()

    def _on_hover_anim(self, v):
        t = float(v)
        self._hover_levels = [
            a + (b - a) * t
            for a, b in zip(self._hover_starts, self._hover_targets)
        ]
        self.update()

    def _hover_to(self, idx: int):
        self._ha.stop()          # 切換色票時從目前進度接著跑
        self._hover_starts = list(self._hover_levels)
        self._hover_targets = [0.0 for _ in self._keys]
        if idx >= 0:
            self._hover_targets[idx] = 1.0
        ms = adur(170 if idx >= 0 else 210, 110)
        if not anim_on() or ms <= 0:
            self._hover_levels = list(self._hover_targets)
            self.update()
            return
        self._ha.setStartValue(0.0)
        self._ha.setEndValue(1.0)
        self._ha.setDuration(ms)
        self._ha.setEasingCurve(QEasingCurve.OutCubic)
        self._ha.start()

    def _toggle_expand(self):
        self._ea.stop()            # 動畫中再點：從目前高度接著動
        self._arrow_anim.stop()
        self._expanded = not self._expanded
        target = self.row_h() * self._rows()
        arrow_target = 1.0 if self._expanded else 0.0
        ms = adur(280, 150)
        if not anim_on() or ms <= 0:
            self._show_all = self._expanded
            self._arrow_t = arrow_target
            self.setFixedHeight(target)
            self.size_changed.emit()
            self.update()
            return
        self._show_all = True      # 往下展開/往上收合過程都看得到全部列
        start_h = float(self.height())
        self._ea.setStartValue(start_h)
        self._ea.setEndValue(float(target))
        self._ea.setDuration(ms)
        self._ea.setEasingCurve(QEasingCurve.OutCubic)
        self._ea.start()
        self._arrow_anim.setStartValue(self._arrow_t)
        self._arrow_anim.setEndValue(arrow_target)
        self._arrow_anim.setDuration(ms)
        self._arrow_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._arrow_anim.start()
        self.size_changed.emit()

    def _center(self, i: int) -> QPointF:
        row, col = divmod(i, self.COLS)
        d, gap, pad, row_h = (panel_f(self.D), panel_f(self.GAP),
                              panel_f(self.PAD), panel_f(self.ROW_H))
        return QPointF(pad + col * (d + gap) + d / 2,
                       row_h * row + row_h / 2)

    def _toggle_rect(self) -> QRectF:
        d, gap, pad = panel_f(self.D), panel_f(self.GAP), panel_f(self.PAD)
        x = pad + self.COLS * (d + gap) - gap + panel_f(7)
        return QRectF(x, (panel_f(self.ROW_H) - panel_f(20)) / 2,
                      panel_f(20), panel_f(20))

    def _idx_at(self, pos) -> int:
        if self._toggle_rect().contains(pos):
            return -2
        d, gap, pad, row_h = (panel_f(self.D), panel_f(self.GAP),
                              panel_f(self.PAD), panel_f(self.ROW_H))
        col = int((pos.x() - pad) // (d + gap))
        within = (pos.x() - pad) - col * (d + gap)
        row = int(pos.y() // row_h)
        i = row * self.COLS + col
        if (0 <= col < self.COLS and within <= d
                and 0 <= i < self._visible()):
            return i
        return -1

    def mouseMoveEvent(self, e):
        idx = self._idx_at(e.position())
        if idx != self._hover:
            self._hover = idx
            self._hover_to(idx)

    def leaveEvent(self, e):
        self._hover = -1
        self._hover_to(-1)

    def mousePressEvent(self, e):
        self.setFocus(Qt.MouseFocusReason)
        idx = self._idx_at(e.position())
        if e.button() != Qt.LeftButton:
            return
        if idx == -2:
            self._toggle_expand()
        elif idx >= 0:
            key = self._keys[idx]
            if self._themes[idx][2] == "custom":
                self._pick_custom()
                return
            if key != self._current:
                self._set_current(key, animate=True)
                self.changed.emit(key)

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Delete, Qt.Key_Backspace):
            self._delete_current()
            e.accept()
            return
        super().keyPressEvent(e)

    def _pick_custom(self):
        """開啟內建自訂主題視窗，成功後直接加入列表並選用。"""
        accent = theme_color() or QColor("#1DB954")
        dlg = CustomThemeDialog(accent, self.window())
        host = self.window()
        if host is not None:
            scr = QApplication.screenAt(host.frameGeometry().center())
            geo = (scr.availableGeometry() if scr is not None
                   else QApplication.primaryScreen().availableGeometry())
            hg = host.frameGeometry()
            gap = panel_px(12)
            x = hg.right() + gap
            if x + dlg.width() > geo.right():
                x = hg.left() - dlg.width() - gap
            x = min(max(geo.left(), x), geo.right() - dlg.width())
            y = min(max(geo.top(), hg.top() + panel_px(6)),
                    geo.bottom() - dlg.height())
            dlg.move(x, y)
        if dlg.exec() != QDialog.Accepted or not dlg.entry():
            return
        entry = dlg.entry()
        self.custom_added.emit(entry)
        self._reload_themes(entry["key"], reveal=True, appear=entry["key"])
        self.changed.emit(entry["key"])

    def _swatch_brush(self, spec, c: QPointF):
        """依主題規格回傳填色（單色 / 漸層 / auto 彩虹）。"""
        d = panel_f(self.D)
        if spec is None:                       # auto：彩虹圓
            g = QConicalGradient(c, -90)
            for stop, col in ((0.0, "#e8638c"), (0.25, "#e0a83c"),
                              (0.5, "#1db954"), (0.75, "#3d9be9"),
                              (1.0, "#e8638c")):
                g.setColorAt(stop, QColor(col))
            return g
        if isinstance(spec, tuple):            # 漸層：左上 → 右下
            g = QLinearGradient(c.x() - d / 2, c.y() - d / 2,
                                c.x() + d / 2, c.y() + d / 2)
            g.setColorAt(0.0, QColor(spec[0]))
            g.setColorAt(1.0, QColor(spec[1]))
            return g
        return QColor(spec)

    def paintEvent(self, _):
        p = QPainter(self)
        aa(p)
        for i in range(self._visible()):
            key, _, spec = self._themes[i]
            is_custom = spec == "custom"
            c = self._center(i)
            d = panel_f(self.D)
            hov = self._hover_levels[i] if i < len(self._hover_levels) else 0.0
            appear = self._appear if key == self._appear_key else 1.0
            remove = 1.0 - self._remove_t if key == self._remove_key else 1.0
            vis = appear * remove
            r = (d / 2 - panel_f(1.5) + panel_f(1.8) * hov) * (
                0.68 + 0.32 * vis)
            p.setOpacity(vis)
            p.setPen(Qt.NoPen)
            if is_custom:
                p.setBrush(QColor(255, 255, 255, 34 + round(18 * hov)))
                p.drawEllipse(c, r, r)
                p.setPen(QPen(QColor(255, 255, 255, 120), 1))
                p.setBrush(Qt.NoBrush)
                p.drawEllipse(c, r - 0.5, r - 0.5)
                p.setPen(QColor(255, 255, 255, 225))
                font = panel_icon_font(9)
                _draw_centered_text(
                    p, QRectF(c.x() - d / 2 + panel_f(0.6),
                              c.y() - d / 2, d, d),
                    GLYPH_SETTINGS, font)
            elif spec == "glass":              # 玻璃：透白圓 + 邊框 + 高光
                p.setBrush(QColor(255, 255, 255, 46))
                p.drawEllipse(c, r, r)
                hl = QLinearGradient(c.x() - r, c.y() - r,
                                     c.x() + r, c.y() + r)
                hl.setColorAt(0.0, QColor(255, 255, 255, 120))
                hl.setColorAt(0.55, QColor(255, 255, 255, 0))
                p.setBrush(hl)
                p.drawEllipse(c, r, r)
                p.setPen(QPen(QColor(255, 255, 255, 130), 1))
                p.setBrush(Qt.NoBrush)
                p.drawEllipse(c, r - 0.5, r - 0.5)
            else:
                p.setBrush(self._swatch_brush(spec, c))
                p.drawEllipse(c, r, r)
            p.setOpacity(1.0)
        if (self._current in self._keys and self._sel_pos >= 0
                and self._keys.index(self._current) < self._visible()):
            cur_idx = self._keys.index(self._current)
            sel_alpha = 1.0 - self._remove_t if self._current == self._remove_key else 1.0
            if self._sa.state() == Anim.Running:
                old_idx = int(round(self._sel_from))
                new_idx = cur_idx
                new_alpha = min(1.0, self._sel_t * 1.15)
                if self._sel_from != self._sel_to:
                    old_alpha = max(0.0, 1.0 - self._sel_t * 1.15)
                    if 0 <= old_idx < self._visible():
                        old_c = self._center(old_idx)
                        self._draw_selection_ring(
                            p, old_c, 1.0 - self._sel_t, old_alpha)
                        self._draw_check(
                            p, old_c,
                            max(0.0, 1.0 - self._sel_t * 1.7))
                if 0 <= new_idx < self._visible():
                    new_c = self._center(new_idx)
                    self._draw_selection_ring(p, new_c, self._sel_t,
                                              sel_alpha * new_alpha)
                    self._draw_check(
                        p, new_c,
                        sel_alpha * max(0.0, (self._sel_t - 0.35) / 0.65))
            else:
                self._draw_selection_ring(p, self._center(cur_idx), 1.0,
                                          sel_alpha)
                self._draw_check(p, self._center(cur_idx), sel_alpha)
        # 展開/收合鈕（第一列右側小箭頭）
        tr = self._toggle_rect()
        p.setPen(QColor(255, 255, 255, 235 if self._hover == -2 else 145))
        p.setFont(panel_icon_font(10))
        c = tr.center()
        p.save()
        p.translate(c)
        p.rotate(-90.0 + 90.0 * self._arrow_t)
        p.translate(-c)
        p.drawText(tr, Qt.AlignCenter, GLYPH_CHEVRON_DOWN)
        p.restore()

    def sizeHint(self):
        from PySide6.QtCore import QSize
        w = (panel_f(self.PAD) * 2
             + self.COLS * (panel_f(self.D) + panel_f(self.GAP))
             - panel_f(self.GAP) + panel_f(27))
        return QSize(round(w), max(self.minimumHeight(), self.height()))


class _FontList(QWidget):
    selected = Signal(str)

    def __init__(self, families: list[str], current: str, accent: QColor,
                 parent=None):
        super().__init__(parent)
        self._all = list(families)
        self._items = list(families)
        self._current = str(current or "")
        self._accent = QColor(accent)
        self._hover = -1
        self._scroll = 0.0
        self._target_scroll = 0.0
        self._scroll_hover = False
        self._scroll_hover_t = 0.0
        self._scroll_drag = False
        self._scroll_drag_delta = 0.0
        self._sa = Anim(self)
        self._sa.valueChanged.connect(self._on_scroll)
        self._scroll_ha = Anim(self)
        self._scroll_ha.valueChanged.connect(self._on_scrollbar_hover)
        self._row_h = panel_px(28)
        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(self._row_h * 7)

    def set_accent(self, c: QColor):
        self._accent = QColor(c)
        self.update()

    def set_filter(self, text: str):
        q = str(text or "").strip().lower()
        if q:
            self._items = [f for f in self._all if q in f.lower()]
        else:
            self._items = list(self._all)
        self._sa.stop()
        self._scroll = 0.0
        self._target_scroll = 0.0
        self._hover = -1
        self._scroll_hover = False
        self._scroll_hover_to(False)
        self.update()

    def set_current(self, text: str):
        self._current = str(text or "")
        self.update()

    def first_item(self) -> str:
        return self._items[0] if self._items else ""

    def _visible_rows(self) -> int:
        return max(1, self.height() // max(1, self._row_h) + 2)

    def _max_scroll(self) -> float:
        return max(0.0, len(self._items) * self._row_h - self.height())

    def _clamp_scroll(self, value: float) -> float:
        return max(0.0, min(self._max_scroll(), float(value)))

    def _scrollbar_geometry(self):
        if self._max_scroll() <= 1:
            return None
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        total_h = max(1.0, float(len(self._items) * self._row_h))
        thumb_h = max(panel_f(24), rect.height() * rect.height() / total_h)
        thumb_h = min(rect.height(), thumb_h)
        span = max(1.0, rect.height() - thumb_h)
        thumb_y = rect.y() + span * (self._scroll / self._max_scroll())
        hit = QRectF(rect.right() - panel_f(16), rect.y(),
                     panel_f(16), rect.height())
        thumb = QRectF(rect.right() - panel_f(5), thumb_y,
                       panel_f(3), thumb_h)
        thumb_hit = QRectF(hit.x(), thumb_y, hit.width(), thumb_h)
        return hit, thumb, thumb_hit

    def _set_scrollbar_hover(self, pos: QPointF | None) -> bool:
        geo = self._scrollbar_geometry()
        hover = bool(geo is not None and pos is not None
                     and geo[0].contains(pos))
        if hover != self._scroll_hover:
            self._scroll_hover = hover
            self._scroll_hover_to(hover)
        if not self._scroll_drag:
            self.setCursor(Qt.OpenHandCursor if hover else Qt.PointingHandCursor)
        return hover

    def _on_scrollbar_hover(self, value):
        self._scroll_hover_t = max(0.0, min(1.0, float(value)))
        self.update()

    def _scroll_hover_to(self, on: bool):
        target = 1.0 if on else 0.0
        self._scroll_ha.stop()
        ms = adur(150 if on else 180, 90)
        if not anim_on() or ms <= 0:
            self._scroll_hover_t = target
            self.update()
            return
        self._scroll_ha.setStartValue(self._scroll_hover_t)
        self._scroll_ha.setEndValue(target)
        self._scroll_ha.setDuration(ms)
        self._scroll_ha.setEasingCurve(QEasingCurve.OutCubic)
        self._scroll_ha.start()

    def _scroll_from_thumb_y(self, y: float, drag_delta: float) -> float:
        geo = self._scrollbar_geometry()
        if geo is None:
            return self._scroll
        hit, thumb, _ = geo
        span = max(1.0, hit.height() - thumb.height())
        ratio = (float(y) - drag_delta - hit.y()) / span
        return self._clamp_scroll(ratio * self._max_scroll())

    def _set_scroll_direct(self, value: float):
        self._sa.stop()
        self._scroll = self._clamp_scroll(value)
        self._target_scroll = self._scroll
        self.update()

    def _begin_scrollbar_drag(self, pos: QPointF) -> bool:
        geo = self._scrollbar_geometry()
        if geo is None:
            return False
        hit, thumb, thumb_hit = geo
        if not hit.contains(pos):
            return False
        self._scroll_drag = True
        self._scroll_hover = True
        self._scroll_hover_to(True)
        self._sa.stop()
        if thumb_hit.contains(pos):
            self._scroll_drag_delta = pos.y() - thumb.y()
        else:
            self._scroll_drag_delta = thumb.height() / 2.0
            self._set_scroll_direct(
                self._scroll_from_thumb_y(pos.y(), self._scroll_drag_delta))
        self.grabMouse()
        self.setCursor(Qt.ClosedHandCursor)
        return True

    def _on_scroll(self, value):
        self._scroll = self._clamp_scroll(float(value))
        self.update()

    def _scroll_to(self, value: float):
        target = self._clamp_scroll(value)
        self._target_scroll = target
        if not anim_on() or adur(190, 100) <= 0:
            self._sa.stop()
            self._scroll = target
            self.update()
            return
        self._sa.stop()
        self._sa.setStartValue(self._scroll)
        self._sa.setEndValue(target)
        self._sa.setDuration(adur(190, 100))
        self._sa.setEasingCurve(QEasingCurve.OutCubic)
        self._sa.start()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        clamped = self._clamp_scroll(self._scroll)
        self._scroll = clamped
        self._target_scroll = self._clamp_scroll(self._target_scroll)

    def wheelEvent(self, e):
        if not self._items:
            return
        pixel = e.pixelDelta().y()
        if pixel:
            delta = pixel
        else:
            delta = e.angleDelta().y() / 120.0 * self._row_h * 3
        self._scroll_to(self._target_scroll - delta)
        e.accept()

    def mouseMoveEvent(self, e):
        if self._scroll_drag:
            self._set_scroll_direct(
                self._scroll_from_thumb_y(e.position().y(),
                                          self._scroll_drag_delta))
            e.accept()
            return
        over_scrollbar = self._set_scrollbar_hover(e.position())
        real = int((e.position().y() + self._scroll) // self._row_h)
        self._hover = (-1 if over_scrollbar else
                       real if 0 <= real < len(self._items) else -1)
        self.update()

    def leaveEvent(self, e):
        if self._scroll_drag:
            return
        self._hover = -1
        self._set_scrollbar_hover(None)
        self.update()

    def mousePressEvent(self, e):
        if e.button() != Qt.LeftButton:
            return
        if self._begin_scrollbar_drag(e.position()):
            e.accept()
            return
        idx = int((e.position().y() + self._scroll) // self._row_h)
        if 0 <= idx < len(self._items):
            self.selected.emit(self._items[idx])
            e.accept()

    def mouseReleaseEvent(self, e):
        if self._scroll_drag:
            self._scroll_drag = False
            self.releaseMouse()
            self._set_scrollbar_hover(e.position())
            e.accept()

    def paintEvent(self, _):
        p = QPainter(self)
        aa(p)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(QColor(255, 255, 255, 26), 1))
        p.setBrush(QColor(255, 255, 255, 12))
        p.drawRoundedRect(rect, panel_f(9), panel_f(9))

        p.setFont(panel_font(12))
        p.setClipRect(rect)
        start = int(self._scroll // self._row_h)
        y_shift = self._scroll - start * self._row_h
        visible = self._visible_rows()
        for row in range(visible):
            idx = start + row
            if idx >= len(self._items):
                break
            item = self._items[idx]
            y = row * self._row_h - y_shift
            rr = QRectF(panel_f(4), y + panel_f(2),
                        self.width() - panel_f(8), self._row_h - panel_f(4))
            selected = item == self._current
            hover = idx == self._hover
            if selected or hover:
                if selected:
                    col = QColor(self._accent)
                    col.setAlpha(72)
                else:
                    col = QColor(255, 255, 255, 24)
                p.setPen(Qt.NoPen)
                p.setBrush(col)
                p.drawRoundedRect(rr, panel_f(7), panel_f(7))
            alpha = 238 if selected else 188
            if hover and not selected:
                alpha = 218
            p.setPen(QColor(255, 255, 255, alpha))
            p.drawText(rr.adjusted(panel_f(9), 0, -panel_f(9), 0),
                       Qt.AlignVCenter | Qt.AlignLeft, item)

        if not self._items:
            p.setPen(QColor(255, 255, 255, 120))
            p.drawText(rect, Qt.AlignCenter, tr("unset"))
        else:
            geo = self._scrollbar_geometry()
            if geo is None:
                return
            _, thumb, _ = geo
            t = self._scroll_hover_t
            w = panel_f(3 + 2 * t)
            draw_thumb = QRectF(thumb.center().x() - w / 2.0, thumb.y(),
                                w, thumb.height())
            p.setPen(Qt.NoPen)
            alpha = round(42 + (94 - 42) * t)
            p.setBrush(QColor(255, 255, 255, alpha))
            p.drawRoundedRect(draw_thumb, w / 2.0, w / 2.0)


class _FontPopup(QWidget):
    selected = Signal(str)

    def __init__(self, families: list[str], current: str, accent: QColor,
                 parent=None):
        ensure_safe_app_font()
        super().__init__(parent)
        self.setFont(panel_font(12))
        self.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint
                            | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self._accent = QColor(accent)
        self._families = list(families)
        self._closing = False
        self._shown_pos = QPoint()
        self._slide_dir = 1
        self._anim = Anim(self)
        self._anim.valueChanged.connect(self._on_popup_anim)
        self._anim.finished.connect(self._popup_anim_done)
        self.setFixedSize(panel_px(310), panel_px(334))

        lay = QVBoxLayout(self)
        lay.setContentsMargins(panel_px(12), panel_px(12),
                               panel_px(12), panel_px(12))
        lay.setSpacing(panel_px(8))

        self.search = QLineEdit()
        self.search.setFixedHeight(panel_px(30))
        self.search.addAction(
            glyph_icon(GLYPH_SEARCH, panel_px(15),
                       QColor(255, 255, 255, 142)),
            QLineEdit.LeadingPosition)
        self.search.setStyleSheet(
            "QLineEdit { background: rgba(255,255,255,18);"
            " color: #ececf2; border: 1px solid rgba(255,255,255,36);"
            f" border-radius: {panel_px(9)}px;"
            f" padding: 0 {panel_px(10)}px;"
            f" font: {panel_px(12)}px 'Segoe UI'; }}"
            "QLineEdit:focus { border-color: rgba(255,255,255,86); }")
        lay.addWidget(self.search)

        self.list = _FontList(self._families, current, self._accent)
        lay.addWidget(self.list, 1)
        self.search.textChanged.connect(self.list.set_filter)
        self.search.returnPressed.connect(self._accept_text)
        self.list.selected.connect(self._select)

    def set_accent(self, c: QColor):
        self._accent = QColor(c)
        self.list.set_accent(c)
        self.update()

    def popup_at(self, anchor: QWidget):
        g = anchor.mapToGlobal(QPoint(0, anchor.height() + panel_px(6)))
        scr = QApplication.screenAt(g)
        geo = (scr.availableGeometry() if scr is not None
               else QApplication.primaryScreen().availableGeometry())
        x = min(max(geo.left(), g.x()), geo.right() + 1 - self.width())
        y = g.y()
        above = False
        if y + self.height() > geo.bottom() + 1:
            y = anchor.mapToGlobal(QPoint(0, -self.height()
                                          - panel_px(6))).y()
            above = True
        y = min(max(geo.top(), y), geo.bottom() + 1 - self.height())
        self._closing = False
        self._shown_pos = QPoint(x, y)
        self._slide_dir = -1 if above else 1
        self._anim.stop()
        slide = panel_px(10) * self._slide_dir
        self.setWindowOpacity(0.0)
        self.move(x, y + slide)
        self.show()
        self.raise_()
        self.search.setFocus(Qt.PopupFocusReason)
        ms = adur(210, 120)
        if not anim_on() or ms <= 0:
            self.setWindowOpacity(1.0)
            self.move(self._shown_pos)
            return
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.setDuration(ms)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.start()

    def dismiss(self):
        if self._closing:
            return
        self._anim.stop()
        self._closing = True
        ms = adur(170, 100)
        if not anim_on() or ms <= 0:
            self.close()
            return
        self._anim.setStartValue(float(self.windowOpacity()))
        self._anim.setEndValue(0.0)
        self._anim.setDuration(ms)
        self._anim.setEasingCurve(QEasingCurve.InCubic)
        self._anim.start()

    def _on_popup_anim(self, value):
        t = max(0.0, min(1.0, float(value)))
        self.setWindowOpacity(t)
        slide = panel_px(10) * self._slide_dir
        self.move(self._shown_pos.x(),
                  round(self._shown_pos.y() + slide * (1.0 - t)))

    def _popup_anim_done(self):
        if self._closing:
            self.close()

    def _accept_text(self):
        text = self.search.text().strip()
        self._select(text or self.list.first_item())

    def _select(self, text: str):
        text = str(text or "").strip()
        if not text:
            return
        self.selected.emit(text)
        self.dismiss()

    def changeEvent(self, e):
        super().changeEvent(e)
        if e.type() == QEvent.ActivationChange and not self.isActiveWindow():
            self.dismiss()

    def paintEvent(self, _):
        p = QPainter(self)
        aa(p)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(rect, panel_f(13), panel_f(13))
        p.fillPath(path, QColor(21, 21, 27, 252))
        p.setPen(QPen(QColor(255, 255, 255, 30), 1))
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)


class FontPicker(QWidget):
    """自繪字體選擇器：點開後可搜尋，也可直接輸入字體名稱。"""

    currentTextChanged = Signal(str)

    _families_cache: list[str] | None = None

    def __init__(self, current: str, parent=None):
        super().__init__(parent)
        if FontPicker._families_cache is None:
            FontPicker._families_cache = [
                f for f in QFontDatabase.families()
                if is_safe_ui_font(f)
            ]
            if not FontPicker._families_cache:
                FontPicker._families_cache = [safe_font_family()]
        self._families = FontPicker._families_cache
        current = safe_font_family(current)
        if current and current not in self._families and is_safe_ui_font(current):
            self._families = [current] + self._families
        self._text = (current if current in self._families
                      else safe_font_family(SETTINGS.get("font")))
        self._accent = QColor("#1DB954")
        self._hover = 0.0
        self._press = 1.0
        self._popup: _FontPopup | None = None
        self._ha = Anim(self)
        self._ha.valueChanged.connect(self._on_hover)
        self._pa = Anim(self)
        self._pa.valueChanged.connect(self._on_press)
        self.setFixedHeight(panel_px(30))
        self.setMinimumWidth(panel_px(160))
        self.setFocusPolicy(Qt.StrongFocus)
        self.setCursor(Qt.PointingHandCursor)

    def currentText(self) -> str:
        return self._text

    def setCurrentText(self, text: str):
        self._set_text(text, emit=False)

    def set_accent(self, c: QColor):
        self._accent = QColor(c)
        if self._popup is not None:
            self._popup.set_accent(c)
        self.update()

    def _set_text(self, text: str, emit: bool = True):
        text = safe_font_family(text)
        if not text:
            return
        if text == self._text:
            return
        self._text = text
        if emit:
            self.currentTextChanged.emit(text)
        self.update()

    def _on_hover(self, v):
        self._hover = float(v)
        self.update()

    def _on_press(self, v):
        self._press = float(v)
        self.update()

    def _anim(self, anim: Anim, cur: float, to: float, ms: int):
        anim.stop()
        if not anim_on() or ms <= 0:
            anim.valueChanged.emit(to)
            return
        anim.setStartValue(cur)
        anim.setEndValue(to)
        anim.setDuration(ms)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.start()

    def _open_popup(self, initial: str = ""):
        if self._popup is not None and self._popup.isVisible():
            if initial:
                self._popup.raise_()
                self._popup.search.setText(initial)
                self._popup.search.setFocus(Qt.PopupFocusReason)
            else:
                self._popup.dismiss()
            return
        self._popup = _FontPopup(self._families, self._text, self._accent,
                                 self.window())
        self._popup.selected.connect(self._set_text)
        self._popup.destroyed.connect(lambda *_: setattr(self, "_popup", None))
        self._popup.popup_at(self)
        if initial:
            self._popup.search.setText(initial)

    def enterEvent(self, e):
        self._anim(self._ha, self._hover, 1.0, adur(150, 90))

    def leaveEvent(self, e):
        self._anim(self._ha, self._hover, 0.0, adur(180, 100))

    def mousePressEvent(self, e):
        if e.button() != Qt.LeftButton:
            return
        self._anim(self._pa, self._press, 0.96, adur(70, 50))

    def mouseReleaseEvent(self, e):
        self._anim(self._pa, self._press, 1.0, adur(150, 90))
        if self.rect().contains(e.position().toPoint()):
            self._open_popup()

    def keyPressEvent(self, e):
        text = e.text()
        if text and text.isprintable():
            self._open_popup(text)
            e.accept()
            return
        if e.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Down,
                       Qt.Key_Space):
            self._open_popup()
            e.accept()
            return
        super().keyPressEvent(e)

    def paintEvent(self, _):
        p = QPainter(self)
        aa(p)
        c = self.rect().center()
        p.translate(c.x(), c.y())
        p.scale(self._press, self._press)
        p.translate(-c.x(), -c.y())
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(QColor(255, 255, 255, 36), 1))
        p.setBrush(QColor(255, 255, 255, 16 + round(10 * self._hover)))
        p.drawRoundedRect(r, panel_f(9), panel_f(9))
        p.setFont(panel_font(12))
        p.setPen(QColor(255, 255, 255, 212))
        text_rect = r.adjusted(panel_f(10), 0, -panel_f(30), 0)
        fm = QFontMetricsF(panel_font(12))
        txt = fm.elidedText(self._text, Qt.ElideRight,
                            max(1, round(text_rect.width())))
        p.drawText(text_rect, Qt.AlignVCenter | Qt.AlignLeft, txt)
        p.setFont(panel_icon_font(10))
        p.setPen(QColor(255, 255, 255, 150 + round(60 * self._hover)))
        p.drawText(QRectF(r.right() - panel_f(26), r.y(),
                          panel_f(22), r.height()),
                   Qt.AlignCenter, GLYPH_CHEVRON_DOWN)


# ------------------------------------------------------------ 設定面板 ----

class _PanelBody(QWidget):
    def paintEvent(self, _):
        p = QPainter(self)
        aa(p)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(rect, panel_f(16), panel_f(16))
        p.fillPath(path, QColor(21, 21, 27, 250))
        p.setPen(QPen(QColor(255, 255, 255, 26), 1))
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)


class _ScrollablePanelBody(_PanelBody):
    """圓角面板外框 + 可垂直捲動的內容層。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.viewport = QWidget(self)
        self.viewport.setAttribute(Qt.WA_TranslucentBackground)
        self.viewport.setMouseTracking(True)
        self.content = QWidget(self.viewport)
        self.content.setAttribute(Qt.WA_TranslucentBackground)
        self.content.setMouseTracking(True)
        self.content.installEventFilter(self)
        self._header_widget: QWidget | None = None
        self._footer_widget: QWidget | None = None
        self._header_h = 0
        self._footer_h = 0
        self._viewport_h = 0
        self._offset = 0.0
        self._target_offset = 0.0
        self._content_h = 0
        self._scroll_hover = False
        self._scroll_hover_t = 0.0
        self._scroll_drag = False
        self._scroll_drag_delta = 0.0
        self._sa = Anim(self)
        self._sa.valueChanged.connect(self._on_scroll)
        self._scroll_ha = Anim(self)
        self._scroll_ha.valueChanged.connect(self._on_scrollbar_hover)
        self.setMouseTracking(True)

    def set_fixed_header(self, widget: QWidget | None):
        self._header_widget = widget
        if widget is not None:
            widget.setParent(self)
            widget.setMouseTracking(True)
            widget.show()

    def set_fixed_footer(self, widget: QWidget | None):
        self._footer_widget = widget
        if widget is not None:
            widget.setParent(self)
            widget.setMouseTracking(True)
            widget.show()

    def _fixed_height_for_width(self, widget: QWidget | None,
                                width: int) -> int:
        if widget is None:
            return 0
        widget.setFixedWidth(max(1, int(width)))
        lay = widget.layout()
        if lay is not None:
            lay.activate()
        return max(1, widget.sizeHint().height())

    def content_height_for_width(self, width: int) -> int:
        self.content.setFixedWidth(max(1, int(width)))
        lay = self.content.layout()
        if lay is not None:
            lay.activate()
        header_h = self._fixed_height_for_width(self._header_widget, width)
        footer_h = self._fixed_height_for_width(self._footer_widget, width)
        content_h = max(1, self.content.sizeHint().height() + panel_px(2))
        return max(1, header_h + content_h + footer_h)

    def set_viewport(self, width: int, height: int, content_h: int):
        width = max(1, int(width))
        height = max(1, int(height))
        self._header_h = self._fixed_height_for_width(
            self._header_widget, width)
        self._footer_h = self._fixed_height_for_width(
            self._footer_widget, width)
        self._viewport_h = max(1, height - self._header_h - self._footer_h)
        self._content_h = max(
            1, int(content_h) - self._header_h - self._footer_h)
        if self._header_widget is not None:
            self._header_widget.setGeometry(0, 0, width, self._header_h)
            self._header_widget.raise_()
        if self._footer_widget is not None:
            self._footer_widget.setGeometry(
                0, height - self._footer_h, width, self._footer_h)
            self._footer_widget.raise_()
        self.viewport.setGeometry(0, self._header_h, width, self._viewport_h)
        self.content.resize(width, max(self._viewport_h, self._content_h))
        lay = self.content.layout()
        if lay is not None:
            lay.activate()
        self._offset = self._clamp(self._offset)
        self._target_offset = self._clamp(self._target_offset)
        self._place_content()

    def _max_offset(self) -> float:
        return max(0.0, float(self._content_h - self._viewport_h))

    def _clamp(self, value: float) -> float:
        return max(0.0, min(self._max_offset(), float(value)))

    def _scrollbar_geometry(self):
        if self._max_offset() <= 1:
            return None
        rect = QRectF(self.viewport.geometry()).adjusted(0.5, 0.5, -0.5, -0.5)
        track_h = rect.height() - panel_f(24)
        if track_h <= 0:
            return None
        thumb_h = max(panel_f(28), track_h * self.height()
                      / max(1.0, float(self._content_h)))
        thumb_h = min(track_h, thumb_h)
        track_y = rect.y() + panel_f(12)
        span = max(1.0, track_h - thumb_h)
        thumb_y = track_y + span * (self._offset / self._max_offset())
        hit = QRectF(rect.right() - panel_f(18), track_y,
                     panel_f(18), track_h)
        thumb = QRectF(rect.right() - panel_f(7), thumb_y,
                       panel_f(3), thumb_h)
        thumb_hit = QRectF(hit.x(), thumb_y, hit.width(), thumb_h)
        return hit, thumb, thumb_hit

    def _set_scrollbar_hover(self, pos: QPointF | None) -> bool:
        geo = self._scrollbar_geometry()
        hover = bool(geo is not None and pos is not None
                     and geo[0].contains(pos))
        if hover != self._scroll_hover:
            self._scroll_hover = hover
            self._scroll_hover_to(hover)
        if not self._scroll_drag:
            cursor = Qt.OpenHandCursor if hover else Qt.ArrowCursor
            self.setCursor(cursor)
            self.content.setCursor(cursor)
        return hover

    def _on_scrollbar_hover(self, value):
        self._scroll_hover_t = max(0.0, min(1.0, float(value)))
        self.update()

    def _scroll_hover_to(self, on: bool):
        target = 1.0 if on else 0.0
        self._scroll_ha.stop()
        ms = adur(150 if on else 180, 90)
        if not anim_on() or ms <= 0:
            self._scroll_hover_t = target
            self.update()
            return
        self._scroll_ha.setStartValue(self._scroll_hover_t)
        self._scroll_ha.setEndValue(target)
        self._scroll_ha.setDuration(ms)
        self._scroll_ha.setEasingCurve(QEasingCurve.OutCubic)
        self._scroll_ha.start()

    def _offset_from_thumb_y(self, y: float, drag_delta: float) -> float:
        geo = self._scrollbar_geometry()
        if geo is None:
            return self._offset
        hit, thumb, _ = geo
        span = max(1.0, hit.height() - thumb.height())
        ratio = (float(y) - drag_delta - hit.y()) / span
        return self._clamp(ratio * self._max_offset())

    def _set_offset_direct(self, value: float):
        self._sa.stop()
        self._offset = self._clamp(value)
        self._target_offset = self._offset
        self._place_content()

    def _begin_scrollbar_drag(self, pos: QPointF) -> bool:
        geo = self._scrollbar_geometry()
        if geo is None:
            return False
        hit, thumb, thumb_hit = geo
        if not hit.contains(pos):
            return False
        self._scroll_drag = True
        self._scroll_hover = True
        self._scroll_hover_to(True)
        self._sa.stop()
        if thumb_hit.contains(pos):
            self._scroll_drag_delta = pos.y() - thumb.y()
        else:
            self._scroll_drag_delta = thumb.height() / 2.0
            self._set_offset_direct(
                self._offset_from_thumb_y(pos.y(), self._scroll_drag_delta))
        self.grabMouse()
        self.setCursor(Qt.ClosedHandCursor)
        self.content.setCursor(Qt.ClosedHandCursor)
        return True

    def _drag_scrollbar_to(self, pos: QPointF) -> bool:
        if not self._scroll_drag:
            return False
        self._set_offset_direct(
            self._offset_from_thumb_y(pos.y(), self._scroll_drag_delta))
        return True

    def _end_scrollbar_drag(self) -> bool:
        if not self._scroll_drag:
            return False
        self._scroll_drag = False
        self.releaseMouse()
        return True

    def _content_event_pos(self, event) -> QPointF:
        pos = event.position()
        cp = self.content.pos()
        vp = self.viewport.pos()
        return QPointF(pos.x() + cp.x() + vp.x(),
                       pos.y() + cp.y() + vp.y())

    def _place_content(self):
        self.content.move(0, -round(self._offset))
        self.viewport.update()
        self.update()

    def set_scroll_offset(self, value: float):
        self._sa.stop()
        self._offset = self._clamp(value)
        self._target_offset = self._offset
        self._place_content()

    def _on_scroll(self, value):
        self._offset = self._clamp(float(value))
        self._place_content()

    def _scroll_to(self, value: float):
        target = self._clamp(value)
        self._target_offset = target
        ms = adur(210, 120)
        if not anim_on() or ms <= 0:
            self._sa.stop()
            self._offset = target
            self._place_content()
            return
        self._sa.stop()
        self._sa.setStartValue(self._offset)
        self._sa.setEndValue(target)
        self._sa.setDuration(ms)
        self._sa.setEasingCurve(QEasingCurve.OutCubic)
        self._sa.start()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._offset = self._clamp(self._offset)
        self._target_offset = self._clamp(self._target_offset)
        self._place_content()

    def eventFilter(self, obj, event):
        if obj is self.content:
            if event.type() == QEvent.MouseButtonPress:
                if (event.button() == Qt.LeftButton
                        and self._begin_scrollbar_drag(
                            self._content_event_pos(event))):
                    event.accept()
                    return True
            elif event.type() == QEvent.MouseMove:
                pos = self._content_event_pos(event)
                if self._drag_scrollbar_to(pos):
                    event.accept()
                    return True
                self._set_scrollbar_hover(pos)
            elif event.type() == QEvent.MouseButtonRelease:
                pos = self._content_event_pos(event)
                if self._end_scrollbar_drag():
                    self._set_scrollbar_hover(pos)
                    event.accept()
                    return True
            elif event.type() == QEvent.Leave and not self._scroll_drag:
                self._set_scrollbar_hover(None)
        return super().eventFilter(obj, event)

    def wheelEvent(self, e):
        if self._max_offset() <= 1:
            e.ignore()
            return
        pixel = e.pixelDelta().y()
        if pixel:
            delta = pixel
        else:
            delta = e.angleDelta().y() / 120.0 * panel_px(58)
        self._scroll_to(self._target_offset - delta)
        e.accept()

    def mousePressEvent(self, e):
        if (e.button() == Qt.LeftButton
                and self._begin_scrollbar_drag(e.position())):
            e.accept()
            return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._drag_scrollbar_to(e.position()):
            e.accept()
            return
        self._set_scrollbar_hover(e.position())
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if self._end_scrollbar_drag():
            self._set_scrollbar_hover(e.position())
            e.accept()
            return
        super().mouseReleaseEvent(e)

    def leaveEvent(self, e):
        if not self._scroll_drag:
            self._set_scrollbar_hover(None)
        super().leaveEvent(e)

    def paintEvent(self, e):
        super().paintEvent(e)
        geo = self._scrollbar_geometry()
        if geo is None:
            return
        _, thumb, _ = geo
        t = self._scroll_hover_t
        w = panel_f(3 + 2 * t)
        draw_thumb = QRectF(thumb.center().x() - w / 2.0, thumb.y(),
                            w, thumb.height())
        p = QPainter(self)
        aa(p)
        p.setPen(Qt.NoPen)
        alpha = round(44 + (98 - 44) * t)
        p.setBrush(QColor(255, 255, 255, alpha))
        p.drawRoundedRect(draw_thumb, w / 2.0, w / 2.0)


class _PanelZoomOverlay(QWidget):
    """設定面板縮放過渡：沿用主視窗的截圖矩形內插效果。"""

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
        self._buf: QPixmap | None = None
        self._buf2: QPixmap | None = None
        self._shadow_included = False
        self._align_top = False     # True=頂部對齊不拉伸（分類切換用）
        self._slide = 0.0           # align_top 時新圖上移入場量（邏輯像素）
        self.hide()

    def setup(self, old_pm: QPixmap, r0, new_pm: QPixmap, r1,
              shadow_included: bool = False, align_top: bool = False,
              slide: float = 0.0):
        self._old, self._new = old_pm, new_pm
        self._r0, self._r1 = QRectF(r0), QRectF(r1)
        self._t = 0.0
        self._shadow_included = bool(shadow_included)
        self._align_top = bool(align_top)
        self._slide = float(slide)
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
        if self._r1.width() <= 0:
            return panel_f(16)
        return panel_f(16) * w / self._r1.width()

    def _compose(self, rect: QRectF) -> tuple[QPixmap, float, float]:
        dpr = self.devicePixelRatioF()
        bw = max(1.0, rect.width() * dpr)
        bh = max(1.0, rect.height() * dpr)
        if (self._buf is None or self._buf.width() < bw
                or self._buf.height() < bh):
            self._buf = QPixmap(int(bw) + 2, int(bh) + 2)
            self._buf2 = QPixmap(int(bw) + 2, int(bh) + 2)
        target = QRectF(0, 0, bw, bh)
        t = self._t

        def dst(pm: QPixmap, slide: float) -> QRectF:
            # align_top：原始尺寸、頂部對齊（超出 buffer 的底部由 buffer 邊界
            # 自然裁切，paintEvent 只取 cur_rect 大小 → 內容不縱向擠壓）；
            # 否則整張拉伸填滿 target（縮放過渡用）
            if self._align_top:
                return QRectF(0.0, slide, pm.width(), pm.height())
            return target

        self._buf.fill(Qt.transparent)
        p = QPainter(self._buf)
        aa(p)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        if self._new is not None and t > 0.0:
            slide = self._slide * dpr * (1.0 - t)
            p.setOpacity(t)
            p.drawPixmap(dst(self._new, slide), self._new,
                         QRectF(self._new.rect()))
        if self._old is not None and t < 1.0:
            if t <= 0.0:
                p.setOpacity(1.0)
                p.drawPixmap(dst(self._old, 0.0), self._old,
                             QRectF(self._old.rect()))
            else:
                self._buf2.fill(Qt.transparent)
                p2 = QPainter(self._buf2)
                aa(p2)
                p2.setRenderHint(QPainter.SmoothPixmapTransform, True)
                p2.setOpacity(1.0 - t)
                p2.drawPixmap(dst(self._old, 0.0), self._old,
                              QRectF(self._old.rect()))
                p2.end()
                p.setOpacity(1.0)
                p.setCompositionMode(QPainter.CompositionMode_Plus)
                p.drawPixmap(0, 0, self._buf2)
        p.end()
        return self._buf, bw, bh

    def shadow_included(self) -> bool:
        return self._shadow_included

    def composite(self) -> QPixmap:
        rect = self.cur_rect()
        pm, bw, bh = self._compose(rect)
        out = pm.copy(0, 0, int(bw), int(bh))
        out.setDevicePixelRatio(self.devicePixelRatioF())
        return out

    def paintEvent(self, _):
        p = QPainter(self)
        aa(p)
        rect = self.cur_rect()
        clip = QPainterPath()
        rad = self._clip_radius(rect.width())
        clip.addRoundedRect(rect, rad, rad)
        p.setClipPath(clip)
        pm, bw, bh = self._compose(rect)
        p.drawPixmap(rect, pm, QRectF(0, 0, bw, bh))


class _PanelFadeOverlay(QWidget):
    """設定面板語言切換過渡：舊畫面淡出、新畫面淡入。"""

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
        self._buf: QPixmap | None = None
        self._buf2: QPixmap | None = None
        self.hide()

    def setup(self, old_pm: QPixmap, old_rect, new_pm: QPixmap, new_rect):
        self._old = old_pm
        self._new = new_pm
        self._r0 = QRectF(old_rect)
        self._r1 = QRectF(new_rect)
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

    def _compose(self, rect: QRectF) -> tuple[QPixmap, float, float]:
        dpr = self.devicePixelRatioF()
        bw = max(1.0, rect.width() * dpr)
        bh = max(1.0, rect.height() * dpr)
        if (self._buf is None or self._buf.width() < bw
                or self._buf.height() < bh):
            self._buf = QPixmap(int(bw) + 2, int(bh) + 2)
            self._buf2 = QPixmap(int(bw) + 2, int(bh) + 2)
        target = QRectF(0, 0, bw, bh)
        t = self._t
        self._buf.fill(Qt.transparent)
        p = QPainter(self._buf)
        aa(p)
        if self._new is not None and t > 0.0:
            p.setOpacity(t)
            p.drawPixmap(target, self._new, QRectF(self._new.rect()))
        if self._old is not None and t < 1.0:
            if t <= 0.0:
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
                p.drawPixmap(0, 0, self._buf2)
        p.end()
        return self._buf, bw, bh

    def paintEvent(self, _):
        p = QPainter(self)
        aa(p)
        r = self.cur_rect()
        clip = QPainterPath()
        clip.addRoundedRect(r, panel_f(16), panel_f(16))
        p.setClipPath(clip)
        pm, bw, bh = self._compose(r)
        p.drawPixmap(r, pm, QRectF(0, 0, bw, bh))


class _PanelSlideOverlay(QWidget):
    """設定面板類型切換：舊面板滑出、新面板滑入。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self._old: QPixmap | None = None
        self._new: QPixmap | None = None
        self._r0 = QRectF()
        self._r1 = QRectF()
        self._clip_rect = QRectF()
        self._clip_radius = panel_f(16)
        self._t = 0.0
        self.hide()

    def setup(self, old_pm: QPixmap, old_rect,
              new_pm: QPixmap, new_rect,
              clip_rect=None, clip_radius: float | None = None):
        self._old = old_pm
        self._new = new_pm
        self._r0 = QRectF(old_rect)
        self._r1 = QRectF(new_rect)
        self._clip_rect = (QRectF(clip_rect) if clip_rect is not None
                           else self._r0.united(self._r1))
        self._clip_radius = (panel_f(16) if clip_radius is None
                             else max(0.0, float(clip_radius)))
        self._t = 0.0
        self.update()

    def set_t(self, t: float):
        self._t = max(0.0, min(1.0, float(t)))
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        aa(p)
        span = max(self._r0.width(), self._r1.width(), panel_f(80))
        clip_rect = QRectF(self._clip_rect)
        if not clip_rect.isValid():
            clip_rect = self._r0.united(self._r1)
        if not clip_rect.isValid():
            clip_rect = QRectF(self.rect())
        clip = QPainterPath()
        if self._clip_radius > 0.0:
            clip.addRoundedRect(clip_rect, self._clip_radius,
                                self._clip_radius)
        else:
            clip.addRect(clip_rect)
        p.fillPath(clip, QColor(21, 21, 27, 252))
        p.setClipPath(clip)
        if self._old is not None:
            r = QRectF(self._r0)
            r.moveLeft(self._r0.x() - span * self._t)
            p.drawPixmap(r, self._old, QRectF(self._old.rect()))
        if self._new is not None:
            r = QRectF(self._r1)
            r.moveLeft(self._r1.x() + span * (1.0 - self._t))
            p.drawPixmap(r, self._new, QRectF(self._new.rect()))


class SettingsPanel(QWidget):
    """獨立的無邊框設定視窗；所有變更即時套用。"""

    setting_changed = Signal(str, object)
    position_committed = Signal(QPoint)
    closed = Signal()

    def __init__(self, accent: QColor, parent=None):
        ensure_safe_app_font()
        super().__init__(parent)
        self.setFont(panel_font(12))
        self.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint
                            | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.setAutoFillBackground(False)
        self._drag_off = None
        self._accent = QColor(accent)
        self._grad_pair = _panel_target_pair(self._accent)
        self._grad_from = (QColor(self._grad_pair[0]),
                           QColor(self._grad_pair[1]))
        self._grad_to = (QColor(self._grad_pair[0]),
                         QColor(self._grad_pair[1]))
        self._grad_explicit = theme_gradient() is not None
        self._grad_mode = _panel_pair_mode()
        _set_panel_gradient(self._grad_pair)
        self._grad_anim = Anim(self)
        self._grad_anim.valueChanged.connect(self._on_theme_gradient)
        self._shadow_op = 1.0 if SETTINGS.get("shadow", True) else 0.0
        self._shadow_anim = Anim(self)
        self._shadow_anim.valueChanged.connect(self._on_shadow_op)
        self._overlay: _PanelZoomOverlay | None = None
        self._zoom_restart = False
        self._zoom_anim = Anim(self)
        self._zoom_anim.valueChanged.connect(self._on_zoom)
        self._zoom_anim.finished.connect(self._zoom_done)
        self._final_size = None
        self._fade_overlay: _PanelFadeOverlay | None = None
        self._fade_final_size = None
        self._fade_abort = False
        self._lang_old_pm: QPixmap | None = None
        self._lang_old_rect = QRectF()
        self._fade_anim = Anim(self)
        self._fade_anim.valueChanged.connect(self._on_language_fade)
        self._fade_anim.finished.connect(self._language_fade_done)
        self._type_overlay: _PanelZoomOverlay | None = None
        self._type_slide_anim = Anim(self)
        self._type_slide_anim.valueChanged.connect(self._on_type_slide)
        self._type_slide_anim.finished.connect(self._type_slide_done)
        self._type_slide_abort = False
        self._type_direct = False
        self._type_from_size = QSize()
        self._type_to_size = QSize()
        self._type_from_pos = QPoint()
        self._type_to_pos = QPoint()
        self._type_from_body = QRect()
        self._type_to_body = QRect()
        self._type_final_body = QRect()
        self._type_to_content_h = 0
        self._lang_timer = QTimer(self)
        self._lang_timer.setSingleShot(True)
        self._lang_timer.timeout.connect(self.rebuild_for_language)
        self._body: _PanelBody | None = None
        self.advanced_box: _PanelBody | None = None
        self._full_boxes: list[_ScrollablePanelBody] = []
        self._full_box_sections: dict[str, _ScrollablePanelBody] = {}
        self._current_panel_type = SETTINGS.get("settings_panel_type",
                                                "normal")
        self._advanced_eff: QGraphicsOpacityEffect | None = None
        self._advanced_open = False
        self._advanced_hiding = False
        self._advanced_side = "right"
        self._advanced_geo = QRectF()
        self._advanced_t = 0.0
        self._theme_row_h = 0
        self._theme_resize_anchor: QPoint | None = None
        self._theme_scroll_from = 0.0
        self._theme_scroll_to = 0.0
        self._theme_row_from = 0
        self._theme_row_to = 0
        self._section_resize_anchor: QPoint | None = None
        self._section_frame_lock_size: QSize | None = None
        self._section_frame_lock_body_h = 0
        self._section_frame_lock_content_h = 0
        self._advanced_anim = Anim(self)
        self._advanced_anim.valueChanged.connect(self._on_advanced_anim)
        self._advanced_anim.finished.connect(self._advanced_anim_done)
        self._geo_anim = Anim(self)
        self._geo_anim.valueChanged.connect(self._on_window_geometry)
        self._geo_anim.finished.connect(self._window_geometry_done)
        self._geo_from_pos = QPoint()
        self._geo_to_pos = QPoint()
        self._geo_from_size = QSize()
        self._geo_to_size = QSize()
        self._build_body()
        QTimer.singleShot(0, lambda: self.sync_weather_controls(animate=False))

    def _build_body(self, expanded: bool | None = None,
                    resize_window: bool = True):
        body = _ScrollablePanelBody(self)
        self._labels = {}
        self._toggle_labels = {}
        self._section_labels = []
        self._search_rows = []
        self._section_groups = []
        self._section_wrappers = {}
        self._section_gap_layouts = {}
        self._section_target_gaps = {}
        self._section_anim_full_heights = {}
        self._section_collapsed = getattr(self, "_section_collapsed", {})
        self._section_anims = {}
        self._section_anim_containers = {}
        self._section_anim_targets = {}
        self._section_animating = set()
        panel_type = SETTINGS.get("settings_panel_type", "normal")
        self._current_panel_type = panel_type
        categorized = panel_type == "categories"
        full_mode = panel_type == "full"
        single_panel = panel_type in ("categories", "full")
        self._full_boxes = []
        self._full_box_sections = {}
        if single_panel:
            self._advanced_open = False
            self._advanced_hiding = False
        self._panel_category = getattr(
            self, "_panel_category", "section_general")
        if self._panel_category not in PANEL_CATEGORY_KEYS:
            self._panel_category = "section_general"
        self.sg_panel_category = None
        lay = QVBoxLayout(body.content)
        lay.setContentsMargins(panel_px(20), panel_px(10),
                               panel_px(20), panel_px(10))
        lay.setSpacing(panel_px(10))
        lay.setAlignment(Qt.AlignTop)

        # 標題列 + 常駐搜尋列
        header_box = QWidget(body)
        header_lay = QVBoxLayout(header_box)
        header_lay.setContentsMargins(0, 0, 0, panel_px(8))
        header_lay.setSpacing(panel_px(8))

        head_box = QWidget(header_box)
        head = QHBoxLayout(head_box)
        head.setContentsMargins(panel_px(20), panel_px(14),
                                panel_px(20), 0)
        head.setSpacing(panel_px(8))
        title = QLabel(tr("settings"))
        self._title_label = title
        title.setFont(panel_font(14, QFont.DemiBold))
        title.setStyleSheet("color: rgba(255,255,255,235);")
        head.addWidget(title)
        head.addStretch(1)
        btn_close = IconButton(GLYPH_CLOSE, panel_px(10), panel_px(24),
                               fx="spin")
        self._btn_close = btn_close
        btn_close.clicked.connect(self.animated_close)
        head.addWidget(btn_close)
        header_lay.addWidget(head_box)

        search_box = QWidget(header_box)
        search_lay = QVBoxLayout(search_box)
        search_lay.setContentsMargins(panel_px(20), 0, panel_px(20), 0)
        search_lay.setSpacing(0)
        self.search = QLineEdit(search_box)
        self.search.setFixedHeight(panel_px(30))
        self.search.setPlaceholderText(tr("search_settings"))
        self.search.setStyleSheet(
            "QLineEdit { background: rgba(255,255,255,16);"
            " color: #ececf2; border: 1px solid rgba(255,255,255,34);"
            f" border-radius: {panel_px(9)}px;"
            f" padding: 0 {panel_px(10)}px;"
            f" font: {panel_px(12)}px 'Segoe UI'; }}"
            "QLineEdit:focus { border-color: rgba(255,255,255,76); }"
            "QLineEdit::placeholder { color: rgba(255,255,255,95); }")
        search_lay.addWidget(self.search)
        header_lay.addWidget(search_box)
        body.set_fixed_header(header_box)

        if categorized:
            self.sg_panel_category = Segmented(
                panel_category_options(), self._panel_category,
                accent=self._accent)
            lay.addWidget(self.sg_panel_category)

        full_layouts: dict[str, QVBoxLayout] = {}
        if full_mode:
            for section_key in PANEL_CATEGORY_KEYS:
                box = _ScrollablePanelBody(self)
                box.hide()
                box_lay = QVBoxLayout(box.content)
                box_lay.setContentsMargins(panel_px(20), panel_px(14),
                                           panel_px(20), panel_px(18))
                box_lay.setSpacing(panel_px(8))
                box_lay.setAlignment(Qt.AlignTop)
                full_layouts[section_key] = box_lay
                self._full_boxes.append(box)
                self._full_box_sections[section_key] = box

        current_section: list[QWidget] | None = None
        current_section_key = ""
        current_layout = lay

        def section(layout, label_key):
            nonlocal current_section, current_section_key, current_layout
            if full_mode and label_key in full_layouts:
                layout = full_layouts[label_key]
            group_id = f"{label_key}:{len(self._section_groups)}"
            collapsed = bool(self._section_collapsed.get(group_id, False))
            section_gap = layout.spacing()
            if section_gap < 0:
                section_gap = panel_px(10)
            section_box = QWidget()
            section_box.setSizePolicy(QSizePolicy.Preferred,
                                      QSizePolicy.Fixed)
            section_lay = QVBoxLayout(section_box)
            section_lay.setContentsMargins(0, 0, 0, 0)
            section_lay.setSpacing(0 if collapsed else section_gap)
            section_lay.setAlignment(Qt.AlignTop)
            layout.addWidget(section_box)

            lab = SectionLabel(tr(label_key), collapsed)
            self._section_labels.append((label_key, lab))
            lab.setFont(panel_font(14, QFont.DemiBold))
            lab.setStyleSheet("color: rgba(255,255,255,225);")
            lab.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
            section_lay.addWidget(lab)
            group = QWidget()
            group.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
            group_lay = QVBoxLayout(group)
            group_lay.setContentsMargins(0, 0, 0, 0)
            group_lay.setSpacing(panel_px(10))
            group_lay.setAlignment(Qt.AlignTop)
            if collapsed:
                group.setFixedHeight(0)
                group.hide()
            section_lay.addWidget(group)
            current_layout = group_lay
            current_section = []
            current_section_key = label_key
            self._section_wrappers[group_id] = section_box
            self._section_gap_layouts[group_id] = section_lay
            self._section_target_gaps[group_id] = section_gap
            self._section_groups.append(
                (label_key, lab, current_section, group_id, group))
            lab.clicked.connect(
                lambda gid=group_id, header=lab, container=group:
                    self._toggle_section(gid, header, container))
            return lab

        def register_search(host: QWidget, label_key: str):
            keys = {label_key.lower()}
            if label_key != "FPS":
                keys.add(tr(label_key).lower())
            else:
                keys.add("fps")
            self._search_rows.append((host, label_key, keys))
            if current_section is not None:
                current_section.append(host)

        def row(label_key, control, stretch=True, top=False):
            host = QWidget()
            control._row_host = host
            host.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
            h = QHBoxLayout()
            host.setLayout(h)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(panel_px(10))
            lab = QLabel(tr(label_key) if label_key != "FPS" else "FPS")
            self._labels[label_key] = lab
            lab.setFont(panel_font(12))
            lab.setStyleSheet("color: rgba(255,255,255,185);")
            lab.setFixedWidth(panel_px(90))
            if top:
                # 控制項會伸縮（色票列展開）：標籤釘在第一列的位置不動
                lab.setFixedHeight(SwatchRow.row_h())
                h.addWidget(lab, 0, Qt.AlignTop)
            else:
                h.addWidget(lab)
            if stretch:
                h.addWidget(control, 1)
            else:
                h.addWidget(control)
                h.addStretch(1)
            row_h = max(lab.sizeHint().height(), control.height(),
                        control.sizeHint().height())
            host.setFixedHeight(max(1, row_h))
            host._full_h = max(1, row_h)
            if top and hasattr(control, "size_changed"):
                control.size_changed.connect(
                    lambda host=host, control=control:
                        host.setFixedHeight(max(1, control.height())))
            current_layout.addWidget(host)
            register_search(host, label_key)
            return control

        def build_general():
            section(lay, "section_general")
            self.sg_panel_type = row("settings_panel_type", Segmented(
                settings_panel_type_options(), SETTINGS["settings_panel_type"],
                accent=self._accent))
            self.sg_source = row("source", Segmented(
                source_options(), SETTINGS["source"], accent=self._accent))
            self.tg_startup = row("startup_enabled", Toggle(
                bool(SETTINGS["startup_enabled"]), accent=self._accent),
                stretch=False)
            self.sg_startup_show = row("startup_show", Segmented(
                startup_show_options(), SETTINGS["startup_show"],
                accent=self._accent))
            self.sg_lang = row("language", Segmented(
                LANGUAGES, SETTINGS["language"], accent=self._accent))

        def build_appearance():
            section(lay, "section_appearance")
            self.sw_theme = row("theme", SwatchRow(SETTINGS["theme"],
                                                   expanded=expanded),
                                stretch=False, top=True)
            self.bg_image = row("background_image", ImagePathPicker(
                SETTINGS.get("background_image", ""), accent=self._accent))
            self.sg_bg_image_mode = row("background_image_mode", Segmented(
                background_image_mode_options(),
                SETTINGS["background_image_mode"], accent=self._accent))
            self.sl_bg_image_brightness = row(
                "background_image_brightness",
                PanelSlider(35, 165,
                            SETTINGS["background_image_brightness"] * 100,
                            fmt=lambda v: f"{v:.0f}%",
                            accent=self._accent))
            self.tg_bg_image_parallax = row("background_image_parallax",
                Toggle(bool(SETTINGS.get("background_image_parallax", False)),
                       accent=self._accent),
                stretch=False)
            self.sl_bg_image_parallax_strength = row(
                "background_image_parallax_strength",
                PanelSlider(
                    0, 200,
                    SETTINGS.get("background_image_parallax_strength", 1.0) * 100,
                    fmt=lambda v: f"{v:.0f}%",
                    accent=self._accent))
            self.sl_bg_image_parallax_fps = row(
                "background_image_parallax_fps",
                PanelSlider(
                    5, 60,
                    SETTINGS.get("background_image_parallax_fps", 30),
                    fmt=lambda v: f"{v:.0f}",
                    step=1, accent=self._accent))
            weather = SETTINGS.get("weather_effect", "rain")
            if weather not in ("rain", "snow", "custom"):
                weather = "rain"
            self.sg_weather_effect = row("weather_effect", Segmented(
                weather_effect_options(), weather, accent=self._accent))
            self.tg_weather_enabled = row("weather_enabled",
                Toggle(bool(SETTINGS.get("weather_enabled", False)),
                       accent=self._accent),
                stretch=False)
            self.sl_weather_intensity = row("weather_intensity", PanelSlider(
                0, 100, SETTINGS.get(f"{weather}_intensity", 0.55) * 100,
                fmt=lambda v: f"{v:.1f}%" if v < 10 else f"{v:.0f}%",
                step=0.1, accent=self._accent))
            self.sl_rain_length = row("rain_length", PanelSlider(
                5, 160, SETTINGS.get("rain_length", 1.0) * 100,
                fmt=lambda v: f"{v:.0f}%", accent=self._accent))
            self.sl_rain_thickness = row("rain_thickness", PanelSlider(
                30, 260, SETTINGS.get("rain_thickness", 1.0) * 100,
                fmt=lambda v: f"{v:.0f}%", accent=self._accent))
            self.sl_rain_direction = row("rain_direction", PanelSlider(
                -55, 55, SETTINGS.get("rain_direction", 18.0),
                fmt=lambda v: f"{v:+.0f}°", accent=self._accent))
            self.sl_rain_fall_speed = row("rain_fall_speed", PanelSlider(
                25, 250, SETTINGS.get("rain_fall_speed", 1.0) * 100,
                fmt=lambda v: f"{v:.0f}%", accent=self._accent))
            self.sl_snow_size = row("snow_size", PanelSlider(
                45, 220, SETTINGS.get("snow_size", 1.0) * 100,
                fmt=lambda v: f"{v:.0f}%", accent=self._accent))
            self.sl_snow_spin_speed = row("snow_spin_speed", PanelSlider(
                0, 300, SETTINGS.get("snow_spin_speed", 1.0) * 100,
                fmt=lambda v: f"{v:.0f}%", accent=self._accent))
            self.sl_snow_fall_speed = row("snow_fall_speed", PanelSlider(
                25, 250, SETTINGS.get("snow_fall_speed", 1.0) * 100,
                fmt=lambda v: f"{v:.0f}%", accent=self._accent))
            self.sl_custom_size = row("custom_size", PanelSlider(
                45, 220, SETTINGS.get("custom_size", 1.0) * 100,
                fmt=lambda v: f"{v:.0f}%", accent=self._accent))
            self.sl_custom_spin_speed = row("custom_spin_speed", PanelSlider(
                0, 300, SETTINGS.get("custom_spin_speed", 1.0) * 100,
                fmt=lambda v: f"{v:.0f}%", accent=self._accent))
            self.sl_custom_fall_speed = row("custom_fall_speed", PanelSlider(
                25, 250, SETTINGS.get("custom_fall_speed", 1.0) * 100,
                fmt=lambda v: f"{v:.0f}%", accent=self._accent))
            self.ed_custom_symbols = QLineEdit(
                str(SETTINGS.get("custom_symbols", "❄,❅,❆")))
            self.ed_custom_symbols.setPlaceholderText("❄,❅,❆")
            self.ed_custom_symbols.setFixedHeight(panel_px(30))
            self.ed_custom_symbols.setStyleSheet(
                "QLineEdit { background: rgba(255,255,255,16);"
                " border: 1px solid rgba(255,255,255,30);"
                " border-radius: 8px; padding: 0 10px;"
                " color: rgba(255,255,255,225); }"
                "QLineEdit:focus { border-color: rgba(255,255,255,76); }")
            self.ed_custom_symbols.setFont(panel_font(11))
            self.sl_custom_symbols = row(
                "custom_symbols", self.ed_custom_symbols)
            self.custom_image = row("custom_image", ImagePathPicker(
                SETTINGS.get("custom_image", ""), accent=self._accent,
                title_key="custom_image"))
            self.sync_weather_controls(adjust=False)
            self.tg_lightning_enabled = row("lightning_enabled",
                Toggle(bool(SETTINGS.get("lightning_enabled", False)),
                       accent=self._accent),
                stretch=False)
            self.sl_lightning_size = row("lightning_size", PanelSlider(
                30, 200, SETTINGS.get("lightning_size", 1.0) * 100,
                fmt=lambda v: f"{v:.0f}%", accent=self._accent))
            self.sl_lightning_thickness = row(
                "lightning_thickness",
                PanelSlider(40, 300,
                            SETTINGS.get("lightning_thickness", 1.0) * 100,
                            fmt=lambda v: f"{v:.0f}%",
                            accent=self._accent))
            self.sl_lightning_intensity = row(
                "lightning_intensity",
                PanelSlider(0, 250,
                            SETTINGS.get("lightning_intensity", 0.55) * 100,
                            fmt=lambda v: f"{v:.0f}%",
                            accent=self._accent))
            self.sl_lightning_duration = row(
                "lightning_duration",
                PanelSlider(5, 150,
                            SETTINGS.get("lightning_duration", 0.18) * 100,
                            fmt=lambda v: f"{v / 100.0:.2f}s",
                            step=1, accent=self._accent))
            self.tg_lightning_duration_random = row(
                "lightning_duration_random",
                Toggle(bool(SETTINGS.get("lightning_duration_random", False)),
                       accent=self._accent),
                stretch=False)
            self.sg_auto_theme = row("auto_theme", Segmented(
                auto_theme_options(), SETTINGS["auto_theme"],
                accent=self._accent))
            self.sl_opacity = row("opacity", PanelSlider(
                35, 100, SETTINGS["bg_opacity"] * 100,
                fmt=lambda v: f"{v:.0f}%", accent=self._accent))
            self.sl_brightness = row("brightness", PanelSlider(
                55, 145, SETTINGS["brightness"] * 100,
                fmt=lambda v: f"{v:.0f}%", accent=self._accent))
            self.sl_scale = row("player_size", PanelSlider(
                80, 300, SETTINGS["scale"] * 100,
                fmt=lambda v: f"{v:.0f}%", accent=self._accent))
            self.sl_settings_scale = row("settings_size", PanelSlider(
                80, 200, SETTINGS["settings_scale"] * 100,
                fmt=lambda v: f"{v:.0f}%", live=False, accent=self._accent))
            self.sl_radius = row("radius", PanelSlider(
                6, 28, SETTINGS["radius"],
                fmt=lambda v: f"{v:.0f}px", accent=self._accent))
            self.sg_card_preset = row("card_preset", Segmented(
                card_preset_options(), SETTINGS["card_preset"], accent=self._accent))

        def build_text():
            section(lay, "section_text")
            self.fp_font = row("font", FontPicker(SETTINGS["font"]))
            self.cp_font_color = row("font_color", ColorValueButton(
                SETTINGS.get("font_color", ""), "#ffffff",
                "font_color", accent=self._accent))
            self.cp_source_text_color = row("source_text_color",
                ColorValueButton(SETTINGS.get("source_text_color", ""),
                                 "#ffffff", "source_text_color",
                                 accent=self._accent))
            self.cp_number_color = row("number_color", ColorValueButton(
                SETTINGS.get("number_color", ""), "#ffffff",
                "number_color", accent=self._accent))
            self.tg_marquee = row("marquee_enabled", Toggle(
                bool(SETTINGS["marquee_enabled"]), accent=self._accent),
                stretch=False)
            self.sl_title_size = row("title_size", PanelSlider(
                60, 180, SETTINGS["title_size"] * 100,
                fmt=lambda v: f"{v:.0f}%", accent=self._accent))
            self.sl_artist_size = row("artist_size", PanelSlider(
                60, 180, SETTINGS["artist_size"] * 100,
                fmt=lambda v: f"{v:.0f}%", accent=self._accent))
            self.sl_title_x = row("title_x_offset", PanelSlider(
                -80, 80, SETTINGS["title_x_offset"],
                fmt=lambda v: f"{v:.0f}px", accent=self._accent))
            self.sl_title_y = row("title_y_offset", PanelSlider(
                -80, 80, SETTINGS["title_y_offset"],
                fmt=lambda v: f"{v:.0f}px", accent=self._accent))
            self.sl_artist_x = row("artist_x_offset", PanelSlider(
                -80, 80, SETTINGS["artist_x_offset"],
                fmt=lambda v: f"{v:.0f}px", accent=self._accent))
            self.sl_artist_y = row("artist_y_offset", PanelSlider(
                -80, 80, SETTINGS["artist_y_offset"],
                fmt=lambda v: f"{v:.0f}px", accent=self._accent))

        def build_cover():
            section(lay, "section_cover")
            self.tg_show_cover = row("show_cover", Toggle(
                bool(SETTINGS["show_cover"]), accent=self._accent),
                stretch=False)
            self.sg_art_mode = row("art_mode", Segmented(
                art_mode_options(), SETTINGS["art_mode"], accent=self._accent))
            self.tg_show_tonearm = row("show_tonearm", Toggle(
                bool(SETTINGS["show_tonearm"]), accent=self._accent),
                stretch=False)
            self.sl_cover_blur = row("cover_blur", PanelSlider(
                0, 14, SETTINGS["cover_blur"],
                fmt=lambda v: f"{v:.1f}px", accent=self._accent, step=0.1))
            self.sg_cover_shape = row("cover_shape", Segmented(
                cover_shape_options(), SETTINGS["cover_shape"], accent=self._accent))
            self.sl_cover_radius_strength = row(
                "cover_radius_strength",
                PanelSlider(0, 200, SETTINGS["cover_radius_strength"] * 100,
                            fmt=lambda v: f"{v:.0f}%",
                            accent=self._accent))

        def build_buttons():
            section(lay, "section_buttons")
            self.cp_topbar_icon_color = row("topbar_icon_color",
                ColorValueButton(SETTINGS.get("topbar_icon_color", ""),
                                 "#ffffff", "topbar_icon_color",
                                 accent=self._accent))
            self.sl_control_button_size = row("control_button_size", PanelSlider(
                70, 160, SETTINGS["control_button_size"] * 100,
                fmt=lambda v: f"{v:.0f}%", accent=self._accent))
            self.sl_control_button_spacing = row(
                "control_button_spacing",
                PanelSlider(40, 220, SETTINGS["control_button_spacing"] * 100,
                            fmt=lambda v: f"{v:.0f}%",
                            accent=self._accent))
            self.sg_ctl = row("button_pos", Segmented(
                align_options(), SETTINGS["controls_align"], accent=self._accent))
            self.tg_btn_shuffle = row("show_btn_shuffle", Toggle(
                bool(SETTINGS["show_btn_shuffle"]), accent=self._accent),
                stretch=False)
            self.tg_btn_prev = row("show_btn_prev", Toggle(
                bool(SETTINGS["show_btn_prev"]), accent=self._accent),
                stretch=False)
            self.tg_btn_next = row("show_btn_next", Toggle(
                bool(SETTINGS["show_btn_next"]), accent=self._accent),
                stretch=False)
            self.tg_btn_repeat = row("show_btn_repeat", Toggle(
                bool(SETTINGS["show_btn_repeat"]), accent=self._accent),
                stretch=False)

        if panel_type == "normal":
            build_appearance()
            build_text()
            build_general()
            build_cover()
            build_buttons()
        else:
            build_general()
            build_appearance()
            build_text()
            build_cover()
            build_buttons()

        self.btn_advanced = PanelButton("", accent=self._accent, parent=self)
        self.advanced_box = _ScrollablePanelBody(self)
        self.advanced_box.hide()
        self._advanced_eff = QGraphicsOpacityEffect(self.advanced_box)
        self._advanced_eff.setOpacity(0.0)
        self.advanced_box.setGraphicsEffect(self._advanced_eff)
        if single_panel:
            adv = lay
        else:
            adv = QVBoxLayout(self.advanced_box.content)
            adv.setContentsMargins(panel_px(20), panel_px(10),
                                   panel_px(20), panel_px(18))
            adv.setSpacing(panel_px(8))
            adv.setAlignment(Qt.AlignTop)

        def update_advanced_button():
            self._update_advanced_button()

        def toggle_advanced():
            self._advanced_open = not self._advanced_open
            update_advanced_button()
            self._toggle_advanced_panel(self._advanced_open)

        def close_advanced():
            if not self._advanced_open and not self._advanced_hiding:
                return
            self._advanced_open = False
            update_advanced_button()
            self._toggle_advanced_panel(False)

        if not single_panel:
            self.btn_advanced.clicked.connect(toggle_advanced)

            adv_head_box = QWidget(self.advanced_box)
            adv_head = QHBoxLayout(adv_head_box)
            adv_head.setContentsMargins(panel_px(20), panel_px(14),
                                        panel_px(20), 0)
            adv_head.setSpacing(panel_px(8))
            self._advanced_title_label = QLabel(tr("advanced"))
            self._advanced_title_label.setFont(panel_font(13, QFont.DemiBold))
            self._advanced_title_label.setStyleSheet(
                "color: rgba(255,255,255,220);")
            adv_head.addWidget(self._advanced_title_label)
            adv_head.addStretch(1)
            self.btn_advanced_close = IconButton(
                GLYPH_CLOSE, panel_px(10), panel_px(24), fx="spin")
            self.btn_advanced_close.clicked.connect(close_advanced)
            adv_head.addWidget(self.btn_advanced_close)
            self.advanced_box.set_fixed_header(adv_head_box)
        else:
            self._advanced_title_label = QLabel(tr("advanced"), self)
            self._advanced_title_label.hide()
            self.btn_advanced_close = IconButton(
                GLYPH_CLOSE, panel_px(10), panel_px(24), fx="spin", parent=self)
            self.btn_advanced_close.hide()

        def adv_row(label_key, control, stretch=True):
            if categorized or full_mode:
                return row(label_key, control, stretch=stretch)
            host = QWidget()
            h = QHBoxLayout()
            host.setLayout(h)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(panel_px(10))
            lab = QLabel(tr(label_key) if label_key != "FPS" else "FPS")
            self._labels[label_key] = lab
            lab.setFont(panel_font(12))
            lab.setStyleSheet("color: rgba(255,255,255,165);")
            lab.setFixedWidth(panel_px(108))
            h.addWidget(lab)
            if stretch:
                h.addWidget(control, 1)
            else:
                h.addWidget(control)
                h.addStretch(1)
            current_layout.addWidget(host)
            register_search(host, label_key)
            return control

        def adv_toggle(label_key, setting_key):
            t = Toggle(bool(SETTINGS[setting_key]), accent=self._accent)
            adv_row(label_key, t, stretch=False)
            t.changed.connect(
                lambda v, k=setting_key: self.setting_changed.emit(k, v))
            return t

        section(adv, "section_appearance")
        self.sl_auto_strength = adv_row("auto_color_strength", PanelSlider(
            0, 100, SETTINGS["auto_color_strength"] * 100,
            fmt=lambda v: f"{v:.0f}%", accent=self._accent))

        section(adv, "section_cover")
        self.sl_tonearm_speed = adv_row("tonearm_speed", PanelSlider(
            40, 250, SETTINGS["tonearm_speed"] * 100,
            fmt=lambda v: f"{v / 100.0:.1f}x", accent=self._accent))
        self.sl_vinyl_spin_speed = adv_row("vinyl_spin_speed", PanelSlider(
            40, 250, SETTINGS["vinyl_spin_speed"] * 100,
            fmt=lambda v: f"{v / 100.0:.1f}x", accent=self._accent))
        self.sl_art_cover_size = adv_row("art_cover_size", PanelSlider(
            60, 140, SETTINGS["art_cover_size"] * 100,
            fmt=lambda v: f"{v:.0f}%", accent=self._accent))
        self.sl_art_vinyl_size = adv_row("art_vinyl_size", PanelSlider(
            70, 135, SETTINGS["art_vinyl_size"] * 100,
            fmt=lambda v: f"{v:.0f}%", accent=self._accent))
        self.sl_audio_feedback_thickness = adv_row(
            "audio_feedback_thickness",
            PanelSlider(40, 250, SETTINGS["audio_feedback_thickness"] * 100,
                        fmt=lambda v: f"{v:.0f}%", accent=self._accent))
        self.sl_audio_feedback_sensitivity = adv_row(
            "audio_feedback_sensitivity",
            PanelSlider(20, 300, SETTINGS["audio_feedback_sensitivity"] * 100,
                        fmt=lambda v: f"{v:.0f}%", accent=self._accent))
        self.tg_show_vinyl_center = adv_toggle(
            "show_vinyl_center", "show_vinyl_center")
        self.sl_vinyl_center_size = adv_row("vinyl_center_size", PanelSlider(
            40, 140, SETTINGS["vinyl_center_size"] * 100,
            fmt=lambda v: f"{v:.0f}%", accent=self._accent))
        self.tg_cover_border = adv_toggle("cover_border", "cover_border")
        self.sl_cover_border_width = adv_row("cover_border_width", PanelSlider(
            1, 8, SETTINGS["cover_border_width"],
            fmt=lambda v: f"{v:.1f}px", accent=self._accent))
        self.sl_cover_border_opacity = adv_row("cover_border_opacity", PanelSlider(
            0, 100, SETTINGS["cover_border_opacity"] * 100,
            fmt=lambda v: f"{v:.0f}%", accent=self._accent))

        section(adv, "section_controls")
        self.sg_seek = adv_row("seek_bar", Segmented(
            seek_options(), SETTINGS["seek_style"], accent=self._accent))
        self.sg_progress_time = adv_row("progress_time", Segmented(
            progress_time_options(), SETTINGS["progress_time_mode"],
            accent=self._accent))
        self.sl_seek_wave_amp = adv_row("seek_wave_amp", PanelSlider(
            0, 200, SETTINGS["seek_wave_amp"] * 100,
            fmt=lambda v: f"{v:.0f}%", accent=self._accent))
        self.sl_seek_wave_speed = adv_row("seek_wave_speed", PanelSlider(
            25, 250, SETTINGS["seek_wave_speed"] * 100,
            fmt=lambda v: f"{v:.0f}%", accent=self._accent))
        self.sl_seek_glow_strength = adv_row("seek_glow_strength", PanelSlider(
            0, 200, SETTINGS["seek_glow_strength"] * 100,
            fmt=lambda v: f"{v:.0f}%", accent=self._accent))
        self.cp_seek_fill_color = adv_row("seek_fill_color",
            ColorValueButton(SETTINGS.get("seek_fill_color", ""),
                             "accent", "seek_fill_color",
                             accent=self._accent))
        self.cp_seek_thumb_color = adv_row("seek_thumb_color",
            ColorValueButton(SETTINGS.get("seek_thumb_color", ""),
                             "#ffffff", "seek_thumb_color",
                             accent=self._accent))
        self.cp_seek_track_color = adv_row("seek_track_color",
            ColorValueButton(SETTINGS.get("seek_track_color", ""),
                             "#ffffff", "seek_track_color",
                             accent=self._accent))
        self.sl_seek_length = adv_row("seek_length", PanelSlider(
            20, 130, SETTINGS["seek_length"] * 100,
            fmt=lambda v: f"{v:.0f}%", accent=self._accent))
        self.sl_seek_thumb_size = adv_row("seek_thumb_size", PanelSlider(
            20, 150, SETTINGS["seek_thumb_size"] * 100,
            fmt=lambda v: f"{v:.0f}%", accent=self._accent))
        self.sg_thumb = adv_row("seek_thumb", Segmented(
            seek_thumb_options(), SETTINGS["seek_thumb"], accent=self._accent))
        self.tg_controls_hover = adv_toggle("controls_hover",
                                            "controls_hover")
        self.tg_topbar_hover = adv_toggle("topbar_hover", "topbar_hover")

        section(adv, "section_performance")
        self.sl_fps = adv_row("FPS", PanelSlider(
            24, 240, SETTINGS["fps"],
            fmt=lambda v: f"{v:.0f}", accent=self._accent))
        self.tg_show_fps = adv_toggle("show_fps", "show_fps")
        self.tg_anim_enabled = adv_toggle("anim_enabled", "anim_enabled")
        self.tg_aa = adv_toggle("antialias", "antialias")
        self.tg_src = adv_toggle("show_source", "show_source")
        self.tg_shadow = adv_toggle("shadow", "shadow")
        self.tg_gpu = adv_toggle("gpu", "gpu")

        section(adv, "section_hotkeys")
        self.kb_toggle = adv_row("hotkey_toggle", KeyBindButton(
            SETTINGS.get("hotkey", ""), accent=self._accent))
        self.kb_play = adv_row("hotkey_play", KeyBindButton(
            SETTINGS.get("hotkey_play", ""), accent=self._accent))
        self.kb_prev = adv_row("hotkey_prev", KeyBindButton(
            SETTINGS.get("hotkey_prev", ""), accent=self._accent))
        self.kb_next = adv_row("hotkey_next", KeyBindButton(
            SETTINGS.get("hotkey_next", ""), accent=self._accent))
        self.kb_vol_up = adv_row("hotkey_vol_up", KeyBindButton(
            SETTINGS.get("hotkey_vol_up", ""), accent=self._accent))
        self.kb_vol_down = adv_row("hotkey_vol_down", KeyBindButton(
            SETTINGS.get("hotkey_vol_down", ""), accent=self._accent))

        update_advanced_button()
        self.advanced_box.setVisible(False if single_panel else self._advanced_open)
        if self._advanced_eff is not None:
            self._advanced_eff.setOpacity(
                0.0 if single_panel else (1.0 if self._advanced_open else 0.0))

        foot_box = QWidget(body)
        foot = QHBoxLayout(foot_box)
        foot.setContentsMargins(panel_px(20), panel_px(10),
                                panel_px(20), panel_px(18))
        foot.setSpacing(panel_px(8))
        self.btn_reset = PanelButton(tr("reset_settings"), accent=self._accent)
        if single_panel:
            self.btn_advanced.hide()
            foot.addStretch(1)
        else:
            foot.addWidget(self.btn_advanced, 1)
        foot.addWidget(self.btn_reset)
        body.set_fixed_footer(foot_box)

        self.sw_theme.changed.connect(
            lambda v: self.setting_changed.emit("theme", v))
        self.sw_theme.custom_added.connect(
            lambda v: self.setting_changed.emit("custom_theme_add", v))
        self.sw_theme.custom_deleted.connect(
            lambda v: self.setting_changed.emit("custom_theme_delete", v))
        self.sg_auto_theme.changed.connect(
            lambda v: self.setting_changed.emit("auto_theme", v))
        self.bg_image.changed.connect(
            lambda v: self.setting_changed.emit("background_image", v))
        self.sg_bg_image_mode.changed.connect(
            lambda v: self.setting_changed.emit("background_image_mode", v))
        self.sl_bg_image_brightness.changed.connect(
            lambda v: self.setting_changed.emit(
                "background_image_brightness", v / 100.0))
        self.tg_bg_image_parallax.changed.connect(
            lambda v: self.setting_changed.emit(
                "background_image_parallax", v))
        self.sl_bg_image_parallax_strength.changed.connect(
            lambda v: self.setting_changed.emit(
                "background_image_parallax_strength", v / 100.0))
        self.sl_bg_image_parallax_fps.changed.connect(
            lambda v: self.setting_changed.emit(
                "background_image_parallax_fps", int(v)))
        self.sg_weather_effect.changed.connect(
            lambda v: self.setting_changed.emit("weather_effect", v))
        self.tg_weather_enabled.changed.connect(
            lambda v: self.setting_changed.emit("weather_enabled", v))
        self.sl_weather_intensity.changed.connect(
            lambda v: self.setting_changed.emit(
                f"{SETTINGS.get('weather_effect', 'rain')}_intensity",
                v / 100.0))
        self.sl_rain_length.changed.connect(
            lambda v: self.setting_changed.emit("rain_length", v / 100.0))
        self.sl_rain_thickness.changed.connect(
            lambda v: self.setting_changed.emit("rain_thickness", v / 100.0))
        self.sl_rain_direction.changed.connect(
            lambda v: self.setting_changed.emit("rain_direction", v))
        self.sl_rain_fall_speed.changed.connect(
            lambda v: self.setting_changed.emit("rain_fall_speed", v / 100.0))
        self.sl_snow_size.changed.connect(
            lambda v: self.setting_changed.emit("snow_size", v / 100.0))
        self.sl_snow_spin_speed.changed.connect(
            lambda v: self.setting_changed.emit("snow_spin_speed", v / 100.0))
        self.sl_snow_fall_speed.changed.connect(
            lambda v: self.setting_changed.emit("snow_fall_speed", v / 100.0))
        self.sl_custom_size.changed.connect(
            lambda v: self.setting_changed.emit("custom_size", v / 100.0))
        self.sl_custom_spin_speed.changed.connect(
            lambda v: self.setting_changed.emit(
                "custom_spin_speed", v / 100.0))
        self.sl_custom_fall_speed.changed.connect(
            lambda v: self.setting_changed.emit(
                "custom_fall_speed", v / 100.0))
        self.ed_custom_symbols.editingFinished.connect(
            lambda: self.setting_changed.emit(
                "custom_symbols", self.ed_custom_symbols.text()))
        self.custom_image.changed.connect(
            lambda v: self.setting_changed.emit("custom_image", v))
        self.tg_lightning_enabled.changed.connect(
            lambda v: self.setting_changed.emit("lightning_enabled", v))
        self.sl_lightning_size.changed.connect(
            lambda v: self.setting_changed.emit("lightning_size", v / 100.0))
        self.sl_lightning_thickness.changed.connect(
            lambda v: self.setting_changed.emit(
                "lightning_thickness", v / 100.0))
        self.sl_lightning_intensity.changed.connect(
            lambda v: self.setting_changed.emit(
                "lightning_intensity", v / 100.0))
        self.sl_lightning_duration.changed.connect(
            lambda v: self.setting_changed.emit(
                "lightning_duration", v / 100.0))
        self.tg_lightning_duration_random.changed.connect(
            lambda v: self.setting_changed.emit(
                "lightning_duration_random", v))
        self.sg_art_mode.changed.connect(
            lambda v: self.setting_changed.emit("art_mode", v))
        self.tg_show_tonearm.changed.connect(
            lambda v: self.setting_changed.emit("show_tonearm", v))
        self.sg_source.changed.connect(
            lambda v: self.setting_changed.emit("source", v))
        self.sg_panel_type.changed.connect(
            lambda v: self.setting_changed.emit("settings_panel_type", v))
        if self.sg_panel_category is not None:
            self.sg_panel_category.changed.connect(self._set_panel_category)
        self.tg_startup.changed.connect(
            lambda v: self.setting_changed.emit("startup_enabled", v))
        self.sg_startup_show.changed.connect(
            lambda v: self.setting_changed.emit("startup_show", v))
        self.sl_opacity.changed.connect(
            lambda v: self.setting_changed.emit("bg_opacity", v / 100.0))
        self.sl_brightness.changed.connect(
            lambda v: self.setting_changed.emit("brightness", v / 100.0))
        self.sl_scale.changed.connect(
            lambda v: self.setting_changed.emit("scale", v / 100.0))
        self.sl_settings_scale.changed.connect(
            lambda v: self.setting_changed.emit("settings_scale", v / 100.0))
        self.sl_radius.changed.connect(
            lambda v: self.setting_changed.emit("radius", int(round(v))))
        self.sl_auto_strength.changed.connect(
            lambda v: self.setting_changed.emit("auto_color_strength", v / 100.0))
        self.sg_card_preset.changed.connect(
            lambda v: self.setting_changed.emit("card_preset", v))
        self.sl_tonearm_speed.changed.connect(
            lambda v: self.setting_changed.emit("tonearm_speed", v / 100.0))
        self.sl_vinyl_spin_speed.changed.connect(
            lambda v: self.setting_changed.emit("vinyl_spin_speed", v / 100.0))
        self.sl_art_cover_size.changed.connect(
            lambda v: self.setting_changed.emit("art_cover_size", v / 100.0))
        self.sl_art_vinyl_size.changed.connect(
            lambda v: self.setting_changed.emit("art_vinyl_size", v / 100.0))
        self.sl_audio_feedback_thickness.changed.connect(
            lambda v: self.setting_changed.emit("audio_feedback_thickness",
                                                v / 100.0))
        self.sl_audio_feedback_sensitivity.changed.connect(
            lambda v: self.setting_changed.emit("audio_feedback_sensitivity",
                                                v / 100.0))
        self.sl_vinyl_center_size.changed.connect(
            lambda v: self.setting_changed.emit("vinyl_center_size", v / 100.0))
        self.tg_show_cover.changed.connect(
            lambda v: self.setting_changed.emit("show_cover", v))
        self.sl_cover_blur.changed.connect(
            lambda v: self.setting_changed.emit("cover_blur", v))
        self.sg_cover_shape.changed.connect(
            lambda v: self.setting_changed.emit("cover_shape", v))
        self.sl_cover_radius_strength.changed.connect(
            lambda v: self.setting_changed.emit("cover_radius_strength",
                                                v / 100.0))
        self.sl_cover_border_width.changed.connect(
            lambda v: self.setting_changed.emit("cover_border_width", v))
        self.sl_cover_border_opacity.changed.connect(
            lambda v: self.setting_changed.emit("cover_border_opacity", v / 100.0))
        self.sl_fps.changed.connect(
            lambda v: self.setting_changed.emit("fps", int(round(v))))
        self.kb_toggle.changed.connect(
            lambda v: self.setting_changed.emit("hotkey", v))
        self.kb_play.changed.connect(
            lambda v: self.setting_changed.emit("hotkey_play", v))
        self.kb_prev.changed.connect(
            lambda v: self.setting_changed.emit("hotkey_prev", v))
        self.kb_next.changed.connect(
            lambda v: self.setting_changed.emit("hotkey_next", v))
        self.kb_vol_up.changed.connect(
            lambda v: self.setting_changed.emit("hotkey_vol_up", v))
        self.kb_vol_down.changed.connect(
            lambda v: self.setting_changed.emit("hotkey_vol_down", v))
        self.sg_seek.changed.connect(
            lambda v: self.setting_changed.emit("seek_style", v))
        self.sg_progress_time.changed.connect(
            lambda v: self.setting_changed.emit("progress_time_mode", v))
        self.sl_seek_wave_amp.changed.connect(
            lambda v: self.setting_changed.emit("seek_wave_amp", v / 100.0))
        self.sl_seek_wave_speed.changed.connect(
            lambda v: self.setting_changed.emit("seek_wave_speed", v / 100.0))
        self.sl_seek_glow_strength.changed.connect(
            lambda v: self.setting_changed.emit("seek_glow_strength", v / 100.0))
        self.cp_seek_fill_color.changed.connect(
            lambda v: self.setting_changed.emit("seek_fill_color", v))
        self.cp_seek_thumb_color.changed.connect(
            lambda v: self.setting_changed.emit("seek_thumb_color", v))
        self.cp_seek_track_color.changed.connect(
            lambda v: self.setting_changed.emit("seek_track_color", v))
        self.sl_seek_length.changed.connect(
            lambda v: self.setting_changed.emit("seek_length", v / 100.0))
        self.sl_seek_thumb_size.changed.connect(
            lambda v: self.setting_changed.emit("seek_thumb_size", v / 100.0))
        self.sg_thumb.changed.connect(
            lambda v: self.setting_changed.emit("seek_thumb", v))
        self.sg_ctl.changed.connect(
            lambda v: self.setting_changed.emit("controls_align", v))
        self.sg_lang.changed.connect(
            lambda v: self.setting_changed.emit("language", v))
        self.fp_font.currentTextChanged.connect(
            lambda v: self.setting_changed.emit("font", v))
        self.cp_font_color.changed.connect(
            lambda v: self.setting_changed.emit("font_color", v))
        self.cp_source_text_color.changed.connect(
            lambda v: self.setting_changed.emit("source_text_color", v))
        self.cp_number_color.changed.connect(
            lambda v: self.setting_changed.emit("number_color", v))
        self.tg_marquee.changed.connect(
            lambda v: self.setting_changed.emit("marquee_enabled", v))
        self.sl_title_size.changed.connect(
            lambda v: self.setting_changed.emit("title_size", v / 100.0))
        self.sl_artist_size.changed.connect(
            lambda v: self.setting_changed.emit("artist_size", v / 100.0))
        self.sl_title_x.changed.connect(
            lambda v: self.setting_changed.emit("title_x_offset", v))
        self.sl_title_y.changed.connect(
            lambda v: self.setting_changed.emit("title_y_offset", v))
        self.sl_artist_x.changed.connect(
            lambda v: self.setting_changed.emit("artist_x_offset", v))
        self.sl_artist_y.changed.connect(
            lambda v: self.setting_changed.emit("artist_y_offset", v))
        self.sl_control_button_size.changed.connect(
            lambda v: self.setting_changed.emit(
                "control_button_size", v / 100.0))
        self.cp_topbar_icon_color.changed.connect(
            lambda v: self.setting_changed.emit("topbar_icon_color", v))
        self.sl_control_button_spacing.changed.connect(
            lambda v: self.setting_changed.emit(
                "control_button_spacing", v / 100.0))
        self.tg_btn_shuffle.changed.connect(
            lambda v: self.setting_changed.emit("show_btn_shuffle", v))
        self.tg_btn_prev.changed.connect(
            lambda v: self.setting_changed.emit("show_btn_prev", v))
        self.tg_btn_next.changed.connect(
            lambda v: self.setting_changed.emit("show_btn_next", v))
        self.tg_btn_repeat.changed.connect(
            lambda v: self.setting_changed.emit("show_btn_repeat", v))
        self.btn_reset.clicked.connect(
            lambda: self.setting_changed.emit("settings_reset", True))
        self.search.textChanged.connect(self._apply_search)

        self._body = body
        self._theme_row_h = self.sw_theme.height()
        # 色票列展開/收合 → 面板高度跟著伸縮。固定 header/footer 後統一走
        # relayout，避免舊的局部高度算法讓固定按鈕與內容互相拉扯。
        self.sw_theme.size_changed.connect(self._on_theme_size_changed)
        self._apply_search(self.search.text(), relayout=False)
        return self._apply_body_geometry(resize_window=resize_window)

    def _panel_layout(self, panel: QWidget):
        content = getattr(panel, "content", panel)
        return content.layout()

    def _panel_content_height(self, panel: QWidget, width: int) -> int:
        if isinstance(panel, _ScrollablePanelBody):
            return panel.content_height_for_width(width)
        panel.setFixedWidth(width)
        lay = panel.layout()
        if lay is not None:
            lay.activate()
        return max(1, panel.sizeHint().height())

    def _set_panel_viewport(self, panel: QWidget, width: int, height: int,
                            content_h: int):
        if isinstance(panel, _ScrollablePanelBody):
            panel.set_viewport(width, height, content_h)

    def _apply_body_geometry(self, resize_window: bool = True,
                             animate: bool = True):
        if self._body is None:
            return self.size()
        old_main_global = None
        if self.isVisible() and self._body.isVisible():
            old_main_global = self.mapToGlobal(self._body.geometry().topLeft())
        pm = panel_margin()
        base_w = panel_w()
        geo0 = self._screen_geometry_for(
            self.pos(), QSize(base_w + pm * 2, max(1, self.height())))
        w = min(base_w, max(260, geo0.width() - pm * 2))
        h = self._panel_content_height(self._body, w)
        gap = panel_px(10)
        panel_type = SETTINGS.get("settings_panel_type", "normal")
        full_mode = panel_type == "full"
        if full_mode:
            geo = self._screen_geometry_for(
                self.pos(), QSize(w + pm * 2, max(1, self.height())))
            panel_items: list[tuple[_ScrollablePanelBody, int]] = [
                (self._body, h)
            ]
            query_active = bool(getattr(self, "search", None)
                                and self.search.text().strip())
            for key in PANEL_CATEGORY_KEYS:
                box = self._full_box_sections.get(key)
                if box is None:
                    continue
                visible = box.isVisible() if query_active else True
                box.setVisible(visible)
                if not visible:
                    continue
                panel_items.append((box, self._panel_content_height(box, w)))

            max_cols = max(1, (geo.width() - pm * 2 + gap) // (w + gap))
            cols = max(1, min(len(panel_items), max_cols))
            rows = max(1, (len(panel_items) + cols - 1) // cols)
            max_panel_h = max(
                panel_px(150),
                (geo.height() - pm * 2 - gap * (rows - 1)) // rows)
            view_heights = [
                min(content_h, max_panel_h) for _, content_h in panel_items
            ]
            row_heights = []
            for row_i in range(rows):
                start = row_i * cols
                row_heights.append(max(view_heights[start:start + cols]))

            y = pm
            for row_i, row_h in enumerate(row_heights):
                x = pm
                for col_i in range(cols):
                    idx = row_i * cols + col_i
                    if idx >= len(panel_items):
                        break
                    panel, content_h = panel_items[idx]
                    view_h = view_heights[idx]
                    panel.setGeometry(x, y, w, view_h)
                    self._set_panel_viewport(panel, w, view_h, content_h)
                    panel.show()
                    x += w + gap
                y += row_h + gap

            final_w = cols * w + (cols - 1) * gap + pm * 2
            final_h = sum(row_heights) + (rows - 1) * gap + pm * 2
            final = QSize(final_w, final_h)
            if resize_window:
                self._set_window_geometry(self.pos(), final, animate=animate)
            return final

        single_panel = panel_type in ("categories", "full")
        adv_visible = (not single_panel and self.advanced_box is not None
                       and (self._advanced_open or self._advanced_hiding))
        adv_w = w
        adv_h = 0
        if self.advanced_box is not None:
            adv_lay = self._panel_layout(self.advanced_box)
            if adv_lay is not None:
                adv_lay.activate()
            adv_h = self._panel_content_height(self.advanced_box, adv_w)
        if adv_visible:
            self._advanced_side = self._choose_advanced_side(adv_w, gap)
        main_x = pm
        adv_x = pm + w + gap
        adv_y = pm
        if adv_visible and self._advanced_side == "left":
            adv_x = pm
            main_x = pm + adv_w + gap
        elif adv_visible and self._advanced_side == "bottom":
            adv_x = pm
            main_x = pm
        side_by_side = adv_visible and self._advanced_side != "bottom"
        final_w = w + pm * 2 + (adv_w + gap if side_by_side else 0)
        raw_h = ((h + gap + adv_h + pm * 2)
                 if adv_visible and self._advanced_side == "bottom"
                 else max(h, adv_h if adv_visible else 0) + pm * 2)
        geo = self._screen_geometry_for(self.pos(), QSize(final_w, raw_h))
        if adv_visible and self._advanced_side == "bottom":
            max_stack_h = max(panel_px(260), geo.height() - pm * 2 - gap)
            if h + adv_h <= max_stack_h:
                body_h = h
                adv_view_h = adv_h
            else:
                body_h = min(h, max(panel_px(150), round(max_stack_h * 0.42)))
                adv_view_h = min(adv_h, max(1, max_stack_h - body_h))
                if adv_view_h >= adv_h:
                    body_h = min(h, max(1, max_stack_h - adv_view_h))
                elif body_h >= h:
                    adv_view_h = min(adv_h, max(1, max_stack_h - body_h))
            adv_y = pm + body_h + gap
        else:
            max_inner_h = max(panel_px(160), geo.height() - pm * 2)
            body_h = min(h, max_inner_h)
            adv_view_h = min(adv_h, max_inner_h) if adv_visible else adv_h
        self._body.setGeometry(main_x, pm, w, body_h)
        self._set_panel_viewport(self._body, w, body_h, h)
        if self.advanced_box is not None:
            self._advanced_geo = QRectF(adv_x, adv_y, adv_w, adv_view_h)
            self.advanced_box.setGeometry(adv_x, adv_y, adv_w, adv_view_h)
            self._set_panel_viewport(
                self.advanced_box, adv_w, adv_view_h, adv_h)
        final = self.size().expandedTo(self.minimumSizeHint())
        final.setWidth(final_w)
        final_h = ((body_h + gap + adv_view_h + pm * 2)
                   if adv_visible and self._advanced_side == "bottom"
                   else max(body_h, adv_view_h if adv_visible else 0) + pm * 2)
        final.setHeight(final_h)
        if resize_window:
            target_pos = QPoint(self.pos())
            if old_main_global is not None:
                target_pos = old_main_global - QPoint(main_x, pm)
            self._set_window_geometry(target_pos, final, animate=animate)
        return final

    def _relayout(self, animate: bool = True):
        self._apply_body_geometry(animate=animate)
        self.update()

    def _on_theme_size_changed(self):
        if self._body is None or not hasattr(self, "sw_theme"):
            return
        new_row_h = self.sw_theme.height()
        old_row_h = self._theme_row_h or new_row_h
        delta = new_row_h - old_row_h
        self._theme_row_h = new_row_h
        if abs(delta) < 1:
            self.sw_theme.update()
            return
        self._sync_section_container_heights()
        self._relayout(animate=False)
        self.update()

    def _screen_geometry_for(self, pos: QPoint, size: QSize):
        center = QPoint(pos.x() + size.width() // 2,
                        pos.y() + size.height() // 2)
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

    def _bounded_window_pos(self, pos: QPoint, size: QSize) -> QPoint:
        geo = self._screen_geometry_for(pos, size)
        if size.width() >= geo.width():
            x = geo.left()
        else:
            x = min(max(pos.x(), geo.left()), geo.right() + 1 - size.width())
        if size.height() >= geo.height():
            y = geo.top()
        else:
            y = min(max(pos.y(), geo.top()), geo.bottom() + 1 - size.height())
        return QPoint(x, y)

    def _set_window_geometry(self, pos: QPoint, size: QSize,
                             animate: bool = True):
        target_pos = self._bounded_window_pos(pos, size)
        target_size = QSize(size)
        if (not animate or not self.isVisible() or not anim_on()
                or adur(230, 130) <= 0):
            self._geo_anim.stop()
            if self.size() != target_size:
                self.setFixedSize(target_size)
            if self.pos() != target_pos:
                self.move(target_pos)
            return
        if self.pos() == target_pos and self.size() == target_size:
            return
        cur_pos = QPoint(self.pos())
        cur_size = QSize(self.size())
        if self._geo_anim.state() == Anim.Running:
            self._geo_anim.stop()
            self.setFixedSize(cur_size)
            self.move(cur_pos)
        else:
            self._geo_anim.stop()
        self._geo_from_pos = cur_pos
        self._geo_to_pos = QPoint(target_pos)
        self._geo_from_size = cur_size
        self._geo_to_size = QSize(target_size)
        self._geo_anim.setStartValue(0.0)
        self._geo_anim.setEndValue(1.0)
        self._geo_anim.setDuration(adur(230, 130))
        self._geo_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._geo_anim.start()

    def _on_window_geometry(self, value):
        t = max(0.0, min(1.0, float(value)))
        x = round(self._geo_from_pos.x()
                  + (self._geo_to_pos.x() - self._geo_from_pos.x()) * t)
        y = round(self._geo_from_pos.y()
                  + (self._geo_to_pos.y() - self._geo_from_pos.y()) * t)
        w = round(self._geo_from_size.width()
                  + (self._geo_to_size.width()
                     - self._geo_from_size.width()) * t)
        h = round(self._geo_from_size.height()
                  + (self._geo_to_size.height()
                     - self._geo_from_size.height()) * t)
        self.setFixedSize(max(1, w), max(1, h))
        self.move(x, y)
        self.update()

    def _window_geometry_done(self):
        self.setFixedSize(self._geo_to_size)
        self.move(self._geo_to_pos)
        self.update()
        self.position_committed.emit(QPoint(self.pos()))

    def _stop_window_geometry_at_current(self):
        if self._geo_anim.state() != Anim.Running:
            return
        pos = QPoint(self.pos())
        size = QSize(self.size())
        self._geo_anim.stop()
        self.setFixedSize(size)
        self.move(pos)

    def _update_advanced_button(self):
        if not hasattr(self, "btn_advanced"):
            return
        self.btn_advanced.set_text(tr("advanced"))
        self.btn_advanced.set_chevron(self._advanced_open)

    def _category_content_rect(self) -> QRect:
        if self._body is None:
            return QRect()
        top = None
        for _, lab, _, _, _ in self._section_groups:
            if lab.isVisible():
                top = lab.mapTo(self._body, QPoint(0, 0)).y()
                break
        if top is None:
            top = 0
        top = max(0, min(self._body.height() - 1, int(top)))
        return QRect(0, top, self._body.width(),
                     max(1, self._body.height() - top))

    def _body_rect_to_panel(self, rect: QRect) -> QRectF:
        if self._body is None:
            return QRectF(rect)
        top_left = self._body.geometry().topLeft() + rect.topLeft()
        return QRectF(top_left.x(), top_left.y(),
                      rect.width(), rect.height())

    def _set_panel_category(self, key: str):
        if key not in PANEL_CATEGORY_KEYS:
            return
        if key == self._panel_category:
            return
        if SETTINGS.get("settings_panel_type") != "categories":
            self._panel_category = key
            if self._body is not None:
                self._body.show()
                self._body.raise_()
                self._body.set_scroll_offset(0.0)
            self._apply_search(self.search.text())
            return
        self._animate_category_switch(key)

    def _animate_category_switch(self, key: str):
        """categories 模式切分類：舊內容淡出、新內容上移淡入、面板高度平滑
        過渡。沿用 scale 切換那套 _overlay/_zoom_anim/_zoom_done 基礎設施
        （陰影、圓角、視窗收尾都已驗證），差別是 align_top 不縱向拉伸。"""
        body = self._body
        ms = adur(240, 130)
        if (body is None or not anim_on() or ms <= 0
                or not self.isVisible()):
            self._panel_category = key
            if body is not None:
                body.show()
                body.raise_()
                body.set_scroll_offset(0.0)
            self._apply_search(self.search.text(), relayout=False)
            self._relayout(animate=False)
            self.update()
            return

        # 縮放動畫（scale 或上一次分類切換）仍在跑：從目前合成畫面接續
        if self._zoom_anim.state() == Anim.Running and self._overlay is not None:
            self._zoom_restart = True
            self._zoom_anim.stop()
            self._zoom_restart = False
            r0 = self._overlay.cur_rect().toRect()
            old_pm = self._overlay.composite()
        else:
            r0 = body.geometry()
            old_pm = body.grab()

        old_size = QSize(self.size())

        # 套用新分類（categories 不重建 widget，只切 section 可見性）
        self._panel_category = key
        self._apply_search(self.search.text(), relayout=False)
        final_size = self._apply_body_geometry(resize_window=False,
                                               animate=False)
        body.show()             # restart 接續時 body 可能仍 hidden，grab 前先還原
        body.set_scroll_offset(0.0)
        body.raise_()
        new_pm = body.grab()
        r1 = body.geometry()
        self._final_size = (final_size.width(), final_size.height())

        # 視窗撐到新舊較大者，overlay 在內部以 align_top 交叉淡化＋上移；
        # 高度差由 cur_rect 內插畫出，動畫結束 _zoom_done 收到最終尺寸
        self.setFixedSize(max(self._final_size[0], old_size.width()),
                          max(self._final_size[1], old_size.height()))
        if self._overlay is None:
            self._overlay = _PanelZoomOverlay(self)
        self._overlay.setGeometry(self.rect())
        self._overlay.setup(old_pm, r0, new_pm, r1,
                            shadow_included=False, align_top=True,
                            slide=panel_px(10))
        self._overlay.show()
        self._overlay.raise_()
        body.hide()
        self.repaint()

        self._zoom_anim.setStartValue(0.0)
        self._zoom_anim.setEndValue(1.0)
        self._zoom_anim.setDuration(ms)
        self._zoom_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._zoom_anim.start()

    def _section_toggle_anim_enabled(self) -> bool:
        return True

    def _toggle_section(self, group_id: str, header: SectionLabel,
                        container: QWidget):
        collapsed = not bool(self._section_collapsed.get(group_id, False))
        self._section_collapsed[group_id] = collapsed
        animate = self._section_toggle_anim_enabled()
        header.set_collapsed(collapsed, animate=animate)
        self._animate_section(group_id, container, collapsed, animate=animate)

    def _section_content_height(self, container: QWidget) -> int:
        lay = container.layout()
        if lay is not None:
            lay.activate()
            hint = lay.sizeHint().height()
        else:
            hint = container.sizeHint().height()
        return max(0, hint)

    def _section_gap(self, group_id: str) -> int:
        return int(self._section_target_gaps.get(group_id, panel_px(10)))

    def _set_section_gap(self, group_id: str, value: float):
        lay = self._section_gap_layouts.get(group_id)
        if lay is None:
            return
        gap = max(0, round(float(value)))
        if lay.spacing() != gap:
            lay.setSpacing(gap)
            wrapper = self._section_wrappers.get(group_id)
            if wrapper is not None:
                wrapper.updateGeometry()

    def _set_section_gap_for_height(self, group_id: str, height: float):
        full_h = max(1.0, float(self._section_anim_full_heights.get(
            group_id, 1.0)))
        ratio = max(0.0, min(1.0, float(height) / full_h))
        self._set_section_gap(group_id, self._section_gap(group_id) * ratio)

    def _sync_section_container_heights(self):
        for _, _, _, group_id, container in self._section_groups:
            if group_id in self._section_animating or not container.isVisible():
                continue
            h = self._section_content_height(container)
            if container.height() != h:
                container.setFixedHeight(h)

    def _section_frame_lock_enabled(self) -> bool:
        return (SETTINGS.get("settings_panel_type", "normal") == "normal"
                and self.advanced_box is not None
                and not self._advanced_open
                and not self._advanced_hiding)

    def _clear_section_frame_lock(self):
        self._section_frame_lock_size = None
        self._section_frame_lock_body_h = 0
        self._section_frame_lock_content_h = 0

    def _begin_section_frame_lock(self, group_id: str,
                                  start: float, end: float):
        self._clear_section_frame_lock()
        if not self._section_frame_lock_enabled() or self._body is None:
            return
        if end <= start:
            return
        container = self._section_anim_containers.get(group_id)
        if container is None:
            return
        body_geo = self._body.geometry()
        body_w = max(1, body_geo.width())
        lay = self._section_gap_layouts.get(group_id)

        # 展開時先把捲動內容層固定到最終尺寸。動畫每幀只改 section
        # clip 高度，不再重算整個面板高度，避免上方控制項在透明視窗中重繪抖動。
        self._set_section_gap(group_id, self._section_gap(group_id))
        container.setFixedHeight(max(0, round(float(end))))
        target_content_h = self._panel_content_height(self._body, body_w)
        container.setFixedHeight(max(0, round(float(start))))
        self._set_section_gap_for_height(group_id, start)
        content_lay = self._panel_layout(self._body)
        if content_lay is not None:
            content_lay.activate()

        pm = panel_margin()
        geo = self._screen_geometry_for(
            self.pos(), QSize(self.width(), target_content_h + pm * 2))
        max_inner_h = max(panel_px(160), geo.height() - pm * 2)
        lock_h = max(self.height(), min(target_content_h, max_inner_h) + pm * 2)
        lock_size = QSize(self.width(), max(1, lock_h))
        body_h = max(1, lock_size.height() - pm * 2)
        target_pos = self._bounded_window_pos(self.pos(), lock_size)
        if self.size() != lock_size:
            self.setFixedSize(lock_size)
        if self.pos() != target_pos:
            self.move(target_pos)
        self._body.setGeometry(body_geo.x(), body_geo.y(), body_w, body_h)
        self._set_panel_viewport(self._body, body_w, body_h, target_content_h)
        self._section_frame_lock_size = lock_size
        self._section_frame_lock_body_h = body_h
        self._section_frame_lock_content_h = target_content_h

    def _relayout_section_frame(self):
        if self._section_resize_anchor is None:
            self._relayout(animate=False)
            return
        self._geo_anim.stop()
        lock_size = self._section_frame_lock_size
        if lock_size is not None and self._body is not None:
            target_pos = self._bounded_window_pos(
                self._section_resize_anchor, lock_size)
            if self.size() != lock_size:
                self.setFixedSize(lock_size)
            if self.pos() != target_pos:
                self.move(target_pos)
            g = self._body.geometry()
            body_h = max(1, self._section_frame_lock_body_h or g.height())
            content_h = max(
                1, self._section_frame_lock_content_h
                or getattr(self._body, "_content_h", body_h))
            if g.height() != body_h:
                self._body.setGeometry(g.x(), g.y(), g.width(), body_h)
            if (getattr(self._body, "_viewport_h", 0)
                    != body_h - getattr(self._body, "_header_h", 0)
                    - getattr(self._body, "_footer_h", 0)):
                self._set_panel_viewport(self._body, g.width(),
                                         body_h, content_h)
            lay = self._panel_layout(self._body)
            if lay is not None:
                lay.activate()
            self._body.viewport.update()
            self.update()
            return
        final = self._apply_body_geometry(resize_window=False, animate=False)
        target_pos = self._bounded_window_pos(
            self._section_resize_anchor, final)
        if self.size() != final:
            self.setFixedSize(final)
        if self.pos() != target_pos:
            self.move(target_pos)
        self.update()

    def _set_section_height(self, group_id: str, value: float):
        container = self._section_anim_containers.get(group_id)
        if container is None:
            return
        h = max(0, round(float(value)))
        container.setFixedHeight(h)
        if h > 0 and not container.isVisible():
            container.show()
        self._set_section_gap_for_height(group_id, h)
        self._relayout_section_frame()

    def _on_section_anim(self, group_id: str, value):
        self._set_section_height(group_id, float(value))

    def _section_anim_done(self, group_id: str):
        collapsed = bool(self._section_anim_targets.get(group_id, False))
        container = self._section_anim_containers.get(group_id)
        self._section_animating.discard(group_id)
        if container is None:
            self._clear_section_frame_lock()
            return
        self._clear_section_frame_lock()
        if collapsed:
            self._set_section_gap(group_id, 0)
            container.setFixedHeight(0)
            container.hide()
            self._apply_search(self.search.text(), relayout=False)
            self._relayout_section_frame()
        else:
            self._set_section_gap(group_id, self._section_gap(group_id))
            container.setFixedHeight(self._section_content_height(container))
            container.show()
            self._relayout_section_frame()
        self._section_anim_full_heights.pop(group_id, None)
        self._section_resize_anchor = None

    def _animate_section(self, group_id: str, container: QWidget,
                         collapsed: bool, animate: bool = True):
        anim = self._section_anims.get(group_id)
        if anim is not None and anim.state() == Anim.Running:
            anim.stop()
        self._section_anim_containers[group_id] = container
        self._section_anim_targets[group_id] = bool(collapsed)
        if getattr(self, "search", None) is not None and self.search.text().strip():
            self._section_animating.discard(group_id)
            self._clear_section_frame_lock()
            container.setMinimumHeight(0)
            container.setMaximumHeight(16777215)
            self._apply_search(self.search.text(), relayout=False)
            self._relayout(animate=False)
            return
        ms = adur(260, 150)
        should_animate = bool(animate and anim_on() and ms > 0
                              and self.isVisible())
        if should_animate:
            self._section_animating.add(group_id)
        else:
            self._section_animating.discard(group_id)
        self._apply_search(self.search.text(), relayout=False)
        full_h = (self._section_content_height(container)
                  if should_animate or not collapsed else 0)
        self._section_anim_full_heights[group_id] = max(1, full_h)
        start = container.height() if container.isVisible() else 0
        if collapsed and start <= 0:
            start = full_h
        end = 0 if collapsed else full_h
        if not should_animate:
            self._stop_window_geometry_at_current()
            if collapsed:
                self._set_section_gap(group_id, 0)
                container.setFixedHeight(0)
                container.hide()
            else:
                self._set_section_gap(group_id, self._section_gap(group_id))
                container.setFixedHeight(full_h)
                container.show()
            self._section_resize_anchor = None
            self._clear_section_frame_lock()
            self._section_anim_full_heights.pop(group_id, None)
            self._relayout(animate=False)
            return
        if anim is None:
            anim = Anim(self)
            anim.valueChanged.connect(
                lambda v, gid=group_id: self._on_section_anim(gid, v))
            anim.finished.connect(
                lambda gid=group_id: self._section_anim_done(gid))
            self._section_anims[group_id] = anim
        self._stop_window_geometry_at_current()
        self._section_resize_anchor = QPoint(self.pos())
        self._begin_section_frame_lock(group_id, start, end)
        anim.setStartValue(start)
        anim.setEndValue(end)
        anim.setDuration(ms)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.start()

    def _apply_search(self, text: str = "", relayout: bool = True):
        query = str(text or "").strip().lower()
        categorized = SETTINGS.get("settings_panel_type", "normal") == "categories"
        full_mode = SETTINGS.get("settings_panel_type", "normal") == "full"
        section_animate = self._section_toggle_anim_enabled()
        any_advanced = False
        row_match: dict[QWidget, bool] = {}
        full_box_visible: dict[str, bool] = {}
        for host, label_key, keys in self._search_rows:
            terms = set(keys)
            if label_key == "FPS":
                terms.add("fps")
            else:
                terms.add(tr(label_key).lower())
            match = not query or any(query in term for term in terms)
            row_match[host] = match
            host.setVisible(match)
            if (match and query and self.advanced_box is not None
                    and self.advanced_box.isAncestorOf(host)):
                any_advanced = True

        for section_key, lab, children, group_id, container in self._section_groups:
            category_match = (not categorized or query
                              or section_key == self._panel_category)
            collapsed = bool(self._section_collapsed.get(group_id, False))
            lab.set_collapsed(collapsed and not query,
                              animate=section_animate)
            any_match = any(row_match.get(w, w.isVisible()) for w in children)
            animating = group_id in self._section_animating
            section_visible = category_match and (not query or any_match)
            show_content = section_visible and (query or not collapsed
                                                or animating)
            wrapper = self._section_wrappers.get(group_id)
            for w in children:
                w.setMinimumHeight(0)
                w.setMaximumHeight(16777215)
                w.setVisible(show_content and row_match.get(w, w.isVisible()))
            lab.setVisible(section_visible)
            if animating:
                if show_content and not container.isVisible():
                    container.show()
            elif show_content:
                self._set_section_gap(group_id, self._section_gap(group_id))
                container.setMinimumHeight(0)
                container.setMaximumHeight(16777215)
                container.show()
            else:
                self._set_section_gap(group_id, 0)
                container.setFixedHeight(0)
                container.hide()
            if wrapper is not None:
                wrapper.setVisible(section_visible)
            if full_mode:
                full_box_visible[section_key] = (
                    full_box_visible.get(section_key, False)
                    or section_visible)

        if full_mode:
            for key, box in self._full_box_sections.items():
                box.setVisible(full_box_visible.get(key, False))

        self._sync_section_container_heights()

        if (not categorized and query and any_advanced
                and not self._advanced_open):
            self._advanced_open = True
            self._update_advanced_button()
            self._toggle_advanced_panel(True)
        elif relayout:
            self._relayout()

    def _choose_advanced_side(self, adv_w: int, gap: int) -> str:
        if self._body is None:
            return "right"
        scr = QApplication.screenAt(self.frameGeometry().center())
        geo = (scr or QApplication.primaryScreen()).availableGeometry()
        main_geo = self._body.geometry()
        full_w = main_geo.width() + adv_w + gap + panel_margin() * 2
        if full_w > geo.width():
            return "bottom"
        main_left = self.x() + main_geo.x()
        main_right = main_left + main_geo.width()
        right_space = geo.right() + 1 - main_right
        left_space = main_left - geo.left()
        need = adv_w + gap + panel_margin()
        if right_space >= need:
            return "right"
        if left_space >= need:
            return "left"
        return "right" if right_space >= left_space else "left"

    def _keep_on_screen(self):
        self._set_window_geometry(self.pos(), self.size(), animate=True)

    def _toggle_advanced_panel(self, open_: bool):
        self._advanced_anim.stop()
        if self.advanced_box is None:
            self._relayout()
            return
        if open_:
            self._advanced_hiding = False
            self.advanced_box.show()
            self._apply_body_geometry()
            self._advanced_t = 0.0
            self._on_advanced_anim(0.0)
            ms = adur(260, 150)
            if not anim_on() or ms <= 0 or not self.isVisible():
                self._on_advanced_anim(1.0)
                return
            self._advanced_anim.setStartValue(0.0)
            self._advanced_anim.setEndValue(1.0)
        else:
            self._advanced_hiding = True
            ms = adur(220, 130)
            if not anim_on() or ms <= 0 or not self.isVisible():
                self._on_advanced_anim(0.0)
                self._advanced_anim_done()
                return
            self._advanced_anim.setStartValue(self._advanced_t)
            self._advanced_anim.setEndValue(0.0)
        self._advanced_anim.setDuration(ms)
        self._advanced_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._advanced_anim.start()

    def _on_advanced_anim(self, v):
        self._advanced_t = max(0.0, min(1.0, float(v)))
        if self.advanced_box is None:
            return
        if self._advanced_eff is not None:
            self._advanced_eff.setOpacity(self._advanced_t)
        g = QRectF(self._advanced_geo)
        slide = panel_px(14) * (1.0 - self._advanced_t)
        if self._advanced_side == "bottom":
            dx = 0
            dy = slide
        else:
            dx = -slide if self._advanced_side == "right" else slide
            dy = 0
        self.advanced_box.setGeometry(round(g.x() + dx), round(g.y() + dy),
                                      round(g.width()), round(g.height()))
        self.update()

    def _advanced_anim_done(self):
        if self.advanced_box is None:
            return
        if self._advanced_hiding and not self._advanced_open:
            self._advanced_hiding = False
            self.advanced_box.hide()
            self.update()
            self.repaint()
            self._apply_body_geometry()
            self.update()
            self.repaint()
            QTimer.singleShot(0, self.repaint)
            QTimer.singleShot(16, self.repaint)
        elif self._advanced_open:
            self._on_advanced_anim(1.0)

    def rebuild_for_panel_type(self):
        if self._body is None:
            self._build_body()
            return
        if self._type_slide_anim.state() == Anim.Running:
            self._type_slide_abort = True
            self._type_slide_anim.stop()
            self._type_slide_abort = False
            self._type_direct = False
            if self._type_overlay is not None:
                self._type_overlay.hide()
        old_panel_type = self._current_panel_type
        new_panel_type = SETTINGS.get("settings_panel_type", "normal")
        wide_capture = old_panel_type == "full" or new_panel_type == "full"
        expanded = self.sw_theme.is_expanded()
        old_size = QSize(self.size())
        old_body = self._body
        old_body.set_scroll_offset(0.0)
        old_body_rect = QRect(old_body.geometry())
        old_advanced = self.advanced_box
        old_full_boxes = list(getattr(self, "_full_boxes", []))
        ms = adur(280, 150)
        freeze_updates = (not wide_capture and anim_on() and ms > 0
                          and self.isVisible()
                          and self.updatesEnabled())
        if freeze_updates:
            self.setUpdatesEnabled(False)
        if wide_capture:
            old_pm = self.grab()
            old_rect = QRectF(0, 0, old_size.width(), old_size.height())
        for w in [old_body, old_advanced, *old_full_boxes]:
            if w is not None:
                w.hide()

        final_size = self._build_body(expanded=expanded, resize_window=False)
        if self._body is None:
            if freeze_updates:
                self.setUpdatesEnabled(True)
            return
        self.setFixedSize(max(final_size.width(), old_size.width()),
                          max(final_size.height(), old_size.height()))
        self._body.show()
        for box in getattr(self, "_full_boxes", []):
            if not box.isHidden():
                box.show()
        if self.advanced_box is not None and self._advanced_open:
            self.advanced_box.show()
            self._on_advanced_anim(1.0)
        self._final_size = (final_size.width(), final_size.height())

        if not wide_capture:
            final_body = QRect(self._body.geometry())
            final_content_h = int(getattr(self._body, "_content_h",
                                          final_body.height()))
            for w in [old_body, old_advanced, *old_full_boxes]:
                if w is not None:
                    w.deleteLater()
            if not anim_on() or ms <= 0 or not self.isVisible():
                self._set_window_geometry(self.pos(), final_size,
                                          animate=False)
                if freeze_updates:
                    self.setUpdatesEnabled(True)
                self.update()
                return

            self._type_from_size = QSize(old_size)
            self._type_to_size = QSize(final_size)
            self._type_from_pos = QPoint(self.pos())
            self._type_to_pos = self._bounded_window_pos(
                QPoint(self.pos()), QSize(final_size))
            self._type_direct = True
            self._type_from_body = old_body_rect
            self._type_final_body = final_body
            self._type_to_body = QRect(final_body)
            self._type_to_content_h = final_content_h
            self.setFixedSize(old_size)
            self.move(self._type_from_pos)
            self._on_type_slide(0.0)
            self._body.show()
            self._body.raise_()
            if freeze_updates:
                self.setUpdatesEnabled(True)
                freeze_updates = False
            self.repaint()

            self._type_slide_anim.setStartValue(0.0)
            self._type_slide_anim.setEndValue(1.0)
            self._type_slide_anim.setDuration(ms)
            self._type_slide_anim.setEasingCurve(QEasingCurve.OutCubic)
            self._type_slide_anim.start()
            return

        new_pm = self.grab().copy(0, 0, final_size.width(),
                                  final_size.height())
        new_rect = QRectF(0, 0, final_size.width(), final_size.height())
        for w in [old_body, old_advanced, *old_full_boxes]:
            if w is not None:
                w.deleteLater()

        if not anim_on() or ms <= 0 or not self.isVisible():
            self.setFixedSize(*self._final_size)
            self._keep_on_screen()
            self.update()
            return

        # 面板類型切換尺寸差異極大（412×997↔2342×760↔412×471），舊的滑動
        # 疊圖（填滿新舊聯集矩形的不透明深色 + 超大 span 橫掃）會爆出大片深色
        # 空白；改用縮放交叉淡化（矩形 r0→r1 內插、透明合成），全程無空白
        if not isinstance(self._type_overlay, _PanelZoomOverlay):
            self._type_overlay = _PanelZoomOverlay(self)
        self._type_overlay.setGeometry(self.rect())
        self._type_overlay.setup(old_pm, old_rect, new_pm, new_rect,
                                 shadow_included=wide_capture)
        self._type_overlay.show()
        self._type_overlay.raise_()
        self._body.hide()
        for box in getattr(self, "_full_boxes", []):
            box.hide()
        if self.advanced_box is not None:
            self.advanced_box.hide()
        self.repaint()

        self._type_slide_anim.setStartValue(0.0)
        self._type_slide_anim.setEndValue(1.0)
        self._type_slide_anim.setDuration(ms)
        self._type_slide_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._type_slide_anim.start()

    def rebuild_for_scale(self):
        if self._body is None:
            self._build_body()
            return
        expanded = self.sw_theme.is_expanded()
        wide_capture = (self._advanced_open or self._advanced_hiding
                        or self._current_panel_type == "full")
        if self._zoom_anim.state() == Anim.Running and self._overlay is not None:
            self._zoom_restart = True
            self._zoom_anim.stop()
            self._zoom_restart = False
            r0 = self._overlay.cur_rect().toRect()
            old_pm = self._overlay.composite()
        else:
            r0 = self.rect() if wide_capture else self._body.geometry()
            old_pm = self.grab() if wide_capture else self._body.grab()

        old_size = self.size()
        old_body = self._body
        old_advanced = self.advanced_box
        old_full_boxes = list(getattr(self, "_full_boxes", []))
        for w in [old_body, old_advanced, *old_full_boxes]:
            if w is not None:
                w.hide()
        final_size = self._build_body(expanded=expanded, resize_window=False)
        if self._body is None:
            return
        if wide_capture:
            self.setFixedSize(max(final_size.width(), old_size.width()),
                              max(final_size.height(), old_size.height()))
        self._body.show()
        if self._current_panel_type == "full":
            for box in getattr(self, "_full_boxes", []):
                box.show()
        if self.advanced_box is not None and self._advanced_open:
            self.advanced_box.show()
            self._on_advanced_anim(1.0)
        if wide_capture:
            new_pm = self.grab().copy(0, 0, final_size.width(),
                                      final_size.height())
            r1 = QRectF(0, 0, final_size.width(), final_size.height())
        else:
            new_pm = self._body.grab()
            r1 = self._body.geometry()
        self._final_size = (final_size.width(), final_size.height())
        for w in [old_body, old_advanced, *old_full_boxes]:
            if w is not None:
                w.deleteLater()

        ms = adur(260, 140)
        if not anim_on() or ms <= 0 or not self.isVisible():
            self.setFixedSize(*self._final_size)
            self._keep_on_screen()
            self.update()
            return

        self.setFixedSize(max(self._final_size[0], old_size.width()),
                          max(self._final_size[1], old_size.height()))
        if self._overlay is None:
            self._overlay = _PanelZoomOverlay(self)
        self._overlay.setGeometry(self.rect())
        self._overlay.setup(old_pm, r0, new_pm, r1,
                            shadow_included=wide_capture)
        self._overlay.show()
        self._overlay.raise_()
        self._body.hide()
        for box in getattr(self, "_full_boxes", []):
            box.hide()
        if self.advanced_box is not None:
            self.advanced_box.hide()
        self.repaint()

        self._zoom_anim.setStartValue(0.0)
        self._zoom_anim.setEndValue(1.0)
        self._zoom_anim.setDuration(ms)
        self._zoom_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._zoom_anim.start()

    def request_language_rebuild(self):
        self._lang_timer.setInterval(0)
        self._lang_timer.start()

    def _prepare_language_fade(self, *_):
        if self._body is None:
            return
        if self._fade_anim.state() == Anim.Running:
            self._fade_abort = True
            self._fade_anim.stop()
            self._fade_abort = False
            if self._fade_overlay is not None:
                self._fade_overlay.hide()
            self._body.show()
            self._body.raise_()

        self._lang_old_pm = None
        self._lang_old_rect = QRectF()
        ms = adur(220, 120)
        if not anim_on() or ms <= 0 or not self.isVisible():
            return

        old_pm = self._body.grab()
        old_rect = self._body.geometry()
        self._lang_old_pm = old_pm
        self._lang_old_rect = QRectF(old_rect)
        if self._fade_overlay is None:
            self._fade_overlay = _PanelFadeOverlay(self)
        self._fade_overlay.setGeometry(self.rect())
        self._fade_overlay.setup(old_pm, old_rect, old_pm, old_rect)
        self._fade_overlay.show()
        self._fade_overlay.raise_()
        self.repaint()

    def _apply_language_texts(self):
        self._title_label.setText(tr("settings"))
        self._advanced_title_label.setText(tr("advanced"))
        self.search.setPlaceholderText(tr("search_settings"))
        for key, lab in self._labels.items():
            lab.setText(tr(key) if key != "FPS" else "FPS")
        for key, lab in self._section_labels:
            lab.set_title(tr(key))
        for key, lab in self._toggle_labels.items():
            lab.setText(tr(key))
        self.sg_auto_theme.set_options(auto_theme_options(),
                                       SETTINGS["auto_theme"])
        self.sg_bg_image_mode.set_options(
            background_image_mode_options(), SETTINGS["background_image_mode"])
        self.sg_weather_effect.set_options(
            weather_effect_options(), SETTINGS["weather_effect"])
        self.sg_source.set_options(source_options(), SETTINGS["source"])
        self.sg_panel_type.set_options(settings_panel_type_options(),
                                       SETTINGS["settings_panel_type"])
        if self.sg_panel_category is not None:
            self.sg_panel_category.set_options(
                panel_category_options(), self._panel_category)
        self.sg_startup_show.set_options(startup_show_options(),
                                         SETTINGS["startup_show"])
        self.sg_seek.set_options(seek_options(), SETTINGS["seek_style"])
        self.sg_progress_time.set_options(
            progress_time_options(), SETTINGS["progress_time_mode"])
        self.sg_thumb.set_options(seek_thumb_options(),
                                  SETTINGS["seek_thumb"])
        self.sg_card_preset.set_options(card_preset_options(),
                                        SETTINGS["card_preset"])
        self.sg_art_mode.set_options(art_mode_options(),
                                     SETTINGS["art_mode"])
        self.sg_cover_shape.set_options(cover_shape_options(),
                                        SETTINGS["cover_shape"])
        self.sg_ctl.set_options(align_options(), SETTINGS["controls_align"])
        self.sg_lang.set_options(LANGUAGES, SETTINGS["language"])
        self.kb_toggle.update()
        self.kb_play.update()
        self.kb_prev.update()
        self.kb_next.update()
        self.kb_vol_up.update()
        self.kb_vol_down.update()
        self.btn_reset._text = tr("reset_settings")
        self.btn_reset.update()
        if hasattr(self, "bg_image"):
            self.bg_image.refresh_language()
        if hasattr(self, "custom_image"):
            self.custom_image.refresh_language()
        for w in (getattr(self, "cp_font_color", None),
                  getattr(self, "cp_source_text_color", None),
                  getattr(self, "cp_number_color", None),
                  getattr(self, "cp_topbar_icon_color", None),
                  getattr(self, "cp_seek_fill_color", None),
                  getattr(self, "cp_seek_thumb_color", None),
                  getattr(self, "cp_seek_track_color", None)):
            if w is not None:
                w.update()
        self._update_advanced_button()
        self.sw_theme.update()
        self._apply_search(self.search.text())

    def rebuild_for_language(self):
        if self._body is None:
            self._build_body()
            return
        if self._fade_anim.state() == Anim.Running:
            self._fade_abort = True
            self._fade_anim.stop()
            self._fade_abort = False
        self._lang_old_pm = None
        self._lang_old_rect = QRectF()
        if self._fade_overlay is not None:
            self._fade_overlay.hide()
        self._apply_language_texts()
        lay = self._panel_layout(self._body)
        if lay is not None:
            lay.activate()
        self._body.show()
        self._body.raise_()
        if self.advanced_box is not None and self._advanced_open:
            self.advanced_box.show()
            self._on_advanced_anim(1.0)
        self._apply_body_geometry()
        self.update()
        self.repaint()

    def _on_language_fade(self, v):
        if self._fade_overlay is not None:
            self._fade_overlay.set_t(float(v))

    def _language_fade_done(self):
        if self._fade_abort:
            return
        self._lang_old_pm = None
        self._lang_old_rect = QRectF()
        if self._fade_overlay is not None:
            self._fade_overlay.hide()
        if self._body is not None:
            self._body.show()
            self._body.raise_()
        self.repaint()

    def _on_type_slide(self, v):
        if self._type_direct:
            t = max(0.0, min(1.0, float(v)))
            if self._type_from_size.isValid() and self._type_to_size.isValid():
                x = round(self._type_from_pos.x()
                          + (self._type_to_pos.x()
                             - self._type_from_pos.x()) * t)
                y = round(self._type_from_pos.y()
                          + (self._type_to_pos.y()
                             - self._type_from_pos.y()) * t)
                w = round(self._type_from_size.width()
                          + (self._type_to_size.width()
                             - self._type_from_size.width()) * t)
                h = round(self._type_from_size.height()
                          + (self._type_to_size.height()
                             - self._type_from_size.height()) * t)
                self.setFixedSize(max(1, w), max(1, h))
                self.move(x, y)
            if (self._body is not None and self._type_from_body.isValid()
                    and self._type_to_body.isValid()):
                r0 = self._type_from_body
                r1 = self._type_to_body
                bx = round(r0.x() + (r1.x() - r0.x()) * t)
                by = round(r0.y() + (r1.y() - r0.y()) * t)
                bw = round(r0.width() + (r1.width() - r0.width()) * t)
                bh = round(r0.height() + (r1.height() - r0.height()) * t)
                self._body.setGeometry(bx, by, max(1, bw), max(1, bh))
                self._set_panel_viewport(self._body, max(1, bw), max(1, bh),
                                         max(1, self._type_to_content_h))
                self._body.set_scroll_offset(0.0)
            self.update()
            return
        if self._type_overlay is not None:
            self._type_overlay.set_t(float(v))

    def _type_slide_done(self):
        if self._type_slide_abort:
            return
        if self._type_direct:
            if self._body is not None:
                self._body.show()
                self._body.raise_()
                if self._type_final_body.isValid():
                    if self._body.geometry() != self._type_final_body:
                        self._body.setGeometry(self._type_final_body)
                    self._set_panel_viewport(
                        self._body, self._type_final_body.width(),
                        self._type_final_body.height(),
                        max(1, self._type_to_content_h))
                    self._body.set_scroll_offset(0.0)
            if self._final_size:
                final_size = QSize(self._final_size[0], self._final_size[1])
                if self.size() != final_size:
                    self.setFixedSize(final_size)
                if self.pos() != self._type_to_pos:
                    self.move(self._type_to_pos)
            self._type_direct = False
            self.update()
            return
        if self._type_overlay is not None:
            self._type_overlay.hide()
        if self._body is not None:
            self._body.show()
            self._body.raise_()
        if SETTINGS.get("settings_panel_type") == "full":
            # 此刻 box 仍處於動畫期間的 hide() 狀態，lab.isVisible() 會因
            # 祖先隱藏一律回 False；改用 isVisibleTo(box) 只看 lab 自身（搜尋
            # 過濾）的可見性，否則會把所有子面板誤判成不可見而全部藏掉
            for key, box in self._full_box_sections.items():
                vis = any(lab.isVisibleTo(box)
                          for k, lab, _, _, _ in self._section_groups
                          if k == key)
                box.setVisible(vis)
                if vis:
                    box.raise_()
        if self.advanced_box is not None and self._advanced_open:
            self.advanced_box.show()
            self._on_advanced_anim(1.0)
        if self._final_size:
            self.setFixedSize(*self._final_size)
            self._keep_on_screen()
        self.repaint()

    def _on_zoom(self, v):
        if self._overlay is not None:
            self._overlay.set_t(float(v))

    def _zoom_done(self):
        if self._zoom_restart:
            return
        if self._overlay is not None:
            self._overlay.hide()
        if self._body is not None:
            self._body.show()
        if SETTINGS.get("settings_panel_type") == "full":
            # 同 _type_slide_done：box 仍 hidden，須用 isVisibleTo 判斷
            for key, box in self._full_box_sections.items():
                vis = any(lab.isVisibleTo(box)
                          for k, lab, _, _, _ in self._section_groups
                          if k == key)
                box.setVisible(vis)
                if vis:
                    box.raise_()
        if self.advanced_box is not None and self._advanced_open:
            self.advanced_box.show()
            self._on_advanced_anim(1.0)
        if self._final_size:
            self.setFixedSize(*self._final_size)
            self._keep_on_screen()
        self.repaint()

    def _controls(self):
        controls = (self.sl_opacity, self.sl_brightness,
                    self.sl_bg_image_brightness,
                    self.sl_bg_image_parallax_strength,
                    self.sl_bg_image_parallax_fps,
                    self.sl_weather_intensity,
                    self.sl_rain_length, self.sl_rain_thickness,
                    self.sl_rain_direction, self.sl_rain_fall_speed,
                    self.sl_snow_size, self.sl_snow_spin_speed,
                    self.sl_snow_fall_speed,
                    self.sl_custom_size, self.sl_custom_spin_speed,
                    self.sl_custom_fall_speed,
                    self.sl_lightning_size, self.sl_lightning_thickness,
                    self.sl_lightning_intensity,
                    self.sl_lightning_duration,
                    self.sl_scale,
                    self.sl_settings_scale, self.sl_radius, self.sl_fps,
                    self.sl_title_size, self.sl_artist_size,
                    self.sl_title_x, self.sl_title_y,
                    self.sl_artist_x, self.sl_artist_y,
                    self.sl_auto_strength, self.sl_cover_border_width,
                    self.sl_cover_border_opacity, self.sl_cover_blur,
                    self.sl_cover_radius_strength,
                    self.sl_seek_wave_amp, self.sl_seek_wave_speed,
                    self.sl_seek_glow_strength, self.sl_seek_length,
                    self.sl_seek_thumb_size,
                    self.sl_control_button_size,
                    self.sl_control_button_spacing,
                    self.sl_tonearm_speed, self.sl_vinyl_spin_speed,
                    self.sl_art_cover_size, self.sl_art_vinyl_size,
                    self.sl_audio_feedback_thickness,
                    self.sl_audio_feedback_sensitivity,
                    self.sl_vinyl_center_size,
                    self.kb_toggle, self.kb_play,
                    self.kb_prev, self.kb_next, self.kb_vol_up,
                    self.kb_vol_down, self.sg_auto_theme, self.sg_seek,
                    self.sg_progress_time, self.sg_thumb, self.sg_panel_type,
                    self.sg_panel_category, self.sg_bg_image_mode,
                    self.sg_weather_effect,
                    self.sg_source, self.sg_startup_show,
                    self.sg_ctl, self.sg_card_preset,
                    self.sg_art_mode, self.sg_cover_shape,
                    self.sg_lang, self.btn_advanced, self.btn_reset,
                    self.btn_advanced_close, self.fp_font,
                    self.bg_image, self.custom_image, self.cp_font_color,
                    self.cp_source_text_color, self.cp_number_color,
                    self.cp_topbar_icon_color, self.cp_seek_fill_color,
                    self.cp_seek_thumb_color, self.cp_seek_track_color,
                    self.tg_startup, self.tg_aa, self.tg_src,
                    self.tg_bg_image_parallax,
                    self.tg_weather_enabled, self.tg_lightning_enabled,
                    self.tg_lightning_duration_random,
                    self.tg_shadow, self.tg_gpu, self.tg_controls_hover,
                    self.tg_topbar_hover, self.tg_show_fps,
                    self.tg_anim_enabled, self.tg_show_cover,
                    self.tg_show_tonearm, self.tg_show_vinyl_center,
                    self.tg_cover_border, self.tg_marquee,
                    self.tg_btn_shuffle, self.tg_btn_prev, self.tg_btn_next,
                    self.tg_btn_repeat)
        return tuple(w for w in controls if w is not None)

    def sync_weather_controls(self, adjust: bool = True,
                              animate: bool = True):
        weather = SETTINGS.get("weather_effect", "rain")
        if weather not in ("rain", "snow", "custom"):
            weather = "rain"
        if hasattr(self, "sl_weather_intensity"):
            self.sl_weather_intensity.set_value(
                SETTINGS.get(f"{weather}_intensity", 0.55) * 100)
            self.sl_rain_length.set_value(
                SETTINGS.get("rain_length", 1.0) * 100)
            self.sl_rain_thickness.set_value(
                SETTINGS.get("rain_thickness", 1.0) * 100)
            self.sl_rain_direction.set_value(
                SETTINGS.get("rain_direction", 18.0))
            self.sl_rain_fall_speed.set_value(
                SETTINGS.get("rain_fall_speed", 1.0) * 100)
            self.sl_snow_size.set_value(
                SETTINGS.get("snow_size", 1.0) * 100)
            self.sl_snow_spin_speed.set_value(
                SETTINGS.get("snow_spin_speed", 1.0) * 100)
            self.sl_snow_fall_speed.set_value(
                SETTINGS.get("snow_fall_speed", 1.0) * 100)
            self.sl_custom_size.set_value(
                SETTINGS.get("custom_size", 1.0) * 100)
            self.sl_custom_spin_speed.set_value(
                SETTINGS.get("custom_spin_speed", 1.0) * 100)
            self.sl_custom_fall_speed.set_value(
                SETTINGS.get("custom_fall_speed", 1.0) * 100)
            if self.ed_custom_symbols.text() != SETTINGS.get(
                    "custom_symbols", "❄,❅,❆"):
                self.ed_custom_symbols.setText(
                    str(SETTINGS.get("custom_symbols", "❄,❅,❆")))
            self.custom_image.set_value(SETTINGS.get("custom_image", ""))
            rain = weather == "rain"
            snow = weather == "snow"
            custom = weather == "custom"
            for control in (self.sl_rain_length, self.sl_rain_thickness,
                            self.sl_rain_direction,
                            self.sl_rain_fall_speed):
                self._set_weather_row_visible(control, rain, adjust and animate)
            for control in (self.sl_snow_size, self.sl_snow_spin_speed,
                            self.sl_snow_fall_speed):
                self._set_weather_row_visible(control, snow,
                                              adjust and animate)
            for control in (self.sl_custom_size, self.sl_custom_spin_speed,
                            self.sl_custom_fall_speed,
                            self.ed_custom_symbols, self.custom_image):
                self._set_weather_row_visible(control, custom,
                                              adjust and animate)
            if adjust and self._body is not None:
                self._apply_body_geometry(animate=animate)

    def _set_weather_row_visible(self, control: QWidget, visible: bool,
                                 animate: bool):
        host = getattr(control, "_row_host", control.parentWidget())
        if host is None:
            return
        full_h = max(1, int(getattr(host, "_full_h",
                                    host.sizeHint().height() or host.height())))
        target_h = full_h if visible else 0
        was_visible = host.isVisible()
        eff = host.graphicsEffect()
        cur_opacity = eff.opacity() if isinstance(
            eff, QGraphicsOpacityEffect) else 1.0
        anim = getattr(host, "_weather_anim", None)
        if anim is not None:
            anim.stop()
        if not animate or not anim_on():
            host.setFixedHeight(target_h)
            host.setVisible(visible)
            if isinstance(eff, QGraphicsOpacityEffect):
                eff.setOpacity(1.0)
            return
        if was_visible == visible and cur_opacity >= 0.999:
            return
        if not isinstance(eff, QGraphicsOpacityEffect):
            eff = QGraphicsOpacityEffect(host)
            host.setGraphicsEffect(eff)
        if not visible:
            host.hide()
            eff.setOpacity(1.0)
            return
        host.setFixedHeight(full_h)
        host.show()
        eff.setOpacity(0.0 if not was_visible else cur_opacity)
        if anim is None:
            anim = Anim(host)
            host._weather_anim = anim
            anim.valueChanged.connect(
                lambda value, eff=eff:
                    eff.setOpacity(max(0.0, min(1.0, float(value)))))
        old_done = getattr(host, "_weather_done_cb", None)
        if old_done is not None:
            try:
                anim.finished.disconnect(old_done)
            except (TypeError, RuntimeError):
                pass

        def on_done(host=host, full_h=full_h, eff=eff):
            host.setFixedHeight(full_h)
            host.show()
            eff.setOpacity(1.0)

        anim.finished.connect(on_done)
        host._weather_done_cb = on_done
        anim.setStartValue(float(eff.opacity()))
        anim.setEndValue(1.0)
        anim.setDuration(adur(160, 90))
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.start()

    def _repaint_controls(self):
        for w in self._controls():
            w.update()

    def _pair_key(self, pair: tuple[QColor, QColor]) -> tuple[str, str]:
        return pair[0].name(QColor.HexArgb), pair[1].name(QColor.HexArgb)

    def _on_theme_gradient(self, v):
        t = float(v)
        pair = (blend(self._grad_from[0], self._grad_to[0], t),
                blend(self._grad_from[1], self._grad_to[1], t))
        _set_panel_gradient(pair)
        self._grad_pair = pair
        self._repaint_controls()

    def _on_shadow_op(self, value):
        self._shadow_op = max(0.0, min(1.0, float(value)))
        self.update()

    def set_shadow_visible(self, visible: bool, animate: bool = True):
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
        p = QPainter(self)
        p.setCompositionMode(QPainter.CompositionMode_Source)
        p.fillRect(self.rect(), Qt.transparent)
        p.setCompositionMode(QPainter.CompositionMode_SourceOver)
        p.end()
        # 陰影用預先模糊好的貼圖（QGraphicsDropShadowEffect 會讓滑桿/
        # 開關每幀動畫都重新模糊整個面板，非常卡）
        if self._body is None or self._shadow_op <= 0.001:
            return
        p = QPainter(self)
        blur = panel_px(15)

        def draw_rect_shadow(r: QRectF, alpha_factor: float = 1.0):
            op = self._shadow_op * max(0.0, min(1.0, float(alpha_factor)))
            if op <= 0.001 or r.width() <= 1 or r.height() <= 1:
                return
            sh = soft_shadow(round(r.width()), round(r.height()),
                             panel_f(16), blur=blur, alpha=160,
                             dpr=self.devicePixelRatioF())
            p.save()
            p.setOpacity(op)
            p.setRenderHint(QPainter.SmoothPixmapTransform, True)
            p.drawPixmap(QRectF(r.x() - blur, r.y() - blur + panel_f(5),
                                r.width() + blur * 2,
                                r.height() + blur * 2),
                         sh, QRectF(sh.rect()))
            p.restore()

        def draw_panel_shadow(w: QWidget, alpha_factor: float = 1.0):
            op = self._shadow_op * max(0.0, min(1.0, float(alpha_factor)))
            if op <= 0.001:
                return
            g = w.geometry()
            shadow_h = g.height()
            sh = soft_shadow(g.width(), shadow_h, panel_f(16),
                             blur=blur, alpha=160,
                             dpr=self.devicePixelRatioF())
            p.save()
            p.setOpacity(op)
            p.drawPixmap(g.x() - blur, g.y() - blur + panel_px(5), sh)
            p.restore()

        # 縮放過渡進行中（scale 或面板類型切換）：陰影跟著內插矩形畫；
        # 截圖已含陰影者（wide_capture）不重畫。body/box 此時都 hidden
        for ov in (self._overlay, self._type_overlay):
            if ov is not None and ov.isVisible():
                if not ov.shadow_included():
                    draw_rect_shadow(ov.cur_rect())
                return
        draw_panel_shadow(self._body)
        for box in getattr(self, "_full_boxes", []):
            if box.isVisible():
                draw_panel_shadow(box)
        if (self.advanced_box is not None
                and (self.advanced_box.isVisible()
                     or self._advanced_hiding)):
            draw_panel_shadow(self.advanced_box, self._advanced_t)

    def set_accent(self, c: QColor, force: bool = False):
        self._accent = QColor(c)
        target_pair = _panel_target_pair(self._accent)
        explicit = theme_gradient() is not None
        mode = _panel_pair_mode()
        leaving_explicit = self._grad_explicit and not explicit
        mode_changed = mode != self._grad_mode
        should_animate = force or explicit or leaving_explicit or mode_changed
        if (should_animate
                and self._pair_key(target_pair) != self._pair_key(self._grad_to)):
            self._grad_from = (QColor(self._grad_pair[0]),
                               QColor(self._grad_pair[1]))
            self._grad_to = (QColor(target_pair[0]), QColor(target_pair[1]))
            ms = adur(420, 220)
            self._grad_anim.stop()
            if not anim_on() or ms <= 0:
                _set_panel_gradient(self._grad_to)
                self._grad_pair = self._grad_to
            else:
                self._grad_anim.setStartValue(0.0)
                self._grad_anim.setEndValue(1.0)
                self._grad_anim.setDuration(ms)
                self._grad_anim.setEasingCurve(QEasingCurve.OutCubic)
                self._grad_anim.start()
        elif not should_animate and self._grad_anim.state() != Anim.Running:
            _set_panel_gradient(target_pair)
            self._grad_pair = target_pair
            self._grad_to = (QColor(target_pair[0]), QColor(target_pair[1]))
        self._grad_explicit = explicit
        self._grad_mode = mode
        for w in self._controls():
            w.set_accent(c)

    def open_at(self, pos: QPoint):
        self._set_window_geometry(pos, self.size(), animate=False)
        fade_in(self)

    def animated_close(self):
        fade_out(self, self.hide)

    def hideEvent(self, e):
        super().hideEvent(e)
        self.closed.emit()

    # 拖曳面板
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._stop_window_geometry_at_current()
            self._drag_off = (e.globalPosition().toPoint()
                              - self.frameGeometry().topLeft())

    def mouseMoveEvent(self, e):
        if self._drag_off is not None and e.buttons() & Qt.LeftButton:
            self.move(e.globalPosition().toPoint() - self._drag_off)

    def mouseReleaseEvent(self, e):
        self._drag_off = None
        self._keep_on_screen()
        self.position_committed.emit(QPoint(self.pos()))


# ------------------------------------------------------------ 音量彈窗 ----

class VolumePopup(QWidget):
    """點音量鈕彈出的直向滑桿，支援拖曳、滾輪、靜音。"""

    vol_changed = Signal(float)
    mute_toggled = Signal(bool)

    BW, BH = 46, 178       # 本體大小
    M = 14                 # 陰影留邊

    def __init__(self, accent: QColor, value, muted=False, parent=None):
        ensure_safe_app_font()
        super().__init__(parent)
        self.setFont(panel_font(12))
        self.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint
                            | Qt.NoDropShadowWindowHint
                            | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self._accent = QColor(accent)
        self._enabled = value is not None
        self._val = float(value) if value is not None else 0.0
        self._muted = muted
        self._drag = False
        self._closing = False       # 淡出關閉進行中（防重入）
        self._filter_installed = False
        self._auto_dismiss = False
        self._leave_timer = QTimer(self)
        self._leave_timer.setSingleShot(True)
        self._leave_timer.setInterval(420)
        self._leave_timer.timeout.connect(self._dismiss)

        self._disp = self._val      # 顯示值（點擊/滾輪滑移動畫）
        self._va = Anim(self)
        self._va.valueChanged.connect(self._on_disp)
        self._hover = 0.0           # 圓鈕 hover 放大進度
        self._ha = Anim(self)
        self._ha.valueChanged.connect(self._on_hover)
        self._mt = 1.0 if muted else 0.0   # 靜音過渡（填滿淡出/圖示變色）
        self._ma = Anim(self)
        self._ma.valueChanged.connect(self._on_mt)
        self.setFixedSize(self.BW + self.M * 2, self.BH + self.M * 2)

    def set_accent(self, c: QColor):
        """跟著卡片主題色變化（accent_changed 漸變逐幀進來）。"""
        self._accent = QColor(c)
        self.update()

    # ---- 動畫 ----

    def _on_disp(self, v):
        self._disp = float(v)
        self.update()

    def _on_hover(self, v):
        self._hover = float(v)
        self.update()

    def _on_mt(self, v):
        self._mt = float(v)
        self.update()

    def _anim_to(self, anim: Anim, cur: float, to: float, ms: int):
        anim.stop()
        if not anim_on() or ms <= 0:
            anim.valueChanged.emit(to)
            return
        anim.setStartValue(cur)
        anim.setEndValue(to)
        anim.setDuration(ms)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.start()

    def enterEvent(self, e):
        self._leave_timer.stop()
        if self._enabled:
            self._anim_to(self._ha, self._hover, 1.0, adur(150, 90))

    def leaveEvent(self, e):
        self._anim_to(self._ha, self._hover, 0.0, adur(190, 110))
        if not self._drag:
            self._leave_timer.start()

    def _set_muted(self, muted: bool):
        self._muted = muted
        self.mute_toggled.emit(muted)
        self._anim_to(self._ma, self._mt, 1.0 if muted else 0.0,
                      adur(220, 120))

    # 軌道範圍（本體座標）
    def _track(self):
        x = self.M + self.BW / 2
        top = self.M + 34
        bottom = self.M + self.BH - 40
        return x, top, bottom

    def _val_from_y(self, y: float) -> float:
        _, top, bottom = self._track()
        return min(1.0, max(0.0, (bottom - y) / max(1.0, bottom - top)))

    def _set_val(self, v: float, ms: int = 0):
        self._val = min(1.0, max(0.0, v))
        if self._muted and self._val > 0:
            self._set_muted(False)
        self.vol_changed.emit(self._val)
        self._anim_to(self._va, self._disp, self._val, ms)

    def _dismiss(self):
        """點擊彈窗外側：淡出後才真正關閉（與開啟的淡入對稱）。"""
        if self._closing or not self.isVisible():
            return
        self._closing = True
        self._leave_timer.stop()
        self._remove_filter()
        fade_out(self, self.close, slide=8)

    def dismiss(self):
        self._dismiss()

    def _install_filter(self):
        app = QApplication.instance()
        if app is not None and not self._filter_installed:
            app.installEventFilter(self)
            self._filter_installed = True

    def _remove_filter(self):
        app = QApplication.instance()
        if app is not None and self._filter_installed:
            app.removeEventFilter(self)
        self._filter_installed = False

    def _enable_auto_dismiss(self):
        if not self._closing:
            self._auto_dismiss = True

    def _can_auto_dismiss(self) -> bool:
        return self._auto_dismiss and not self._closing and self.isVisible()

    def eventFilter(self, obj, event):
        if event.type() == QEvent.MouseButtonPress and self._can_auto_dismiss():
            if hasattr(event, "globalPosition"):
                gp = event.globalPosition().toPoint()
            else:
                gp = event.globalPos()
            if not self.geometry().contains(gp):
                self._dismiss()
        return super().eventFilter(obj, event)

    def changeEvent(self, e):
        super().changeEvent(e)
        if (e.type() == QEvent.ActivationChange and self._can_auto_dismiss()
                and not self.isActiveWindow()):
            QTimer.singleShot(0, self._dismiss)

    def closeEvent(self, e):
        self._leave_timer.stop()
        self._remove_filter()
        super().closeEvent(e)

    def hideEvent(self, e):
        self._leave_timer.stop()
        self._remove_filter()
        super().hideEvent(e)

    def mousePressEvent(self, e):
        if not self.rect().contains(e.position().toPoint()):
            self._dismiss()     # Popup 外點擊
            return
        if not self._enabled or self._closing:
            return
        y = e.position().y()
        if y > self.M + self.BH - 36:          # 底部靜音區
            self._set_muted(not self._muted)
        else:
            self._drag = True
            self._set_val(self._val_from_y(y), adur(180, 100))

    def mouseMoveEvent(self, e):
        if self._drag:
            self._set_val(self._val_from_y(e.position().y()))   # 直接跟手

    def mouseReleaseEvent(self, e):
        self._drag = False

    def wheelEvent(self, e):
        if self._enabled:
            d = 0.04 if e.angleDelta().y() > 0 else -0.04
            self._set_val(self._val + d, adur(150, 90))

    def paintEvent(self, _):
        p = QPainter(self)
        aa(p)
        body = QRectF(self.M, self.M, self.BW, self.BH)
        path = QPainterPath()
        path.addRoundedRect(body, 13, 13)
        p.fillPath(path, QColor(21, 21, 27, 250))
        p.setPen(QPen(QColor(255, 255, 255, 26), 1))
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)

        x, top, bottom = self._track()
        disp = min(1.0, max(0.0, self._disp))
        # 百分比
        p.setFont(ui_font(10, QFont.DemiBold))
        muted_red = QColor(235, 82, 92)
        p.setPen(muted_red if self._muted and self._enabled
                 else QColor(255, 255, 255, 200 if self._enabled else 80))
        pct = f"{round(self._val * 100)}" if self._enabled else "--"
        p.drawText(QRectF(self.M, self.M + 8, self.BW, 16),
                   Qt.AlignCenter, pct)
        # 軌道
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 34))
        p.drawRoundedRect(QRectF(x - 2.5, top, 5, bottom - top), 2.5, 2.5)
        fill_a = 1.0 - self._mt            # 靜音時填滿淡出
        if self._enabled and disp > 0 and fill_a > 0.01:
            c0 = QColor(self._accent)
            c0.setAlpha(round(255 * fill_a))
            c1 = self._accent.lighter(125)
            c1.setAlpha(round(255 * fill_a))
            g = QLinearGradient(0, bottom, 0, top)
            g.setColorAt(0.0, c0)
            g.setColorAt(1.0, c1)
            fy = bottom - (bottom - top) * disp
            p.setBrush(g)
            p.drawRoundedRect(QRectF(x - 2.5, fy, 5, bottom - fy), 2.5, 2.5)
        if self._enabled:
            fy = bottom - (bottom - top) * disp
            r = 6.0 + 1.0 * self._hover + (0.6 if self._drag else 0.0)
            p.setBrush(QColor(0, 0, 0, 70))
            p.drawEllipse(QPointF(x, fy + 0.8), r, r)
            p.setBrush(QColor(255, 255, 255))
            p.drawEllipse(QPointF(x, fy), r, r)
        # 靜音鈕
        p.setFont(icon_font(13))
        if not self._enabled:
            p.setPen(QColor(255, 255, 255, 70))
        elif self._muted:
            p.setPen(muted_red)
        else:
            p.setPen(blend(QColor(255, 255, 255, 150),
                           self._accent.lighter(120), self._mt))
        glyph = GLYPH_MUTE if (self._muted or not self._enabled) else GLYPH_VOLUME
        p.drawText(QRectF(self.M, self.M + self.BH - 34, self.BW, 26),
                   Qt.AlignCenter, glyph)

    def popup_at(self, global_center_x: int, global_top_y: int):
        """以底部中心對齊指定點上方彈出。"""
        x = global_center_x - self.width() // 2
        y = global_top_y - self.height() + self.M - 2
        self.move(x, y)
        self._auto_dismiss = False
        self._install_filter()
        fade_in(self, slide=8)
        self.raise_()
        self.activateWindow()
        self.setFocus(Qt.PopupFocusReason)
        QTimer.singleShot(120, self._enable_auto_dismiss)
