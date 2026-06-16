"""應用程式音量控制與系統音訊分析。"""
import math
import threading
import time
from ctypes import HRESULT, POINTER, c_ubyte, c_uint32, c_uint64, string_at
from ctypes.wintypes import DWORD
from typing import Optional

try:
    from pycaw.pycaw import AudioUtilities
    _OK = True
except Exception:
    _OK = False

try:
    from pycaw.pycaw import IAudioMeterInformation
    from pycaw.api.audioclient import IAudioClient
    from pycaw.pycaw import EDataFlow, ERole, IMMDeviceEnumerator
    from pycaw.utils import CLSID_MMDeviceEnumerator
    from comtypes import COMMETHOD, GUID, IUnknown
    import comtypes
    _METER_OK = _OK
except Exception:
    IAudioClient = None
    IAudioMeterInformation = None
    EDataFlow = None
    ERole = None
    IMMDeviceEnumerator = None
    CLSID_MMDeviceEnumerator = None
    COMMETHOD = None
    GUID = None
    IUnknown = object
    comtypes = None
    _METER_OK = False

try:
    import numpy as np
    import sounddevice as sd
    _SPECTRUM_OK = True
except Exception:
    np = None
    sd = None
    _SPECTRUM_OK = False


if GUID is not None:
    class IAudioCaptureClient(IUnknown):
        _iid_ = GUID("{C8ADBD64-E71E-48A0-A4DE-185C395CD317}")
        _methods_ = (
            COMMETHOD(
                [],
                HRESULT,
                "GetBuffer",
                (["out"], POINTER(POINTER(c_ubyte)), "ppData"),
                (["out"], POINTER(c_uint32), "pNumFramesToRead"),
                (["out"], POINTER(DWORD), "pdwFlags"),
                (["out"], POINTER(c_uint64), "pu64DevicePosition"),
                (["out"], POINTER(c_uint64), "pu64QPCPosition"),
            ),
            COMMETHOD(
                [], HRESULT, "ReleaseBuffer",
                (["in"], c_uint32, "NumFramesRead")),
            COMMETHOD(
                [], HRESULT, "GetNextPacketSize",
                (["out"], POINTER(c_uint32), "pNumFramesInNextPacket")),
        )
else:
    IAudioCaptureClient = None


class AppVolume:
    """讀寫指定進程所有音訊工作階段的音量與靜音。"""

    def __init__(self):
        self._sessions = []

    @staticmethod
    def available() -> bool:
        return _OK

    def refresh(self, exe_names: list[str]) -> bool:
        """重新列舉指定 exe 的音訊工作階段；回傳是否找到。"""
        self._sessions = []
        if not _OK or not exe_names:
            return False
        targets = {n.lower() for n in exe_names}
        try:
            for s in AudioUtilities.GetAllSessions():
                try:
                    proc = s.Process
                    if proc and proc.name().lower() in targets:
                        self._sessions.append(s.SimpleAudioVolume)
                except Exception:
                    continue
        except Exception:
            return False
        return bool(self._sessions)

    def get(self) -> Optional[float]:
        for v in self._sessions:
            try:
                return float(v.GetMasterVolume())
            except Exception:
                continue
        return None

    def set(self, value: float):
        value = min(1.0, max(0.0, value))
        for v in self._sessions:
            try:
                v.SetMasterVolume(value, None)
            except Exception:
                continue

    def get_mute(self) -> bool:
        for v in self._sessions:
            try:
                return bool(v.GetMute())
            except Exception:
                continue
        return False

    def set_mute(self, mute: bool):
        for v in self._sessions:
            try:
                v.SetMute(1 if mute else 0, None)
            except Exception:
                continue


class AppAudioMeter:
    """讀取指定進程音訊工作階段的目前峰值；不可用時回傳 None。"""

    def __init__(self):
        self._meters = []

    @staticmethod
    def available() -> bool:
        return _METER_OK

    def refresh(self, exe_names: list[str]) -> bool:
        self._meters = []
        if not _METER_OK or IAudioMeterInformation is None or not exe_names:
            return False
        targets = {n.lower() for n in exe_names}
        try:
            for s in AudioUtilities.GetAllSessions():
                try:
                    proc = s.Process
                    if proc and proc.name().lower() in targets:
                        self._meters.append(
                            s._ctl.QueryInterface(IAudioMeterInformation))
                except Exception:
                    continue
        except Exception:
            return False
        return bool(self._meters)

    def peak(self) -> Optional[float]:
        vals = []
        for meter in self._meters:
            try:
                vals.append(float(meter.GetPeakValue()))
            except Exception:
                continue
        if not vals:
            return None
        return max(0.0, min(1.0, max(vals)))


class AppMasterAudioMeter:
    """讀取目前預設輸出裝置的總輸出峰值。"""

    def __init__(self):
        self._meter = None

    @staticmethod
    def available() -> bool:
        return _METER_OK

    def refresh(self) -> bool:
        self._meter = None
        if (not _METER_OK or IAudioMeterInformation is None
                or IMMDeviceEnumerator is None or comtypes is None):
            return False
        try:
            enum = comtypes.CoCreateInstance(
                CLSID_MMDeviceEnumerator, IMMDeviceEnumerator,
                comtypes.CLSCTX_INPROC_SERVER)
            dev = enum.GetDefaultAudioEndpoint(
                EDataFlow.eRender.value, ERole.eMultimedia.value)
            iface = dev.Activate(
                IAudioMeterInformation._iid_, comtypes.CLSCTX_ALL, None)
            self._meter = iface.QueryInterface(IAudioMeterInformation)
            return True
        except Exception:
            self._meter = None
            return False

    def peak(self) -> Optional[float]:
        if self._meter is None and not self.refresh():
            return None
        try:
            return max(0.0, min(1.0, float(self._meter.GetPeakValue())))
        except Exception:
            self._meter = None
            return None


class SystemSpectrumAnalyzer:
    """WASAPI loopback / input fallback 的 64 段對數頻譜分析器。"""

    SAMPLE_RATE = 44100
    FFT_SIZE = 2048
    BAR_COUNT = 64
    ATTACK_TAU = 0.035   # bar 竄起時間常數（秒）：小=反應快、衝擊強
    RELEASE_TAU = 0.22   # bar 回落時間常數（秒）：大=尾巴長、不抖
    PEAK_TAU = 1.2       # 正規化峰值衰減時間常數（秒）：小=動態跟得緊
    SILENCE_HOLD = 0.05  # 多久沒有新樣本流入就當作靜音（秒）：loopback 暫停渲染
                         # 時不送 callback，緩衝會凍結。偵測下限是一個 callback
                         # 間隔（blocksize 512 @ 44.1kHz≈11.6ms），這裡留約 4 倍
                         # 餘裕，播放中不會誤判、暫停時又幾乎無感延遲。
    SILENCE_RELEASE_TAU = 0.07  # 靜音時 bar 專用回落時間常數（秒）：比音樂尾巴
                         # （RELEASE_TAU）快很多，暫停瞬間就俐落縮回，不拖泥帶水。

    def __init__(self):
        self._lock = threading.Lock()
        self._stream = None
        self._native_thread = None
        self._native_stop = threading.Event()
        self._native_ready = threading.Event()
        self._native_started = False
        self._started = False
        self._failed = False
        self._device_label = ""
        self._peak = 1.0
        self._last_bars_t = None
        self._last_write_t = None
        if _SPECTRUM_OK:
            self._buffer = np.zeros(self.SAMPLE_RATE, dtype=np.float32)
            self._write_pos = 0
            self._window = np.hanning(self.FFT_SIZE).astype(np.float32)
            self._smooth = np.zeros(self.BAR_COUNT, dtype=np.float32)
            self._edges = np.geomspace(20.0, 16000.0, self.BAR_COUNT + 1)
            self._freqs = np.fft.rfftfreq(self.FFT_SIZE, 1.0 / self.SAMPLE_RATE)
            self._groups = self._build_groups()
            # 頻率傾斜補償：音樂能量隨頻率遞減（低音遠強於高頻），而全域共用
            # 峰值正規化會讓中高頻被低音壓到不動。對每段中心頻乘遞增增益把
            # 高頻拉回可見量級（只增不減，低音 punch 不動）；clamp 防過曝。
            _fc = np.sqrt(self._edges[:-1] * self._edges[1:])
            self._tilt = np.clip(
                (_fc / 1000.0) ** 0.40, 1.0, 2.6).astype(np.float32)
            # 每個頻帶以「中心頻率對應的小數 bin 位置」取樣，對 rfft 量值做
            # 線性內插。低頻對數頻帶比 bin 還窄時，最低幾帶不再對到同一個
            # bin（值相同會讓最左幾根 bar 黏成一塊），內插出各自不同的值。
            self._band_centers = (
                _fc / (self.SAMPLE_RATE / self.FFT_SIZE)).astype(np.float32)
        else:
            self._buffer = None
            self._write_pos = 0
            self._window = None
            self._smooth = None
            self._edges = None
            self._freqs = None
            self._groups = []
            self._tilt = None
            self._band_centers = None

    @staticmethod
    def available() -> bool:
        return _SPECTRUM_OK

    def _build_groups(self):
        groups = []
        for lo, hi in zip(self._edges[:-1], self._edges[1:]):
            idx = np.where((self._freqs >= lo) & (self._freqs < hi))[0]
            if idx.size == 0:
                nearest = int(np.argmin(np.abs(self._freqs - lo)))
                idx = np.array([nearest])
            groups.append(idx)
        return groups

    def _find_device(self):
        if not _SPECTRUM_OK:
            return None
        try:
            devices = sd.query_devices()
            hostapis = sd.query_hostapis()
        except Exception:
            return None

        wasapi_idx = None
        for idx, api in enumerate(hostapis):
            if "wasapi" in str(api.get("name", "")).lower():
                wasapi_idx = idx
                break

        if wasapi_idx is not None:
            wasapi_extra = None
            try:
                wasapi_extra = sd.WasapiSettings(loopback=True)
            except TypeError:
                pass

            if wasapi_extra is not None:
                try:
                    out_idx = sd.default.device[1]
                    if out_idx is not None and out_idx >= 0:
                        dev = devices[out_idx]
                        if int(dev.get("hostapi", -1)) == wasapi_idx:
                            channels = max(
                                1, min(2, int(dev["max_output_channels"])))
                            return (out_idx, channels, wasapi_extra,
                                    f"WASAPI loopback: {dev['name']}")
                except Exception:
                    pass

                for idx, dev in enumerate(devices):
                    if (int(dev.get("hostapi", -1)) == wasapi_idx
                            and int(dev.get("max_output_channels", 0)) > 0):
                        channels = max(
                            1, min(2, int(dev["max_output_channels"])))
                        return (idx, channels, wasapi_extra,
                                f"WASAPI loopback: {dev['name']}")

        keywords = ("loopback", "stereo mix", "立體聲混音")
        for idx, dev in enumerate(devices):
            name = str(dev.get("name", ""))
            if (int(dev.get("max_input_channels", 0)) > 0
                    and any(k in name.lower() for k in keywords)):
                channels = max(1, min(2, int(dev["max_input_channels"])))
                return idx, channels, None, f"input: {name}"

        return None

    def _audio_callback(self, indata, frames, _time, status):
        if status:
            pass
        if indata is None or frames <= 0:
            return
        try:
            mono = np.asarray(indata, dtype=np.float32)
            if mono.ndim > 1:
                mono = mono.mean(axis=1)
            mono = mono[-len(self._buffer):]
            n = len(mono)
            with self._lock:
                end = self._write_pos + n
                if end <= len(self._buffer):
                    self._buffer[self._write_pos:end] = mono
                else:
                    first = len(self._buffer) - self._write_pos
                    self._buffer[self._write_pos:] = mono[:first]
                    self._buffer[:end % len(self._buffer)] = mono[first:]
                self._write_pos = end % len(self._buffer)
                self._last_write_t = time.monotonic()
        except Exception:
            return

    def _write_samples(self, samples):
        if samples is None:
            return
        try:
            mono = np.asarray(samples, dtype=np.float32)
            if mono.ndim > 1:
                mono = mono.mean(axis=1)
            mono = mono[-len(self._buffer):]
            n = len(mono)
            if n <= 0:
                return
            with self._lock:
                end = self._write_pos + n
                if end <= len(self._buffer):
                    self._buffer[self._write_pos:end] = mono
                else:
                    first = len(self._buffer) - self._write_pos
                    self._buffer[self._write_pos:] = mono[:first]
                    self._buffer[:end % len(self._buffer)] = mono[first:]
                self._write_pos = end % len(self._buffer)
                self._last_write_t = time.monotonic()
        except Exception:
            return

    def _native_loopback_worker(self):
        audio_client = None
        capture = None
        try:
            comtypes.CoInitialize()
            enum = comtypes.CoCreateInstance(
                CLSID_MMDeviceEnumerator, IMMDeviceEnumerator,
                comtypes.CLSCTX_INPROC_SERVER)
            dev = enum.GetDefaultAudioEndpoint(
                EDataFlow.eRender.value, ERole.eMultimedia.value)
            iface = dev.Activate(IAudioClient._iid_, comtypes.CLSCTX_ALL, None)
            audio_client = iface.QueryInterface(IAudioClient)
            mix = audio_client.GetMixFormat()
            fmt = mix.contents
            channels = max(1, int(fmt.nChannels))
            bits = int(fmt.wBitsPerSample)
            block_align = max(1, int(fmt.nBlockAlign))
            tag = int(fmt.wFormatTag)
            audio_client.Initialize(
                0, 0x00020000, 10_000_000, 0, mix, None)
            service = audio_client.GetService(IAudioCaptureClient._iid_)
            capture = service.QueryInterface(IAudioCaptureClient)
            audio_client.Start()
            self._native_started = True
            self._device_label = "WASAPI native loopback"
            self._native_ready.set()

            while not self._native_stop.is_set():
                packet = capture.GetNextPacketSize()
                if packet <= 0:
                    time.sleep(0.006)
                    continue
                while packet > 0:
                    data, frames, flags, _pos, _qpc = capture.GetBuffer()
                    try:
                        if frames > 0 and not (int(flags) & 0x2):
                            raw = string_at(data, int(frames) * block_align)
                            if bits == 32 and tag in (3, 65534):
                                arr = np.frombuffer(raw, dtype=np.float32)
                            elif bits == 32:
                                arr = (np.frombuffer(raw, dtype=np.int32)
                                       .astype(np.float32) / 2147483648.0)
                            elif bits == 16:
                                arr = (np.frombuffer(raw, dtype=np.int16)
                                       .astype(np.float32) / 32768.0)
                            else:
                                arr = np.zeros(0, dtype=np.float32)
                            if arr.size:
                                self._write_samples(arr.reshape(-1, channels))
                    finally:
                        capture.ReleaseBuffer(frames)
                    packet = capture.GetNextPacketSize()
        except Exception:
            self._native_started = False
            self._native_ready.set()
        finally:
            if audio_client is not None:
                try:
                    audio_client.Stop()
                except Exception:
                    pass
            try:
                comtypes.CoUninitialize()
            except Exception:
                pass

    def _start_native_loopback(self) -> bool:
        if (not _SPECTRUM_OK or not _METER_OK or IAudioClient is None
                or IAudioCaptureClient is None or comtypes is None):
            return False
        self._native_stop.clear()
        self._native_ready.clear()
        self._native_started = False
        self._native_thread = threading.Thread(
            target=self._native_loopback_worker, daemon=True)
        self._native_thread.start()
        self._native_ready.wait(0.8)
        return self._native_started

    def start(self) -> bool:
        if self._started:
            return True
        if self._failed or not _SPECTRUM_OK:
            return False
        found = self._find_device()
        if found is None:
            if self._start_native_loopback():
                self._started = True
                return True
            self._failed = True
            return False
        device, channels, extra_settings, label = found
        try:
            self._stream = sd.InputStream(
                samplerate=self.SAMPLE_RATE,
                blocksize=512,
                dtype="float32",
                device=device,
                channels=channels,
                callback=self._audio_callback,
                extra_settings=extra_settings)
            self._stream.start()
            self._device_label = label
            self._started = True
            return True
        except Exception:
            self._stream = None
            self._failed = True
            return False

    def stop(self):
        stream = self._stream
        self._stream = None
        self._native_stop.set()
        thread = self._native_thread
        self._native_thread = None
        self._started = False
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass
        if thread is not None and thread.is_alive():
            thread.join(timeout=0.5)

    def bars(self) -> Optional[list[float]]:
        if not self.start():
            return None
        now = time.monotonic()
        last_write = self._last_write_t
        # loopback 在沒有音訊渲染時不會送 callback，環形緩衝會凍結在最後一段
        # 音樂。若資料停止流入超過 SILENCE_HOLD 就當作靜音，讓 bar 依 release
        # 時間常數平滑回落歸零，而不是回傳凍結的舊頻譜（卡住不縮回封面）。
        silent = last_write is None or (now - last_write) > self.SILENCE_HOLD
        last = self._last_bars_t
        self._last_bars_t = now
        dt = 0.016 if last is None else min(0.1, max(1e-4, now - last))
        if silent:
            k_dn = 1.0 - math.exp(-dt / self.SILENCE_RELEASE_TAU)
            self._smooth += (0.0 - self._smooth) * k_dn
            self._smooth[self._smooth < 1e-4] = 0.0
            # 峰值同步衰減，下次有音樂時才能立刻重新正規化到滿幅。
            self._peak = max(self._peak * math.exp(-dt / self.PEAK_TAU), 1e-6)
            return self._smooth.tolist()
        with self._lock:
            pos = self._write_pos
            if pos >= self.FFT_SIZE:
                samples = self._buffer[pos - self.FFT_SIZE:pos].copy()
            else:
                samples = np.concatenate((
                    self._buffer[pos - self.FFT_SIZE:],
                    self._buffer[:pos])).copy()
        samples -= float(np.mean(samples))
        spectrum = np.abs(np.fft.rfft(samples * self._window))
        # 頻帶中心對小數 bin 做線性內插（向量化），低頻不再黏成同值
        raw = np.interp(self._band_centers,
                        np.arange(spectrum.size), spectrum).astype(np.float32)
        raw *= self._tilt
        raw = np.log1p(raw * 8.0)

        mx = float(raw.max()) if raw.size else 0.0
        self._peak = max(self._peak * math.exp(-dt / self.PEAK_TAU), mx, 1e-6)
        norm = np.clip(raw / self._peak, 0.0, 1.0)

        # attack 快、release 慢的非對稱平滑（時間基準，與 fps 無關）：
        # bar 隨鼓點瞬間竄起、回落時拖尾巴，做出 Wallpaper Engine 式的彈跳。
        k_up = 1.0 - math.exp(-dt / self.ATTACK_TAU)
        k_dn = 1.0 - math.exp(-dt / self.RELEASE_TAU)
        k = np.where(norm > self._smooth, k_up, k_dn).astype(np.float32)
        self._smooth += (norm - self._smooth) * k
        return self._smooth.tolist()
