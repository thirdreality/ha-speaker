#!/usr/bin/env python3
import argparse
import asyncio
import json
import logging
import os
import sys
import threading
import time
from pathlib import Path
from queue import Queue
from typing import Dict, List, Optional, Set, Union
import fcntl
import subprocess
import signal

import numpy as np
import soundcard as sc
from pymicro_wakeword import MicroWakeWord, MicroWakeWordFeatures
from pyopen_wakeword import OpenWakeWord, OpenWakeWordFeatures

from .models import AvailableWakeWord, Preferences, ServerState, WakeWordType
from .mpv_player import MpvMediaPlayer
from .satellite import VoiceSatelliteProtocol
from .util import get_mac
from .zeroconf import HomeAssistantZeroconf

_LOGGER = logging.getLogger(__name__)
_MODULE_DIR = Path(__file__).parent
_REPO_DIR = _MODULE_DIR.parent
_WAKEWORDS_DIR = _REPO_DIR / "wakewords"
_SOUNDS_DIR = _REPO_DIR / "sounds"
SOUND_CONF = "/data/conf/sound.json"
PLAYBACK_STATE_FILE = "/data/conf/playback_state.json"
LOCK_FILE = "/tmp/sound_config.lock"


class VolumeConfigLock:
    def __init__(self, lock_file: str):
        self.lock_file = lock_file
        self.fd = None
    
    def __enter__(self):
        os.makedirs(os.path.dirname(self.lock_file), exist_ok=True)
        self.fd = open(self.lock_file, 'w')
        fcntl.flock(self.fd.fileno(), fcntl.LOCK_EX)
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.fd:
            fcntl.flock(self.fd.fileno(), fcntl.LOCK_UN)
            self.fd.close()
            self.fd = None

# -----------------------------------------------------------------------------
# TODO
def thread_exception_handler(args):
    """Handle uncaught exceptions in threads and exit program."""
    _LOGGER.critical(
        "FATAL: Uncaught exception in thread '%s'",
        args.thread.name
    )
    _LOGGER.critical("Exception type: %s", args.exc_type.__name__)
    _LOGGER.critical("Exception value: %s", args.exc_value)
    _LOGGER.critical("Exiting program to allow restart by supervisor...")

    os._exit(1)


async def main() -> None:
    threading.excepthook = thread_exception_handler

    parser = argparse.ArgumentParser()
    parser.add_argument("--name", required=True)
    parser.add_argument(
        "--audio-input-device",
        help="soundcard name for input device (see --list-input-devices)",
    )
    parser.add_argument(
        "--list-input-devices",
        action="store_true",
        help="List audio input devices and exit",
    )
    parser.add_argument("--audio-input-block-size", type=int, default=1024)
    parser.add_argument(
        "--audio-output-device",
        help="mpv name for output device (see --list-output-devices)",
    )
    parser.add_argument(
        "--list-output-devices",
        action="store_true",
        help="List audio output devices and exit",
    )
    parser.add_argument(
        "--wake-word-dir",
        default=[_WAKEWORDS_DIR],
        action="append",
        help="Directory with wake word models (.tflite) and configs (.json)",
    )
    parser.add_argument(
        "--wake-model", default="okay_nabu", help="Id of active wake model"
    )
    parser.add_argument("--stop-model", default="stop", help="Id of stop model")
    parser.add_argument(
        "--download-dir",
        default=_REPO_DIR / "local",
        help="Directory to download custom wake word models, etc.",
    )
    parser.add_argument(
        "--refractory-seconds",
        default=2.0,
        type=float,
        help="Seconds before wake word can be activated again",
    )
    #
    parser.add_argument(
        "--wakeup-sound", default=str(_SOUNDS_DIR / "wake_word_triggered.flac")
    )
    parser.add_argument(
        "--timer-finished-sound", default=str(_SOUNDS_DIR / "timer_finished.flac")
    )
    #
    parser.add_argument("--preferences-file", default=_REPO_DIR / "preferences.json")
    #
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Address for ESPHome server (default: 0.0.0.0)",
    )
    parser.add_argument(
        "--port", type=int, default=6053, help="Port for ESPHome server (default: 6053)"
    )
    parser.add_argument(
        "--debug", action="store_true", help="Print DEBUG messages to console"
    )
    args = parser.parse_args()

    if args.list_input_devices:
        print("Input devices")
        print("=" * 13)
        for idx, mic in enumerate(sc.all_microphones()):
            print(f"[{idx}]", mic.name)
        return

    if args.list_output_devices:
        from mpv import MPV

        player = MPV()
        print("Output devices")
        print("=" * 14)

        for speaker in player.audio_device_list:  # type: ignore
            print(speaker["name"] + ":", speaker["description"])
        return

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format='%(asctime)s.%(msecs)03d [%(levelname)s] %(name)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    _LOGGER.debug(args)

    args.download_dir = Path(args.download_dir)
    args.download_dir.mkdir(parents=True, exist_ok=True)

    # Resolve microphone
    if args.audio_input_device is not None:
        try:
            args.audio_input_device = int(args.audio_input_device)
        except ValueError:
            pass

        mic = sc.get_microphone(args.audio_input_device)
    else:
        mic = sc.default_microphone()

    # Load available wake words
    wake_word_dirs = [Path(ww_dir) for ww_dir in args.wake_word_dir]
    wake_word_dirs.append(args.download_dir / "external_wake_words")
    available_wake_words: Dict[str, AvailableWakeWord] = {}

    for wake_word_dir in wake_word_dirs:
        for model_config_path in wake_word_dir.glob("*.json"):
            model_id = model_config_path.stem
            if model_id == args.stop_model:
                # Don't show stop model as an available wake word
                continue

            with open(model_config_path, "r", encoding="utf-8") as model_config_file:
                model_config = json.load(model_config_file)
                model_type = WakeWordType(model_config["type"])
                if model_type == WakeWordType.OPEN_WAKE_WORD:
                    wake_word_path = model_config_path.parent / model_config["model"]
                else:
                    wake_word_path = model_config_path

                available_wake_words[model_id] = AvailableWakeWord(
                    id=model_id,
                    type=WakeWordType(model_type),
                    wake_word=model_config["wake_word"],
                    trained_languages=model_config.get("trained_languages", []),
                    wake_word_path=wake_word_path,
                )

    _LOGGER.debug("Available wake words: %s", list(sorted(available_wake_words.keys())))

    # Load preferences
    preferences_path = Path(args.preferences_file)
    if preferences_path.exists():
        _LOGGER.debug("Loading preferences: %s", preferences_path)
        with open(preferences_path, "r", encoding="utf-8") as preferences_file:
            preferences_dict = json.load(preferences_file)
            preferences = Preferences(**preferences_dict)
    else:
        preferences = Preferences()

    # Load wake/stop models
    active_wake_words: Set[str] = set()
    wake_models: Dict[str, Union[MicroWakeWord, OpenWakeWord]] = {}
    if preferences.active_wake_words:
        # Load preferred models
        for wake_word_id in preferences.active_wake_words:
            wake_word = available_wake_words.get(wake_word_id)
            if wake_word is None:
                _LOGGER.warning("Unrecognized wake word id: %s", wake_word_id)
                continue

            _LOGGER.debug("Loading wake model: %s", wake_word_id)
            wake_models[wake_word_id] = wake_word.load()
            active_wake_words.add(wake_word_id)

    if not wake_models:
        # Load default model
        wake_word_id = args.wake_model
        wake_word = available_wake_words[wake_word_id]

        _LOGGER.debug("Loading wake model: %s", wake_word_id)
        wake_models[wake_word_id] = wake_word.load()
        active_wake_words.add(wake_word_id)

    # TODO: allow openWakeWord for "stop"
    stop_model: Optional[MicroWakeWord] = None
    for wake_word_dir in wake_word_dirs:
        stop_config_path = wake_word_dir / f"{args.stop_model}.json"
        if not stop_config_path.exists():
            continue

        _LOGGER.debug("Loading stop model: %s", stop_config_path)
        stop_model = MicroWakeWord.from_config(stop_config_path)
        break

    assert stop_model is not None

    initial_volume = 50
    initial_mic_muted = False
    try:
        if Path(SOUND_CONF).exists():
            with open(SOUND_CONF, 'r') as f:
                sound_config = json.load(f)
                initial_volume = sound_config.get('volume', 50)
                initial_mic_muted = sound_config.get('mic_mute', 0) == 0
                _LOGGER.info("Loaded initial volume: %d, mic_muted: %s", initial_volume, initial_mic_muted)
    except Exception as e:
        _LOGGER.warning("Failed to load sound config, using default volume: %s", e)

    saved_playback = load_playback_state()
    
    def on_playback_state_change(url: Optional[str], playlist: List[str]):
        save_playback_state(state, url, playlist)

    state = ServerState(
        name=args.name,
        mac_address=get_mac(),
        audio_queue=Queue(),
        entities=[],
        available_wake_words=available_wake_words,
        wake_words=wake_models,
        active_wake_words=active_wake_words,
        stop_word=stop_model,
        music_player=MpvMediaPlayer(
            device=args.audio_output_device,
            state_callback=on_playback_state_change
        ),
        tts_player=MpvMediaPlayer(
            device=args.audio_output_device,
        ),
        wakeup_sound=args.wakeup_sound,
        timer_finished_sound=args.timer_finished_sound,
        preferences=preferences,
        preferences_path=preferences_path,
        refractory_seconds=args.refractory_seconds,
        download_dir=args.download_dir,
        loop=None,
        mic_muted=initial_mic_muted,
    )

    graceful_shutdown.state = state
    signal.signal(signal.SIGTERM, graceful_shutdown)
    signal.signal(signal.SIGINT, graceful_shutdown)

    state.music_player.set_volume(initial_volume, from_external=True)
    state.tts_player.set_volume(initial_volume, from_external=True)

    volume_monitor_thread = threading.Thread(
        target=monitor_volume_config,
        args=(state, SOUND_CONF),
        daemon=True,
    )
    volume_monitor_thread.start()

    memory_monitor_thread = threading.Thread(
        target=monitor_memory_and_restart,
        args=(state, 10),
        daemon=True,
        name="MemoryMonitor"
    )
    memory_monitor_thread.start()
    _LOGGER.info("Memory monitor thread started")

    home_button_thread = threading.Thread(
        target=monitor_home_button,
        args=(state, "/dev/input/event0"),
        daemon=True,
        name="HomeButtonMonitor"
    )
    home_button_thread.start()
    _LOGGER.info("Home button monitor thread started")

    process_audio_thread = threading.Thread(
        target=process_audio,
        args=(state, mic, args.audio_input_block_size),
        daemon=True,
    )
    process_audio_thread.start()

    loop = asyncio.get_running_loop()
    state.loop = loop
    server = await loop.create_server(
        lambda: VoiceSatelliteProtocol(state), host=args.host, port=args.port
    )

    # Auto discovery (zeroconf, mDNS)
    discovery = HomeAssistantZeroconf(port=args.port, name=args.name)
    await discovery.register_server()

    if saved_playback and saved_playback.get('is_playing'):
        url = saved_playback.get('url')
        if url:
            _LOGGER.info("Restoring playback: %s", url)
            loop.call_later(2.0, restore_playback, state, saved_playback)

    try:
        async with server:
            _LOGGER.info("Server started (host=%s, port=%s)", args.host, args.port)
            await server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        state.audio_queue.put_nowait(None)
        process_audio_thread.join()

    _LOGGER.debug("Server stopped")


# -----------------------------------------------------------------------------
def restore_playback(state: ServerState, playback_state: dict):
    """Restore playback from saved state."""
    try:
        url = playback_state.get('url')
        playlist = playback_state.get('playlist', [])
        
        if url:
            full_playlist = [url] + playlist
            state.music_player.play(full_playlist)
            _LOGGER.info("Playback restored successfully")
            
            if state.media_player_entity:
                from aioesphomeapi.model import MediaPlayerState
                state.loop.call_soon_threadsafe(
                    state.media_player_entity.server.send_messages,
                    [state.media_player_entity._update_state(MediaPlayerState.PLAYING)]
                )
    except Exception as e:
        _LOGGER.error("Failed to restore playback: %s", e)

def save_playback_state(state: ServerState, url: Optional[str], playlist: List[str] = None):
    """Persist current playback state to disk for crash recovery."""
    try:
        playback_state = {
            'url': url,
            'playlist': playlist or [],
            'is_playing': state.music_player.is_playing,
            'volume': state.music_player._unduck_volume,
            'timestamp': time.time()
        }
        
        tmpfile = f"{PLAYBACK_STATE_FILE}.tmp"
        with open(tmpfile, 'w') as f:
            json.dump(playback_state, f, indent=2)
        os.rename(tmpfile, PLAYBACK_STATE_FILE)
        
        _LOGGER.debug("Saved playback state: %s", url)
    except Exception as e:
        _LOGGER.error("Failed to save playback state: %s", e)

def load_playback_state():
    """Load saved playback state. Returns None if expired (>24h) or missing."""
    try:
        if not Path(PLAYBACK_STATE_FILE).exists():
            return None
            
        with open(PLAYBACK_STATE_FILE, 'r') as f:
            playback_state = json.load(f)
        
        timestamp = playback_state.get('timestamp', 0)
        if time.time() - timestamp > 86400:
            _LOGGER.info("Playback state too old, ignoring")
            return None
            
        _LOGGER.debug("Loaded playback state: %s", playback_state.get('url'))
        return playback_state
    except Exception as e:
        _LOGGER.error("Failed to load playback state: %s", e)
        return None

def clear_playback_state():
    """Remove saved playback state file."""
    try:
        if Path(PLAYBACK_STATE_FILE).exists():
            os.remove(PLAYBACK_STATE_FILE)
            _LOGGER.debug("Cleared playback state")
    except Exception as e:
        _LOGGER.error("Failed to clear playback state: %s", e)

def monitor_volume_config(state: ServerState, config_path: str):
    """Watch config file for external volume changes (e.g., hardware buttons)."""
    last_mtime = 0
    last_volume = -1
    last_mic_muted = None
    
    _LOGGER.debug("Starting volume config monitor: %s", config_path)
    
    while state.media_player_entity is None:
        time.sleep(0.1)
    
    _LOGGER.debug("media_player_entity initialized, starting volume sync")
    
    try:
        if os.path.exists(config_path):
            with VolumeConfigLock(LOCK_FILE):
                with open(config_path, 'r') as f:
                    config = json.load(f)
                    initial_vol = config.get('volume', 50)
            
            last_volume = initial_vol
            state.media_player_entity.update_volume_from_external(initial_vol)
            _LOGGER.info("Initial volume synced to HA: %d", initial_vol)
    except Exception as e:
        _LOGGER.error("Failed to sync initial config: %s", e)

    while True:
        try:
            if os.path.exists(config_path):
                mtime = os.path.getmtime(config_path)
                if mtime > last_mtime:
                    last_mtime = mtime

                    with VolumeConfigLock(LOCK_FILE):
                        with open(config_path, "r") as f:
                            config = json.load(f)
                            volume = config.get("volume", 50)
                            mic_muted = config.get("mic_mute", 1) == 0

                    if volume != last_volume:
                        last_volume = volume
                        state.music_player.set_volume(volume, from_external=True)
                        state.tts_player.set_volume(volume, from_external=True)
                        state.media_player_entity.update_volume_from_external(volume)
                        _LOGGER.info("Volume updated from config: %d", volume)

                    if mic_muted != last_mic_muted:
                        last_mic_muted = mic_muted
                        state.mic_muted = mic_muted

                        ent = state.microphone_mute_entity
                        if ent is not None:
                            ent.update_muted_from_external(mic_muted)
                            _LOGGER.info("Mic mute updated from config -> HA: %s", mic_muted)

        except json.JSONDecodeError:
            pass
        except Exception as e:
            _LOGGER.error("Error monitoring volume config: %s", e)

        time.sleep(0.3)    

def monitor_home_button(state: ServerState, input_device: str = "/dev/input/event0"):
    import struct
    import select
    
    _LOGGER.info("Starting home button monitor: %s", input_device)
    
    while state.home_button_entity is None:
        time.sleep(0.1)
    
    _LOGGER.debug("home_button_entity initialized, starting event monitoring")
    
    try:
        with open(input_device, "rb") as f:
            event_size = struct.calcsize('llHHI')
            
            click_count = 0
            last_release_time = None
            MULTI_CLICK_WINDOW = 0.5
            pending_timer = None
            
            def trigger_click_event():
                nonlocal click_count
                if click_count == 1:
                    event_type = "single_press"
                elif click_count == 2:
                    event_type = "double_press"
                elif click_count >= 3:
                    event_type = "triple_press"
                else:
                    return
                
                _LOGGER.info("Home button: %d click(s) -> %s", click_count, event_type)
                state.home_button_entity.trigger_event(event_type)
                click_count = 0
            
            while True:
                if pending_timer and time.time() - last_release_time >= MULTI_CLICK_WINDOW:
                    trigger_click_event()
                    pending_timer = None
                    last_release_time = None
                
                if select.select([f], [], [], 0.1)[0]:
                    event_data = f.read(event_size)
                    if len(event_data) < event_size:
                        continue
                    
                    _, _, ev_type, code, value = struct.unpack('llHHI', event_data)
                    
                    # EV_KEY=1, key 102=Home, value: 1=down, 0=up
                    if ev_type == 1 and code == 102:
                        if value == 1:
                            _LOGGER.debug("Home key pressed")
                        elif value == 0:
                            current_time = time.time()
                            
                            if last_release_time and (current_time - last_release_time) < MULTI_CLICK_WINDOW:
                                click_count += 1
                                _LOGGER.debug("Home key click count: %d", click_count)
                            else:
                                if pending_timer:
                                    trigger_click_event()
                                click_count = 1
                                _LOGGER.debug("Home key: new click sequence")
                            
                            last_release_time = current_time
                            pending_timer = True
                            
    except FileNotFoundError:
        _LOGGER.error("Input device not found: %s", input_device)
    except PermissionError:
        _LOGGER.error("Permission denied to read: %s (need root or input group)", input_device)
    except Exception as e:
        _LOGGER.error("Error monitoring home button: %s", e)
        import traceback
        traceback.print_exc()

def monitor_memory_and_restart(state: ServerState, threshold_mb: int = 10):
    """Monitor free memory and exit for restart when critically low."""
    _LOGGER.info(f"Starting memory monitor (threshold: {threshold_mb} MB free)")
    
    time.sleep(10)
    
    consecutive_low_memory = 0
    check_interval = 15
    
    while True:
        try:
            free_mb = None
            try:
                with open('/proc/meminfo', 'r') as f:
                    for line in f:
                        if line.startswith('MemFree:'):
                            free_kb = int(line.split()[1])
                            free_mb = free_kb / 1024
                            break
            except Exception as e:
                _LOGGER.error("Failed to read memory info: %s", e)
                time.sleep(check_interval)
                continue
            
            if free_mb is None:
                time.sleep(check_interval)
                continue
            
            if free_mb < threshold_mb:
                consecutive_low_memory += 1
                _LOGGER.warning(
                    f"Low memory detected: {free_mb:.1f} MB free "
                    f"(threshold: {threshold_mb} MB, count: {consecutive_low_memory})"
                )
                
                if consecutive_low_memory >= 2:
                    _LOGGER.debug(
                        f"Memory critically low: {free_mb:.1f} MB free. "
                        "Saving state and exiting for restart..."
                    )
                    
                    try:
                        if state.music_player and state.music_player.is_playing:
                            current_state = state.music_player.get_current_state()
                            save_playback_state(
                                state, 
                                current_state['url'], 
                                current_state['playlist']
                            )
                            _LOGGER.info("Playback state saved before restart")
                        else:
                            clear_playback_state()
                    except Exception as e:
                        _LOGGER.error(f"Failed to save playback state: {e}")
                    
                    _LOGGER.info("Exiting process (PID: %d) for memory cleanup", os.getpid())
                    os._exit(1)
                    
            else:
                if consecutive_low_memory > 0:
                    _LOGGER.info(f"Memory recovered: {free_mb:.1f} MB free")
                consecutive_low_memory = 0
                
        except Exception as e:
            _LOGGER.error(f"Error in memory monitor: {e}")
            consecutive_low_memory = 0
        
        time.sleep(check_interval)

def graceful_shutdown(signum, frame):
    """Handle SIGTERM/SIGINT: save playback state before exit."""
    _LOGGER.info(f"Received signal {signum}, saving state before shutdown...")
    try:
        if hasattr(graceful_shutdown, 'state'):
            state = graceful_shutdown.state
            if state.music_player and state.music_player.is_playing:
                current_state = state.music_player.get_current_state()
                save_playback_state(
                    state, 
                    current_state['url'], 
                    current_state['playlist']
                )
                _LOGGER.info("Playback state saved on shutdown")
    except Exception as e:
        _LOGGER.error(f"Error saving state on shutdown: {e}")
    
    sys.exit(0)

def process_audio(state: ServerState, mic, block_size: int):
    """Process audio chunks from the microphone."""

    wake_words: List[Union[MicroWakeWord, OpenWakeWord]] = []
    micro_features: Optional[MicroWakeWordFeatures] = None
    micro_inputs: List[np.ndarray] = []

    oww_features: Optional[OpenWakeWordFeatures] = None
    oww_inputs: List[np.ndarray] = []
    has_oww = False

    last_active: Optional[float] = None

    try:
        _LOGGER.debug("Opening audio input device: %s", mic.name)
        with mic.recorder(samplerate=16000, channels=1, blocksize=block_size) as mic_in:
            while True:
                audio_chunk_array = mic_in.record(block_size).reshape(-1)
                audio_chunk = (
                    (np.clip(audio_chunk_array, -1.0, 1.0) * 32767.0)
                    .astype("<i2")  # little-endian 16-bit signed
                    .tobytes()
                )

                if state.satellite is None:
                    continue

                if state.mic_muted:
                    continue

                if (not wake_words) or (state.wake_words_changed and state.wake_words):
                    # Update list of wake word models to process
                    state.wake_words_changed = False
                    wake_words = [
                        ww
                        for ww in state.wake_words.values()
                        if ww.id in state.active_wake_words
                    ]

                    has_oww = False
                    for wake_word in wake_words:
                        if isinstance(wake_word, OpenWakeWord):
                            has_oww = True

                    if micro_features is None:
                        micro_features = MicroWakeWordFeatures()

                    if has_oww and (oww_features is None):
                        oww_features = OpenWakeWordFeatures.from_builtin()

                try:
                    state.satellite.handle_audio(audio_chunk)

                    assert micro_features is not None
                    micro_inputs.clear()
                    micro_inputs.extend(micro_features.process_streaming(audio_chunk))

                    if has_oww:
                        assert oww_features is not None
                        oww_inputs.clear()
                        oww_inputs.extend(oww_features.process_streaming(audio_chunk))

                    for wake_word in wake_words:
                        activated = False
                        if isinstance(wake_word, MicroWakeWord):
                            for micro_input in micro_inputs:
                                if wake_word.process_streaming(micro_input):
                                    activated = True
                        elif isinstance(wake_word, OpenWakeWord):
                            for oww_input in oww_inputs:
                                for prob in wake_word.process_streaming(oww_input):
                                    if prob > 0.5:
                                        activated = True

                        if activated:
                            # Check refractory
                            now = time.monotonic()
                            if (last_active is None) or (
                                (now - last_active) > state.refractory_seconds
                            ):
                                state.satellite.wakeup(wake_word)
                                last_active = now

                    # Always process to keep state correct
                    stopped = False
                    for micro_input in micro_inputs:
                        if state.stop_word.process_streaming(micro_input):
                            stopped = True

                    if stopped and (state.stop_word.id in state.active_wake_words):
                        state.satellite.stop()
                except Exception:
                    _LOGGER.exception("Unexpected error handling audio")
    except Exception:
        _LOGGER.exception("Unexpected error processing audio")
        sys.exit(1)


# -----------------------------------------------------------------------------

if __name__ == "__main__":
    asyncio.run(main())
