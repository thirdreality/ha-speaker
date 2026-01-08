"""Media player using mpv in a subprocess."""

import logging
import time
from collections.abc import Callable
from threading import Lock
from typing import List, Optional, Union

from mpv import MPV

_LOGGER = logging.getLogger(__name__)


class MpvMediaPlayer:
    def __init__(
        self, 
        device: Optional[str] = None,
        volume_callback: Optional[Callable[[int], None]] = None,
        state_callback: Optional[Callable[[str, List[str]], None]] = None
    ) -> None:
        self.player = MPV(
            cache=True,
            demuxer_max_bytes='20M',
            demuxer_max_back_bytes='5M',
            cache_secs=10,
            stream_buffer_size='512k',
            cache_on_disk=False,
            audio_buffer=0.5,
            demuxer_readahead_secs=5,
            hr_seek='no',
            video=False,
            msg_level='all=error',
            stream_lavf_o='reconnect=1,reconnect_streamed=1,reconnect_delay_max=5',
            ao='pulse',
            keep_open='no', # if yes, tts will not end when the player is stopped
            gapless_audio='yes',
            audio_stream_silence='yes',
            audio_exclusive='no',
        )

        if device:
            self.player["audio-device"] = device

        self.is_playing = False
        self.volume_callback = volume_callback
        self.state_callback = state_callback

        self._playlist: List[str] = []
        self._current_url: Optional[str] = None
        self._done_callback: Optional[Callable[[], None]] = None
        self._done_callback_lock = Lock()

        self._duck_volume: int = 50
        self._unduck_volume: int = 100
        self._ignore_callback = False

        self._last_event_time = None

        self.player.event_callback("end-file")(self._on_end_file)
        self.player.event_callback("start-file")(self._on_start_file)
        self.player.event_callback("file-loaded")(self._on_file_loaded)
        
        try:
            self.player.event_callback("playback-restart")(self._on_playback_restart)
        except (AttributeError, KeyError) as e:
            _LOGGER.debug(f"playback-restart event not available: {e}")
        
        _LOGGER.info("MpvMediaPlayer initialized")

    def _on_start_file(self, event) -> None:
        """Called when MPV starts loading a file."""
        self._last_event_time = time.time()
        _LOGGER.debug(f"START-FILE: url={self._current_url}")

    def _on_file_loaded(self, event) -> None:
        """Called when file is fully loaded. Fix is_playing if out of sync due to async events."""
        self._last_event_time = time.time()
        _LOGGER.debug(f"FILE-LOADED: url={self._current_url}")

        # Fix state desync caused by delayed end-file events from previous stop()
        if self._current_url and not self.is_playing and not self.player.pause:
            _LOGGER.debug("Fixing is_playing state after file loaded")
            self.is_playing = True

    def _on_playback_restart(self, event) -> None:
        """Called on playback restart (e.g., after seek or stream reconnect)."""
        self._last_event_time = time.time()
        _LOGGER.debug(f"PLAYBACK-RESTART: url={self._current_url}")

        # Fix state desync on stream reconnect
        if self._current_url and not self.is_playing and not self.player.pause:
            _LOGGER.debug("Fixing is_playing state after playback restart")
            self.is_playing = True

    def play(
        self,
        url: Union[str, List[str]],
        done_callback: Optional[Callable[[], None]] = None,
        stop_first: bool = True,
    ) -> None:
        
        _LOGGER.debug(f"PLAY called: url={url}, is_playing={self.is_playing}")

        self.stop()

        if isinstance(url, str):
            self._playlist = [url]
        else:
            self._playlist = url

        next_url = self._playlist.pop(0)
        self._current_url = next_url
        _LOGGER.debug(f"Playing: {next_url} (playlist remaining: {len(self._playlist)})")

        self._done_callback = done_callback
        self.is_playing = True

        try:
            self.player.play(next_url)
            _LOGGER.debug(f"MPV play() called successfully")
        except Exception as e:
            _LOGGER.error(f"Error calling MPV play(): {e}")
            self.is_playing = False
            raise
        
        if self.state_callback:
            try:
                self.state_callback(next_url, self._playlist.copy())
            except Exception as e:
                _LOGGER.error("Error in state callback: %s", e)

    def pause(self) -> None:
        self.player.pause = True
        self.is_playing = False

    def resume(self) -> None:
        self.player.pause = False
        if self._current_url:
            self.is_playing = True

    def stop(self) -> None:
        if self._current_url or self._playlist:
            _LOGGER.debug(f"Stop: url={self._current_url}, playlist={len(self._playlist)}")
        
        try:
            self.player.stop()
        except Exception as e:
            _LOGGER.error(f"Error stopping player: {e}")
            
        self._playlist.clear()
        self._current_url = None
        self.is_playing = False
        
        if self.state_callback:
            try:
                self.state_callback(None, [])
            except Exception as e:
                _LOGGER.error("Error in state callback: %s", e)

    def get_current_state(self):
        """Return current playback state for persistence."""
        return {
            'url': self._current_url,
            'playlist': self._playlist.copy(),
            'is_playing': self.is_playing
        }

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
        """Handle end-file event. Skip state update for STOP/RESTARTED/REDIRECT reasons."""
        time_since_last = None
        if self._last_event_time:
            time_since_last = time.time() - self._last_event_time
        
        try:
            reason = event['reason'] if 'reason' in event else 0
            file_error = event['file_error'] if 'file_error' in event else 0
        except (KeyError, TypeError, AttributeError):
            reason = 0
            file_error = 0
        
        reason_map = {
            0: "EOF",
            1: "RESTARTED", # seek or reload
            2: "STOP",
            3: "QUIT",
            4: "ERROR",
            5: "REDIRECT",
            6: "UNKNOWN"
        }
        reason_str = reason_map.get(reason, f"UNKNOWN({reason})")
        
        _LOGGER.warning(
            f"⏹ END-FILE: reason={reason_str}({reason}), "
            f"file_error={file_error}, "
            f"url={self._current_url}, "
            f"playlist={len(self._playlist)}, "
            f"is_playing={self.is_playing}, "
            f"time_since_last={time_since_last:.1f}s" if time_since_last else ""
        )

        # Skip state update - these reasons don't mean playback actually ended
        if reason == 5:  # redirect
            _LOGGER.debug("Stream redirect detected, continuing playback")
            return

        if reason == 1:  # restarted
            _LOGGER.debug("Stream restarted (reconnect/seek), continuing playback")
            return

        if reason == 2:  # stop
            _LOGGER.debug("Stop command received, skipping state update in end-file handler")
            return
        
        # Play next item in playlist if available
        if self._playlist:
            next_url = self._playlist.pop(0)
            _LOGGER.debug(f"Playing next in playlist: {next_url}")
            self._current_url = next_url
            self._last_event_time = time.time()
            
            try:
                self.player.play(next_url)
            except Exception as e:
                _LOGGER.error(f"Error playing next URL: {e}")
            
            if self.state_callback:
                try:
                    self.state_callback(next_url, self._playlist.copy())
                except Exception as e:
                    _LOGGER.error("Error in state callback: %s", e)
            return

        if reason == 4:  # error
            _LOGGER.error(f"Playback error: file_error={file_error}, url={self._current_url}")

        # Detect unexpected EOF on live streams (network issue)
        is_likely_live_stream = False
        if self._current_url:
            url_lower = self._current_url.lower()
            live_indicators = ['/live/', '/stream/', '.m3u8', 'radio', 'broadcast']
            is_likely_live_stream = any(indicator in url_lower for indicator in live_indicators)
            
            if time_since_last and time_since_last < 300:
                _LOGGER.debug(f"Short playback duration ({time_since_last:.1f}s), treating as normal file")
                is_likely_live_stream = False
        
        if is_likely_live_stream and reason == 0:  # eof on likely live stream
            _LOGGER.warning(
                f"Unexpected EOF on live stream {self._current_url}. "
                f"Stream may have ended or network issue occurred."
            )
        _LOGGER.info(
            f"Playback ended: reason={reason_str}, "
            f"is_live_stream={is_likely_live_stream}, "
            f"calling done_callback"
        )
        self.is_playing = False
        self._current_url = None

        todo_callback: Optional[Callable[[], None]] = None
        with self._done_callback_lock:
            if self._done_callback:
                todo_callback = self._done_callback
                self._done_callback = None

        if todo_callback:
            try:
                _LOGGER.debug("Calling done_callback...")
                todo_callback()
                _LOGGER.debug("done_callback completed")
            except Exception:
                _LOGGER.exception("Unexpected error running done callback")
