"""Media player using mpv in a subprocess."""

import logging
from collections.abc import Callable
from threading import Lock
from typing import List, Optional, Union

from mpv import MPV

_LOGGER = logging.getLogger(__name__)


class MpvMediaPlayer:
    def __init__(
        self, 
        device: Optional[str] = None,
        volume_callback: Optional[Callable[[int], None]] = None
    ) -> None:
        self.player = MPV(
            cache=True,
            demuxer_max_bytes='20M',
            demuxer_max_back_bytes='5M',
            cache_secs=10,
            stream_buffer_size='512k',
            cache_on_disk=False,
            keep_open=False,
            audio_buffer=0.5,
            demuxer_readahead_secs=5,
            hr_seek='no',
            video=False,
            msg_level='all=error',
            audio_samplerate=48000,
            audio_channels='stereo',
            ao_null_untimed='yes',
            audio_wait_open=0.5,
        )

        if device:
            self.player["audio-device"] = device

        self.is_playing = False
        self.volume_callback = volume_callback

        self._playlist: List[str] = []
        self._done_callback: Optional[Callable[[], None]] = None
        self._done_callback_lock = Lock()

        self._duck_volume: int = 50
        self._unduck_volume: int = 100
        self._ignore_callback = False

        self.player.event_callback("end-file")(self._on_end_file)

    def play(
        self,
        url: Union[str, List[str]],
        done_callback: Optional[Callable[[], None]] = None,
        stop_first: bool = True,
    ) -> None:
        self.stop()

        if isinstance(url, str):
            self._playlist = [url]
        else:
            self._playlist = url

        next_url = self._playlist.pop(0)
        _LOGGER.debug("Playing %s", next_url)

        self._done_callback = done_callback
        self.is_playing = True
        self.player.play(next_url)

    def pause(self) -> None:
        self.player.pause = True
        self.is_playing = False

    def resume(self) -> None:
        self.player.pause = False
        if self._playlist:
            self.is_playing = True

    def stop(self) -> None:
        self.player.stop()
        self._playlist.clear()

    def duck(self) -> None:
        self._ignore_callback = True
        self.player.volume = self._duck_volume
        self._ignore_callback = False

    def unduck(self) -> None:
        self._ignore_callback = True
        self.player.volume = self._unduck_volume
        self._ignore_callback = False

    def set_volume(self, volume: int, from_external: bool = False) -> None:
        volume = max(0, min(100, volume))
        
        if from_external:
            self._ignore_callback = True
        
        self.player.volume = volume
        self._unduck_volume = volume
        self._duck_volume = volume // 2

        if not from_external and self.volume_callback and not self._ignore_callback:
            try:
                self.volume_callback(volume)
            except Exception as e:
                _LOGGER.error("Error in volume callback: %s", e)
        
        self._ignore_callback = False

    def _on_end_file(self, event) -> None:
        if self._playlist:
            self.player.play(self._playlist.pop(0))
            return

        self.is_playing = False

        todo_callback: Optional[Callable[[], None]] = None
        with self._done_callback_lock:
            if self._done_callback:
                todo_callback = self._done_callback
                self._done_callback = None

        if todo_callback:
            try:
                todo_callback()
            except Exception:
                _LOGGER.exception("Unexpected error running done callback")
