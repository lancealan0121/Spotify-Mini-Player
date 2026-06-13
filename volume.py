"""應用程式音量控制：透過 Windows Core Audio（pycaw）操作指定進程
（Spotify / 瀏覽器）的音量，與系統主音量無關。pycaw 不可用時自動停用。
"""
from typing import Optional

try:
    from pycaw.pycaw import AudioUtilities
    _OK = True
except Exception:
    _OK = False


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
