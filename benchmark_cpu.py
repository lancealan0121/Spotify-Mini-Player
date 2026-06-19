#!/usr/bin/env python
"""Spotify Mini — CPU 效能基準測試。

針對每個可能吃 CPU 的子系統做獨立測量，依耗時排名找出瓶頸。
不依賴實際 Spotify 播放，使用假資料與合成圖片。

用法：
    python benchmark_cpu.py              # 完整測試
    python benchmark_cpu.py --quick      # 快速測試（較少次數）
    python benchmark_cpu.py --frames N   # 自訂連續幀模擬幀數
"""

import math
import os
import statistics
import sys
import time

# 確保 Windows console 能輸出 Unicode
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtCore import QEasingCurve, QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import (QColor, QFont, QFontMetricsF, QImage,
                            QLinearGradient, QPainter, QPainterPath, QPen,
                            QPixmap, QRadialGradient)
from PySide6.QtWidgets import QApplication

from style import (SETTINGS, Anim, aa, apply_settings_data, blend,
                   cover_gradient, dominant_color, load_settings,
                   soft_shadow, theme_color, theme_gradient)

BENCH_DIR = os.path.dirname(os.path.abspath(__file__))
TEST_IMG_PATH = os.path.join(BENCH_DIR, "spt.png")


# ═══════════════════════════════════════════════════════════════
# 工具函式
# ═══════════════════════════════════════════════════════════════

def load_settings_clean():
    """載入設定並關閉動畫/特效避免干擾。"""
    load_settings()
    SETTINGS["anim"] = "off"
    SETTINGS["anim_enabled"] = False
    SETTINGS["fps"] = 240
    SETTINGS["scale"] = 1.0
    SETTINGS["bg_opacity"] = 1.0
    SETTINGS["radius"] = 15
    SETTINGS["theme"] = "auto"
    SETTINGS["auto_theme"] = "gradient"
    SETTINGS["antialias"] = True
    SETTINGS["show_fps"] = False
    SETTINGS["weather_enabled"] = False


def load_test_image(w: int = 300, h: int = 300) -> QImage:
    """載入測試封面圖片。"""
    if os.path.exists(TEST_IMG_PATH):
        img = QImage(TEST_IMG_PATH)
        if not img.isNull():
            return img.scaled(w, h, Qt.KeepAspectRatioByExpanding,
                             Qt.SmoothTransformation)
    img = QImage(w, h, QImage.Format_RGB32)
    p = QPainter(img)
    g = QLinearGradient(0, 0, w, h)
    g.setColorAt(0.0, QColor("#1DB954"))
    g.setColorAt(0.5, QColor("#3D9BE9"))
    g.setColorAt(1.0, QColor("#9B5FD0"))
    p.fillRect(0, 0, w, h, g)
    p.end()
    return img


def fmt_ns(ns: float) -> str:
    if ns < 1000:
        return f"{ns:.1f} ns"
    if ns < 1_000_000:
        return f"{ns / 1000:.1f} µs"
    if ns < 1_000_000_000:
        return f"{ns / 1_000_000:.1f} ms"
    return f"{ns / 1_000_000_000:.2f} s"


def clear_shadow_caches():
    """清除 soft_shadow 的所有快取，確保測量的是真實生成成本。"""
    import style as _s
    _s._SHADOW_CACHE.clear()
    _s._SHADOW_TPL.clear()


def clear_dominant_cache():
    """清除 dominant_color / cover_gradient 快取。"""
    import style as _s
    _s._DOM_CACHE.clear()
    _s._GRAD_CACHE.clear()


# ═══════════════════════════════════════════════════════════════
# 測試案例
# ═══════════════════════════════════════════════════════════════

class BenchCase:
    """單一測試案例。"""
    def __init__(self, name: str, category: str, fn, warmup: int = 5,
                 iters: int = 50, setup: callable = None,
                 teardown: callable = None):
        self.name = name
        self.category = category
        self._fn = fn
        self.warmup = warmup
        self.iters = iters
        self._setup = setup
        self._teardown = teardown
        self.times: list[float] = []
        self.mean = 0.0
        self.median = 0.0
        self.p99 = 0.0
        self.min_val = 0.0
        self.max_val = 0.0
        self.std = 0.0

    def run(self):
        if self._setup:
            self._setup()
        for _ in range(self.warmup):
            self._fn()
        self.times = []
        for _ in range(self.iters):
            if self._setup:
                self._setup()
            t0 = time.perf_counter()
            self._fn()
            self.times.append(time.perf_counter() - t0)
        if self._teardown:
            self._teardown()
        self._calc()
        return self

    def _calc(self):
        self.mean = statistics.mean(self.times)
        self.median = statistics.median(self.times)
        self.p99 = sorted(self.times)[int(len(self.times) * 0.99)]
        self.min_val = min(self.times)
        self.max_val = max(self.times)
        self.std = (statistics.stdev(self.times)
                    if len(self.times) > 1 else 0.0)


class BenchSuite:
    """收集所有測試並依耗時排名輸出。"""

    def __init__(self, app: QApplication):
        self.app = app
        self.tests: list[BenchCase] = []

    def add(self, name: str, category: str, fn, warmup: int = 5,
            iters: int = 50, setup: callable = None,
            teardown: callable = None):
        self.tests.append(
            BenchCase(name, category, fn, warmup, iters, setup, teardown))

    def run_all(self):
        n = len(self.tests)
        print("=" * 80)
        print("  Spotify Mini — CPU Benchmark")
        print(f"  Python {sys.version.split()[0]}  |  "
              f"{self.tests[0].iters if self.tests else 'N/A'} iters/case  "
              f"(warmup: {self.tests[0].warmup if self.tests else 'N/A'})")
        print("=" * 80)

        for i, t in enumerate(self.tests):
            sys.stdout.write(
                f"\r  [{i + 1}/{n}] {t.name:<52}")
            sys.stdout.flush()
            t.run()
        print("\r" + " " * 72 + "\r", end="")

        ranked = sorted(self.tests, key=lambda t: t.mean, reverse=True)
        total = sum(t.mean for t in ranked)

        print("\n  >> 依 CPU 耗時排名（單次呼叫，不含快取命中路徑）\n")
        name_w = max(len(t.name) for t in self.tests) + 2
        print(f"  {'項目':<{name_w}} {'平均':>10}  {'P99':>10}  "
              f"{'最小':>10}  {'佔比':>7}")
        print(f"  {'─' * name_w}  {'─' * 10}  {'─' * 10}  "
              f"{'─' * 10}  {'─' * 7}")

        printed_cats = set()
        for t in ranked:
            if t.category not in printed_cats:
                print(f"\n  --- {t.category} ---")
                printed_cats.add(t.category)
            pct = f"{t.mean / total * 100:.1f}%" if total > 0 else "—"
            print(f"  {t.name:<{name_w}} {fmt_ns(t.mean * 1e9):>10}  "
                  f"{fmt_ns(t.p99 * 1e9):>10}  "
                  f"{fmt_ns(t.min_val * 1e9):>10}  {pct:>7}")

        print(f"\n  {'─' * name_w}  {'─' * 10}  {'─' * 10}  "
              f"{'─' * 10}  {'─' * 7}")
        print(f"  {'合計':<{name_w}} {fmt_ns(total * 1e9):>10}\n")

        # 前 5 大瓶頸
        top5 = ranked[:5]
        print("  >> 前 5 大 CPU 瓶頸（依單次耗時）：")
        for i, t in enumerate(top5):
            print(f"    {i + 1}. [{t.category}] {t.name}")
            print(f"       平均 {fmt_ns(t.mean * 1e9)}  "
                  f"P99 {fmt_ns(t.p99 * 1e9)}  "
                  f"範圍 {fmt_ns(t.min_val * 1e9)}~{fmt_ns(t.max_val * 1e9)}")
        print()

        return ranked


# ═══════════════════════════════════════════════════════════════
# 建構測試套件
# ═══════════════════════════════════════════════════════════════

def build_suite(app: QApplication, card, art_view, marquee, seek_bar,
                weather_layer, img_300, img_600, quick: bool = False
                ) -> BenchSuite:
    suite = BenchSuite(app)
    iters = 15 if quick else 50
    few = 8 if quick else 20

    # ── 封面顏色分析 ──
    def dom_setup():
        clear_dominant_cache()

    suite.add("dominant_color (封面取主色)", "封面顏色分析",
              lambda: dominant_color(img_300),
              warmup=5, iters=iters, setup=dom_setup)

    suite.add("cover_gradient (封面雙色)", "封面顏色分析",
              lambda: cover_gradient(img_300),
              warmup=5, iters=iters, setup=dom_setup)

    # ── 陰影生成（高斯模糊） ──
    def shadow_setup():
        clear_shadow_caches()

    suite.add("soft_shadow (首次生成)", "陰影生成",
              lambda: soft_shadow(400, 148, 15, 18, 150, 1.0),
              warmup=2, iters=few, setup=shadow_setup)

    suite.add("soft_shadow (快取命中)", "陰影生成",
              lambda: soft_shadow(400, 148, 15, 18, 150, 1.0),
              warmup=3, iters=iters)

    # 不同尺寸（強制重建模板）
    def shadow_varied():
        clear_shadow_caches()
        soft_shadow(380, 140, 14, 18, 150, 1.0)

    suite.add("soft_shadow (不同尺寸, 重建模板)", "陰影生成",
              lambda: soft_shadow(380, 140, 14, 18, 150, 1.0),
              warmup=2, iters=few, setup=shadow_setup)

    # ── 卡片背景 pixmap 生成 ──
    def bg_cold():
        card.invalidate_bg()
        card._bg_pixmap()

    suite.add("bg_pixmap (重建, 冷路徑)", "卡片背景",
              bg_cold, warmup=3, iters=few)

    def bg_hot():
        card._bg_pixmap()

    suite.add("bg_pixmap (快取命中)", "卡片背景",
              bg_hot, warmup=5, iters=iters)

    # ── 卡片 paintEvent ──
    def card_paint_cold():
        card.invalidate_bg()
        card.repaint()
        app.processEvents()

    suite.add("card_paint (含 bg 重建)", "卡片背景",
              card_paint_cold, warmup=3, iters=few)

    def card_paint_hot():
        card.repaint()
        app.processEvents()

    suite.add("card_paint (bg 已快取)", "卡片背景",
              card_paint_hot, warmup=5, iters=iters)

    # ── 封面元件 ──
    def art_paint():
        art_view.repaint()
        app.processEvents()

    suite.add("art_paint (cover 模式)", "封面元件",
              art_paint, warmup=5, iters=iters)

    # 換曲過渡
    def art_xfade_setup():
        pm_a = QPixmap.fromImage(img_300.scaled(
            96, 96, Qt.KeepAspectRatioByExpanding,
            Qt.SmoothTransformation))
        art_view.set_pixmap(pm_a, animate=False)
        app.processEvents()

    pm_b = None

    def art_xfade():
        nonlocal pm_b
        if pm_b is None:
            img2 = QImage(300, 300, QImage.Format_RGB32)
            p = QPainter(img2)
            g = QLinearGradient(0, 0, 300, 300)
            g.setColorAt(0.0, QColor("#E8638C"))
            g.setColorAt(1.0, QColor("#904E95"))
            p.fillRect(0, 0, 300, 300, g)
            p.end()
            pm_b = QPixmap.fromImage(img2.scaled(
                96, 96, Qt.KeepAspectRatioByExpanding,
                Qt.SmoothTransformation))
        pm_a = QPixmap.fromImage(img_300.scaled(
            96, 96, Qt.KeepAspectRatioByExpanding,
            Qt.SmoothTransformation))
        art_view.set_pixmap(pm_a, animate=False)
        app.processEvents()
        art_view.set_pixmap(pm_b, animate=True)
        app.processEvents()

    suite.add("art_transition (換曲交叉淡化)", "封面元件",
              art_xfade, warmup=2, iters=few, setup=art_xfade_setup)

    # 測試 vinyl 模式 paint（比 cover 模式重很多）
    def art_paint_vinyl():
        art_view.set_mode("vinyl", animate=False)
        art_view.repaint()
        app.processEvents()

    suite.add("art_paint (vinyl 模式)", "封面元件",
              art_paint_vinyl, warmup=3, iters=few,
              setup=lambda: art_view.set_mode("cover", animate=False))

    # ── 跑馬燈 ──
    def marquee_paint():
        marquee.setText(
            "Bohemian Rhapsody - Queen (Live Aid 1985)", animate=False)
        marquee.repaint()
        app.processEvents()

    suite.add("marquee_paint (靜態文字)", "跑馬燈文字",
              marquee_paint, warmup=5, iters=iters)

    def marquee_transition():
        marquee.setText("Stairway to Heaven - Led Zeppelin",
                       animate=False)
        app.processEvents()
        marquee.setText(
            "Hotel California - Eagles (Hell Freezes Over)",
            animate=True)
        app.processEvents()

    suite.add("marquee_transition (換曲文字動畫)", "跑馬燈文字",
              marquee_transition, warmup=2, iters=few)

    # ── 進度條 ──
    def seek_wave():
        SETTINGS["seek_style"] = "wave"
        seek_bar.repaint()
        app.processEvents()

    suite.add("seek_paint (wave 波浪)", "進度條",
              seek_wave, warmup=5, iters=iters)

    def seek_glow():
        SETTINGS["seek_style"] = "glow"
        seek_bar.repaint()
        app.processEvents()

    suite.add("seek_paint (glow 流光)", "進度條",
              seek_glow, warmup=5, iters=iters)

    SETTINGS["seek_style"] = "wave"

    # ── 天氣特效 ──
    def weather_setup():
        SETTINGS["weather_enabled"] = True
        SETTINGS["rain_enabled"] = True
        SETTINGS["rain_intensity"] = 0.55
        weather_layer._sync_drop_count()
        weather_layer._last = time.monotonic()
        # 跑幾次 tick 讓它穩定
        for _ in range(3):
            weather_layer._tick()

    def weather_teardown():
        SETTINGS["weather_enabled"] = False
        SETTINGS["rain_enabled"] = False

    suite.add("weather_tick (粒子物理更新)", "天氣特效",
              lambda: weather_layer._tick(),
              warmup=5, iters=iters,
              setup=weather_setup, teardown=weather_teardown)

    suite.add("weather_paint (雨天繪製)", "天氣特效",
              lambda: (weather_layer.repaint(), app.processEvents()),
              warmup=3, iters=few,
              setup=weather_setup, teardown=weather_teardown)

    # ── Qt 繪圖基礎操作（用來建立 baseline） ──
    suite.add("QPainter 純文字繪製", "Qt 繪圖基礎",
              lambda: _bench_text(), warmup=10, iters=iters * 2)

    suite.add("QPainter 圓角 clip + 漸層", "Qt 繪圖基礎",
              lambda: _bench_clip_gradient(), warmup=10, iters=iters)

    from PySide6.QtWidgets import QGraphicsBlurEffect, QGraphicsScene

    def bench_blur():
        src = QPixmap(100, 100)
        src.fill(Qt.transparent)
        p = QPainter(src)
        p.setRenderHint(QPainter.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, 100, 100), 15, 15)
        p.fillPath(path, QColor(0, 0, 0, 150))
        p.end()
        scene = QGraphicsScene()
        item = scene.addPixmap(src)
        eff = QGraphicsBlurEffect()
        eff.setBlurRadius(18)
        item.setGraphicsEffect(eff)
        out = QPixmap(136, 136)
        out.fill(Qt.transparent)
        p = QPainter(out)
        scene.render(p, QRectF(0, 0, 136, 136),
                    QRectF(-18, -18, 136, 136))
        p.end()

    suite.add("QGraphicsBlurEffect (高斯模糊)", "Qt 繪圖基礎",
              bench_blur, warmup=3, iters=few)

    def bench_pixmap_scale():
        pm = QPixmap.fromImage(img_600)
        pm.scaled(96, 96, Qt.KeepAspectRatioByExpanding,
                 Qt.SmoothTransformation)

    suite.add("QPixmap.scaled (平滑縮放)", "Qt 繪圖基礎",
              bench_pixmap_scale, warmup=5, iters=iters)

    # ── 動畫系統 ──
    suite.add("blend (顏色內插)", "動畫系統",
              lambda: blend(QColor("#1DB954"), QColor("#3D9BE9"), 0.5),
              warmup=10, iters=iters * 3)

    def bench_anim_step():
        a = Anim()
        a.setStartValue(0.0)
        a.setEndValue(1.0)
        a.setDuration(300)
        a.setEasingCurve(QEasingCurve.OutCubic)
        a._t0 = time.monotonic() - 0.15
        a._running = True
        a._step(time.monotonic())

    suite.add("Anim._step (數值動畫更新)", "動畫系統",
              bench_anim_step, warmup=10, iters=iters * 2)

    # ── 字體度量 ──
    fm = QFontMetricsF(QFont("Arial", 14))

    suite.add("QFontMetricsF.horizontalAdvance", "Qt 繪圖基礎",
              lambda: fm.horizontalAdvance(
                  "Bohemian Rhapsody - Queen"),
              warmup=10, iters=iters * 3)

    # ── bg_target 邏輯運算 ──
    suite.add("bg_target (背景色計算)", "卡片背景",
              lambda: card._bg_target(QColor("#1DB954")),
              warmup=10, iters=iters * 3)

    return suite


def _bench_text():
    pm = QPixmap(200, 30)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.TextAntialiasing, True)
    p.setFont(QFont("Arial", 14))
    p.setPen(QColor(255, 255, 255, 242))
    p.drawText(QRectF(0, 0, 200, 30), Qt.AlignLeft | Qt.AlignVCenter,
               "Bohemian Rhapsody")
    p.end()


def _bench_clip_gradient():
    pm = QPixmap(400, 148)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    path = QPainterPath()
    path.addRoundedRect(QRectF(0, 0, 400, 148), 15, 15)
    p.setClipPath(path)
    g = QLinearGradient(0, 0, 400, 148)
    g.setColorAt(0.0, QColor(30, 30, 40))
    g.setColorAt(1.0, QColor(20, 20, 30))
    p.fillPath(path, g)
    p.end()


# ═══════════════════════════════════════════════════════════════
# 連續幀模擬
# ═══════════════════════════════════════════════════════════════

class FrameSim:
    """模擬連續幀渲染，測量真實場景下的幀耗時分布。"""

    def __init__(self, card, marquee, seek_bar, weather_layer):
        self.card = card
        self.marquee = marquee
        self.seek_bar = seek_bar
        self.weather = weather_layer
        self.app = QApplication.instance()

    def run(self, frames: int = 500, with_weather: bool = False,
            label: str = "") -> dict:
        card = self.card
        # 確保已快取背景（熱路徑）
        card.invalidate_bg()
        card._bg_pixmap()

        self.marquee.setText(
            "Bohemian Rhapsody - Queen", animate=False)
        self.seek_bar.set_data(85.0, 245.0)

        weather_enabled = with_weather
        if weather_enabled:
            SETTINGS["weather_enabled"] = True
            SETTINGS["rain_enabled"] = True
            SETTINGS["rain_intensity"] = 0.55
            self.weather._sync_drop_count()

        progress = 85.0
        duration = 245.0
        times = []

        print(f"\n  >> 模擬 {frames} 幀連續渲染"
              + (f"（{label}）" if label else "") + "...")

        for i in range(frames):
            t0 = time.perf_counter()

            # 進度條更新（模擬 50ms 間隔）
            if i % 3 == 1:
                progress += 50.0 / 1000.0 * 3  # 3 幀跳一次
                if progress > duration:
                    progress = 0.0
                self.seek_bar.set_data(progress, duration)

            # 天氣物理更新（每幀）
            if weather_enabled:
                self.weather._tick()

            # 完整渲染
            card.repaint()
            self.app.processEvents()

            times.append(time.perf_counter() - t0)

        if weather_enabled:
            SETTINGS["weather_enabled"] = False
            SETTINGS["rain_enabled"] = False

        # 捨棄前 15 幀（冷啟動抖動）
        times = times[15:]
        if not times:
            return {}

        return {
            "frames": len(times),
            "mean": statistics.mean(times),
            "median": statistics.median(times),
            "p99": sorted(times)[int(len(times) * 0.99)],
            "p999": sorted(times)[int(len(times) * 0.999)],
            "min": min(times),
            "max": max(times),
            "std": statistics.stdev(times),
        }


def print_frame_stats(stats: dict, indent: str = "    "):
    if not stats:
        return
    fps_avg = 1.0 / stats["mean"] if stats["mean"] > 0 else 0
    fps_p99 = 1.0 / stats["p99"] if stats["p99"] > 0 else 0
    print(f"{indent}幀數: {stats['frames']}")
    print(f"{indent}平均幀時: {fmt_ns(stats['mean'] * 1e9)}  "
          f"({fps_avg:.0f} fps)")
    print(f"{indent}中位幀時: {fmt_ns(stats['median'] * 1e9)}")
    print(f"{indent}P99 幀時: {fmt_ns(stats['p99'] * 1e9)}  "
          f"({fps_p99:.0f} fps)")
    print(f"{indent}P99.9 幀時: {fmt_ns(stats['p999'] * 1e9)}")
    print(f"{indent}最差幀時: {fmt_ns(stats['max'] * 1e9)}")
    print(f"{indent}幀時 std: {fmt_ns(stats['std'] * 1e9)}")
    print(f"{indent}幀時範圍: {fmt_ns(stats['min'] * 1e9)} ~ "
          f"{fmt_ns(stats['max'] * 1e9)}")


# ═══════════════════════════════════════════════════════════════
# 設定面板 benchmark
# ═══════════════════════════════════════════════════════════════

def bench_settings_panel(app: QApplication, quick: bool = False):
    """設定面板是另一個 CPU 重災區：透明視窗 + 上百個自繪控制項。

    量三件事：整面板重繪、accent/主題色動畫每幀成本（會重畫所有可見控制
    項）、各類控制項單次 paint × 數量的貢獻排名。數字每次略有不同，所以
    只輸出實測值與依數據排出的名次，不寫死任何建議文字。
    """
    import collections
    from PySide6.QtWidgets import QWidget
    from settings_ui import SettingsPanel
    import settings_ui

    it = 20 if quick else 50

    print("\n" + "=" * 80)
    print("  設定面板 benchmark（透明視窗 + 自繪控制項）")
    print("=" * 80)

    panel = SettingsPanel(QColor("#1DB954"))
    panel.show()
    app.processEvents()

    def med(fn, n):
        fn()
        app.processEvents()
        ts = []
        for _ in range(n):
            t0 = time.perf_counter()
            fn()
            app.processEvents()
            ts.append(time.perf_counter() - t0)
        return statistics.median(ts)

    # 可見控制項統計
    visible = [w for w in panel.findChildren(QWidget)
               if w.isVisible() and w.width() > 2
               and type(w).__name__ not in ("QWidget", "QLabel")]
    counts = collections.Counter(type(w).__name__ for w in visible)

    print(f"\n  面板尺寸 {panel.width()}×{panel.height()}  |  "
          f"可見自繪控制項 {len(visible)} 個\n")

    # 整面板重繪 / accent 動畫每幀
    full = med(lambda: panel.repaint(), it)

    def accent_frame():
        settings_ui._set_panel_gradient(
            (QColor("#1DB954"), QColor("#3D9BE9")))
        panel._repaint_controls()

    accent = med(accent_frame, it)

    print(f"  {'場景':<34} {'每幀':>10}  {'fps':>7}")
    print(f"  {'─' * 34}  {'─' * 10}  {'─' * 7}")
    print(f"  {'整面板重繪 (panel.repaint)':<34} "
          f"{fmt_ns(full * 1e9):>10}  {1.0 / full:>6.0f}")
    print(f"  {'accent 主題色動畫 (每幀重畫可見控制項)':<34} "
          f"{fmt_ns(accent * 1e9):>10}  {1.0 / accent:>6.0f}")

    # 各類控制項單次 paint × 數量
    reps: dict[str, QWidget] = {}
    for w in visible:
        reps.setdefault(type(w).__name__, w)

    rows = []
    for name, w in reps.items():
        each = med(lambda w=w: w.repaint(), it)
        rows.append((each * counts[name], name, each, counts[name]))
    rows.sort(reverse=True)

    print(f"\n  >> 各類控制項 paint 貢獻（單次 × 可見數量）\n")
    print(f"  {'控制項':<22} {'單次':>10}  {'數量':>5}  {'小計':>10}")
    print(f"  {'─' * 22}  {'─' * 10}  {'─' * 5}  {'─' * 10}")
    for total, name, each, cnt in rows:
        print(f"  {name:<22} {fmt_ns(each * 1e9):>10}  {cnt:>5}  "
              f"{fmt_ns(total * 1e9):>10}")

    panel.hide()
    panel.deleteLater()
    app.processEvents()

    return {"full": full, "accent": accent, "rows": rows,
            "visible": len(visible), "size": (panel.width(), panel.height())}


# ═══════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════

def main():
    quick = "--quick" in sys.argv
    frames = 500
    for i, arg in enumerate(sys.argv):
        if arg == "--frames" and i + 1 < len(sys.argv):
            try:
                frames = int(sys.argv[i + 1])
            except ValueError:
                pass

    app = QApplication(sys.argv)
    load_settings_clean()

    # 測試圖片
    img_300 = load_test_image(300, 300)
    img_600 = load_test_image(600, 600)

    # 建立測試元件
    from main import Card

    card = Card()
    card.setGeometry(0, 0, 400, 148)
    card.show()

    art_view = card.art
    seek_bar = card.seek
    weather = card.rain
    marquee = card.title

    # 設定假封面
    pm = QPixmap.fromImage(img_300.scaled(
        96, 96, Qt.KeepAspectRatioByExpanding,
        Qt.SmoothTransformation))
    art_view.set_pixmap(pm, animate=False)
    app.processEvents()

    card._dom = dominant_color(img_300)
    card._cover_grad = cover_gradient(img_300)
    card._art_img = img_300
    card._art_pm = pm

    # 設定進度條
    seek_bar.set_data(85.0, 245.0)
    seek_bar.setGeometry(50, 108, 300, 18)

    # 設定跑馬燈
    marquee.setText("Bohemian Rhapsody - Queen", animate=False)

    # 確保背景已快取
    card.invalidate_bg()
    card._bg_pixmap()
    app.processEvents()

    # ── 獨立元件 benchmark ──
    suite = build_suite(app, card, art_view, marquee, seek_bar,
                        weather, img_300, img_600, quick)
    ranked = suite.run_all()

    # ── 連續幀模擬 ──
    print("=" * 80)
    print("  連續幀渲染模擬（模擬真實播放場景，背景已快取）")
    print("=" * 80)

    sim = FrameSim(card, marquee, seek_bar, weather)

    stats_no_w = sim.run(frames=frames, with_weather=False, label="無天氣")
    print_frame_stats(stats_no_w)

    stats_w = sim.run(frames=frames, with_weather=True, label="有雨天氣")
    print_frame_stats(stats_w)

    if stats_no_w and stats_w:
        overhead = stats_w["mean"] - stats_no_w["mean"]
        print(f"\n    天氣特效增量: {fmt_ns(overhead * 1e9)}/幀  "
              f"({overhead / stats_no_w['mean'] * 100:+.1f}%)")

    # ── 不同封面模式對比 ──
    print("\n  >> 封面模式對比（連續 200 幀）：")
    for mode in ("cover", "vinyl", "pulse", "audio"):
        art_view.set_mode(mode, animate=False)
        app.processEvents()
        t0 = time.perf_counter()
        for _ in range(200):
            card.repaint()
            app.processEvents()
        dt = (time.perf_counter() - t0) / 200
        label = {"cover": "封面", "vinyl": "唱片", "pulse": "脈衝",
                 "audio": "音訊頻譜"}.get(mode, mode)
        print(f"    {mode} ({label}): {fmt_ns(dt * 1e9)}/幀  "
              f"({1.0 / dt:.0f} fps)")

    # 回復
    art_view.set_mode("cover", animate=False)

    # ── 設定面板 ──
    panel_stats = bench_settings_panel(app, quick)

    # ── 總結（全部由實測數據導出，不寫死建議文字） ──
    print("\n" + "=" * 80)
    print("  >> 總結（依本次實測數據）")
    print("=" * 80)

    top = ranked[:3]
    print("\n  單次最貴操作（冷路徑，設定/換曲時）：")
    for i, t in enumerate(top):
        print(f"    {i + 1}. [{t.category}] {t.name}  "
              f"{fmt_ns(t.mean * 1e9)}")

    if stats_no_w:
        print(f"\n  播放熱路徑：{fmt_ns(stats_no_w['mean'] * 1e9)}/幀  "
              f"(~{1.0 / stats_no_w['mean']:.0f} fps)  "
              f"P99 {fmt_ns(stats_no_w['p99'] * 1e9)}")

    if panel_stats:
        worst = panel_stats["rows"][0] if panel_stats["rows"] else None
        print(f"\n  設定面板：整面板重繪 {fmt_ns(panel_stats['full'] * 1e9)}"
              f" (~{1.0 / panel_stats['full']:.0f} fps)  |  "
              f"accent 動畫 {fmt_ns(panel_stats['accent'] * 1e9)}/幀"
              f" (~{1.0 / panel_stats['accent']:.0f} fps)")
        if worst:
            print(f"  面板 paint 最大貢獻：{worst[1]} ×{worst[3]} = "
                  f"{fmt_ns(worst[0] * 1e9)}")
        print("  注意：透明視窗每次 repaint 含 backing-store/DWM flush，"
              "單控制項數百 µs 多為此開銷，非繪圖本身。")

    # 清理
    card.hide()
    card.deleteLater()
    app.processEvents()
    return 0


if __name__ == "__main__":
    sys.exit(main())
