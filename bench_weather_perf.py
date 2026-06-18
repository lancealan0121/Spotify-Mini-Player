import ctypes
import gc
import json
import math
import os
import statistics
import subprocess
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QApplication

import main as app_main
from style import (CARD_H, CARD_W, FPS_MAX, FPS_MIN, SETTINGS, S, aa,
                   anim_on, adur)


WIDTH = CARD_W
HEIGHT = CARD_H
WARMUP_FRAMES = 80
MEASURE_FRAMES = 420
FPS_SETTING = 144
SEED = 20260618


def _memory_mb():
    if os.name != "nt":
        return None
    try:
        from ctypes import wintypes

        psapi = ctypes.WinDLL("Psapi.dll", use_last_error=True)
        kernel = ctypes.WinDLL("Kernel32.dll", use_last_error=True)
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        psapi.GetProcessMemoryInfo.argtypes = [
            wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD]
        psapi.GetProcessMemoryInfo.restype = wintypes.BOOL

        class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        counters = PROCESS_MEMORY_COUNTERS()
        counters.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS)
        handle = kernel.GetCurrentProcess()
        ok = psapi.GetProcessMemoryInfo(
            handle, ctypes.byref(counters), counters.cb)
        if not ok:
            return None
        return {
            "working_set_mb": counters.WorkingSetSize / 1024 / 1024,
            "pagefile_mb": counters.PagefileUsage / 1024 / 1024,
        }
    except Exception:
        return None


def _gpu_process_sample():
    if os.name != "nt":
        return None
    ps = (
        "$pidNum = " + str(os.getpid()) + "\n"
        "$ErrorActionPreference='Stop'\n"
        "$samples = (Get-Counter '\\GPU Engine(*)\\Utilization Percentage' "
        "-SampleInterval 1 -MaxSamples 1).CounterSamples\n"
        "$sum = ($samples | Where-Object { $_.InstanceName -match "
        "\"pid_$pidNum\" } | Measure-Object -Property CookedValue -Sum).Sum\n"
        "if ($null -eq $sum) { $sum = 0 }\n"
        "[Console]::Out.Write([Math]::Round($sum, 3))\n"
    )
    try:
        cp = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            capture_output=True, text=True, timeout=4)
        if cp.returncode != 0:
            return None
        raw = cp.stdout.strip()
        return float(raw) if raw else None
    except Exception:
        return None


class LegacyWeatherLayer(app_main._WeatherLayer):
    def apply_fps(self):
        fps = max(FPS_MIN, min(FPS_MAX, int(SETTINGS.get("fps", 60))))
        self._timer.setInterval(
            0 if fps >= FPS_MAX else max(8, round(1000 / fps)))

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
                if (d["y"] - size > h or d["x"] < -w * 0.22
                        or d["x"] > w * 1.22):
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
                       + sway * self._rng.uniform(-0.18, 0.18)) * dt
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

    def _custom_image_pixmap(self, px: float) -> QPixmap | None:
        img = self._load_custom_image()
        if img is None:
            return None
        dpr = max(1.0, self.devicePixelRatioF())
        px_i = max(6, min(42, round(px)))
        dpr_i = max(1, round(dpr * 100))
        key = (self._custom_image_path, px_i, dpr_i)
        pm = self._custom_image_cache.get(key)
        if pm is not None:
            return pm
        side = max(1, round(px_i * dpr))
        pm = QPixmap.fromImage(img).scaled(
            side, side, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        pm.setDevicePixelRatio(dpr)
        if len(self._custom_image_cache) > 48:
            self._custom_image_cache.clear()
        self._custom_image_cache[key] = pm
        return pm

    def _snow_glyph_pixmap(self, glyph: str, px: float) -> QPixmap:
        dpr = max(1.0, self.devicePixelRatioF())
        px_i = max(7, min(30, round(px)))
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
        p.drawText(QRectF(0, 0, logical, logical), Qt.AlignCenter, glyph)
        p.end()
        if len(self._snow_cache) > 96:
            self._snow_cache.clear()
        self._snow_cache[key] = pm
        return pm

    def paintEvent(self, _):
        if self._intensity <= 0.0005 or self._fade <= 0.001:
            return
        p = QPainter(self)
        aa(p)
        p.setOpacity(self._fade)
        p.setClipPath(self._clip_path())
        if self._effect in ("snow", "custom"):
            for d in self._drops:
                depth = d["depth"]
                alpha = round((48 + depth * 106)
                              * (0.38 + self._intensity * 0.66))
                if alpha <= 2:
                    continue
                size = max(0.5, float(d.get("size", 2.0)))
                if self._effect == "custom":
                    pm = self._custom_image_pixmap(
                        max(7.0, min(36.0, size * 5.2)))
                else:
                    pm = None
                if pm is None:
                    glyph_px = max(7.0, min(28.0, size * 4.2))
                    pm = self._snow_glyph_pixmap(str(d.get("glyph", "*")),
                                                 glyph_px)
                dpr = max(1.0, pm.devicePixelRatioF())
                pw, ph = pm.width() / dpr, pm.height() / dpr
                p.save()
                p.translate(d["x"], d["y"])
                p.rotate(float(d.get("angle", 0.0)))
                p.setOpacity(self._fade * min(1.0, alpha / 210.0))
                p.setRenderHint(QPainter.SmoothPixmapTransform, True)
                p.drawPixmap(QPointF(-pw / 2.0, -ph / 2.0), pm)
                p.restore()
            return
        drift_k = math.tan(math.radians(self._direction))
        line_col = QColor(214, 232, 255)
        pen = QPen(line_col, 1.0)
        pen.setCapStyle(Qt.RoundCap)
        hi_col = QColor(255, 255, 255)
        hi_pen = QPen(hi_col, max(0.25, 0.45 * self._thickness_scale))
        for d in self._drops:
            depth = d["depth"]
            alpha = round((26 + depth * 92)
                          * (0.42 + self._intensity * 0.72))
            if alpha <= 2:
                continue
            length = d["len"]
            drift = drift_k * length
            line_col.setAlpha(min(150, alpha))
            pen.setColor(line_col)
            pen.setWidthF((0.45 + depth * 1.15) * self._thickness_scale)
            p.setPen(pen)
            p.drawLine(QPointF(d["x"], d["y"]),
                       QPointF(d["x"] - drift, d["y"] - length))
            if depth > 0.62:
                hi_col.setAlpha(min(70, alpha // 2))
                hi_pen.setColor(hi_col)
                p.setPen(hi_pen)
                p.drawLine(QPointF(d["x"] + 0.8, d["y"] - length * 0.1),
                           QPointF(d["x"] - drift * 0.42,
                                   d["y"] - length * 0.62))
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


def configure(effect, custom_image=False):
    SETTINGS["fps"] = FPS_SETTING
    SETTINGS["antialias"] = True
    SETTINGS["scale"] = 1.0
    SETTINGS["radius"] = 15
    SETTINGS["anim_enabled"] = False
    SETTINGS["anim"] = "off"
    SETTINGS["weather_enabled"] = True
    SETTINGS["weather_effect"] = effect
    SETTINGS["rain_intensity"] = 0.85
    SETTINGS["rain_length"] = 1.0
    SETTINGS["rain_thickness"] = 1.0
    SETTINGS["rain_direction"] = 18.0
    SETTINGS["rain_fall_speed"] = 1.0
    SETTINGS["snow_intensity"] = 0.85
    SETTINGS["snow_size"] = 1.0
    SETTINGS["snow_spin_speed"] = 1.0
    SETTINGS["snow_fall_speed"] = 1.0
    SETTINGS["custom_intensity"] = 0.85
    SETTINGS["custom_size"] = 1.0
    SETTINGS["custom_spin_speed"] = 1.0
    SETTINGS["custom_fall_speed"] = 1.0
    SETTINGS["custom_symbols"] = "A,B"
    SETTINGS["custom_image"] = (
        os.path.join(os.path.dirname(__file__), "spt.png")
        if custom_image else "")


def build_layer(cls, effect, custom_image=False):
    configure(effect, custom_image=custom_image)
    layer = cls()
    layer.setAttribute(Qt.WA_DontShowOnScreen, True)
    layer.resize(WIDTH, HEIGHT)
    layer._rng.seed(SEED)
    layer.apply_settings()
    layer._timer.stop()
    layer._fade_anim.stop()
    layer._fade = 1.0
    layer._active_target = True
    layer._drops.clear()
    layer._splashes.clear()
    layer._rng.seed(SEED)
    layer._sync_drop_count()
    layer.show()
    QApplication.processEvents()
    return layer


def percentile(values, pct):
    if not values:
        return 0.0
    data = sorted(values)
    idx = int(round((len(data) - 1) * pct))
    return data[idx]


def run_case(cls, label, effect, custom_image=False):
    layer = build_layer(cls, effect, custom_image=custom_image)
    image = QImage(WIDTH, HEIGHT, QImage.Format_ARGB32_Premultiplied)
    image.fill(0)
    for _ in range(WARMUP_FRAMES):
        layer._tick()
        image.fill(0)
        layer.render(image)
    gc.collect()
    mem0 = _memory_mb()
    wall0 = time.perf_counter()
    tick_ms = []
    paint_ms = []
    frame_ms = []
    for _ in range(MEASURE_FRAMES):
        start = time.perf_counter()
        t0 = time.perf_counter()
        layer._tick()
        t1 = time.perf_counter()
        image.fill(0)
        layer.render(image)
        t2 = time.perf_counter()
        tick_ms.append((t1 - t0) * 1000.0)
        paint_ms.append((t2 - t1) * 1000.0)
        frame_ms.append((t2 - start) * 1000.0)
    wall1 = time.perf_counter()
    mem1 = _memory_mb()
    interval = max(1, layer._timer.interval())
    effective_fps = 1000.0 / interval
    frame_avg = statistics.fmean(frame_ms)
    estimated_ms_per_sec = frame_avg * effective_fps
    result = {
        "label": label,
        "effect": effect if not custom_image else "custom_image",
        "drops": len(layer._drops),
        "timer_interval_ms": layer._timer.interval(),
        "effective_fps": effective_fps,
        "tick_avg_ms": statistics.fmean(tick_ms),
        "paint_avg_ms": statistics.fmean(paint_ms),
        "frame_avg_ms": frame_avg,
        "frame_p95_ms": percentile(frame_ms, 0.95),
        "frame_p99_ms": percentile(frame_ms, 0.99),
        "estimated_ms_per_sec": estimated_ms_per_sec,
        "estimated_single_core_pct": estimated_ms_per_sec / 10.0,
        "memory_before": mem0,
        "memory_after": mem1,
    }
    if mem0 is not None and mem1 is not None:
        result["memory_delta_mb"] = {
            "working_set_mb": (
                mem1["working_set_mb"] - mem0["working_set_mb"]),
            "pagefile_mb": mem1["pagefile_mb"] - mem0["pagefile_mb"],
        }
    layer.hide()
    layer.deleteLater()
    QApplication.processEvents()
    return result


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    cases = [
        ("rain", False),
        ("snow", False),
        ("custom", False),
        ("custom", True),
    ]
    results = []
    for effect, custom_image in cases:
        results.append(run_case(
            LegacyWeatherLayer, "legacy", effect, custom_image=custom_image))
        results.append(run_case(
            app_main._WeatherLayer, "optimized", effect,
            custom_image=custom_image))
    gpu = _gpu_process_sample()
    print(json.dumps({
        "width": WIDTH,
        "height": HEIGHT,
        "frames": MEASURE_FRAMES,
        "warmup_frames": WARMUP_FRAMES,
        "fps_setting": FPS_SETTING,
        "gpu_process_sample_pct": gpu,
        "results": results,
    }, ensure_ascii=True, indent=2))
    app.quit()


if __name__ == "__main__":
    main()
