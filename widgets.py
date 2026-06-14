"""播放器自訂元件：跑馬燈、圖示按鈕、播放鈕、進度條（含動畫特效）。"""
import math
import time

from PySide6.QtCore import QEasingCurve, QPoint, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (QBrush, QColor, QFont, QFontMetricsF,
                           QLinearGradient, QPainter, QPainterPath, QPen,
                           QPixmap, QRadialGradient)
from PySide6.QtWidgets import (QAbstractButton, QGraphicsBlurEffect,
                               QGraphicsScene, QWidget)

from style import (GLYPH_NOTE, GLYPH_VOLUME_0, GLYPH_VOLUME_1,
                   GLYPH_VOLUME_2, GLYPH_VOLUME_3, SETTINGS, SPOTIFY_GREEN,
                   Anim, aa, adur, anim_full, anim_on, blend, fps_ms,
                   icon_font, tr, ui_font)


class MarqueeLabel(QWidget):
    """文字超出寬度時自動左右捲動的標籤（速度與更新率無關）。"""

    SPEED = 27.0          # px / 秒
    HOLD = 1.5            # 捲動前後停留秒數

    def __init__(self, px: int, color: QColor, weight=QFont.Normal,
                 parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.setAutoFillBackground(False)
        self._px = px
        self._weight = weight
        self._font = ui_font(px, weight)
        # 不對齊像素網格：放大/捲動時純幾何縮放，消除字形 hinting 造成的抖動
        self._font.setHintingPreference(QFont.PreferNoHinting)
        self._color = QColor(color)
        self._marquee_enabled = bool(SETTINGS.get("marquee_enabled", True))
        self._text = ""
        self._text_w = 0.0
        self._offset = 0.0
        self._hold = 0.0
        self._last = time.monotonic()
        self._gap = 48.0
        self._visual_scale = 1.0
        self._visual_y = 0.0
        self._visual_h = 0.0
        self._text_layer_cache = {}
        self._old_text = ""          # 換曲過渡：舊文字
        self._old_w = 0.0
        self._old_off = 0.0
        self._tr = 1.0               # 過渡進度（1 = 無過渡）
        self._ta = Anim(self)
        self._ta.valueChanged.connect(self._on_tr)
        self._ta.finished.connect(self._tr_done)
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.PreciseTimer)
        self._timer.setInterval(fps_ms())
        self._timer.timeout.connect(self._tick)

    def set_color(self, color: QColor):
        self._color = QColor(color)
        self._clear_text_layers()
        self.update()

    def set_font_px(self, px: int):
        if px == self._px:
            return
        self._px = px
        self._font = ui_font(px, self._weight)
        self._font.setHintingPreference(QFont.PreferNoHinting)
        self._clear_text_layers()
        fm = QFontMetricsF(self._font)
        self._text_w = fm.horizontalAdvance(self._text)
        self._old_w = fm.horizontalAdvance(self._old_text)
        self._sync_scroll_timer()
        self.update()

    def set_marquee_enabled(self, enabled: bool):
        enabled = bool(enabled)
        if enabled == self._marquee_enabled:
            return
        self._marquee_enabled = enabled
        self._offset = 0.0
        self._hold = self.HOLD
        self._last = time.monotonic()
        self._sync_scroll_timer()
        self.update()

    def set_visual_scale(self, scale: float):
        self.set_visual_frame(scale=scale)

    def set_visual_frame(self, y: float | None = None,
                         height: float | None = None,
                         scale: float | None = None):
        old = (self._visual_y, self._visual_h, self._visual_scale)
        if y is not None:
            self._visual_y = float(y)
        if height is not None:
            self._visual_h = max(1.0, float(height))
        if scale is not None:
            self._visual_scale = max(0.75, min(1.35, float(scale)))
        if (abs(old[0] - self._visual_y) < 0.02
                and abs(old[1] - self._visual_h) < 0.02
                and abs(old[2] - self._visual_scale) < 0.002):
            return
        self._sync_scroll_timer()
        self.update()

    def _sync_scroll_timer(self):
        need = (self._marquee_enabled
                and self._text_w * self._visual_scale > self.width())
        if need:
            self._timer.start()
        else:
            self._timer.stop()

    def apply_fps(self):
        self._timer.setInterval(fps_ms())

    def resizeEvent(self, _):
        self._sync_scroll_timer()

    def _on_tr(self, v):
        self._tr = float(v)
        self.update()

    def _tr_done(self):
        self._tr = 1.0
        self._old_text = ""
        self.update()

    def setText(self, text: str, animate: bool = True):
        if text == self._text:
            return
        self._ta.stop()              # 收掉進行中的過渡（同步發 finished）
        ms = adur(340, 190)
        if animate and ms > 0 and self.isVisible() and self._text:
            # 換曲過渡：舊文字上滑淡出、新文字自下方滑入
            self._old_text = self._text
            self._old_w = self._text_w
            self._old_off = self._offset
            self._ta.setStartValue(0.0)
            self._ta.setEndValue(1.0)
            self._ta.setDuration(ms)
            self._ta.setEasingCurve(QEasingCurve.OutCubic)
            self._ta.start()
        self._text = text
        self._offset = 0.0
        self._hold = self.HOLD
        self._last = time.monotonic()
        self._text_w = QFontMetricsF(self._font).horizontalAdvance(text)
        self._clear_text_layers()
        self._sync_scroll_timer()
        self.update()

    def _clear_text_layers(self):
        self._text_layer_cache.clear()

    def _text_layer(self, text: str):
        if not text:
            return None
        # 文字動畫期間只縮放這張圖層；DPR 1.0 時也用 2x 渲染，
        # 避免 15px 字放大到 18px 左右時明顯發糊。
        dpr = max(2.0, self.devicePixelRatioF())
        key = (text, self._color.rgba(), self._font.family(),
               self._font.pixelSize(), self._font.weight(),
               round(dpr * 100))
        cached = self._text_layer_cache.get(key)
        if cached is not None:
            return cached

        fm = QFontMetricsF(self._font)
        text_w = max(1.0, fm.horizontalAdvance(text))
        line_h = max(1.0, fm.height())
        pad = 3.0
        logical_w = math.ceil(text_w + pad * 2 + 2)
        logical_h = math.ceil(line_h + pad * 2)
        pm = QPixmap(max(1, round(logical_w * dpr)),
                     max(1, round(logical_h * dpr)))
        pm.setDevicePixelRatio(dpr)
        pm.fill(Qt.transparent)

        qp = QPainter(pm)
        qp.setRenderHint(QPainter.TextAntialiasing, True)
        qp.setFont(self._font)
        qp.setPen(self._color)
        qp.drawText(QPointF(pad, pad + fm.ascent()), text)
        qp.end()

        layer = (pm, float(logical_w), float(logical_h), float(line_h), pad)
        self._text_layer_cache[key] = layer
        if len(self._text_layer_cache) > 12:
            self._text_layer_cache.pop(next(iter(self._text_layer_cache)))
        return layer

    def _draw_text_layer(self, p: QPainter, text: str, x: float, y: float,
                         h: float, scale: float, opacity: float = 1.0):
        layer = self._text_layer(text)
        if layer is None:
            return
        pm, logical_w, logical_h, line_h, pad = layer
        cy = y + h / 2.0
        top = y + (h - line_h) / 2.0 - pad
        target = QRectF((float(x) - pad) * scale,
                        cy + (top - cy) * scale,
                        logical_w * scale,
                        logical_h * scale)
        p.save()
        p.setOpacity(max(0.0, min(1.0, float(opacity))))
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        p.drawPixmap(target, pm, QRectF(pm.rect()))
        p.restore()

    def _tick(self):
        now = time.monotonic()
        dt = min(0.1, now - self._last)
        self._last = now
        if self._hold > 0:
            self._hold -= dt
            return
        self._offset += self.SPEED * dt
        if self._offset >= self._text_w + self._gap:
            self._offset = 0.0
            self._hold = self.HOLD
        self.update()

    def _elided(self, text: str, width: float) -> str:
        width = max(0.0, float(width))
        if not text or width <= 0.0:
            return ""
        fm = QFontMetricsF(self._font)
        if fm.horizontalAdvance(text) <= width:
            return text
        suffix = "..."
        if fm.horizontalAdvance(suffix) > width:
            return ""
        lo, hi = 0, len(text)
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if fm.horizontalAdvance(text[:mid] + suffix) <= width:
                lo = mid
            else:
                hi = mid - 1
        return text[:lo] + suffix

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.TextAntialiasing)
        y = self._visual_y
        h = self._visual_h or float(self.height())
        scale = self._visual_scale
        avail_w = self.width() / max(0.01, scale)
        if self._tr < 1.0:           # 換曲過渡：舊字上滑淡出、新字下滑入
            t = self._tr
            rise = h * 0.55
            if self._marquee_enabled:
                old_x = -self._old_off
                old_text = self._old_text
            else:
                old_x = 0.0
                old_text = self._elided(self._old_text, avail_w)
            self._draw_text_layer(p, old_text, old_x, y - rise * t, h,
                                  scale, 1.0 - t)
            if self._marquee_enabled:
                new_x = 0.0
                new_text = self._text
            else:
                new_x = 0.0
                new_text = self._elided(self._text, avail_w)
            self._draw_text_layer(p, new_text, new_x,
                                  y + rise * (1.0 - t), h, scale,
                                  min(1.0, t * 1.15))
            return
        if not self._marquee_enabled:
            self._draw_text_layer(p, self._elided(self._text, avail_w),
                                  0.0, y, h, scale)
        elif self._text_w <= avail_w:
            self._draw_text_layer(p, self._text, 0.0, y, h, scale)
        else:
            self._draw_text_layer(p, self._text, -self._offset, y, h, scale)
            self._draw_text_layer(p, self._text,
                                  -self._offset + self._text_w + self._gap,
                                  y, h, scale)


class ArtView(QWidget):
    """封面圖：換曲時舊圖淡出、新圖淡入微縮放的交叉過渡；無封面畫占位。"""

    def __init__(self, size: int, radius: int, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.setAutoFillBackground(False)
        self._size = size
        self._cover_scale = max(
            0.6, min(1.4, float(SETTINGS.get("art_cover_size", 1.0))))
        self._vinyl_scale = max(
            0.7, min(1.35, float(SETTINGS.get("art_vinyl_size", 1.0))))
        self._layout_size = max(self.cover_size(), self.vinyl_size())
        self._radius = radius
        self.pad = max(8, round(self._layout_size * 0.18))
        self._pm: QPixmap | None = None
        self._old: QPixmap | None = None
        self._pm_blur: QPixmap | None = None
        self._old_blur: QPixmap | None = None
        self._cover_blur = float(SETTINGS.get("cover_blur", 0.0))
        self._t = 1.0                # 過渡進度（1 = 無過渡）
        self._anim = Anim(self)
        self._anim.valueChanged.connect(self._on_t)
        self._anim.finished.connect(self._done)
        self._ra = Anim(self)
        self._ra.valueChanged.connect(self._on_radius)
        self._hover = 0.0
        self._ha = Anim(self)
        self._ha.valueChanged.connect(self._on_hover)
        self._accent = QColor(SPOTIFY_GREEN)
        self._border_t = 1.0 if SETTINGS.get("cover_border", False) else 0.0
        self._border_w = float(SETTINGS.get("cover_border_width", 2.0))
        self._border_op = float(SETTINGS.get("cover_border_opacity", 0.85))
        self._border_t0 = self._border_t
        self._border_t1 = self._border_t
        self._border_w0 = self._border_w
        self._border_w1 = self._border_w
        self._border_op0 = self._border_op
        self._border_op1 = self._border_op
        self._ba = Anim(self)
        self._ba.valueChanged.connect(self._on_border)
        self._mode = "cover"
        self._vinyl = 0.0
        self._ma = Anim(self)
        self._ma.valueChanged.connect(self._on_mode)
        self._playing = False
        self._arm = 0.0
        self._arm_target = 0.0
        self._arma = Anim(self)
        self._arma.valueChanged.connect(self._on_arm)
        self._tonearm_op = 1.0 if SETTINGS.get("show_tonearm", True) else 0.0
        self._tonearm_target = self._tonearm_op
        self._tonearm_oa = Anim(self)
        self._tonearm_oa.valueChanged.connect(self._on_tonearm_op)
        self._spin = 0.0
        self._spin_speed = 0.0
        self._spin_cooldown = 0.0
        self._spin_last = time.monotonic()
        self._spin_timer = QTimer(self)
        self._spin_timer.setTimerType(Qt.PreciseTimer)
        self._spin_timer.setInterval(fps_ms())
        self._spin_timer.timeout.connect(self._spin_tick)
        self.setMouseTracking(True)
        self.setFixedSize(self._layout_size + self.pad * 2,
                          self._layout_size + self.pad * 2)

    def cover_size(self) -> int:
        return max(1, round(self._size * self._cover_scale))

    def vinyl_size(self) -> int:
        return max(1, round(self._size * self._vinyl_scale))

    def layout_span(self) -> int:
        return self._layout_size

    def _on_t(self, v):
        self._t = float(v)
        self.update()

    def _done(self):
        self._t = 1.0
        self._old = None
        self._old_blur = None
        self.update()

    def _on_hover(self, v):
        self._hover = float(v)
        self.update()

    def _on_radius(self, v):
        self._radius = max(0.0, float(v))
        self.update()

    def _on_border(self, v):
        t = max(0.0, min(1.0, float(v)))
        self._border_t = self._border_t0 + (self._border_t1 - self._border_t0) * t
        self._border_w = self._border_w0 + (self._border_w1 - self._border_w0) * t
        self._border_op = self._border_op0 + (self._border_op1 - self._border_op0) * t
        self.update()

    def set_accent(self, c: QColor):
        self._accent = QColor(c)
        self.update()

    def set_scales(self, cover_scale: float, vinyl_scale: float):
        cover_scale = max(0.6, min(1.4, float(cover_scale)))
        vinyl_scale = max(0.7, min(1.35, float(vinyl_scale)))
        if (abs(cover_scale - self._cover_scale) < 0.0001
                and abs(vinyl_scale - self._vinyl_scale) < 0.0001):
            return
        self._cover_scale = cover_scale
        self._vinyl_scale = vinyl_scale
        self._layout_size = max(self.cover_size(), self.vinyl_size())
        self.pad = max(8, round(self._layout_size * 0.18))
        self.setFixedSize(self._layout_size + self.pad * 2,
                          self._layout_size + self.pad * 2)
        self._sync_spin()
        self.update()

    def set_radius(self, radius: int, animate: bool = False):
        radius = max(0, min(self.cover_size() // 2, int(radius)))
        if abs(radius - self._radius) < 0.5:
            self._radius = radius
            self.update()
            return
        self._ra.stop()
        ms = adur(260, 140)
        if (not animate or not anim_on() or ms <= 0 or not self.isVisible()):
            self._radius = radius
            self.update()
            return
        self._ra.setStartValue(float(self._radius))
        self._ra.setEndValue(float(radius))
        self._ra.setDuration(ms)
        self._ra.setEasingCurve(QEasingCurve.OutCubic)
        self._ra.start()

    def set_border(self, enabled: bool, width: float,
                   opacity: float = 0.85,
                   animate: bool = True):
        width = max(1.0, min(8.0, float(width)))
        opacity = max(0.0, min(1.0, float(opacity)))
        target_t = 1.0 if enabled else 0.0
        self._ba.stop()
        ms = adur(220, 120)
        if (not animate or not anim_on() or ms <= 0 or not self.isVisible()):
            self._border_t = target_t
            self._border_w = width
            self._border_op = opacity
            self.update()
            return
        self._border_t0, self._border_t1 = self._border_t, target_t
        self._border_w0, self._border_w1 = self._border_w, width
        self._border_op0, self._border_op1 = self._border_op, opacity
        self._ba.setStartValue(0.0)
        self._ba.setEndValue(1.0)
        self._ba.setDuration(ms)
        self._ba.setEasingCurve(QEasingCurve.OutCubic)
        self._ba.start()

    def _make_blurred_pixmap(self, pm: QPixmap | None) -> QPixmap | None:
        radius = max(0.0, min(14.0, float(self._cover_blur)))
        if pm is None or pm.isNull() or radius <= 0.01:
            return pm
        dpr = max(1.0, pm.devicePixelRatioF())
        w = max(1.0, pm.width() / dpr)
        h = max(1.0, pm.height() / dpr)
        rect = QRectF(0, 0, w, h)
        out = QPixmap(max(1, round(w * dpr)), max(1, round(h * dpr)))
        out.setDevicePixelRatio(dpr)
        out.fill(Qt.transparent)

        scene = QGraphicsScene()
        scene.setSceneRect(rect)
        item = scene.addPixmap(pm)
        item.setPos(0, 0)
        eff = QGraphicsBlurEffect()
        eff.setBlurRadius(radius)
        item.setGraphicsEffect(eff)

        p = QPainter(out)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        scene.render(p, rect, rect)
        p.end()
        return out

    def _paint_pixmap(self, pm: QPixmap | None,
                      blurred: QPixmap | None) -> QPixmap | None:
        if pm is None:
            return None
        if self._cover_blur <= 0.01:
            return pm
        return blurred if blurred is not None else pm

    def set_blur(self, radius: float):
        radius = round(max(0.0, min(14.0, float(radius))), 1)
        if abs(radius - self._cover_blur) < 0.01:
            return
        self._cover_blur = radius
        self._pm_blur = self._make_blurred_pixmap(self._pm)
        self._old_blur = self._make_blurred_pixmap(self._old)
        self.update()

    def _on_mode(self, v):
        self._vinyl = float(v)
        self._sync_spin()
        self.update()

    def _on_arm(self, v):
        self._arm = float(v)
        self.update()

    def _on_tonearm_op(self, v):
        self._tonearm_op = max(0.0, min(1.0, float(v)))
        self.update()

    def set_tonearm_visible(self, visible: bool, animate: bool = True):
        target = 1.0 if visible else 0.0
        self._tonearm_target = target
        if abs(target - self._tonearm_op) < 0.001:
            self._tonearm_op = target
            self.update()
            return
        self._tonearm_oa.stop()
        ms = adur(240 if target > self._tonearm_op else 190, 120)
        if not animate or not anim_on() or ms <= 0 or not self.isVisible():
            self._tonearm_op = target
            self.update()
            return
        self._tonearm_oa.setStartValue(self._tonearm_op)
        self._tonearm_oa.setEndValue(target)
        self._tonearm_oa.setDuration(ms)
        self._tonearm_oa.setEasingCurve(QEasingCurve.OutCubic)
        self._tonearm_oa.start()

    def _spin_tick(self):
        now = time.monotonic()
        dt = min(0.1, now - self._spin_last)
        self._spin_last = now
        base_speed = 54.0 * float(SETTINGS.get("vinyl_spin_speed", 1.0))
        if self._playing:
            self._spin_speed = base_speed
            self._spin_cooldown = 0.0
        elif self._spin_cooldown > 0.0:
            self._spin_cooldown = max(0.0, self._spin_cooldown - dt)
            t = self._spin_cooldown / 0.42
            self._spin_speed = base_speed * t * t
        else:
            self._spin_speed = 0.0
        if self._spin_speed > 0.0:
            self._spin = (self._spin + self._spin_speed * dt) % 360.0
        self.update()
        if not self._playing and self._spin_speed <= 0.05:
            self._spin_speed = 0.0
            self._sync_spin()

    def _sync_spin(self):
        active = (self.isVisible() and self._vinyl > 0.02
                  and (self._playing or self._spin_cooldown > 0.0
                       or self._spin_speed > 0.05))
        if active:
            if not self._spin_timer.isActive():
                self._spin_last = time.monotonic()
                self._spin_timer.start()
        else:
            self._spin_timer.stop()

    def set_playing(self, playing: bool):
        was_playing = self._playing
        self._playing = bool(playing)
        if self._playing:
            self._spin_speed = 54.0 * float(SETTINGS.get("vinyl_spin_speed", 1.0))
            self._spin_cooldown = 0.0
        elif was_playing:
            base_speed = 54.0 * float(SETTINGS.get("vinyl_spin_speed", 1.0))
            self._spin_speed = max(self._spin_speed, base_speed)
            self._spin_cooldown = 0.42
        self._sync_spin()
        target = 1.0 if self._playing else 0.0
        if abs(target - self._arm_target) < 0.001:
            return
        self._arm_target = target
        self._arma.stop()
        speed = max(0.4, float(SETTINGS.get("tonearm_speed", 1.0)))
        ms = round(adur(340 if self._playing else 300, 170) / speed)
        if not anim_on() or ms <= 0 or not self.isVisible():
            self._arm = target
            self.update()
            return
        self._arma.setStartValue(self._arm)
        self._arma.setEndValue(target)
        self._arma.setDuration(ms)
        self._arma.setEasingCurve(QEasingCurve.OutCubic)
        self._arma.start()

    def apply_fps(self):
        self._spin_timer.setInterval(fps_ms())

    def apply_motion_settings(self):
        if self._playing:
            self._spin_speed = 54.0 * float(
                SETTINGS.get("vinyl_spin_speed", 1.0))
        self._sync_spin()
        self.update()

    def set_mode(self, mode: str, animate: bool = True):
        mode = "vinyl" if mode == "vinyl" else "cover"
        self._mode = mode
        target = 1.0 if mode == "vinyl" else 0.0
        self._ma.stop()
        ms = adur(360, 190)
        if not animate or not anim_on() or ms <= 0:
            self._vinyl = target
            self._sync_spin()
            self.update()
            return
        self._ma.setStartValue(self._vinyl)
        self._ma.setEndValue(target)
        self._ma.setDuration(ms)
        self._ma.setEasingCurve(QEasingCurve.OutCubic)
        self._ma.start()

    def showEvent(self, e):
        super().showEvent(e)
        self._sync_spin()

    def hideEvent(self, e):
        super().hideEvent(e)
        self._spin_timer.stop()

    def _hover_to(self, on: bool):
        self._ha.stop()
        target = 1.0 if on else 0.0
        ms = adur(190 if on else 230, 110)
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

    def set_pixmap(self, pm: QPixmap | None, animate: bool = True):
        if pm is None and self._pm is None:
            return
        self._anim.stop()            # 收掉進行中的過渡（同步發 finished）
        ms = adur(420, 220)
        if animate and ms > 0 and self.isVisible():
            self._old = self._pm
            self._old_blur = self._pm_blur
            self._anim.setStartValue(0.0)
            self._anim.setEndValue(1.0)
            self._anim.setDuration(ms)
            self._anim.setEasingCurve(QEasingCurve.OutCubic)
            self._anim.start()
        else:
            self._old = None
            self._old_blur = None
            self._t = 1.0
        self._pm = pm
        self._pm_blur = self._make_blurred_pixmap(pm)
        self.update()

    def _visual_rect(self, kind: str = "cover") -> QRectF:
        size = self.vinyl_size() if kind == "vinyl" else self.cover_size()
        x = self.pad + (self._layout_size - size) / 2
        y = self.pad + (self._layout_size - size) / 2
        return QRectF(x, y, size, size)

    def _shape_path(self, rect: QRectF) -> QPainterPath:
        path = QPainterPath()
        if self._radius >= min(rect.width(), rect.height()) / 2 - 0.5:
            path.addEllipse(rect)
        elif self._radius > 0:
            path.addRoundedRect(rect, self._radius, self._radius)
        else:
            path.addRect(rect)
        return path

    def _apply_hover_transform(self, p: QPainter):
        if self._hover <= 0.001:
            return
        r = self._visual_rect("cover")
        c = r.center()
        p.translate(c)
        p.rotate(-1.8 * self._hover)
        s = 1.0 + 0.035 * self._hover
        p.scale(s, s)
        p.translate(-c)

    def _draw_pixmap(self, p: QPainter, pm: QPixmap, alpha: float,
                     scale: float = 1.0):
        if alpha <= 0.01:
            return
        r = self._visual_rect("cover")
        p.save()
        p.setOpacity(alpha)
        if scale != 1.0:
            c = r.center()
            p.translate(c)
            p.scale(scale, scale)
            p.translate(-c)
        p.setClipPath(self._shape_path(r))
        p.drawPixmap(r, pm, QRectF(pm.rect()))
        p.restore()

    def _draw_border(self, p: QPainter, alpha: float):
        if alpha <= 0.01 or self._border_t <= 0.001:
            return
        w = max(1.0, self._border_w)
        r = self._visual_rect("cover").adjusted(
            -w / 2, -w / 2, w / 2, w / 2)
        op = alpha * self._border_t * self._border_op
        col = QColor(self._accent).lighter(128)
        col.setAlpha(round(205 * op))
        hi = QColor(255, 255, 255, round(72 * op))
        radius = self._radius + w / 2 if self._radius > 0 else 0.0
        join = Qt.RoundJoin if self._radius > 0 else Qt.MiterJoin
        p.save()
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(col, w, Qt.SolidLine, Qt.RoundCap, join))
        if radius > 0:
            p.drawRoundedRect(r, radius, radius)
        else:
            p.drawRect(r)
        if w >= 2.4:
            p.setPen(QPen(hi, max(0.8, w * 0.34),
                          Qt.SolidLine, Qt.RoundCap, join))
            hr = r.adjusted(-w * 0.12, -w * 0.12,
                            w * 0.12, w * 0.12)
            if radius > 0:
                p.drawRoundedRect(hr, self._radius + w * 0.62,
                                  self._radius + w * 0.62)
            else:
                p.drawRect(hr)
        p.restore()

    def _draw_label_pixmap(self, p: QPainter, rect: QRectF, alpha: float,
                           pm: QPixmap | None = None):
        if alpha <= 0.01:
            return
        p.save()
        p.setOpacity(alpha)
        path = QPainterPath()
        path.addEllipse(rect)
        p.setClipPath(path)
        if pm is None:
            pm = self._pm
        if pm is not None:
            p.drawPixmap(rect, pm, QRectF(pm.rect()))
        else:
            p.fillPath(path, QColor(255, 255, 255, 28))
            p.setClipping(False)
            p.setFont(icon_font(round(rect.width() * 0.42)))
            p.setPen(QColor(255, 255, 255, 75))
            p.drawText(rect, Qt.AlignCenter, GLYPH_NOTE)
        p.restore()

    def _draw_vinyl(self, p: QPainter, alpha: float):
        if alpha <= 0.01:
            return
        r = self._visual_rect("vinyl")
        c = r.center()
        rad = min(r.width(), r.height()) / 2
        p.save()
        p.setOpacity(alpha)

        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 42))
        p.drawEllipse(r.adjusted(rad * 0.018, rad * 0.035,
                                 -rad * 0.018, -rad * 0.005))

        style = "clean"
        g = QRadialGradient(c, rad)
        if style == "silver":
            g.setColorAt(0.00, QColor(128, 130, 138))
            g.setColorAt(0.22, QColor(64, 66, 74))
            g.setColorAt(0.62, QColor(34, 35, 42))
            g.setColorAt(0.86, QColor(82, 84, 92))
            g.setColorAt(1.00, QColor(150, 152, 160))
        elif style == "clear":
            g.setColorAt(0.00, QColor(78, 110, 122, 185))
            g.setColorAt(0.22, QColor(18, 35, 44, 165))
            g.setColorAt(0.64, QColor(8, 16, 22, 150))
            g.setColorAt(0.86, QColor(28, 56, 70, 165))
            g.setColorAt(1.00, QColor(78, 118, 134, 190))
        elif style == "retro":
            g.setColorAt(0.00, QColor(68, 58, 50))
            g.setColorAt(0.18, QColor(24, 20, 18))
            g.setColorAt(0.64, QColor(8, 7, 7))
            g.setColorAt(0.86, QColor(28, 23, 20))
            g.setColorAt(1.00, QColor(74, 60, 48))
        else:
            g.setColorAt(0.00, QColor(52, 52, 58))
            g.setColorAt(0.18, QColor(18, 18, 22))
            g.setColorAt(0.64, QColor(5, 5, 8))
            g.setColorAt(0.86, QColor(14, 14, 19))
            g.setColorAt(1.00, QColor(38, 38, 45))
        p.setPen(QPen(QColor(255, 255, 255, 38), 1))
        p.setBrush(g)
        p.drawEllipse(r)

        p.setPen(QPen(QColor(255, 255, 255, 9), max(0.65, rad * 0.006)))
        for frac in (0.24, 0.29, 0.34, 0.39, 0.44, 0.49, 0.54,
                     0.59, 0.64, 0.69, 0.74, 0.79, 0.84, 0.89):
            rr = rad * frac
            p.drawEllipse(c, rr, rr)
        p.setPen(QPen(QColor(0, 0, 0, 72), max(0.7, rad * 0.007)))
        for frac in (0.32, 0.47, 0.61, 0.77, 0.87):
            rr = rad * frac
            p.drawEllipse(c, rr, rr)
        if style == "retro":
            p.setPen(QPen(QColor(210, 170, 94, 28), max(0.7, rad * 0.008)))
            for frac in (0.36, 0.58, 0.82):
                rr = rad * frac
                p.drawEllipse(c, rr, rr)
        elif style == "silver":
            p.setPen(QPen(QColor(255, 255, 255, 34), max(0.8, rad * 0.010)))
            p.drawEllipse(c, rad * 0.76, rad * 0.76)
        elif style == "clear":
            p.setPen(QPen(QColor(180, 230, 255, 30), max(0.8, rad * 0.010)))
            p.drawEllipse(c, rad * 0.84, rad * 0.84)

        shine_path = QPainterPath()
        shine_path.addEllipse(r)
        p.save()
        p.setClipPath(shine_path)
        p.translate(c)
        p.rotate(-17)
        p.translate(-c)
        shine = QLinearGradient(c.x() - rad * 0.62, c.y() - rad,
                                c.x() - rad * 0.18, c.y() + rad)
        shine.setColorAt(0.0, QColor(255, 255, 255, 0))
        shine.setColorAt(0.48, QColor(255, 255, 255, 24))
        shine.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.setPen(Qt.NoPen)
        p.setBrush(shine)
        p.drawRoundedRect(QRectF(c.x() - rad * 0.56, c.y() - rad * 0.92,
                                 rad * 0.18, rad * 1.84),
                          rad * 0.09, rad * 0.09)
        side_shine = QLinearGradient(c.x() + rad * 0.40, c.y() - rad,
                                     c.x() + rad * 0.72, c.y() + rad)
        side_shine.setColorAt(0.0, QColor(255, 255, 255, 0))
        side_shine.setColorAt(0.52, QColor(255, 255, 255, 13))
        side_shine.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.setBrush(side_shine)
        p.drawRoundedRect(QRectF(c.x() + rad * 0.47, c.y() - rad * 0.78,
                                 rad * 0.12, rad * 1.56),
                          rad * 0.06, rad * 0.06)
        p.restore()

        p.setPen(QPen(QColor(0, 0, 0, 120), max(2.0, rad * 0.035)))
        p.drawEllipse(c, rad * 0.91, rad * 0.91)
        p.setPen(QPen(QColor(255, 255, 255, 26), max(1.0, rad * 0.015)))
        p.drawEllipse(c, rad * 0.96, rad * 0.96)

        hi = QLinearGradient(r.topLeft(), r.bottomRight())
        hi.setColorAt(0.0, QColor(255, 255, 255, 62))
        hi.setColorAt(0.35, QColor(255, 255, 255, 8))
        hi.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.setPen(Qt.NoPen)
        p.setBrush(hi)
        p.drawEllipse(QRectF(c.x() - rad * 0.88, c.y() - rad * 0.88,
                             rad * 1.76, rad * 1.76))

        p.save()
        p.translate(c)
        p.rotate(self._spin)
        p.translate(-c)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(3, 3, 7, 245))
        p.drawEllipse(c, rad * 0.63, rad * 0.63)
        label = QRectF(c.x() - rad * 0.54, c.y() - rad * 0.54,
                       rad * 1.08, rad * 1.08)
        if self._t < 1.0:
            self._draw_label_pixmap(
                p, label, alpha * (1.0 - self._t),
                self._paint_pixmap(self._old, self._old_blur))
            self._draw_label_pixmap(
                p, label, alpha * self._t,
                self._paint_pixmap(self._pm, self._pm_blur))
        else:
            self._draw_label_pixmap(
                p, label, alpha,
                self._paint_pixmap(self._pm, self._pm_blur))
        p.setClipping(False)
        p.setPen(QPen(QColor(0, 0, 0, 185), max(2.0, rad * 0.035)))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(c, rad * 0.57, rad * 0.57)
        p.restore()

        p.restore()

    def _draw_tonearm(self, p: QPainter, alpha: float):
        if alpha <= 0.01:
            return
        r = self._visual_rect("vinyl")
        c = r.center()
        rad = min(r.width(), r.height()) / 2
        p.save()
        p.setOpacity(alpha)

        # 右上轉軸 + 直線段轉角；固定在唱盤上方，不受封面 hover 變形影響。
        pad = self.pad
        shift = QPointF(-rad * 0.16, 0.0)
        pivot = QPointF(r.right() + pad * 0.42,
                        r.top() + pad * 0.52) + shift
        elbow = QPointF(c.x() + rad * 1.01, c.y() + rad * 0.18) + shift
        cart = QPointF(c.x() + rad * 0.34, c.y() + rad * 0.80) + shift
        arm = max(0.0, min(1.0, self._arm))
        rest_angle = math.radians(-12.0 * (1.0 - arm))
        if abs(rest_angle) > 0.0001:
            cos_a = math.cos(rest_angle)
            sin_a = math.sin(rest_angle)

            def arm_point(pt: QPointF) -> QPointF:
                dx = pt.x() - pivot.x()
                dy = pt.y() - pivot.y()
                return QPointF(pivot.x() + dx * cos_a - dy * sin_a,
                               pivot.y() + dx * sin_a + dy * cos_a)

            elbow = arm_point(elbow)
            cart = arm_point(cart)
        arm_w = max(2.0, rad * 0.034)
        pivot_r = max(5.2, rad * 0.095)

        def rounded_arm_path(offset: QPointF = QPointF()) -> QPainterPath:
            start = pivot + offset
            joint = elbow + offset
            end = cart + offset
            v1x = start.x() - joint.x()
            v1y = start.y() - joint.y()
            v2x = end.x() - joint.x()
            v2y = end.y() - joint.y()
            l1 = math.hypot(v1x, v1y)
            l2 = math.hypot(v2x, v2y)
            if l1 <= 0.01 or l2 <= 0.01:
                path = QPainterPath()
                path.moveTo(start)
                path.lineTo(joint)
                path.lineTo(end)
                return path
            corner = min(rad * 0.13, l1 * 0.42, l2 * 0.42)
            pre = QPointF(joint.x() + v1x / l1 * corner,
                          joint.y() + v1y / l1 * corner)
            post = QPointF(joint.x() + v2x / l2 * corner,
                           joint.y() + v2y / l2 * corner)
            path = QPainterPath()
            path.moveTo(start)
            path.lineTo(pre)
            path.quadTo(joint, post)
            path.lineTo(end)
            return path

        p.setBrush(Qt.NoBrush)
        p.save()
        p.translate(QPointF(1.0, 1.4))
        p.setPen(QPen(QColor(0, 0, 0, 72), arm_w + 2.0,
                      Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.drawPath(rounded_arm_path())
        p.restore()

        p.setPen(QPen(QColor(190, 192, 198, 230), arm_w,
                      Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.drawPath(rounded_arm_path())
        p.setPen(QPen(QColor(252, 252, 255, 145),
                      max(0.9, arm_w * 0.34),
                      Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.drawPath(rounded_arm_path(QPointF(-arm_w * 0.19, 0)))

        tail_dx = pivot.x() - elbow.x()
        tail_dy = pivot.y() - elbow.y()
        tail_len = math.hypot(tail_dx, tail_dy)
        if tail_len > 0.01:
            ux = tail_dx / tail_len
            uy = tail_dy / tail_len
            tail_start = pivot + QPointF(ux * pivot_r * 0.52,
                                         uy * pivot_r * 0.52)
            tail_end = pivot + QPointF(ux * rad * 0.16,
                                       uy * rad * 0.16)
            tail_r = max(1.5, rad * 0.030)
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(QColor(0, 0, 0, 70), arm_w + 1.8,
                          Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            p.drawLine(tail_start + QPointF(0.8, 1.1),
                       tail_end + QPointF(0.8, 1.1))
            p.setPen(QPen(QColor(184, 186, 196, 225),
                          max(1.4, arm_w * 0.86),
                          Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            p.drawLine(tail_start, tail_end)
            p.setPen(QPen(QColor(228, 228, 236, 115),
                          max(0.7, rad * 0.009)))
            p.setBrush(QColor(40, 40, 48, 242))
            p.drawEllipse(tail_end, tail_r, tail_r)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(210, 210, 220, 175))
            p.drawEllipse(tail_end, tail_r * 0.38, tail_r * 0.38)

        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 58))
        p.drawEllipse(pivot + QPointF(0.8, 1.1), pivot_r * 1.12,
                      pivot_r * 1.12)
        p.setPen(QPen(QColor(230, 230, 238, 145), max(1.0, rad * 0.016)))
        p.setBrush(QColor(32, 32, 38, 242))
        p.drawEllipse(pivot, pivot_r, pivot_r)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(78, 78, 86, 240))
        p.drawEllipse(pivot, pivot_r * 0.58, pivot_r * 0.58)
        p.setBrush(QColor(192, 192, 202, 210))
        p.drawEllipse(pivot, pivot_r * 0.22, pivot_r * 0.22)

        cart_w = max(8.0, rad * 0.22)
        cart_h = max(5.2, rad * 0.13)
        p.save()
        p.translate(cart)
        cart_angle = math.degrees(math.atan2(cart.y() - elbow.y(),
                                             cart.x() - elbow.x())) + 180.0
        p.rotate(cart_angle)
        cart_rect = QRectF(-cart_w / 2, -cart_h / 2, cart_w, cart_h)
        p.setPen(QPen(QColor(210, 210, 220, 110), max(0.8, rad * 0.010)))
        p.setBrush(QColor(28, 28, 34, 238))
        p.drawRoundedRect(cart_rect, rad * 0.020, rad * 0.020)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(220, 220, 228, 150))
        p.drawRoundedRect(QRectF(-cart_w * 0.22, -cart_h * 0.22,
                                 cart_w * 0.30, cart_h * 0.44),
                          rad * 0.012, rad * 0.012)
        p.restore()

        p.restore()

    def _draw_placeholder(self, p: QPainter, alpha: float):
        if alpha <= 0.01:
            return
        r = self._visual_rect("cover")
        p.setOpacity(alpha)
        path = self._shape_path(r)
        p.fillPath(path, QColor(255, 255, 255, 16))
        p.setFont(icon_font(round(self.cover_size() * 0.27)))
        p.setPen(QColor(255, 255, 255, 70))
        p.drawText(r, Qt.AlignCenter, GLYPH_NOTE)
        p.setOpacity(1.0)

    def paintEvent(self, _):
        p = QPainter(self)
        aa(p)
        t = self._t
        p.save()
        self._apply_hover_transform(p)
        cover_alpha = max(0.0, min(1.0, 1.0 - self._vinyl))
        vinyl_alpha = max(0.0, min(1.0, self._vinyl))
        pm = self._paint_pixmap(self._pm, self._pm_blur)
        old = self._paint_pixmap(self._old, self._old_blur)
        if pm is None:
            self._draw_placeholder(p, t * cover_alpha)
        else:
            if t < 1.0:              # 新圖 0.94 → 1.0 微縮放淡入
                self._draw_pixmap(p, pm, t * cover_alpha,
                                  0.94 + 0.06 * t)
            else:
                self._draw_pixmap(p, pm, t * cover_alpha)
        if t < 1.0:
            if old is not None:
                self._draw_pixmap(p, old, (1.0 - t) * cover_alpha)
            else:
                self._draw_placeholder(p, (1.0 - t) * cover_alpha)
        self._draw_border(p, cover_alpha)
        self._draw_vinyl(p, vinyl_alpha)
        p.restore()
        if self._tonearm_op > 0.001:
            self._draw_tonearm(p, vinyl_alpha * self._tonearm_op)


class _AnimButton(QAbstractButton):
    """hover 漸變 + 按壓縮放回彈的共用基底（皆為時間基準動畫）。"""

    HOVER_GROW = 0.12     # hover 時放大比例
    PRESS_SCALE = 0.85    # 按壓縮小比例

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.setAutoFillBackground(False)
        self._hov = 0.0          # hover 進度 0~1（顏色 / 縮放共用）
        self._press = 1.0        # 按壓縮放
        self._suppress_next_hover = False
        self._enter_suppressed = False
        self._ha = Anim(self)
        self._ha.valueChanged.connect(self._on_hov)
        self._ha.finished.connect(self._hover_anim_done)
        self._pa = Anim(self)
        self._pa.valueChanged.connect(self._on_press)
        self.setCursor(Qt.PointingHandCursor)
        self._hover_pulse_phase = 0

    def _on_hov(self, v):
        self._hov = float(v)
        self.update()

    def _on_press(self, v):
        self._press = float(v)
        self.update()

    def _animate(self, anim, cur, to, ms, easing):
        anim.stop()
        if not anim_on() or ms <= 0:
            anim.valueChanged.emit(to)
            return
        anim.setStartValue(cur)
        anim.setEndValue(to)
        anim.setDuration(ms)
        anim.setEasingCurve(easing)
        anim.start()

    def suppress_next_hover_animation(self):
        self._suppress_next_hover = True

    def _hover_anim_done(self):
        if self._hover_pulse_phase == 1:
            self._hover_pulse_phase = 2
            self._animate(self._ha, self._hov, 0.0, adur(170, 100),
                          QEasingCurve.OutCubic)
        elif self._hover_pulse_phase == 2:
            self._hover_pulse_phase = 0
            self._on_hov(0.0)

    def replay_hover_animation(self):
        self._suppress_next_hover = False
        self._enter_suppressed = False
        self._hover_pulse_phase = 0
        self._ha.stop()
        ms = adur(150, 90)
        if not anim_on() or ms <= 0:
            self._on_hov(0.0)
            return
        self._on_hov(0.0)
        self._hover_pulse_phase = 1
        self._animate(self._ha, 0.0, 1.0, ms, QEasingCurve.OutCubic)

    def enterEvent(self, e):
        self._enter_suppressed = False
        self._hover_pulse_phase = 0
        if self._suppress_next_hover:
            self._suppress_next_hover = False
            self._enter_suppressed = True
            self._ha.stop()
            self._on_hov(1.0)
            return
        self._animate(self._ha, self._hov, 1.0, adur(150, 90),
                      QEasingCurve.OutCubic)

    def leaveEvent(self, e):
        self._suppress_next_hover = False
        self._enter_suppressed = False
        self._hover_pulse_phase = 0
        self._animate(self._ha, self._hov, 0.0, adur(190, 110),
                      QEasingCurve.OutCubic)

    def mousePressEvent(self, e):
        super().mousePressEvent(e)
        if e.button() == Qt.LeftButton:
            self._animate(self._pa, self._press, self.PRESS_SCALE,
                          adur(80, 60), QEasingCurve.OutQuad)

    def mouseReleaseEvent(self, e):
        super().mouseReleaseEvent(e)
        if anim_full():
            curve = QEasingCurve(QEasingCurve.OutBack)
            curve.setOvershoot(1.8)
            self._animate(self._pa, self._press, 1.0, 240, curve)
        else:
            self._animate(self._pa, self._press, 1.0, adur(130, 100),
                          QEasingCurve.OutCubic)

    def _scale(self) -> float:
        return self._press * (1.0 + self.HOVER_GROW * self._hov)

    def _transform(self, p: QPainter, dx: float = 0.0, dy: float = 0.0,
                   angle: float = 0.0):
        cx, cy = self.width() / 2, self.height() / 2
        p.translate(cx + dx, cy + dy)
        if angle:
            p.rotate(angle)
        s = self._scale()
        if s != 1.0:
            p.scale(s, s)
        p.translate(-cx, -cy)


class IconButton(_AnimButton):
    """以 Segoe Fluent Icons 字型繪製的小圖示按鈕。

    fx：hover 特效 —— "spin" 多圈轉動、"gear" 120 度轉動、
    "wiggle" 上浮微轉、"lift" 上浮、"volume" 音量由小到大。
    nudge：點擊時圖示往該方向輕推一下（-1 左 / +1 右）。
    """

    HOVER_GROW = 0.0      # 文字字形縮放會左右抖動，圖示鈕不做 hover 放大

    _VOL_SEQ = [GLYPH_VOLUME_0, GLYPH_VOLUME_1, GLYPH_VOLUME_2,
                GLYPH_VOLUME_3]

    def __init__(self, glyph: str, glyph_px=13, diameter=26,
                 checkable=False, dot=False, fx="", nudge=0, parent=None):
        super().__init__(parent)
        self._glyph = glyph
        self._px = glyph_px
        self._dot = dot
        self._fx_kind = fx
        self._nudge_dir = nudge
        self._accent = QColor(SPOTIFY_GREEN)
        self._color_override: QColor | None = None
        self._extra_opacity = 1.0
        self.setCheckable(checkable)
        self.setFixedSize(diameter, diameter)
        self._check_t = 1.0 if self.isChecked() else 0.0
        self._check_anim = Anim(self)
        self._check_anim.valueChanged.connect(self._on_check)
        self.toggled.connect(self._animate_check)

        self._fxt = 0.0          # 特效進度 0~1（spin 角度 / wiggle / volume）
        self._fa = Anim(self)
        self._fa.valueChanged.connect(self._on_fx)
        self._fa.finished.connect(self._on_fx_done)
        self._nud = 0.0          # 點擊輕推進度
        self._na = Anim(self)
        self._na.valueChanged.connect(self._on_nudge)

    def set_glyph(self, glyph: str):
        if glyph != self._glyph:
            self._glyph = glyph
            self.update()

    def set_metrics(self, glyph_px: int, diameter: int):
        glyph_px = max(1, int(glyph_px))
        diameter = max(1, int(diameter))
        changed = self._px != glyph_px or self.width() != diameter
        self._px = glyph_px
        if self.width() != diameter or self.height() != diameter:
            self.setFixedSize(diameter, diameter)
        if changed:
            self.update()

    def set_accent(self, c: QColor):
        self._accent = QColor(c)
        self.update()

    def set_color_override(self, c: QColor | None):
        self._color_override = QColor(c) if c is not None else None
        self.update()

    def set_extra_opacity(self, value: float):
        self._extra_opacity = max(0.0, min(1.0, float(value)))
        self.update()

    def extra_opacity(self) -> float:
        return self._extra_opacity

    # ---- 特效 ----

    def _on_fx(self, v):
        self._fxt = float(v)
        self.update()

    def _on_fx_done(self):
        if self._fx_kind == "spin" and self._fxt >= 0.999:
            self._fxt = 0.0
            self.update()

    def _on_nudge(self, v):
        self._nud = float(v)
        self.update()

    def _on_check(self, v):
        self._check_t = max(0.0, min(1.0, float(v)))
        self.update()

    def _animate_check(self, checked: bool):
        target = 1.0 if checked else 0.0
        self._check_anim.stop()
        ms = adur(190, 110)
        if not anim_on() or ms <= 0 or not self.isVisible():
            self._on_check(target)
            return
        self._check_anim.setStartValue(self._check_t)
        self._check_anim.setEndValue(target)
        self._check_anim.setDuration(ms)
        self._check_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._check_anim.start()

    def _animate_fx(self, to: float, ms: int, curve, start: float | None = None):
        self._fa.stop()
        if start is not None:
            self._fxt = float(start)
        if not anim_on() or ms <= 0:
            self._on_fx(to)
            self._on_fx_done()
            return
        self._fa.setStartValue(self._fxt)
        self._fa.setEndValue(to)
        self._fa.setDuration(ms)
        self._fa.setEasingCurve(curve)
        self._fa.start()

    def enterEvent(self, e):
        super().enterEvent(e)
        if self._enter_suppressed:
            return
        if not self._fx_kind or not anim_on():
            return
        if self._fx_kind == "gear":
            curve = QEasingCurve(QEasingCurve.OutBack)
            curve.setOvershoot(0.9)
            self._animate_fx(1.0, adur(360, 220), curve)
        elif self._fx_kind == "spin":
            self._animate_fx(1.0, adur(460, 260),
                             QEasingCurve.OutCubic, start=0.0)
        elif self._fx_kind == "volume":
            self._animate_fx(1.0, adur(330, 250), QEasingCurve.Linear,
                             start=0.0)
        else:
            self._animate_fx(1.0, adur(560, 320), QEasingCurve.Linear,
                             start=0.0)

    def leaveEvent(self, e):
        super().leaveEvent(e)
        if self._fx_kind == "gear":
            self._animate_fx(0.0, adur(260, 160), QEasingCurve.OutCubic)

    def mouseReleaseEvent(self, e):
        super().mouseReleaseEvent(e)
        if (self._nudge_dir and anim_on()
                and self.rect().contains(e.position().toPoint())):
            self._na.stop()
            self._na.setStartValue(0.0)
            self._na.setEndValue(1.0)
            self._na.setDuration(adur(240, 150))
            self._na.setEasingCurve(QEasingCurve.OutCubic)
            self._na.start()

    def _fx_angle(self) -> float:
        if self._fx_kind == "gear":
            return self._fxt * 105.0
        if self._fx_kind == "spin":
            return self._fxt * 360.0
        if self._fx_kind == "wiggle":
            return -8.0 * self._hov
        return 0.0

    def _fx_dy(self) -> float:
        if self._fx_kind == "wiggle":
            return -2.0 * self._hov
        if self._fx_kind == "lift":
            return -1.8 * self._hov
        return 0.0

    def _draw_glyph(self) -> str:
        if (self._fx_kind == "volume"
                and self._fa.state() == Anim.Running):
            return self._VOL_SEQ[min(3, int(self._fxt * 4))]
        return self._glyph

    def _draw_centered_glyph(self, p: QPainter, rect: QRectF, glyph: str):
        fm = QFontMetricsF(p.font())
        br = fm.tightBoundingRect(glyph)
        x = rect.center().x() - br.x() - br.width() / 2
        y = rect.center().y() - br.y() - br.height() / 2
        p.drawText(QPointF(x, y), glyph)

    def _glyph_layer(self, glyph: str, col: QColor, rect: QRectF) -> QPixmap:
        pm = QPixmap(self.size())
        pm.fill(Qt.transparent)
        gp = QPainter(pm)
        aa(gp)
        gp.setFont(icon_font(self._px))
        gp.setPen(col)
        self._draw_centered_glyph(gp, rect, glyph)
        gp.end()
        return pm

    # ---- 繪製 ----

    def paintEvent(self, _):
        if self._extra_opacity <= 0.001:
            return
        p = QPainter(self)
        aa(p)
        p.setOpacity(self._extra_opacity)
        dx = 0.0
        if self._na.state() == Anim.Running:
            dx = math.sin(self._nud * math.pi) * 3.0 * self._nudge_dir
        dy = self._fx_dy()
        angle = self._fx_angle()

        checked_t = self._check_t if self.isCheckable() else 0.0
        override = (QColor(self._color_override)
                    if self._color_override is not None else None)
        if not self.isEnabled():
            col = QColor(override) if override is not None else QColor(255, 255, 255)
            col.setAlpha(55)
        else:
            if override is None:
                normal = blend(QColor(255, 255, 255, 150),
                               QColor(255, 255, 255, 245), self._hov)
                active = blend(self._accent.lighter(118),
                               self._accent.lighter(140), self._hov)
            else:
                c0, c1 = QColor(override), QColor(override)
                c0.setAlpha(150)
                c1.setAlpha(245)
                normal = blend(c0, c1, self._hov)
                active = blend(override.lighter(118),
                               override.lighter(140), self._hov)
            col = blend(normal, active, checked_t)
        p.setFont(icon_font(self._px))
        p.setPen(col)
        rect = QRectF(self.rect())
        if self._dot:
            lift = -2.0 * checked_t
            rect = rect.adjusted(0, lift, 0, lift)

        glyph = self._draw_glyph()
        stable_layer = (self._fx_kind in ("gear", "wiggle", "spin")
                        or self._nudge_dir or self._dot)
        dot_drawn = False
        if stable_layer:
            pm = self._glyph_layer(glyph, col, rect)
            p.save()
            self._transform(p, dx=dx, dy=dy, angle=angle)
            p.drawPixmap(0, 0, pm)
            if self._dot and checked_t > 0.01:
                p.setPen(Qt.NoPen)
                dot = self._accent.lighter(118)
                dot.setAlpha(round(255 * checked_t))
                p.setBrush(dot)
                p.drawEllipse(QRectF(self.width() / 2 - 1.5,
                                     self.height() - 5.0, 3.0, 3.0))
                dot_drawn = True
            p.restore()
        else:
            self._transform(p, dx=dx, dy=dy, angle=angle)
            if self._fx_kind == "volume":
                p.drawText(rect, Qt.AlignCenter, glyph)
            else:
                self._draw_centered_glyph(p, rect, glyph)
        if self._dot and checked_t > 0.01 and not dot_drawn:
            p.setPen(Qt.NoPen)
            dot = self._accent.lighter(118)
            dot.setAlpha(round(255 * checked_t))
            p.setBrush(dot)
            p.drawEllipse(QRectF(self.width() / 2 - 1.5,
                                 self.height() - 5.0, 3.0, 3.0))


class PlayButton(_AnimButton):
    """白色圓形播放/暫停主按鈕；圖示自繪、實心填滿。"""

    HOVER_GROW = 0.07

    def __init__(self, size=36, parent=None):
        super().__init__(parent)
        self._playing = False
        self._icon_t = 0.0
        self._icon_anim = Anim(self)
        self._icon_anim.valueChanged.connect(self._on_icon)
        self._d = 0
        self.set_diameter(size)

    def set_diameter(self, size: int):
        size = max(1, int(size))
        self._d = size                       # 圓的直徑
        # hover 放大 + 回彈 overshoot 的留邊，避免圓被 widget 邊界裁切
        pad = max(3, round(size * 0.10))
        self.setFixedSize(size + pad * 2, size + pad * 2)
        self.update()

    def _on_icon(self, v):
        self._icon_t = max(0.0, min(1.0, float(v)))
        self.update()

    def set_playing(self, playing: bool):
        playing = bool(playing)
        if playing == self._playing:
            return
        self._playing = playing
        target = 1.0 if playing else 0.0
        self._icon_anim.stop()
        self._on_icon(target)

    def _draw_play_icon(self, p: QPainter, cx: float, cy: float,
                        s: float, opacity: float, t: float):
        if opacity <= 0.001:
            return
        w, h = 13.0 * s, 14.6 * s
        x0 = cx - w / 2 + 1.4 * s
        tri = QPainterPath()
        tri.moveTo(x0, cy - h / 2)
        tri.lineTo(x0 + w, cy)
        tri.lineTo(x0, cy + h / 2)
        tri.closeSubpath()
        p.save()
        p.setOpacity(opacity)
        p.translate(cx, cy)
        p.rotate(-24.0 * t)
        p.scale(1.0 - 0.18 * t, 1.0 + 0.10 * t)
        p.translate(-cx - 0.8 * s * t, -cy)
        ink = QColor(18, 18, 22)
        pen = QPen(ink, 2.6 * s)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        p.setBrush(ink)
        p.drawPath(tri)
        p.restore()

    def _draw_pause_icon(self, p: QPainter, cx: float, cy: float,
                         s: float, opacity: float, t: float):
        if opacity <= 0.001:
            return
        bw, bh, gap = 4.6 * s, 14.0 * s, 3.4 * s
        p.save()
        p.setOpacity(opacity)
        p.translate(cx, cy)
        p.rotate(18.0 * (1.0 - t))
        p.scale(0.58 + 0.42 * t, 1.18 - 0.18 * t)
        p.translate(-cx + 0.6 * s * (1.0 - t), -cy)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(18, 18, 22))
        for dx in (-(gap / 2 + bw), gap / 2):
            p.drawRoundedRect(QRectF(cx + dx, cy - bh / 2, bw, bh),
                              1.8 * s, 1.8 * s)
        p.restore()

    def paintEvent(self, _):
        p = QPainter(self)
        aa(p)
        self._transform(p)
        m = (self.width() - self._d) / 2 + 1
        r = QRectF(self.rect()).adjusted(m, m, -m, -m)
        bg = QColor(255, 255, 255, round(240 + 15 * self._hov))
        p.setPen(Qt.NoPen)
        p.setBrush(bg)
        p.drawEllipse(r)

        s = self._d / 36.0               # 以 36px 為基準縮放圖示
        cx, cy = self.width() / 2, self.height() / 2
        t = self._icon_t
        self._draw_play_icon(p, cx, cy, s, 1.0 - t, t)
        self._draw_pause_icon(p, cx, cy, s, t, t)


class LaunchButton(_AnimButton):
    """空狀態「啟動 Spotify」膠囊按鈕：hover 變亮、按壓回彈、啟動中轉圈。"""

    HOVER_GROW = 0.045
    PRESS_SCALE = 0.94

    def __init__(self, text: str, px: int, h: int, parent=None):
        super().__init__(parent)
        self._text = text
        self._busy_text = tr("launching")
        self._busy = False
        self._font = ui_font(px, QFont.DemiBold)
        self._h = h
        self._accent = QColor(SPOTIFY_GREEN)
        self._grad: tuple[QColor, QColor] | None = None
        fm = QFontMetricsF(self._font)
        w = max(fm.horizontalAdvance(self._text),
                fm.horizontalAdvance(self._busy_text) + h * 0.62)
        # hover 放大 + 回彈 overshoot 的留邊，避免膠囊被 widget 邊界裁切
        self.pad = max(3, round(h * 0.12))
        self.setFixedSize(round(w + h * 1.4) + self.pad * 2,
                          h + self.pad * 2)
        self._t0 = 0.0               # 轉圈起始時間
        self._spin = QTimer(self)
        self._spin.setTimerType(Qt.PreciseTimer)
        self._spin.setInterval(fps_ms())
        self._spin.timeout.connect(self.update)

    def set_theme(self, c: QColor, grad: tuple[QColor, QColor] | None = None):
        self._accent = QColor(c)
        self._grad = (QColor(grad[0]), QColor(grad[1])) if grad else None
        self.update()

    def set_accent(self, c: QColor):
        self.set_theme(c)

    def set_texts(self, text: str, busy_text: str):
        if text == self._text and busy_text == self._busy_text:
            return
        self._text = text
        self._busy_text = busy_text
        fm = QFontMetricsF(self._font)
        w = max(fm.horizontalAdvance(self._text),
                fm.horizontalAdvance(self._busy_text) + self._h * 0.62)
        self.setFixedSize(round(w + self._h * 1.4) + self.pad * 2,
                          self._h + self.pad * 2)
        self.update()

    def apply_fps(self):
        self._spin.setInterval(fps_ms())

    def set_busy(self, busy: bool):
        if busy == self._busy:
            return
        self._busy = busy
        self.setEnabled(not busy)
        self.setCursor(Qt.ArrowCursor if busy else Qt.PointingHandCursor)
        if busy and anim_on():
            self._t0 = time.monotonic()
            self._spin.start()
        else:
            self._spin.stop()
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        aa(p)
        self._transform(p)
        r = QRectF(self.rect()).adjusted(self.pad, self.pad,
                                         -self.pad, -self.pad)
        base = QColor(self._accent)
        if self._grad:
            g = QLinearGradient(r.topLeft(), r.bottomRight())
            c0, c1 = QColor(self._grad[0]), QColor(self._grad[1])
            if self._busy:
                c0, c1 = c0.darker(112), c1.darker(112)
            else:
                c0 = blend(c0, c0.lighter(116), self._hov)
                c1 = blend(c1, c1.lighter(116), self._hov)
            g.setColorAt(0.0, c0)
            g.setColorAt(1.0, c1)
            bg = g
        else:
            bg = (blend(base, base.darker(122), 0.55) if self._busy
                  else blend(base, base.lighter(118), self._hov))
        p.setPen(Qt.NoPen)
        p.setBrush(bg)
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        ink = blend(QColor(8, 10, 12), base.darker(260), 0.35)
        p.setFont(self._font)
        if not self._busy:
            p.setPen(ink)
            p.drawText(r, Qt.AlignCenter, self._text)
            return
        # 啟動中：旋轉弧 + 文字
        fm = QFontMetricsF(self._font)
        tw = fm.horizontalAdvance(self._busy_text)
        d = r.height() * 0.42
        gap = d * 0.45
        x0 = r.center().x() - (d + gap + tw) / 2
        ang = (((time.monotonic() - self._t0) * 300.0) % 360.0
               if anim_on() else 30.0)
        pen = QPen(ink, max(1.6, d * 0.16))
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawArc(QRectF(x0, r.center().y() - d / 2, d, d),
                  int(-ang * 16), 110 * 16)
        p.setPen(ink)
        p.drawText(QRectF(x0 + d + gap, r.y(), tw + 4, r.height()),
                   Qt.AlignVCenter | Qt.AlignLeft, self._busy_text)


class SeekBar(QWidget):
    """進度條：點擊滑移動畫、hover 圓鈕彈出、波浪/流光樣式。"""

    seeked = Signal(float)
    previewed = Signal(float)

    WAVE_AMP = 0.10       # 波浪振幅（相對高度）
    WAVE_SPEED = 4.8      # 相位速度 rad/s
    GLOW_SPEED = 0.67     # 流光速度 cycle/s
    PAD = 7.0             # 左右留邊，避免圓鈕與圓端蓋被裁切

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pos = 0.0
        self._dur = 0.0
        self._drag = False
        self._target = 0.0           # 拖曳/點擊的目標秒數
        self._chase = None           # 動畫中的顯示秒數（None = 直接用 _pos）
        self._chase_dur = None       # 回起點動畫用舊 duration 呈現比例
        self._hover = False
        self._playing = False
        self._accent = QColor(SPOTIFY_GREEN)
        self._enabled_seek = False
        self._fill_col = QColor(self._accent)
        self._thumb_col = QColor(255, 255, 255)
        self._track_col = QColor(255, 255, 255, 36)

        # 點擊滑移動畫
        self._ca = Anim(self)
        self._ca.valueChanged.connect(self._on_chase)
        self._ca.finished.connect(self._chase_done)

        # hover 圓鈕彈出動畫（0~1 出現比例）
        self._thumb = 0.0
        self._ta = Anim(self)
        self._ta.valueChanged.connect(self._on_thumb)

        # 波浪/流光相位（時間基準，速度與 fps 無關）
        self._style = SETTINGS.get("seek_style", "wave")
        self._phase = 0.0
        self._glow_phase = 0.0
        self._amp = 0.0              # 目前波浪振幅（平滑過渡）
        self._glow = 0.0             # 流光透明度（播放/暫停淡入淡出）
        self._fx_last = time.monotonic()
        self._fx = QTimer(self)
        self._fx.setTimerType(Qt.PreciseTimer)
        self._fx.setInterval(fps_ms())
        self._fx.timeout.connect(self._fx_tick)

        self.setMouseTracking(True)

    # ---- 外部介面 ----

    def set_accent(self, c: QColor):
        self._accent = QColor(c)
        self.update()

    def set_custom_colors(self, fill: QColor, thumb: QColor, track: QColor):
        self._fill_col = QColor(fill)
        self._thumb_col = QColor(thumb)
        self._track_col = QColor(track)
        self.update()

    def set_seek_enabled(self, ok: bool):
        self._enabled_seek = ok
        self.setCursor(Qt.PointingHandCursor if ok else Qt.ArrowCursor)
        self._sync_thumb()

    def set_playing(self, playing: bool):
        if playing == self._playing:
            return
        self._playing = playing
        self._sync_fx()

    def style_changed(self):
        self._style = SETTINGS.get("seek_style", "wave")
        self._sync_fx()
        self._sync_thumb()
        self.update()

    def apply_fps(self):
        self._fx.setInterval(fps_ms())

    def set_data(self, pos: float, dur: float):
        if self._drag:
            return
        had_duration = self._dur > 0
        self._pos, self._dur = pos, dur
        if had_duration != (self._dur > 0):
            self._sync_thumb()
        self.update()

    def animate_reset_to_start(self, old_pos: float | None = None,
                               old_dur: float | None = None):
        dur = old_dur if old_dur and old_dur > 0 else self._dur
        if dur <= 0:
            return
        cur = old_pos if old_pos is not None else (
            self._chase if self._chase is not None else self._pos)
        if cur <= 0.6:
            return
        self._ca.stop()
        self._chase = min(dur, max(0.0, float(cur)))
        self._chase_dur = float(dur)
        ms = adur(260, 140)
        if not anim_on() or ms <= 0:
            self._chase = None
            self._chase_dur = None
            self.update()
            return
        self._ca.setStartValue(self._chase)
        self._ca.setEndValue(0.0)
        self._ca.setDuration(ms)
        self._ca.setEasingCurve(QEasingCurve.OutCubic)
        self._ca.start()

    def animate_from_ratio(self, old_pos: float, old_dur: float,
                           new_pos: float, new_dur: float):
        if old_dur <= 0 or new_dur <= 0:
            return
        old_ratio = min(1.0, max(0.0, float(old_pos) / float(old_dur)))
        start = old_ratio * float(new_dur)
        end = min(float(new_dur), max(0.0, float(new_pos)))
        if abs(start - end) < max(0.45, float(new_dur) * 0.002):
            return
        self._ca.stop()
        self._pos = end
        self._dur = float(new_dur)
        self._chase = start
        self._chase_dur = None
        ms = adur(420, 230)
        if not anim_on() or ms <= 0:
            self._chase = None
            self.update()
            return
        self._ca.setStartValue(start)
        self._ca.setEndValue(end)
        self._ca.setDuration(ms)
        self._ca.setEasingCurve(QEasingCurve.OutCubic)
        self._ca.start()

    def is_dragging(self) -> bool:
        return self._drag

    def visual_state(self) -> dict:
        return {
            "phase": self._phase,
            "glow_phase": self._glow_phase,
            "amp": self._amp,
            "glow": self._glow,
            "thumb": self._thumb,
            "hover": self._hover,
        }

    def restore_visual_state(self, state: dict | None):
        if not state:
            return
        self._phase = float(state.get("phase", self._phase))
        self._glow_phase = float(state.get("glow_phase", self._glow_phase))
        self._amp = float(state.get("amp", self._amp))
        self._glow = float(state.get("glow", self._glow))
        self._thumb = float(state.get("thumb", self._thumb))
        self._hover = bool(state.get("hover", self._hover))
        self._sync_fx()
        self._sync_thumb()
        self.update()

    # ---- 特效計時器 ----

    def _needs_fx(self) -> bool:
        style = self._style
        if not self.isVisible():
            return False
        if self._amp > 0.001 or self._glow > 0.01:
            return True
        if style == "wave":
            return self._playing and anim_on()
        if style == "glow":
            return self._playing and anim_on()
        return False

    def _sync_fx(self):
        if self._needs_fx():
            if not self._fx.isActive():
                self._fx_last = time.monotonic()
                self._fx.start()
        else:
            self._fx.stop()
            self.update()

    def _fx_tick(self):
        now = time.monotonic()
        dt = min(0.1, now - self._fx_last)
        self._fx_last = now
        style = self._style
        wave_target = 1.0 if (style == "wave"
                              and self._playing and anim_on()) else 0.0
        if style == "wave" or self._amp > 0.001:
            rate = 2.6 if wave_target > self._amp else 2.4
            self._amp += (wave_target - self._amp) * min(1.0, dt * rate)
            if abs(self._amp - wave_target) < 0.01:
                self._amp = wave_target
            speed = float(SETTINGS.get("seek_wave_speed", 1.0))
            self._phase += self.WAVE_SPEED * speed * dt
        glow_target = 1.0 if (style == "glow"
                              and self._playing and anim_on()) else 0.0
        if style == "glow" or self._glow > 0.01:
            rate = 4.0 if glow_target > self._glow else 5.0
            self._glow += (glow_target - self._glow) * min(1.0, dt * rate)
            if abs(self._glow - glow_target) < 0.01:
                self._glow = glow_target
            self._glow_phase += self.GLOW_SPEED * dt
        if not self._needs_fx():
            self._fx.stop()
        self.update()

    def showEvent(self, e):
        super().showEvent(e)
        self._sync_fx()

    def hideEvent(self, e):
        super().hideEvent(e)
        self._fx.stop()

    # ---- 點擊滑移 ----

    def _on_chase(self, v):
        self._chase = float(v)
        self.update()

    def _chase_done(self):
        if not self._drag:
            self._chase = None
            self._chase_dur = None
            self.update()

    def _chase_to(self, sec: float, ms: int):
        self._chase_dur = None
        if not anim_on() or ms <= 0:
            self._ca.stop()
            self._chase = sec
            self.update()
            return
        cur = self._chase if self._chase is not None else self._pos
        self._ca.stop()
        self._ca.setStartValue(cur)
        self._ca.setEndValue(sec)
        self._ca.setDuration(ms)
        self._ca.setEasingCurve(QEasingCurve.OutCubic)
        self._ca.start()

    # ---- hover 圓鈕 ----

    def _on_thumb(self, v):
        self._thumb = float(v)
        self.update()

    def _thumb_should_show(self) -> bool:
        if not self._enabled_seek or self._dur <= 0:
            return False
        if self._drag:
            return True
        if SETTINGS.get("seek_thumb", "hover") == "always":
            return True
        return self._hover

    def _sync_thumb(self):
        self._animate_thumb(self._thumb_should_show())

    def _thumb_size_factor(self) -> float:
        return max(0.2, min(
            1.5, float(SETTINGS.get("seek_thumb_size", 1.0))))

    def _thumb_radius(self, visible: float | None = None) -> float:
        h = max(1.0, float(self.height()))
        factor = self._thumb_size_factor()
        base = max(2.0, h * (4.6 / 18.0)) * factor
        drag = h * (1.2 / 18.0) * factor if self._drag else 0.0
        return (base + drag) * (self._thumb if visible is None else visible)

    def _pad(self) -> float:
        h = max(1.0, float(self.height()))
        return max(self.PAD, h * (self.PAD / 18.0))

    def _animate_thumb(self, show: bool):
        target = 1.0 if show else 0.0
        if (self._ta.state() != Anim.Running
                and abs(self._thumb - target) < 0.001):
            self._thumb = target
            self.update()
            return
        if not anim_on():
            self._thumb = target
            self.update()
            return
        self._ta.stop()
        self._ta.setStartValue(self._thumb)
        if show:
            self._ta.setEndValue(target)
            self._ta.setDuration(adur(260, 130))
            if anim_full():
                curve = QEasingCurve(QEasingCurve.OutBack)
                curve.setOvershoot(2.2)
                self._ta.setEasingCurve(curve)
            else:
                self._ta.setEasingCurve(QEasingCurve.OutCubic)
        else:
            self._ta.setEndValue(target)
            self._ta.setDuration(adur(160, 100))
            self._ta.setEasingCurve(QEasingCurve.InCubic)
        self._ta.start()

    # ---- 滑鼠 ----

    def _sec_from_x(self, x: float) -> float:
        pad = self._pad()
        tw = self.width() - pad * 2
        if tw <= 0:
            return 0.0
        r = (x - pad) / tw
        return min(1.0, max(0.0, r)) * self._dur

    def enterEvent(self, e):
        self._hover = True
        self._sync_thumb()

    def leaveEvent(self, e):
        self._hover = False
        self._sync_thumb()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and self._enabled_seek and self._dur > 0:
            self._drag = True
            self._target = self._sec_from_x(e.position().x())
            self._sync_thumb()
            self.previewed.emit(self._target)
            self._chase_to(self._target, adur(240, 130))

    def mouseMoveEvent(self, e):
        if self._drag:
            self._target = self._sec_from_x(e.position().x())
            self.previewed.emit(self._target)
            if self._ca.state() == Anim.Running:
                # 點擊滑移還沒跑完（快速亂點或點了就拖）：先快速收斂到
                # 手指位置而不是瞬移；貼近之後才切回直接跟手
                cur = self._chase if self._chase is not None else self._pos
                tw = self.width() - self.PAD * 2
                gap_px = (abs(self._target - cur) / self._dur * tw
                          if self._dur > 0 else 0.0)
                if gap_px > 2.5:
                    self._chase_to(self._target, adur(110, 70))
                    return
                self._ca.stop()
            self._chase_to(self._target, 0)   # 拖曳直接跟手

    def mouseReleaseEvent(self, e):
        if self._drag:
            self._drag = False
            self._pos = self._target
            self.seeked.emit(self._target)
            if self._ca.state() != Anim.Running:
                self._chase = None
            self._sync_thumb()
            self.update()

    # ---- 繪製 ----

    def _ratio(self) -> float:
        dur = self._chase_dur if self._chase_dur else self._dur
        if dur <= 0:
            return 0.0
        cur = self._chase if self._chase is not None else self._pos
        return min(1.0, max(0.0, cur / dur))

    def _fill_color(self) -> QColor:
        return QColor(self._fill_col)

    def _thumb_color(self) -> QColor:
        return QColor(self._thumb_col)

    def _track_color(self) -> QColor:
        return QColor(self._track_col)

    def _draw_wave_track(self, p: QPainter, w: float, h: float, pad: float,
                         tw: float, cy: float, bar_h: float, ratio: float,
                         fill_w: float, grad, gray: QColor,
                         thumb_color: QColor):
        wave_amp = float(SETTINGS.get("seek_wave_amp", 1.0))
        amp = h * self.WAVE_AMP * wave_amp * self._amp
        k = 2 * math.pi / max(26.0, h * 1.9)

        def wy(x: float) -> float:
            return cy + math.sin(x * k - self._phase) * amp

        def wave_path(x0: float, x1: float) -> QPainterPath:
            path = QPainterPath()
            steps = max(3, math.ceil((x1 - x0) / 0.75))
            for i in range(steps + 1):
                x = x0 + (x1 - x0) * i / steps
                if i == 0:
                    path.moveTo(x, wy(x))
                else:
                    path.lineTo(x, wy(x))
            return path

        def draw_segment(left: float, right: float, pen: QPen):
            if right <= left:
                return
            if right - left <= bar_h:
                x0 = x1 = (left + right) / 2
            else:
                x0 = left + bar_h / 2
                x1 = right - bar_h / 2
            p.setPen(pen)
            p.drawPath(wave_path(x0, x1))

        sample = min(max(pad + bar_h / 2, fill_w - bar_h / 2),
                     pad + tw - bar_h / 2)
        wave_y = wy(sample)
        p.setBrush(Qt.NoBrush)
        if fill_w < pad + tw - 1:
            pen = QPen(gray, bar_h)
            pen.setCapStyle(Qt.RoundCap)
            pen.setJoinStyle(Qt.RoundJoin)
            draw_segment(fill_w, pad + tw, pen)
        if ratio > 0:
            pen = QPen(QBrush(grad), bar_h)
            pen.setCapStyle(Qt.RoundCap)
            pen.setJoinStyle(Qt.RoundJoin)
            draw_segment(pad, max(pad + bar_h, fill_w), pen)
        if ratio > 0 and self._glow > 0.01:
            fw = max(bar_h, tw * ratio)
            strength = max(0.0, min(
                2.0, float(SETTINGS.get("seek_glow_strength", 1.0))))
            alpha = max(0, min(180, round(76 * self._glow * strength)))
            if alpha > 0:
                t = self._glow_phase % 1.4 - 0.2
                band = max(24.0, fw * 0.22)
                bx = pad + t / 1.0 * (fw + band * 2) - band
                left = max(pad, bx - band * 0.42)
                right = min(fill_w, bx + band * 0.42)
                if right > left:
                    pen = QPen(QColor(255, 255, 255, alpha),
                               bar_h * 1.18)
                    pen.setCapStyle(Qt.RoundCap)
                    pen.setJoinStyle(Qt.RoundJoin)
                    draw_segment(left, right, pen)
        if self._thumb > 0.01 and self._dur > 0:
            r = self._thumb_radius()
            p.setPen(Qt.NoPen)
            c = QColor(thumb_color)
            c.setAlpha(round(c.alpha() * min(1.0, self._thumb)))
            p.setBrush(c)
            p.drawEllipse(QPointF(fill_w, wave_y), r, r)

    def _paint_wave_antialiased(self, p: QPainter, w: float, h: float,
                                pad: float, tw: float, cy: float,
                                bar_h: float, ratio: float, fill_w: float,
                                grad, gray: QColor, thumb_color: QColor):
        ss = 2.0
        pm = QPixmap(max(1, math.ceil(w * ss)), max(1, math.ceil(h * ss)))
        pm.fill(Qt.transparent)
        pp = QPainter(pm)
        aa(pp)
        pp.scale(ss, ss)
        self._draw_wave_track(pp, w, h, pad, tw, cy, bar_h,
                              ratio, fill_w, grad, gray, thumb_color)
        pp.end()
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        p.drawPixmap(QRectF(0, 0, w, h), pm, QRectF(pm.rect()))

    def paintEvent(self, _):
        p = QPainter(self)
        aa(p)
        w, h = self.width(), float(self.height())
        pad = self._pad()
        tw = w - pad * 2                 # 軌道實際寬度
        cy = h / 2
        bar_h = max(3.0, h * 0.22)
        style = self._style

        ratio = self._ratio()
        fill_w = pad + tw * ratio        # 填滿端點（絕對 x）
        grad = QLinearGradient(pad, 0, pad + tw, 0)
        fill_color = self._fill_color()
        thumb_color = self._thumb_color()
        grad.setColorAt(0.0, fill_color.lighter(125))
        grad.setColorAt(1.0, fill_color)
        gray = self._track_color()

        wave_y = cy
        wavy = self._amp > 0.001
        if wavy:
            self._paint_wave_antialiased(p, float(w), h, pad, tw, cy,
                                         bar_h, ratio, fill_w, grad, gray,
                                         thumb_color)
            return

        # 底軌
        p.setPen(Qt.NoPen)
        p.setBrush(gray)
        p.drawRoundedRect(QRectF(pad, cy - bar_h / 2, tw, bar_h),
                          bar_h / 2, bar_h / 2)
        if ratio > 0:
            fw = max(bar_h, tw * ratio)
            p.setPen(Qt.NoPen)
            p.setBrush(grad)
            p.drawRoundedRect(
                QRectF(pad, cy - bar_h / 2, fw, bar_h),
                bar_h / 2, bar_h / 2)
            # 流光：在填滿區掃過一道亮帶
            if self._glow > 0.01 and fw > 8:
                t = self._glow_phase % 1.4 - 0.2  # 留一點頭尾停頓
                band = max(24.0, fw * 0.22)
                bx = pad + t / 1.0 * (fw + band * 2) - band
                g2 = QLinearGradient(bx - band, 0, bx + band, 0)
                white = QColor(255, 255, 255, 0)
                strength = max(0.0, min(
                    2.0, float(SETTINGS.get("seek_glow_strength", 1.0))))
                alpha = max(0, min(255, round(
                    110 * self._glow * strength)))
                g2.setColorAt(0.0, white)
                g2.setColorAt(0.5, QColor(255, 255, 255, alpha))
                g2.setColorAt(1.0, white)
                clip = QPainterPath()
                clip.addRoundedRect(
                    QRectF(pad, cy - bar_h / 2, fw, bar_h),
                    bar_h / 2, bar_h / 2)
                p.setPen(Qt.NoPen)
                p.setBrush(g2)
                p.drawPath(clip)

        # hover / 拖曳圓鈕（彈出動畫）
        if self._thumb > 0.01 and self._dur > 0:
            r = self._thumb_radius()
            cx = fill_w
            p.setPen(Qt.NoPen)
            c = QColor(thumb_color)
            c.setAlpha(round(c.alpha() * min(1.0, self._thumb)))
            p.setBrush(c)
            p.drawEllipse(QPointF(cx, wave_y), r, r)
