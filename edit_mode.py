"""編輯模式：版面提示框、元件庫、淡化動畫與複製元件。"""

import time

from PySide6.QtCore import QEasingCurve, QPoint, QPointF, QRectF, QSizeF, Qt
from PySide6.QtCore import QTimer
from PySide6.QtGui import (QColor, QFont, QGuiApplication, QPainter,
                           QPainterPath, QPen, QPixmap)
from PySide6.QtWidgets import QWidget

from style import (GLYPH_EDIT, SETTINGS, Anim, S, aa, adur, anim_on,
                   fps_ms, icon_font, ui_font)


def _transparent_widget_pixmap(widget: QWidget) -> QPixmap:
    dpr = max(1.0, widget.devicePixelRatioF())
    pm = QPixmap(max(1, round(widget.width() * dpr)),
                 max(1, round(widget.height() * dpr)))
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    try:
        widget.render(p, QPoint(0, 0), widget.rect(),
                      QWidget.RenderFlag.DrawChildren)
    finally:
        p.end()
    return pm


def _unrotated_widget_pixmap(widget: QWidget) -> QPixmap:
    angle_marker = object()
    angle = getattr(widget, "_edit_angle", angle_marker)
    if angle is not angle_marker:
        widget._edit_angle = 0.0
    try:
        return _transparent_widget_pixmap(widget)
    finally:
        if angle is not angle_marker:
            widget._edit_angle = angle


class _EditLayoutOverlay(QWidget):
    """Non-interactive edit guides drawn above the card."""

    def __init__(self, card: "Card"):
        super().__init__(card)
        self.card = card
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_NoSystemBackground)

    def paintEvent(self, _):
        op = self.card.edit_overlay_opacity()
        if op <= 0.001:
            return
        p = QPainter(self)
        aa(p)
        p.setOpacity(op)
        self._paint_rotated_visuals(p)
        pen = QPen(QColor(255, 255, 255, 190), max(1, S(1)))
        pen.setStyle(Qt.DashLine)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        for key in self.card.edit_target_keys():
            r = self.card.edit_target_rect(key)
            if not r.isValid() or r.width() < 2 or r.height() < 2:
                continue
            angle = self.card.edit_target_angle(key)
            p.save()
            if abs(angle) >= 0.01:
                c = r.center()
                p.translate(c)
                p.rotate(angle)
                p.translate(-c)
            p.setPen(pen)
            p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5),
                              S(4), S(4))
            sel_op = self.card.edit_selection_opacity(key)
            if sel_op > 0.001:
                p.save()
                p.setOpacity(op * sel_op)
                p.setPen(QPen(QColor(40, 220, 135, 235), max(1, S(1.7))))
                p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5),
                                  S(4), S(4))
                p.restore()
            rr = self.card.edit_rotate_handle_rect(key)
            rop = self.card.edit_rotate_handle_opacity(key)
            if rr.isValid() and rop > 0.001:
                p.save()
                p.setOpacity(op * rop)
                corner = r.topRight()
                node = QPointF(corner.x() + S(7), corner.y() - S(7))
                nr = S(4.3)
                # 連接莖（細、淡）
                p.setPen(QPen(QColor(255, 255, 255, 70), max(1, S(1.0))))
                p.drawLine(corner, node)
                # 圓形把手：白底 + 深色描邊（設計工具風）
                p.setPen(QPen(QColor(0, 0, 0, 95), max(1, S(1.0))))
                p.setBrush(QColor(255, 255, 255, 242))
                p.drawEllipse(node, nr, nr)
                # 內嵌旋轉箭頭弧
                arc = QRectF(node.x() - nr * 0.5, node.y() - nr * 0.5,
                             nr, nr)
                p.setBrush(Qt.NoBrush)
                p.setPen(QPen(QColor(34, 36, 42, 235), max(1, S(0.9)),
                              Qt.SolidLine, Qt.RoundCap))
                ap = QPainterPath()
                ap.arcMoveTo(arc, 50)
                ap.arcTo(arc, 50, 255)
                p.drawPath(ap)
                p.restore()
                p.setPen(pen)
                p.setBrush(Qt.NoBrush)
            hr = self.card.edit_resize_handle_rect(key)
            hop = self.card.edit_resize_handle_opacity(key)
            if hr.isValid() and hop > 0.001:
                p.save()
                p.setOpacity(op * hop)
                # 圓角方形把手：白底深框 + 內部對角抓握紋（設計工具風）
                c = hr.center()
                gs = S(5.0)
                grip = QRectF(c.x() - gs, c.y() - gs, gs * 2, gs * 2)
                p.setPen(QPen(QColor(0, 0, 0, 95), max(1, S(1.0))))
                p.setBrush(QColor(255, 255, 255, 242))
                p.drawRoundedRect(grip, S(1.7), S(1.7))
                p.setPen(QPen(QColor(34, 36, 42, 215), max(1, S(0.9)),
                              Qt.SolidLine, Qt.RoundCap))
                inr = grip.adjusted(S(1.7), S(1.7), -S(1.7), -S(1.7))
                p.drawLine(QPointF(inr.left(), inr.bottom()),
                           QPointF(inr.right(), inr.top()))
                p.drawLine(QPointF(inr.center().x(), inr.bottom()),
                           QPointF(inr.right(), inr.center().y()))
                p.restore()
                p.setPen(pen)
                p.setBrush(Qt.NoBrush)
            p.restore()

    def _paint_rotated_visuals(self, p: QPainter):
        for key in self.card.edit_target_keys():
            if key == "controls":
                continue
            angle = self.card.edit_target_angle(key)
            if abs(angle) < 0.01:
                continue
            for widget in self.card._edit_target_widgets(key):
                if widget is None or widget.isHidden():
                    continue
                if widget.width() <= 0 or widget.height() <= 0:
                    continue
                if widget.__class__.__name__.endswith("Button"):
                    continue
                pm = _unrotated_widget_pixmap(widget)
                if pm.isNull():
                    continue
                top_left = widget.mapTo(self.card, QPoint(0, 0))
                rect = QRectF(
                    QPointF(top_left), QSizeF(widget.width(), widget.height()))
                center = rect.center()
                p.save()
                p.translate(center)
                p.rotate(angle)
                p.translate(-center)
                p.drawPixmap(rect, pm, QRectF(pm.rect()))
                p.restore()


class _EditLibrary(QWidget):
    """Persistent edit-mode toolbox."""

    def __init__(self, card: "Card"):
        super().__init__(card, Qt.Tool | Qt.FramelessWindowHint)
        self.card = card
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setMouseTracking(True)
        self._rows: list[tuple[str, str, str]] = []
        self._rects: dict[str, QRectF] = {}
        self._drag_key: str | None = None
        self._dragging = False
        self._panel_dragging = False
        self._press_pos = QPoint()
        self._press_global = QPoint()
        self._panel_start = QPoint()
        self._placed = False  # 首次放置後鎖定位置，不跟卡片移動
        self._op = 0.0
        self._target = 0.0
        self._scroll = 0.0
        self._target_scroll = 0.0
        self._scroll_velocity = 0.0
        self._scroll_last_t = 0.0
        self._scroll_timer = QTimer(self)
        self._scroll_timer.setTimerType(Qt.PreciseTimer)
        self._scroll_timer.setInterval(fps_ms())
        self._scroll_timer.timeout.connect(self._step_scroll)
        self._collapse = (
            1.0 if SETTINGS.get("edit_library_collapsed", False) else 0.0)
        self._collapse_target = self._collapse
        self._anim = Anim(self)
        self._anim.valueChanged.connect(self._on_op)
        self._anim.finished.connect(self._done)
        self._collapse_anim = Anim(self)
        self._collapse_anim.valueChanged.connect(self._on_collapse)
        self._collapse_anim.finished.connect(self._collapse_done)
        self.hide()

    def _header_h(self) -> int:
        return S(30)

    def _content_top(self) -> int:
        return S(40)

    def _content_bottom_pad(self) -> int:
        return S(6)

    def _content_height(self) -> int:
        row_h = S(23)
        section_h = S(17)
        sections = 1 + (1 if self.card.hidden_edit_keys() else 0)
        return (self._content_top() + section_h * sections
                + row_h * max(1, len(self._rows))
                + self._content_bottom_pad())

    def _expanded_size(self) -> tuple[int, int]:
        max_h = max(S(72), self.card.height() - S(8))
        return S(156), min(self._content_height(), max_h)

    def _collapsed_size(self) -> tuple[int, int]:
        return S(42), S(28)

    def _target_size(self) -> tuple[int, int]:
        ew, eh = self._expanded_size()
        cw, ch = self._collapsed_size()
        t = max(0.0, min(1.0, self._collapse))
        return (round(ew + (cw - ew) * t),
                round(eh + (ch - eh) * t))

    def _card_origin(self) -> QPoint:
        return self.card.mapToGlobal(QPoint(0, 0))

    def _global_from_relative(self, pos: QPoint) -> QPoint:
        return self._card_origin() + pos

    def _default_relative_pos(self, w: int, _h: int) -> QPoint:
        return QPoint(-w - S(8), S(8))

    def _saved_global_pos(self, w: int, h: int) -> QPoint:
        # 完全自由浮動：位置存絕對螢幕座標（gx/gy），與卡片解耦。舊格式
        # （相對卡片的 x/y）或首次開啟則回退到卡片右上角的預設位置。
        raw = SETTINGS.get("edit_library_pos", {})
        if isinstance(raw, dict) and "gx" in raw and "gy" in raw:
            try:
                return QPoint(round(float(raw["gx"])), round(float(raw["gy"])))
            except (TypeError, ValueError):
                pass
        return self._global_from_relative(self._default_relative_pos(w, h))

    def _clamp_global_pos(self, pos: QPoint, w: int, h: int) -> QPoint:
        app = QGuiApplication.instance()
        if app is None:
            return pos
        probe = QPoint(pos.x() + max(1, w // 2), pos.y() + max(1, h // 2))
        screen = QGuiApplication.screenAt(probe) or QGuiApplication.screenAt(pos)
        screen = screen or QGuiApplication.primaryScreen()
        if screen is None:
            return pos
        geo = screen.availableGeometry()
        keep = S(28)
        x = max(geo.left() - w + keep, min(geo.right() - keep, pos.x()))
        y = max(geo.top(), min(geo.bottom() - keep, pos.y()))
        return QPoint(x, y)

    def _store_pos(self):
        # 存絕對螢幕座標，卡片移動不拖著它跑
        p = self.pos()
        SETTINGS["edit_library_pos"] = {"gx": float(p.x()), "gy": float(p.y())}
        self.card.layout_edit_changed.emit()

    def _apply_geometry(self):
        w, h = self._target_size()
        if self._placed:
            # 已放置：當成完全獨立的視窗，維持目前位置——卡片移動/app 縮放
            # 都不把它拉回去；尺寸變化（展開/收合/scale）原地調整，只夾回
            # 螢幕內以防完全跑出畫面。
            pos = self._clamp_global_pos(self.pos(), w, h)
        else:
            pos = self._clamp_global_pos(self._saved_global_pos(w, h), w, h)
            self._placed = True
        self.setGeometry(pos.x(), pos.y(), w, h)
        self._scroll = min(self._scroll, self._max_scroll())
        self._target_scroll = min(self._target_scroll, self._max_scroll())
        if self._max_scroll() <= 1:
            self._stop_smooth_scroll()
        self.update()

    def _max_scroll(self) -> float:
        visible_h = max(1, self.height())
        return max(0.0, float(self._content_height() - visible_h))

    def _clamp_scroll(self, value: float) -> float:
        return max(0.0, min(self._max_scroll(), float(value)))

    def _stop_smooth_scroll(self):
        self._scroll_timer.stop()
        self._scroll_velocity = 0.0
        self._scroll_last_t = 0.0

    def _start_smooth_scroll(self):
        self._scroll_timer.setInterval(fps_ms())
        if not self._scroll_timer.isActive():
            self._scroll_last_t = time.monotonic()
            self._scroll_timer.start()

    def _step_scroll(self):
        max_scroll = self._max_scroll()
        if max_scroll <= 1:
            self._scroll = 0.0
            self._target_scroll = 0.0
            self._stop_smooth_scroll()
            self.update()
            return

        target = self._clamp_scroll(self._target_scroll)
        self._target_scroll = target
        now = time.monotonic()
        if self._scroll_last_t <= 0.0:
            self._scroll_last_t = now
            return
        dt = max(0.001, min(0.05, now - self._scroll_last_t))
        self._scroll_last_t = now

        ms = adur(210, 120)
        if not anim_on() or ms <= 0:
            self._scroll = target
            self._stop_smooth_scroll()
            self.update()
            return

        smooth_time = max(0.045, (ms / 1000.0) * 0.48)
        omega = 2.0 / smooth_time
        x = omega * dt
        decay = 1.0 / (1.0 + x + 0.48 * x * x + 0.235 * x * x * x)
        change = self._scroll - target
        temp = (self._scroll_velocity + omega * change) * dt
        velocity = (self._scroll_velocity - omega * temp) * decay
        new_scroll = target + (change + temp) * decay

        if ((target - self._scroll) > 0.0) == (new_scroll > target):
            new_scroll = target
            velocity = 0.0
        clamped = self._clamp_scroll(new_scroll)
        if abs(clamped - new_scroll) > 0.001:
            velocity = 0.0
        self._scroll = clamped
        self._scroll_velocity = velocity
        self.update()

        if abs(self._target_scroll - self._scroll) < 0.35:
            if abs(self._scroll_velocity) < 8.0:
                self._scroll = self._target_scroll
                self._stop_smooth_scroll()
                self.update()

    def _scroll_to(self, value: float):
        target = self._clamp_scroll(value)
        self._target_scroll = target
        ms = adur(210, 120)
        if not anim_on() or ms <= 0:
            self._stop_smooth_scroll()
            self._scroll = target
            self.update()
            return
        if abs(self._scroll - target) < 0.35:
            self._scroll = target
            self._stop_smooth_scroll()
            self.update()
            return
        self._start_smooth_scroll()

    def _on_op(self, value):
        self._op = max(0.0, min(1.0, float(value)))
        if self._op > 0.001:
            self.show()
            self.raise_()
        self.update()

    def _done(self):
        if self._target <= 0.001:
            self.hide()
        self.update()

    def _on_collapse(self, value):
        self._collapse = max(0.0, min(1.0, float(value)))
        self._apply_geometry()

    def _collapse_done(self):
        SETTINGS["edit_library_collapsed"] = self._collapse_target > 0.5
        self._apply_geometry()
        self.card.layout_edit_changed.emit()

    def sync(self, animate: bool = True):
        self._rows = self.card.edit_library_rows()
        self._scroll = min(self._scroll, self._max_scroll())
        self._apply_geometry()
        target = 1.0 if self.card.layout_edit_mode() else 0.0
        self._target = target
        self._anim.stop()
        if target > 0.0:
            self.show()
            self.raise_()
        ms = adur(170 if target > self._op else 140, 90)
        if not animate or not anim_on() or ms <= 0 or not self.card.isVisible():
            self._on_op(target)
            self._done()
            return
        self._anim.setStartValue(self._op)
        self._anim.setEndValue(target)
        self._anim.setDuration(ms)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.start()

    def _toggle_collapsed(self):
        target = 0.0 if self._collapse_target > 0.5 else 1.0
        self._collapse_target = target
        self._collapse_anim.stop()
        ms = adur(190, 110)
        if not anim_on() or ms <= 0 or not self.isVisible():
            self._on_collapse(target)
            self._collapse_done()
            return
        self._collapse_anim.setStartValue(self._collapse)
        self._collapse_anim.setEndValue(target)
        self._collapse_anim.setDuration(ms)
        self._collapse_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._collapse_anim.start()

    def _header_rect(self) -> QRectF:
        return QRectF(0, 0, self.width(), S(28))

    def _toggle_rect(self) -> QRectF:
        return QRectF(self.width() - S(28), 0, S(28), S(28))

    def _key_at(self, pos: QPointF) -> str | None:
        if self._collapse > 0.65:
            return None
        if pos.y() < self._header_h():
            return None
        for key, rect in self._rects.items():
            if rect.contains(pos):
                return key
        return None

    def paintEvent(self, _):
        if self._op <= 0.001:
            return
        p = QPainter(self)
        aa(p)
        p.setOpacity(self._op)
        bg = QColor(12, 14, 16, 205)
        border = QColor(255, 255, 255, 48)
        p.setPen(QPen(border, 1))
        p.setBrush(bg)
        p.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5),
                          S(7), S(7))

        if self._collapse > 0.65:
            self._rects.clear()
            p.setPen(QColor(255, 255, 255, 205))
            p.setFont(icon_font(S(13)))
            p.drawText(QRectF(self.rect()), Qt.AlignCenter, GLYPH_EDIT)
            return

        header_h = self._header_h()
        title_rect = QRectF(S(8), 0, max(1, self.width() - S(34)), header_h)
        p.setPen(QColor(255, 255, 255, 190))
        p.setFont(ui_font(S(9), QFont.DemiBold))
        p.drawText(title_rect, Qt.AlignVCenter | Qt.AlignLeft, "Library")
        p.setFont(ui_font(S(12), QFont.DemiBold))
        p.drawText(self._toggle_rect(), Qt.AlignCenter,
                   ">" if self._collapse > 0.5 else "<")
        p.setPen(QPen(QColor(255, 255, 255, 24), 1))
        p.drawLine(S(8), header_h - 1, self.width() - S(8), header_h - 1)

        self._rects.clear()
        p.save()
        p.setClipRect(QRectF(0, header_h, self.width(),
                             max(1, self.height() - header_h)))
        y = self._content_top() - round(self._scroll)
        row_h = S(23)
        last_section = ""
        for row_key, section, label in self._rows:
            if section != last_section:
                section_rect = QRectF(S(8), y - S(1),
                                      self.width() - S(16), S(15))
                if (section_rect.bottom() >= header_h
                        and section_rect.top() <= self.height()):
                    p.setPen(QColor(255, 255, 255, 115))
                    p.setFont(ui_font(S(8), QFont.DemiBold))
                    p.drawText(section_rect, Qt.AlignVCenter | Qt.AlignLeft,
                               section)
                y += S(17)
                last_section = section
            r = QRectF(S(6), y, self.width() - S(12), row_h - S(3))
            if r.bottom() < header_h or r.top() > self.height():
                y += row_h
                continue
            self._rects[row_key] = r
            hov = self._drag_key == row_key
            p.setPen(QPen(QColor(255, 255, 255, 34), 1))
            p.setBrush(QColor(255, 255, 255, 36 if hov else 18))
            p.drawRoundedRect(r, S(5), S(5))
            p.setPen(QColor(255, 255, 255, 212))
            p.setFont(ui_font(S(8.5)))
            p.drawText(r.adjusted(S(6), 0, -S(6), 0),
                       Qt.AlignVCenter | Qt.AlignLeft, label)
            y += row_h
        p.restore()

    def wheelEvent(self, e):
        if self._collapse > 0.65:
            return
        delta = e.angleDelta().y()
        if delta == 0:
            return
        self._scroll_to(self._target_scroll - delta / 120.0 * S(42))
        e.accept()

    def mousePressEvent(self, e):
        if e.button() != Qt.LeftButton:
            return
        self._press_pos = e.position().toPoint()
        self._press_global = e.globalPosition().toPoint()
        self._panel_start = QPoint(self.pos())
        if self._toggle_rect().contains(e.position()):
            self._drag_key = "__toggle__"
            e.accept()
            return
        if self._collapse > 0.65 and self._header_rect().contains(e.position()):
            self._panel_dragging = True
            e.accept()
            return
        key = self._key_at(e.position())
        if key is not None:
            self._drag_key = key
            self._dragging = False
            e.accept()
            self.update()
            return
        if self._header_rect().contains(e.position()):
            self._panel_dragging = True
            e.accept()
            return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._panel_dragging:
            delta = e.globalPosition().toPoint() - self._press_global
            if abs(delta.x()) + abs(delta.y()) > S(2):
                w, h = self.width(), self.height()
                pos = self._clamp_global_pos(self._panel_start + delta, w, h)
                self.move(pos)
            e.accept()
            return
        if self._drag_key is not None and self._drag_key != "__toggle__":
            delta = e.position().toPoint() - self._press_pos
            if abs(delta.x()) + abs(delta.y()) > S(4):
                self._dragging = True
            e.accept()
            return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.LeftButton:
            return
        if self._panel_dragging:
            moved = e.globalPosition().toPoint() - self._press_global
            self._panel_dragging = False
            if self._collapse > 0.65 and abs(moved.x()) + abs(moved.y()) <= S(4):
                self._toggle_collapsed()
            else:
                self._store_pos()
            e.accept()
            return
        if self._drag_key == "__toggle__":
            moved = e.globalPosition().toPoint() - self._press_global
            self._drag_key = None
            if abs(moved.x()) + abs(moved.y()) <= S(4):
                self._toggle_collapsed()
            e.accept()
            self.update()
            return
        if self._drag_key is None:
            super().mouseReleaseEvent(e)
            return
        key = self._drag_key
        global_pos = e.globalPosition().toPoint()
        card_pos = QPointF(self.card.mapFromGlobal(global_pos))
        inside = self.card.rect().contains(card_pos.toPoint())
        drop_pos = card_pos if self._dragging and inside else None
        self._drag_key = None
        dragging = self._dragging
        self._dragging = False
        if key.startswith("hidden:"):
            self.card.restore_hidden_edit_key(key[7:], drop_pos)
        else:
            if drop_pos is None and not dragging:
                drop_pos = self.card.edit_library_default_drop_pos()
            self.card.create_edit_library_instance(key, drop_pos)
        e.accept()
        self.update()


class _EditReplica(QWidget):
    """Independent visual element created from the edit library."""

    def __init__(self, card: "Card", source_key: str, parent=None):
        super().__init__(parent or card)
        self.card = card
        self.source_key = source_key
        self._cached_items: list[tuple[QPixmap, QRectF]] = []
        self._cached_bounds = QRectF()
        self._edit_angle = 0.0
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.setAutoFillBackground(False)
        self.setMouseTracking(True)

    def _capture_items(self) -> tuple[list[tuple[QPixmap, QRectF]], QRectF]:
        widgets = self.card._edit_target_widgets(self.source_key)
        items = []
        bounds = QRectF()
        first = True
        for widget in widgets:
            if widget is None or widget is self or widget.isHidden():
                continue
            if widget.width() <= 0 or widget.height() <= 0:
                continue
            pm = _transparent_widget_pixmap(widget)
            if pm.isNull():
                continue
            pos = widget.mapTo(self.card, QPoint(0, 0))
            rect = QRectF(QPointF(pos), QSizeF(widget.width(), widget.height()))
            bounds = QRectF(rect) if first else bounds.united(rect)
            first = False
            items.append((pm, rect))
        if (items and bounds.isValid()
                and bounds.width() > 0 and bounds.height() > 0):
            self._cached_items = items
            self._cached_bounds = QRectF(bounds)
        return self._cached_items, QRectF(self._cached_bounds)

    def set_edit_angle(self, angle: float):
        angle = float(angle or 0.0)
        if abs(angle - self._edit_angle) < 0.01:
            return
        self._edit_angle = angle
        self.update()

    def paintEvent(self, _):
        items, bounds = self._capture_items()
        if (not items or not bounds.isValid()
                or bounds.width() <= 0 or bounds.height() <= 0):
            return
        p = QPainter(self)
        aa(p)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        if abs(self._edit_angle) >= 0.01:
            p.translate(self.width() / 2.0, self.height() / 2.0)
            p.rotate(self._edit_angle)
            p.translate(-self.width() / 2.0, -self.height() / 2.0)
        sx = self.width() / max(1.0, bounds.width())
        sy = self.height() / max(1.0, bounds.height())
        scale = min(sx, sy)
        ox = (self.width() - bounds.width() * scale) / 2.0
        oy = (self.height() - bounds.height() * scale) / 2.0
        for pm, rect in items:
            target = QRectF(ox + (rect.x() - bounds.x()) * scale,
                            oy + (rect.y() - bounds.y()) * scale,
                            rect.width() * scale,
                            rect.height() * scale)
            p.drawPixmap(target, pm, QRectF(pm.rect()))


class _EditGhostLayer(QWidget):
    """Short-lived snapshot layer used by edit hide/restore animations."""

    def __init__(self, card: "Card"):
        super().__init__(card)
        self.card = card
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self._items: list[tuple[QPixmap, QRectF]] = []
        self._op = 0.0
        self._target = 0.0
        self._done_callback = None
        self._anim = Anim(self)
        self._anim.valueChanged.connect(self._on_op)
        self._anim.finished.connect(self._done)
        self.hide()

    def start(self, widgets: tuple[QWidget, ...] | list[QWidget],
              start: float, end: float, done_callback=None,
              animate: bool = True, hide_source: bool = False):
        pending = self._done_callback
        self._done_callback = None
        self._anim.stop()
        if pending is not None:
            pending()
        self._items.clear()
        captured: list[QWidget] = []
        for widget in widgets:
            if widget is None or widget.isHidden():
                continue
            if widget.width() <= 0 or widget.height() <= 0:
                continue
            pm = _transparent_widget_pixmap(widget)
            if pm.isNull():
                continue
            pos = widget.mapTo(self.card, QPoint(0, 0))
            self._items.append((
                pm,
                QRectF(QPointF(pos), QSizeF(widget.width(), widget.height()))
            ))
            captured.append(widget)
        if not self._items:
            if done_callback is not None:
                done_callback()
            self.hide()
            return
        if hide_source:
            for widget in captured:
                widget.hide()
        self.setGeometry(0, 0, self.card.width(), self.card.height())
        self._op = max(0.0, min(1.0, float(start)))
        self._target = max(0.0, min(1.0, float(end)))
        self._done_callback = done_callback
        self.show()
        self.raise_()
        ms = adur(150 if end > start else 130, 80)
        if (not animate or not anim_on() or ms <= 0
                or not self.card.isVisible()):
            self._on_op(self._target)
            self._done()
            return
        self._anim.setStartValue(self._op)
        self._anim.setEndValue(self._target)
        self._anim.setDuration(ms)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.start()

    def _on_op(self, value):
        self._op = max(0.0, min(1.0, float(value)))
        self.update()

    def _done(self):
        callback = self._done_callback
        self._done_callback = None
        self._items.clear()
        self.hide()
        if callback is not None:
            callback()

    def paintEvent(self, _):
        if self._op <= 0.001 or not self._items:
            return
        p = QPainter(self)
        p.setOpacity(self._op)
        for pm, rect in self._items:
            p.drawPixmap(rect, pm, QRectF(pm.rect()))
