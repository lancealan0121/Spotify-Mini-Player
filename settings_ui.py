"""自訂設定面板與音量彈窗：全部自繪控制項，不用內建外觀。"""
import time

from PySide6.QtCore import (QEvent, QEasingCurve, QPoint, QPointF, QRectF, Qt,
                            QTimer,
                            QVariantAnimation, Signal)
from PySide6.QtGui import (QColor, QConicalGradient, QFont, QFontMetricsF,
                           QLinearGradient, QPainter, QPainterPath, QPen,
                           QPixmap)
from PySide6.QtWidgets import (QApplication, QComboBox, QDialog,
                               QGraphicsOpacityEffect, QHBoxLayout, QLabel,
                               QLineEdit, QVBoxLayout, QWidget)

from style import (AUTO_THEME_MODES, CARD_PRESETS, CONTROLS_ALIGN,
                   GLYPH_CHECK, GLYPH_CHEVRON_DOWN, GLYPH_CHEVRON_UP,
                   GLYPH_CLOSE, GLYPH_MUTE, GLYPH_SETTINGS, GLYPH_VOLUME,
                   LANGUAGES, SEEK_STYLES, SETTINGS, SEEK_THUMBS,
                   SOURCE_MODES, Anim, aa, adur, all_themes, anim_on, blend,
                   icon_font, soft_shadow, theme_color, theme_gradient,
                   theme_label, tr, ui_font)
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
    return ui_font(panel_px(px), weight)


def panel_icon_font(px: int) -> QFont:
    return icon_font(panel_px(px))


def panel_w() -> int:
    return panel_px(PANEL_W_BASE)


def panel_margin() -> int:
    return panel_px(PM_BASE)


def source_options():
    return [(k, tr(f"source_{k}")) for k, _ in SOURCE_MODES]


def seek_options():
    return [(k, tr(f"seek_{k}")) for k, _ in SEEK_STYLES]


def seek_thumb_options():
    return [(k, tr(f"seek_thumb_{k}")) for k, _ in SEEK_THUMBS]


def auto_theme_options():
    return [(k, tr(f"auto_theme_{k}")) for k, _ in AUTO_THEME_MODES]


def art_mode_options():
    return [("cover", tr("art_cover")), ("vinyl", tr("art_vinyl"))]


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
                 live=True, accent=None, parent=None):
        super().__init__(parent)
        self._mn, self._mx = mn, mx
        self._val = min(mx, max(mn, val))
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

    def _track_w(self) -> float:
        return self.width() - panel_f(52.0) - panel_f(self.PAD)  # 右側留給數值

    def _val_from_x(self, x: float) -> float:
        pad = panel_f(self.PAD)
        r = min(1.0, max(0.0, (x - pad) / max(1.0, self._track_w())))
        return self._mn + (self._mx - self._mn) * r

    # ---- 顯示值動畫 ----

    def _on_disp(self, v):
        self._disp = float(v)
        if self._live:
            self.changed.emit(self._disp)
        self.update()

    def _slide_to(self, v: float, ms: int):
        v = min(self._mx, max(self._mn, v))
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
        step = (self._mx - self._mn) / 40.0
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
        self._ha = Anim(self)
        self._ha.valueChanged.connect(self._on_hover)
        self._pa = Anim(self)
        self._pa.valueChanged.connect(self._on_press)
        self.setFixedHeight(panel_px(30))
        self.setMinimumWidth(panel_px(86))
        self.setCursor(Qt.PointingHandCursor)

    def set_accent(self, c: QColor):
        self._accent = QColor(c)
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
        p.drawText(r, Qt.AlignCenter, self._text)


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
        super().__init__(parent)
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
            self.move(base)
            self.setWindowOpacity(end)
            if done:
                done()

        anim.valueChanged.connect(step)
        anim.finished.connect(finish)
        anim.start(QVariantAnimation.DeleteWhenStopped)

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
        self.setFixedHeight(round(float(v)))
        self.size_changed.emit()   # 面板每幀跟著伸縮

    def _expand_done(self):
        self._show_all = self._expanded
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
        self._expanded = not self._expanded
        target = self.row_h() * self._rows()
        ms = adur(280, 150)
        if not anim_on() or ms <= 0:
            self._show_all = self._expanded
            self.setFixedHeight(target)
            self.size_changed.emit()
            self.update()
            return
        self._show_all = True      # 往下展開/往上收合過程都看得到全部列
        self._ea.setStartValue(float(self.height()))
        self._ea.setEndValue(float(target))
        self._ea.setDuration(ms)
        self._ea.setEasingCurve(QEasingCurve.OutCubic)
        self._ea.start()

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
        p.drawText(tr, Qt.AlignCenter,
                   GLYPH_CHEVRON_UP if self._expanded else GLYPH_CHEVRON_DOWN)

    def sizeHint(self):
        from PySide6.QtCore import QSize
        w = (panel_f(self.PAD) * 2
             + self.COLS * (panel_f(self.D) + panel_f(self.GAP))
             - panel_f(self.GAP) + panel_f(27))
        return QSize(round(w), self.minimumHeight())   # 伸縮動畫中高度逐幀變


class FontPicker(QComboBox):
    """深色樣式字體下拉選單。"""

    def __init__(self, current: str, parent=None):
        super().__init__(parent)
        from PySide6.QtGui import QFontDatabase
        fams = [f for f in QFontDatabase.families() if not f.startswith("@")]
        self.addItems(fams)
        if current in fams:
            self.setCurrentText(current)
        self.setFixedHeight(panel_px(30))
        self.setMaxVisibleItems(14)
        self.setStyleSheet(
            'QComboBox { background: rgba(255,255,255,16); color: #e8e8ee;'
            f' border: 1px solid rgba(255,255,255,32); border-radius: {panel_px(9)}px;'
            f' padding: {panel_px(3)}px {panel_px(12)}px;'
            f' font: {panel_px(12)}px "Segoe UI"; }}'
            'QComboBox:hover { background: rgba(255,255,255,26); }'
            f'QComboBox::drop-down {{ border: none; width: {panel_px(20)}px; }}'
            'QComboBox::down-arrow { image: none; }'
            'QComboBox QAbstractItemView { background: #1d1d24;'
            ' color: #e8e8ee; border: 1px solid rgba(255,255,255,32);'
            f' border-radius: {panel_px(9)}px; selection-background-color:'
            f' rgba(255,255,255,34); outline: none; padding: {panel_px(4)}px; }}')


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


class _PanelZoomOverlay(QWidget):
    """設定面板縮放過渡：沿用主視窗的截圖矩形內插效果。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._old: QPixmap | None = None
        self._new: QPixmap | None = None
        self._r0 = QRectF()
        self._r1 = QRectF()
        self._t = 0.0
        self._buf: QPixmap | None = None
        self._buf2: QPixmap | None = None
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
        target = QRectF(0, 0, bw, bh)
        self._buf.fill(Qt.transparent)
        p = QPainter(self._buf)
        aa(p)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        if self._new is not None:
            p.drawPixmap(target, self._new, QRectF(self._new.rect()))
        p.end()
        return self._buf, bw, bh

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


class SettingsPanel(QWidget):
    """獨立的無邊框設定視窗；所有變更即時套用。"""

    setting_changed = Signal(str, object)
    closed = Signal()

    def __init__(self, accent: QColor, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint
                            | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
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
        self._lang_timer = QTimer(self)
        self._lang_timer.setSingleShot(True)
        self._lang_timer.timeout.connect(self.rebuild_for_language)
        self._body: _PanelBody | None = None
        self.advanced_box: _PanelBody | None = None
        self._advanced_eff: QGraphicsOpacityEffect | None = None
        self._advanced_open = False
        self._advanced_hiding = False
        self._advanced_side = "right"
        self._advanced_geo = QRectF()
        self._advanced_t = 0.0
        self._advanced_anim = Anim(self)
        self._advanced_anim.valueChanged.connect(self._on_advanced_anim)
        self._advanced_anim.finished.connect(self._advanced_anim_done)
        self._build_body()

    def _build_body(self, expanded: bool | None = None,
                    resize_window: bool = True):
        body = _PanelBody(self)
        self._labels = {}
        self._toggle_labels = {}
        lay = QVBoxLayout(body)
        lay.setContentsMargins(panel_px(20), panel_px(14),
                               panel_px(20), panel_px(18))
        lay.setSpacing(panel_px(10))

        # 標題列
        head = QHBoxLayout()
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
        lay.addLayout(head)

        def row(label_key, control, stretch=True, top=False):
            h = QHBoxLayout()
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
            lay.addLayout(h)
            return control

        self.sw_theme = row("theme", SwatchRow(SETTINGS["theme"],
                                               expanded=expanded),
                            stretch=False, top=True)
        self.sg_auto_theme = row("auto_theme", Segmented(
            auto_theme_options(), SETTINGS["auto_theme"],
            accent=self._accent))
        self.sg_art_mode = row("art_mode", Segmented(
            art_mode_options(), SETTINGS["art_mode"], accent=self._accent))
        self.sg_source = row("source", Segmented(
            source_options(), SETTINGS["source"], accent=self._accent))
        self.sl_opacity = row("opacity", PanelSlider(
            35, 100, SETTINGS["bg_opacity"] * 100,
            fmt=lambda v: f"{v:.0f}%", accent=self._accent))
        self.sl_brightness = row("brightness", PanelSlider(
            55, 145, SETTINGS["brightness"] * 100,
            fmt=lambda v: f"{v:.0f}%", accent=self._accent))
        self.sl_scale = row("player_size", PanelSlider(
            80, 200, SETTINGS["scale"] * 100,
            fmt=lambda v: f"{v:.0f}%", accent=self._accent))
        self.sl_settings_scale = row("settings_size", PanelSlider(
            80, 200, SETTINGS["settings_scale"] * 100,
            fmt=lambda v: f"{v:.0f}%", live=False, accent=self._accent))
        self.sl_radius = row("radius", PanelSlider(
            6, 28, SETTINGS["radius"],
            fmt=lambda v: f"{v:.0f}px", accent=self._accent))
        self.sg_seek = row("seek_bar", Segmented(
            seek_options(), SETTINGS["seek_style"], accent=self._accent))
        self.sg_ctl = row("button_pos", Segmented(
            align_options(), SETTINGS["controls_align"], accent=self._accent))
        self.sg_lang = row("language", Segmented(
            LANGUAGES, SETTINGS["language"], accent=self._accent))
        self.fp_font = row("font", FontPicker(SETTINGS["font"]))

        self.btn_advanced = PanelButton("", accent=self._accent)
        self.advanced_box = _PanelBody(self)
        self.advanced_box.hide()
        self._advanced_eff = QGraphicsOpacityEffect(self.advanced_box)
        self._advanced_eff.setOpacity(0.0)
        self.advanced_box.setGraphicsEffect(self._advanced_eff)
        adv = QVBoxLayout(self.advanced_box)
        adv.setContentsMargins(panel_px(20), panel_px(14),
                               panel_px(20), panel_px(18))
        adv.setSpacing(panel_px(8))

        def update_advanced_button():
            icon = GLYPH_CHEVRON_UP if self._advanced_open else GLYPH_CHEVRON_DOWN
            self.btn_advanced._text = f"{tr('advanced')}  {icon}"
            self.btn_advanced.update()

        def toggle_advanced():
            self._advanced_open = not self._advanced_open
            update_advanced_button()
            self._toggle_advanced_panel(self._advanced_open)

        self.btn_advanced.clicked.connect(toggle_advanced)

        def adv_row(label_key, control, stretch=True):
            h = QHBoxLayout()
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
            adv.addLayout(h)
            return control

        def adv_toggle(label_key, setting_key):
            t = Toggle(bool(SETTINGS[setting_key]), accent=self._accent)
            adv_row(label_key, t, stretch=False)
            t.changed.connect(
                lambda v, k=setting_key: self.setting_changed.emit(k, v))
            return t

        self.sl_auto_strength = adv_row("auto_color_strength", PanelSlider(
            0, 100, SETTINGS["auto_color_strength"] * 100,
            fmt=lambda v: f"{v:.0f}%", accent=self._accent))
        self.sg_card_preset = adv_row("card_preset", Segmented(
            card_preset_options(), SETTINGS["card_preset"], accent=self._accent))
        self.sl_tonearm_speed = adv_row("tonearm_speed", PanelSlider(
            40, 250, SETTINGS["tonearm_speed"] * 100,
            fmt=lambda v: f"{v / 100.0:.1f}x", accent=self._accent))
        self.sl_vinyl_spin_speed = adv_row("vinyl_spin_speed", PanelSlider(
            40, 250, SETTINGS["vinyl_spin_speed"] * 100,
            fmt=lambda v: f"{v / 100.0:.1f}x", accent=self._accent))
        self.tg_show_cover = adv_toggle("show_cover", "show_cover")
        self.sg_cover_shape = adv_row("cover_shape", Segmented(
            cover_shape_options(), SETTINGS["cover_shape"], accent=self._accent))
        self.tg_cover_border = adv_toggle("cover_border", "cover_border")
        self.sl_cover_border_width = adv_row("cover_border_width", PanelSlider(
            1, 8, SETTINGS["cover_border_width"],
            fmt=lambda v: f"{v:.1f}px", accent=self._accent))
        self.sl_cover_border_opacity = adv_row("cover_border_opacity", PanelSlider(
            0, 100, SETTINGS["cover_border_opacity"] * 100,
            fmt=lambda v: f"{v:.0f}%", accent=self._accent))
        self.sg_thumb = adv_row("seek_thumb", Segmented(
            seek_thumb_options(), SETTINGS["seek_thumb"], accent=self._accent))
        self.sl_fps = adv_row("FPS", PanelSlider(
            24, 240, SETTINGS["fps"],
            fmt=lambda v: f"{v:.0f}", accent=self._accent))
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

        self.tg_controls_hover = adv_toggle("controls_hover",
                                            "controls_hover")
        self.tg_topbar_hover = adv_toggle("topbar_hover", "topbar_hover")
        self.tg_show_fps = adv_toggle("show_fps", "show_fps")
        self.tg_anim_enabled = adv_toggle("anim_enabled", "anim_enabled")
        self.tg_btn_shuffle = adv_toggle("show_btn_shuffle",
                                         "show_btn_shuffle")
        self.tg_btn_prev = adv_toggle("show_btn_prev", "show_btn_prev")
        self.tg_btn_next = adv_toggle("show_btn_next", "show_btn_next")
        self.tg_btn_repeat = adv_toggle("show_btn_repeat", "show_btn_repeat")

        update_advanced_button()
        self.advanced_box.setVisible(self._advanced_open)
        if self._advanced_eff is not None:
            self._advanced_eff.setOpacity(1.0 if self._advanced_open else 0.0)

        def toggle_row():
            h = QHBoxLayout()
            h.setSpacing(panel_px(8))
            lay.addLayout(h)
            return h

        toggles1 = toggle_row()
        toggles2 = toggle_row()

        def tog(layout, label_text, key, tip=""):
            cell = QWidget()
            cell.setFixedWidth(panel_px(160))
            h = QHBoxLayout(cell)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(panel_px(8))
            lab = QLabel(label_text)
            lab.setFont(panel_font(12))
            lab.setStyleSheet("color: rgba(255,255,255,185);")
            lab.setFixedWidth(panel_px(104))
            lab.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
            self._toggle_labels[key] = lab
            t = Toggle(bool(SETTINGS[key]), accent=self._accent)
            t.changed.connect(lambda v, k=key: self.setting_changed.emit(k, v))
            h.addWidget(lab)
            h.addWidget(t)
            layout.addWidget(cell)
            return t

        self.tg_aa = tog(toggles1, tr("antialias"), "antialias")
        self.tg_src = tog(toggles1, tr("show_source"), "show_source")
        toggles1.addStretch(1)
        self.tg_shadow = tog(toggles2, tr("shadow"), "shadow")
        self.tg_gpu = tog(toggles2, tr("gpu"), "gpu", tip=tr("gpu_tip"))
        toggles2.addStretch(1)
        lay.addWidget(self.btn_advanced)

        self.sw_theme.changed.connect(
            lambda v: self.setting_changed.emit("theme", v))
        self.sw_theme.custom_added.connect(
            lambda v: self.setting_changed.emit("custom_theme_add", v))
        self.sw_theme.custom_deleted.connect(
            lambda v: self.setting_changed.emit("custom_theme_delete", v))
        self.sg_auto_theme.changed.connect(
            lambda v: self.setting_changed.emit("auto_theme", v))
        self.sg_art_mode.changed.connect(
            lambda v: self.setting_changed.emit("art_mode", v))
        self.sg_source.changed.connect(
            lambda v: self.setting_changed.emit("source", v))
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
        self.sg_cover_shape.changed.connect(
            lambda v: self.setting_changed.emit("cover_shape", v))
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
        self.sg_thumb.changed.connect(
            lambda v: self.setting_changed.emit("seek_thumb", v))
        self.sg_ctl.changed.connect(
            lambda v: self.setting_changed.emit("controls_align", v))
        self.sg_lang.changing.connect(self._prepare_language_fade)
        self.sg_lang.changed.connect(
            lambda v: self.setting_changed.emit("language", v))
        self.fp_font.currentTextChanged.connect(
            lambda v: self.setting_changed.emit("font", v))

        self._body = body
        # 色票列展開/收合 → 面板高度跟著伸縮
        self.sw_theme.size_changed.connect(self._relayout)
        return self._apply_body_geometry(resize_window=resize_window)

    def _apply_body_geometry(self, resize_window: bool = True):
        if self._body is None:
            return self.size()
        old_main_global = None
        if self.isVisible() and self._body.isVisible():
            old_main_global = self.mapToGlobal(self._body.geometry().topLeft())
        lay = self._body.layout()
        if lay is not None:
            lay.activate()
        self._body.adjustSize()
        pm = panel_margin()
        w = panel_w()
        h = self._body.sizeHint().height()
        gap = panel_px(10)
        adv_visible = (self.advanced_box is not None
                       and (self._advanced_open or self._advanced_hiding))
        adv_w = w
        adv_h = 0
        if self.advanced_box is not None:
            adv_lay = self.advanced_box.layout()
            if adv_lay is not None:
                adv_lay.activate()
            self.advanced_box.adjustSize()
            adv_h = self.advanced_box.sizeHint().height()
        if adv_visible:
            self._advanced_side = self._choose_advanced_side(adv_w, gap)
        main_x = pm
        adv_x = pm + w + gap
        if adv_visible and self._advanced_side == "left":
            adv_x = pm
            main_x = pm + adv_w + gap
        self._body.setGeometry(main_x, pm, w, h)
        if self.advanced_box is not None:
            self._advanced_geo = QRectF(adv_x, pm, adv_w, adv_h)
            self.advanced_box.setGeometry(adv_x, pm, adv_w, adv_h)
        final = self.size().expandedTo(self.minimumSizeHint())
        final.setWidth(w + pm * 2 + (adv_w + gap if adv_visible else 0))
        final.setHeight(max(h, adv_h if adv_visible else 0) + pm * 2)
        if resize_window:
            self.setFixedSize(final)
            if old_main_global is not None:
                self.move(old_main_global - QPoint(main_x, pm))
                self._keep_on_screen()
        return final

    def _relayout(self):
        self._apply_body_geometry()
        self.update()

    def _choose_advanced_side(self, adv_w: int, gap: int) -> str:
        if self._body is None:
            return "right"
        scr = QApplication.screenAt(self.frameGeometry().center())
        geo = (scr or QApplication.primaryScreen()).availableGeometry()
        main_geo = self._body.geometry()
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
        scr = QApplication.screenAt(self.frameGeometry().center())
        geo = (scr or QApplication.primaryScreen()).availableGeometry()
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
        self.move(x, y)

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
        dx = -slide if self._advanced_side == "right" else slide
        self.advanced_box.setGeometry(round(g.x() + dx), round(g.y()),
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

    def rebuild_for_scale(self):
        if self._body is None:
            self._build_body()
            return
        expanded = self.sw_theme.is_expanded()
        wide_capture = self._advanced_open or self._advanced_hiding
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
        old_body.hide()
        if old_advanced is not None:
            old_advanced.hide()
        final_size = self._build_body(expanded=expanded, resize_window=False)
        if self._body is None:
            return
        if wide_capture:
            self.setFixedSize(final_size)
        self._body.show()
        if self.advanced_box is not None and self._advanced_open:
            self.advanced_box.show()
            self._on_advanced_anim(1.0)
        new_pm = self.grab() if wide_capture else self._body.grab()
        r1 = self.rect() if wide_capture else self._body.geometry()
        self._final_size = (final_size.width(), final_size.height())
        old_body.deleteLater()
        if old_advanced is not None:
            old_advanced.deleteLater()

        ms = adur(260, 140)
        if not anim_on() or ms <= 0 or not self.isVisible():
            self.setFixedSize(*self._final_size)
            self.update()
            return

        self.setFixedSize(max(self._final_size[0], old_size.width()),
                          max(self._final_size[1], old_size.height()))
        if self._overlay is None:
            self._overlay = _PanelZoomOverlay(self)
        self._overlay.setGeometry(self.rect())
        self._overlay.setup(old_pm, r0, new_pm, r1)
        self._overlay.show()
        self._overlay.raise_()
        self._body.hide()
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
        for key, lab in self._labels.items():
            lab.setText(tr(key) if key != "FPS" else "FPS")
        for key, lab in self._toggle_labels.items():
            lab.setText(tr(key))
        self.sg_auto_theme.set_options(auto_theme_options(),
                                       SETTINGS["auto_theme"])
        self.sg_source.set_options(source_options(), SETTINGS["source"])
        self.sg_seek.set_options(seek_options(), SETTINGS["seek_style"])
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
        icon = GLYPH_CHEVRON_UP if self._advanced_open else GLYPH_CHEVRON_DOWN
        self.btn_advanced._text = f"{tr('advanced')}  {icon}"
        self.btn_advanced.update()
        self.sw_theme.update()

    def rebuild_for_language(self):
        if self._body is None:
            self._build_body()
            return
        if self._fade_anim.state() == Anim.Running:
            self._fade_abort = True
            self._fade_anim.stop()
            self._fade_abort = False
        prepared = self._lang_old_pm is not None
        if self._fade_overlay is not None and not prepared:
            self._fade_overlay.hide()
        old_pm = self._lang_old_pm if prepared else self._body.grab()
        old_rect = (QRectF(self._lang_old_rect).toRect()
                    if prepared else self._body.geometry())
        ms = adur(220, 120)
        do_anim = anim_on() and ms > 0 and self.isVisible()
        if do_anim and not prepared:
            if self._fade_overlay is None:
                self._fade_overlay = _PanelFadeOverlay(self)
            self._fade_overlay.setGeometry(self.rect())
            self._fade_overlay.setup(old_pm, old_rect, old_pm, old_rect)
            self._fade_overlay.show()
            self._fade_overlay.raise_()
            self.repaint()
        elif do_anim and self._fade_overlay is not None:
            self._fade_overlay.setGeometry(self.rect())
            self._fade_overlay.raise_()
        self._apply_language_texts()
        self._body.layout().activate()
        self._body.repaint()
        new_pm = self._body.grab()
        new_rect = self._body.geometry()
        self._lang_old_pm = None
        self._lang_old_rect = QRectF()

        if not do_anim:
            self._body.show()
            self._body.raise_()
            self.update()
            return

        self._fade_final_size = None
        self._fade_overlay.setup(old_pm, old_rect, new_pm, new_rect)
        self._fade_overlay.show()
        self._fade_overlay.raise_()
        self._body.hide()
        self.repaint()

        self._fade_anim.setStartValue(0.0)
        self._fade_anim.setEndValue(1.0)
        self._fade_anim.setDuration(ms)
        self._fade_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._fade_anim.start()

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
        if self.advanced_box is not None and self._advanced_open:
            self.advanced_box.show()
            self._on_advanced_anim(1.0)
        if self._final_size:
            self.setFixedSize(*self._final_size)
        self.repaint()

    def _controls(self):
        return (self.sl_opacity, self.sl_brightness, self.sl_scale,
                self.sl_settings_scale, self.sl_radius, self.sl_fps,
                self.sl_auto_strength, self.sl_cover_border_width,
                self.sl_cover_border_opacity,
                self.sl_tonearm_speed, self.sl_vinyl_spin_speed,
                self.kb_toggle, self.kb_play,
                self.kb_prev, self.kb_next, self.kb_vol_up,
                self.kb_vol_down, self.sg_auto_theme, self.sg_seek,
                self.sg_thumb,
                self.sg_source, self.sg_ctl, self.sg_card_preset,
                self.sg_art_mode, self.sg_cover_shape,
                self.sg_lang, self.btn_advanced, self.tg_aa, self.tg_src,
                self.tg_shadow, self.tg_gpu, self.tg_controls_hover,
                self.tg_topbar_hover, self.tg_show_fps,
                self.tg_anim_enabled, self.tg_show_cover,
                self.tg_cover_border,
                self.tg_btn_shuffle, self.tg_btn_prev, self.tg_btn_next,
                self.tg_btn_repeat)

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
        # 陰影用預先模糊好的貼圖（QGraphicsDropShadowEffect 會讓滑桿/
        # 開關每幀動畫都重新模糊整個面板，非常卡）
        if self._body is None or self._shadow_op <= 0.001:
            return
        p = QPainter(self)
        blur = panel_px(15)

        def draw_panel_shadow(w: QWidget, alpha_factor: float = 1.0):
            op = self._shadow_op * max(0.0, min(1.0, float(alpha_factor)))
            if op <= 0.001:
                return
            g = w.geometry()
            sh = soft_shadow(g.width(), g.height(), panel_f(16),
                             blur=blur, alpha=160,
                             dpr=self.devicePixelRatioF())
            p.save()
            p.setOpacity(op)
            p.drawPixmap(g.x() - blur, g.y() - blur + panel_px(5), sh)
            p.restore()

        if self._overlay is not None and self._overlay.isVisible():
            g = self._body.geometry()
            sh = soft_shadow(g.width(), g.height(), panel_f(16),
                             blur=blur, alpha=160,
                             dpr=self.devicePixelRatioF())
            r = self._overlay.cur_rect()
            fx = r.width() / max(1.0, float(g.width()))
            fy = r.height() / max(1.0, float(g.height()))
            target = QRectF(r.x() - blur * fx,
                            r.y() - blur * fy + panel_f(5),
                            r.width() + blur * 2 * fx,
                            r.height() + blur * 2 * fy)
            p.setRenderHint(QPainter.SmoothPixmapTransform, True)
            p.setOpacity(self._shadow_op)
            p.drawPixmap(target, sh, QRectF(sh.rect()))
        else:
            draw_panel_shadow(self._body)
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
        self.move(pos)
        fade_in(self)

    def animated_close(self):
        fade_out(self, self.hide)

    def hideEvent(self, e):
        super().hideEvent(e)
        self.closed.emit()

    # 拖曳面板
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag_off = (e.globalPosition().toPoint()
                              - self.frameGeometry().topLeft())

    def mouseMoveEvent(self, e):
        if self._drag_off is not None and e.buttons() & Qt.LeftButton:
            self.move(e.globalPosition().toPoint() - self._drag_off)

    def mouseReleaseEvent(self, e):
        self._drag_off = None


# ------------------------------------------------------------ 音量彈窗 ----

class VolumePopup(QWidget):
    """點音量鈕彈出的直向滑桿，支援拖曳、滾輪、靜音。"""

    vol_changed = Signal(float)
    mute_toggled = Signal(bool)

    BW, BH = 46, 178       # 本體大小
    M = 14                 # 陰影留邊

    def __init__(self, accent: QColor, value, muted=False, parent=None):
        super().__init__(parent)
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
