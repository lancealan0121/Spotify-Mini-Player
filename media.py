"""SMTC 橋接層：透過 Windows 媒體傳輸控制讀取/遙控媒體來源，無需任何該死的要錢 API。
所有 WinRT 呼叫在專屬 asyncio 執行緒上執行，UI 透過 Qt Signal 接收狀態。
"""

import asyncio
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from PySide6.QtCore import QObject, Signal
from winrt.windows.media import MediaPlaybackAutoRepeatMode
from winrt.windows.media.control import (
    GlobalSystemMediaTransportControlsSessionManager as MediaManager,
)
from winrt.windows.media.control import (
    GlobalSystemMediaTransportControlsSessionPlaybackStatus as PlaybackStatus,
)
from winrt.windows.storage.streams import Buffer, DataReader, InputStreamOptions

from style import BROWSER_TOKENS, SETTINGS


@dataclass
class TrackState:
    found: bool = False
    title: str = ""
    artist: str = ""
    album: str = ""
    app_id: str = ""  # SMTC source app user model id
    playing: bool = False
    position: float = 0.0  # 秒（讀取當下的值，UI 自行內插）
    duration: float = 0.0
    read_at: float = 0.0  # time.monotonic() 的讀取時間點
    can_seek: bool = False
    can_next: bool = True
    can_prev: bool = True
    shuffle: Optional[bool] = None
    repeat: Optional[int] = None  # 0=關 1=單曲 2=列表

    @property
    def key(self):
        return (self.title, self.artist, self.album, self.app_id)


def _is_playing(s) -> bool:
    try:
        return s.get_playback_info().playback_status == PlaybackStatus.PLAYING
    except Exception:
        return False


def _pick_session(sessions):
    """依 SETTINGS["source"] 模式挑出要顯示的 session。"""
    mode = SETTINGS.get("source", "spotify")

    def app_id(s):
        return (s.source_app_user_model_id or "").lower()

    spotify = [s for s in sessions if "spotify" in app_id(s)]
    if mode == "spotify":
        for s in spotify:
            if _is_playing(s):
                return s
        return spotify[0] if spotify else None

    if mode == "browser":
        pool = [s for s in sessions if any(t in app_id(s) for t in BROWSER_TOKENS)]
        if not pool:  # 未知瀏覽器：退用非 Spotify 來源
            pool = [s for s in sessions if "spotify" not in app_id(s)]
    else:  # any
        pool = list(sessions)

    if not pool:
        return None
    for s in pool:  # 優先挑正在播放的
        if _is_playing(s):
            return s
    return pool[0]


class MediaBridge(QObject):
    state_changed = Signal(object)  # TrackState
    art_changed = Signal(bytes)  # 新曲目的封面原始影像資料
    art_missing = Signal()  # 新曲目但沒有封面

    POLL = 1.0
    POLL_IDLE = 3.0  # 無 session 一段時間後放寬輪詢，省 CPU
    IDLE_AFTER = 8  # 連續落空次數門檻
    THUMB_CAP = 12  # 封面 LRU 上限

    def __init__(self, parent=None):
        super().__init__(parent)
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._session = None
        self._last_key = None
        self._wake: Optional[asyncio.Event] = None
        self._misses = 0  # 連續沒挑到 session 的次數（asyncio 執行緒專用）
        self._thumbs: OrderedDict = OrderedDict()  # track key → 封面 bytes

    def start(self):
        self._thread.start()

    def poke(self):
        """要求立即重輪詢（來源切換、啟動 Spotify 時用）。"""

        def _set():
            self._misses = 0
            if self._wake is not None:
                self._wake.set()

        self._loop.call_soon_threadsafe(_set)

    # ---- 控制指令（UI 執行緒呼叫，實際執行排到 asyncio 執行緒） ----

    def toggle_play(self):
        self._call(lambda s: s.try_toggle_play_pause_async())

    def next_track(self):
        self._call(lambda s: s.try_skip_next_async())

    def prev_track(self):
        self._call(lambda s: s.try_skip_previous_async())

    def seek(self, seconds: float):
        ticks = int(max(0.0, seconds) * 10_000_000)
        self._call(lambda s: s.try_change_playback_position_async(ticks))

    def set_shuffle(self, active: bool):
        self._call(lambda s: s.try_change_shuffle_active_async(active))

    def set_repeat(self, mode: int):
        rm = MediaPlaybackAutoRepeatMode(mode)
        self._call(lambda s: s.try_change_auto_repeat_mode_async(rm))

    def _call(self, fn):
        self._loop.call_soon_threadsafe(lambda: self._loop.create_task(self._exec(fn)))

    async def _exec(self, fn):
        try:
            s = self._session
            if s is not None:
                await fn(s)
        except Exception:
            pass
        await asyncio.sleep(0.25)  # 給播放器反應時間再重讀狀態
        if self._wake is not None:
            self._wake.set()

    # ---- 背景輪詢 ----

    def _run(self):
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._main())

    async def _main(self):
        self._wake = asyncio.Event()
        mgr = await MediaManager.request_async()
        while True:
            try:
                await self._poll(mgr)
            except Exception:
                self._session = None
                self._last_key = None
                self._misses += 1
                self.state_changed.emit(TrackState())
            timeout = self.POLL_IDLE if self._misses >= self.IDLE_AFTER else self.POLL
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=timeout)
            except asyncio.TimeoutError:
                pass
            self._wake.clear()

    async def _poll(self, mgr):
        session = _pick_session(list(mgr.get_sessions()))
        self._session = session

        if session is None:
            self._last_key = None
            self._misses += 1
            self.state_changed.emit(TrackState())
            return
        self._misses = 0

        info = await session.try_get_media_properties_async()
        pb = session.get_playback_info()
        tl = session.get_timeline_properties()
        ctl = pb.controls
        playing = pb.playback_status == PlaybackStatus.PLAYING

        # Spotify 的 position 常數秒才更新一次；播放中補上經過時間，
        # 避免 UI 端位置鋸齒（亂跳/回溯）。
        pos = tl.position.total_seconds()
        dur = tl.end_time.total_seconds()
        if playing:
            try:
                elapsed = (
                    datetime.now(timezone.utc) - tl.last_updated_time
                ).total_seconds()
                if 0.0 < elapsed < 3600.0:
                    pos += elapsed
            except (TypeError, OSError, OverflowError):
                pass
        if dur > 0:
            pos = min(pos, dur)

        st = TrackState(
            found=True,
            title=info.title or "",
            artist=info.artist or "",
            album=info.album_title or "",
            app_id=session.source_app_user_model_id or "",
            playing=playing,
            position=pos,
            duration=dur,
            read_at=time.monotonic(),
            can_seek=ctl.is_playback_position_enabled,
            can_next=ctl.is_next_enabled,
            can_prev=ctl.is_previous_enabled,
            shuffle=pb.is_shuffle_active,
            repeat=(
                int(pb.auto_repeat_mode) if pb.auto_repeat_mode is not None else None
            ),
        )
        self.state_changed.emit(st)

        if st.key != self._last_key:
            self._last_key = st.key
            data = self._thumbs.get(st.key)
            if data is not None:  # 來回切歌直接用快取，零延遲
                self._thumbs.move_to_end(st.key)
            else:
                data = await self._read_thumb(info.thumbnail)
                if data:
                    self._thumbs[st.key] = data
                    while len(self._thumbs) > self.THUMB_CAP:
                        self._thumbs.popitem(last=False)
            if data:
                self.art_changed.emit(data)
            else:
                self.art_missing.emit()

    async def _read_thumb(self, ref) -> Optional[bytes]:
        if ref is None:
            return None
        try:
            stream = await ref.open_read_async()
            size = int(stream.size)
            if size <= 0:
                return None
            buf = Buffer(size)
            await stream.read_async(buf, size, InputStreamOptions.READ_AHEAD)
            try:
                return bytes(buf)
            except Exception:
                reader = DataReader.from_buffer(buf)
                out = bytearray(buf.length)
                reader.read_bytes(out)
                return bytes(out)
        except Exception:
            return None
