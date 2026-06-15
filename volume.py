"""應用程式音量控制：透過 Windows Core Audio（pycaw）操作指定進程
（Spotify / 瀏覽器）的音量，與系統主音量無關。pycaw 不可用時自動停用。
"""
from typing import Optional

try:
    from pycaw.pycaw import AudioUtilities
    _OK = True
except Exception:
    _OK = False

try:
    from pycaw.pycaw import IAudioMeterInformation
    from pycaw.pycaw import EDataFlow, ERole, IMMDeviceEnumerator
    from pycaw.utils import CLSID_MMDeviceEnumerator
    import comtypes
    _METER_OK = _OK
except Exception:
    IAudioMeterInformation = None
    EDataFlow = None
    ERole = None
    IMMDeviceEnumerator = None
    CLSID_MMDeviceEnumerator = None
    comtypes = None
    _METER_OK = False


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
