"""ThirdReality satellite extension — LED ring effects for voice assistant lifecycle.

This module subclasses VoiceSatelliteProtocol (upstream) and injects LED
animations via dbus-send. It contains NO upstream code and requires only a
single 3-line try/except change in __main__.py to activate.

When the upstream linux-voice-assistant package updates, only __main__.py's
import block needs to be re-verified; this file never changes.
"""

import asyncio
import json
import logging
import subprocess
from pathlib import Path
from typing import Dict, Optional

from aioesphomeapi.api_pb2 import (  # type: ignore[attr-defined]
    SwitchStateResponse,
    UpdateCommandRequest,
)
from aioesphomeapi.model import UpdateCommand, VoiceAssistantEventType

from linux_voice_assistant.satellite import VoiceSatelliteProtocol
from thirdreality.home_button import TRHomeButtonEventEntity
from thirdreality.update import (
    TRUpdateEntity,
    TROtaResult,
    check_version,
    download_firmware,
    install_firmware,
    load_device_info,
)

_LOGGER = logging.getLogger(__name__)

# Maps voice pipeline state → animation filename (under /usr/share/thirdreality/animation/)
_LED_ANIMATIONS: Dict[str, str] = {
    "listening": "active-waking.animation",
    "thinking":  "active-thinking.animation",
    "speaking":  "active-talking.animation",
    "idle":      "active-ending.animation",
    "error":     "active-ending.animation",
    "muted":     "mics-off_on.animation",
    "unmuted":   "none.animation",
}

_ANIM_DIR = "/usr/share/thirdreality/animation/"
_SOUND_CONF = Path("/data/conf/sound.json")
_SET_VOLUME_SCRIPT = Path("/etc/adckey/adckey_function.sh")
_MIC_MUTE_GPIO = Path("/sys/class/gpio/gpio438/value")
_VOLUME_POLL_INTERVAL = 0.5


def _normalize_volume(volume: float) -> float:
    """Clamp a normalized volume into the 0.0-1.0 range."""
    return max(0.0, min(1.0, float(volume)))


def _percent_to_normalized(volume_percent: float) -> float:
    """Convert an integer-style 0-100 volume into a normalized float."""
    return _normalize_volume(float(volume_percent) / 100.0)


def _normalized_to_percent(volume: float) -> int:
    """Convert a normalized volume into a 0-100 integer."""
    return int(round(_normalize_volume(volume) * 100))


def _gpio_to_muted(gpio_value: int) -> bool:
    """Convert ThirdReality GPIO state into assistant muted state."""
    return gpio_value == 0


def _muted_to_gpio(muted: bool) -> int:
    """Convert assistant muted state into ThirdReality GPIO state."""
    return 0 if muted else 1


def _led_fire(state: str, to_idle: bool = False) -> None:
    """Fire-and-forget dbus-send to emit LedShow signal (non-blocking)."""
    filename = _LED_ANIMATIONS.get(state)
    if not filename:
        _LOGGER.warning("[led] unknown state: %s", state)
        return
    animation = _ANIM_DIR + filename
    cmd = [
        "dbus-send",
        "--system",
        "--type=signal",
        "/com/3r/EventBus",
        "com._3reality.EventBus.LedShow",
        f"boolean:{'true' if to_idle else 'false'}",
        f"array:string:{animation}",
    ]
    _LOGGER.debug("[led] firing: %s", " ".join(cmd))
    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            close_fds=True,
        )
        stdout, stderr = proc.communicate(timeout=2)
        if proc.returncode != 0:
            _LOGGER.warning("[led] dbus-send failed (rc=%d): %s", proc.returncode, stderr.decode().strip())
        else:
            _LOGGER.debug("[led] OK: %s → %s", state, animation)
    except subprocess.TimeoutExpired:
        _LOGGER.warning("[led] dbus-send timeout for state: %s", state)
        proc.kill()
    except Exception:
        _LOGGER.warning("[led] exception for state: %s", state, exc_info=True)


class TRSatelliteProtocol(VoiceSatelliteProtocol):
    """VoiceSatelliteProtocol extended with ThirdReality LED ring animations."""

    def __init__(self, state) -> None:
        super().__init__(state)
        self._system_sync_task: Optional[asyncio.Task] = None
        self._update_check_task: Optional[asyncio.Task] = None
        self._update_download_task: Optional[asyncio.Task] = None
        self._last_system_volume: Optional[float] = None
        self._last_system_muted: Optional[bool] = None
        self._install_home_button_entity()
        self._install_volume_bridge()
        self._install_update_entity()

    def connection_made(self, transport) -> None:
        super().connection_made(transport)
        self._sync_state_from_system(force=True)
        self._start_system_sync()
        self._schedule_update_check()

    def connection_lost(self, exc) -> None:
        self._stop_system_sync()
        self._cancel_update_check()
        self._cancel_update_download()
        super().connection_lost(exc)

    def _install_volume_bridge(self) -> None:
        media_player = self.state.media_player_entity
        if media_player is None:
            _LOGGER.warning("[TR][volume] media player entity unavailable")
            return

        media_player.set_volume_callback(self._sync_volume_to_system)

    def _install_home_button_entity(self) -> None:
        existing_entities = [entity for entity in self.state.entities if isinstance(entity, TRHomeButtonEventEntity)]
        if not existing_entities:
            self.state.home_button_entity = TRHomeButtonEventEntity(
                server=self,
                key=len(self.state.entities),
                name="Home Button",
                object_id="thirdreality_home_button",
                event_types=["single_press", "double_press", "triple_press"],
            )
            self.state.entities.append(self.state.home_button_entity)
            return

        self.state.home_button_entity = existing_entities[0]
        for extra in existing_entities[1:]:
            self.state.entities.remove(extra)
        self.state.home_button_entity.server = self

    def _install_update_entity(self) -> None:
        device_info = load_device_info()
        current_version = device_info.current_version if device_info is not None else self.state.version

        existing = next((entity for entity in self.state.entities if isinstance(entity, TRUpdateEntity)), None)
        if existing is None:
            self._update_entity = TRUpdateEntity(
                server=self,
                key=len(self.state.entities),
                name="Firmware Update",
                object_id="thirdreality_firmware_update",
                current_version=current_version,
            )
            self.state.entities.append(self._update_entity)
        else:
            self._update_entity = existing
            self._update_entity.server = self
            self._update_entity.current_version = current_version
            if self._update_entity.latest_version == "":
                self._update_entity.latest_version = current_version

    def _read_system_volume(self) -> Optional[float]:
        sound_config = self._read_sound_config()
        if sound_config is None:
            return None

        volume_percent = sound_config.get("volume")
        if not isinstance(volume_percent, (int, float)):
            _LOGGER.warning("[TR][volume] invalid volume in %s: %r", _SOUND_CONF, volume_percent)
            return None

        return _percent_to_normalized(volume_percent)

    def _read_sound_config(self) -> Optional[Dict[str, object]]:
        if not _SOUND_CONF.exists():
            return None

        try:
            with open(_SOUND_CONF, "r", encoding="utf-8") as sound_file:
                sound_config = json.load(sound_file)
        except Exception:
            _LOGGER.warning("[TR][system] failed to read %s", _SOUND_CONF, exc_info=True)
            return None

        if not isinstance(sound_config, dict):
            _LOGGER.warning("[TR][system] invalid JSON object in %s", _SOUND_CONF)
            return None

        return sound_config

    def _read_system_muted(self) -> Optional[bool]:
        gpio_muted = self._read_gpio_muted()
        if gpio_muted is not None:
            return gpio_muted

        sound_config = self._read_sound_config()
        if sound_config is None:
            return None

        mic_mute = sound_config.get("mic_mute")
        if not isinstance(mic_mute, (int, float)):
            _LOGGER.warning("[TR][mute] invalid mic_mute in %s: %r", _SOUND_CONF, mic_mute)
            return None

        return int(mic_mute) == 0

    def _read_gpio_muted(self) -> Optional[bool]:
        if not _MIC_MUTE_GPIO.exists():
            return None

        try:
            gpio_value = _MIC_MUTE_GPIO.read_text(encoding="utf-8").strip()
        except Exception:
            _LOGGER.warning("[TR][mute] failed to read %s", _MIC_MUTE_GPIO, exc_info=True)
            return None

        if gpio_value not in {"0", "1"}:
            _LOGGER.warning("[TR][mute] invalid GPIO mute value: %r", gpio_value)
            return None

        return _gpio_to_muted(int(gpio_value))

    def _write_gpio_muted(self, muted: bool) -> bool:
        if not _MIC_MUTE_GPIO.exists():
            _LOGGER.warning("[TR][mute] missing GPIO path: %s", _MIC_MUTE_GPIO)
            return False

        gpio_value = str(_muted_to_gpio(muted))
        try:
            _MIC_MUTE_GPIO.write_text(gpio_value, encoding="utf-8")
        except Exception:
            _LOGGER.warning("[TR][mute] failed to write %s", _MIC_MUTE_GPIO, exc_info=True)
            return False

        return True

    def _sync_muted_to_system(self, muted: bool) -> None:
        if self._last_system_muted is not None and self._last_system_muted == muted:
            return

        updated_gpio = self._write_gpio_muted(muted)
        self._update_sound_config({"mic_mute": _muted_to_gpio(muted)})
        if updated_gpio:
            self._last_system_muted = muted

    def _update_sound_config(self, updates: Dict[str, object]) -> bool:
        sound_config = self._read_sound_config() or {}
        changed = False
        for key, value in updates.items():
            if sound_config.get(key) != value:
                sound_config[key] = value
                changed = True

        if not changed:
            return True

        try:
            _SOUND_CONF.parent.mkdir(parents=True, exist_ok=True)
            with open(_SOUND_CONF, "w", encoding="utf-8") as sound_file:
                json.dump(sound_config, sound_file, ensure_ascii=False, indent=4)
        except Exception:
            _LOGGER.warning("[TR][system] failed to write %s", _SOUND_CONF, exc_info=True)
            return False

        return True

    def _sync_volume_to_system(self, volume: float) -> None:
        normalized = _normalize_volume(volume)

        if self._last_system_volume is not None and abs(self._last_system_volume - normalized) < 0.0001:
            return

        if not _SET_VOLUME_SCRIPT.exists():
            _LOGGER.warning("[TR][volume] missing script: %s", _SET_VOLUME_SCRIPT)
            return

        percent = _normalized_to_percent(normalized)
        cmd = [str(_SET_VOLUME_SCRIPT), "SetVolume", str(percent)]
        _LOGGER.debug("[TR][volume] syncing to system: %s", " ".join(cmd))
        try:
            proc = subprocess.run(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                close_fds=True,
                timeout=3,
                check=False,
            )
        except Exception:
            _LOGGER.warning("[TR][volume] failed to set system volume", exc_info=True)
            return

        if proc.returncode != 0:
            _LOGGER.warning(
                "[TR][volume] set volume failed (rc=%d): %s",
                proc.returncode,
                proc.stderr.decode().strip(),
            )
            return

        self._last_system_volume = normalized

    def _sync_volume_from_system(self, *, force: bool = False) -> None:
        normalized = self._read_system_volume()
        if normalized is None:
            return

        volume_changed = (
            force
            or self._last_system_volume is None
            or abs(self._last_system_volume - normalized) >= 0.0001
            or abs(self.state.volume - normalized) >= 0.0001
        )
        if not volume_changed:
            return

        _LOGGER.debug("[TR][volume] syncing from system: %.2f", normalized)
        self._last_system_volume = normalized
        self.state.persist_volume(normalized)

        media_player = self.state.media_player_entity
        if media_player is None:
            return

        media_player.apply_volume_from_state(normalized)
        self.send_messages([media_player._get_state_message()])

    def _sync_muted_from_system(self, *, force: bool = False) -> None:
        muted = self._read_system_muted()
        if muted is None:
            return

        system_changed = self._last_system_muted is None or self._last_system_muted != muted
        state_changed = self.state.muted != muted
        if not (force or system_changed or state_changed):
            return

        _LOGGER.debug("[TR][mute] syncing from system: %s", muted)
        self._last_system_muted = muted

        if state_changed:
            self._apply_mic_mute_state(muted)
            if muted:
                _led_fire("muted", to_idle=True)
            else:
                _led_fire("unmuted", to_idle=True)

        if hasattr(self.state.preferences, "set_mic_muted"):
            self.state.preferences.set_mic_muted(muted)
            self.state.save_preferences()

        mute_switch = self.state.mute_switch_entity
        if mute_switch is not None:
            mute_switch.sync_with_state()
            self.send_messages([SwitchStateResponse(key=mute_switch.key, state=muted)])

    def _sync_state_from_system(self, *, force: bool = False) -> None:
        self._sync_volume_from_system(force=force)
        self._sync_muted_from_system(force=force)

    def _start_system_sync(self) -> None:
        if self._system_sync_task is None or self._system_sync_task.done():
            self._system_sync_task = asyncio.create_task(self._system_sync_loop())

    def _stop_system_sync(self) -> None:
        if self._system_sync_task is None:
            return

        self._system_sync_task.cancel()
        self._system_sync_task = None

    async def _system_sync_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(_VOLUME_POLL_INTERVAL)
                self._sync_state_from_system()
        except asyncio.CancelledError:
            _LOGGER.debug("[TR][system] sync loop stopped")
            raise

    def _schedule_update_check(self) -> None:
        if self._update_check_task is not None and not self._update_check_task.done():
            return
        self._update_check_task = asyncio.create_task(self._check_update_once())

    def _cancel_update_check(self) -> None:
        if self._update_check_task is None:
            return
        self._update_check_task.cancel()
        self._update_check_task = None

    def _cancel_update_download(self) -> None:
        if self._update_download_task is None:
            return
        self._update_download_task.cancel()
        self._update_download_task = None

    async def _check_update_once(self) -> None:
        try:
            device_info = await asyncio.to_thread(load_device_info)
            if device_info is None:
                return

            self._update_entity.current_version = device_info.current_version
            result = await asyncio.to_thread(check_version, device_info)
            self._update_entity.apply_result(result)
            self.send_messages([self._update_entity._get_state_message()])
            _LOGGER.info(
                "[TR][update] current=%s latest=%s has_update=%s",
                result.current_version,
                result.latest_version,
                result.has_update,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            _LOGGER.warning("[TR][update] OTA check failed", exc_info=True)
        finally:
            self._update_check_task = None

    def _build_download_result(self) -> TROtaResult:
        return TROtaResult(
            current_version=self._update_entity.current_version,
            latest_version=self._update_entity.latest_version,
            has_update=self._update_entity.latest_version != self._update_entity.current_version,
            expected_md5=self._update_entity.expected_md5,
            title=self._update_entity.title,
            release_summary=self._update_entity.release_summary,
            release_url=self._update_entity.release_url,
            download_url=self._update_entity.download_url,
        )

    def _schedule_update_download(self) -> None:
        if self._update_download_task is not None and not self._update_download_task.done():
            _LOGGER.warning("[TR][update] download already in progress")
            return
        self._update_download_task = asyncio.create_task(self._download_update_once())

    async def _download_update_once(self) -> None:
        try:
            result = self._build_download_result()
            if not result.download_url:
                raise ValueError("No OTA download URL available")
            if not result.expected_md5:
                raise ValueError("No OTA MD5 available")

            def progress_callback(progress: float, has_progress: bool) -> None:
                self._update_entity.set_download_progress(progress, has_progress=has_progress)
                self.send_messages([self._update_entity._get_state_message()])

            downloaded_path = await asyncio.to_thread(
                download_firmware,
                result,
                progress_callback=progress_callback,
            )
            self._update_entity.mark_download_complete(downloaded_path)
            self.send_messages([self._update_entity._get_state_message()])
            _LOGGER.info("[TR][update] downloaded OTA to %s", downloaded_path)

            self._update_entity.in_progress = True
            self._update_entity.has_progress = False
            self._update_entity.progress = 100.0
            self._update_entity.release_summary = "Starting swupdate installation"
            self.send_messages([self._update_entity._get_state_message()])

            await asyncio.to_thread(install_firmware, downloaded_path)
            self._update_entity.in_progress = False
            self._update_entity.has_progress = False
            self._update_entity.progress = 100.0
            self._update_entity.release_summary = "swupdate completed successfully"
            self.send_messages([self._update_entity._get_state_message()])
            _LOGGER.info("[TR][update] swupdate completed successfully")
        except asyncio.CancelledError:
            raise
        except Exception as err:
            self._update_entity.mark_download_failed(str(err))
            self.send_messages([self._update_entity._get_state_message()])
            _LOGGER.warning("[TR][update] OTA download failed", exc_info=True)
        finally:
            self._update_download_task = None

    def _apply_mic_mute_state(self, muted: bool) -> None:
        """Apply microphone mute without affecting speaker playback."""
        self.state.muted = bool(muted)

        if self.state.muted:
            _LOGGER.debug("[TR][mute] microphone muted")
            self._is_streaming_audio = False
            self.state.stop_word.is_active = False  # type: ignore[attr-defined]
        else:
            _LOGGER.debug("[TR][mute] microphone unmuted")

    # ------------------------------------------------------------------
    # Mute overrides
    # ------------------------------------------------------------------

    def _set_muted(self, new_state: bool) -> None:
        _LOGGER.debug("[TR] _set_muted called: %s", new_state)
        self._apply_mic_mute_state(new_state)
        self._sync_muted_to_system(self.state.muted)
        if hasattr(self.state.preferences, "set_mic_muted"):
            self.state.preferences.set_mic_muted(self.state.muted)
            self.state.save_preferences()
        if new_state:
            _led_fire("muted", to_idle=True)
        else:
            _led_fire("unmuted", to_idle=True)

    def handle_message(self, msg):
        if isinstance(msg, UpdateCommandRequest):
            yield from self._update_entity.handle_message(msg)
            if msg.key == self._update_entity.key:
                if msg.command == UpdateCommand.CHECK:
                    self._schedule_update_check()
                elif msg.command == UpdateCommand.INSTALL:
                    self._schedule_update_download()
            return

        yield from super().handle_message(msg)

    # ------------------------------------------------------------------
    # Lifecycle overrides — call super first, then fire LED
    # ------------------------------------------------------------------

    def wakeup(self, wake_word) -> None:
        """Show 'listening' animation when a valid wake-word fires."""
        _LOGGER.debug("[TR] wakeup called, pipeline_active=%s", self._pipeline_active)
        prev_active = self._pipeline_active
        super().wakeup(wake_word)
        # Only trigger LED if the pipeline actually started (not muted/busy/timer)
        if not prev_active and self._pipeline_active:
            _led_fire("listening")

    def handle_voice_event(self, event_type: VoiceAssistantEventType, data: Dict[str, str]) -> None:
        """Delegate to upstream, then inject LED for relevant events."""
        _LOGGER.debug("[TR] handle_voice_event: %s", event_type.name)
        super().handle_voice_event(event_type, data)

        if event_type in (
            VoiceAssistantEventType.VOICE_ASSISTANT_STT_VAD_END,
            VoiceAssistantEventType.VOICE_ASSISTANT_STT_END,
        ):
            _led_fire("thinking")
        elif event_type == VoiceAssistantEventType.VOICE_ASSISTANT_ERROR:
            _led_fire("error", to_idle=True)

    def play_tts(self) -> None:
        """Show 'speaking' animation just before TTS playback starts."""
        _LOGGER.debug("[TR] play_tts called: tts_url=%s, tts_played=%s", self._tts_url, self._tts_played)
        if (not self._tts_url) or self._tts_played:
            return
        _led_fire("speaking")
        super().play_tts()

    def _tts_finished(self) -> None:
        """Show 'listening' (continue) or 'idle' (end) after TTS finishes."""
        _LOGGER.debug("[TR] _tts_finished called, continue_conversation=%s", self._continue_conversation)
        will_continue = self._continue_conversation
        super()._tts_finished()
        if will_continue:
            _led_fire("listening")
        else:
            _led_fire("idle", to_idle=True)
