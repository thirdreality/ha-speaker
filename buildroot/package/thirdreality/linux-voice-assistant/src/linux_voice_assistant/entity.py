import subprocess
import json
import logging
import asyncio
import base64
import hashlib
import ssl
import certifi
import re
import threading
from urllib import parse, request
from abc import abstractmethod
from collections.abc import Iterable
from typing import Callable, List, Optional, Union

_LOGGER = logging.getLogger(__name__)
SOUND_CONF = "/data/conf/sound.json"
DEVICE_INFO_FILE = "/data/conf/device.json"
OTA_INFO_FILE = "/data/conf/ota_update.json"
OTA_STATUS_FILE = "/data/conf/ota_status.json"

def fetch_github_release_body(owner: str, repo: str, tag: str | None = None, token: str | None = None) -> str:
    """Fetch GitHub release body via the GitHub API.

    If tag is None, fetches the latest release.
    Returns empty string on error.
    """
    try:
        if tag:
            api_url = f"https://api.github.com/repos/{owner}/{repo}/releases/tags/{tag}"
        else:
            api_url = f"https://api.github.com/repos/{owner}/{repo}/releases/latest"

        headers = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "trspk-ota-check/1.0",
        }
        if token:
            headers["Authorization"] = f"token {token}"

        req = request.Request(api_url, headers=headers, method="GET")
        ctx = ssl.create_default_context(cafile=certifi.where())
        with request.urlopen(req, timeout=10, context=ctx) as resp:
            gh_json = json.loads(resp.read().decode("utf-8"))
            return gh_json.get("body") or gh_json.get("name") or ""
    except Exception as e:
        _LOGGER.debug("fetch_github_release_body failed: %s", e)
        return ""


def fetch_github_release_info(owner: str, repo: str, tag: str | None = None, token: str | None = None) -> dict:
    """Fetch full GitHub release JSON (latest if tag is None)."""
    try:
        if tag:
            api_url = f"https://api.github.com/repos/{owner}/{repo}/releases/tags/{tag}"
        else:
            api_url = f"https://api.github.com/repos/{owner}/{repo}/releases/latest"

        headers = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "trspk-ota-check/1.0",
        }
        if token:
            headers["Authorization"] = f"token {token}"

        req = request.Request(api_url, headers=headers, method="GET")
        ctx = ssl.create_default_context(cafile=certifi.where())
        with request.urlopen(req, timeout=10, context=ctx) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        _LOGGER.debug("fetch_github_release_info failed: %s", e)
        return {}


def _normalize_version_str(v: str) -> str:
    if not v:
        return ""
    v = str(v).strip()
    # strip leading v/V
    if v.startswith("v") or v.startswith("V"):
        v = v[1:]
    m = re.match(r"(\d+(?:\.\d+)*)", v)
    if not m:
        return v
    parts = m.group(1).split(".")
    try:
        parts = [str(int(p)) for p in parts]
    except Exception:
        parts = [p.lstrip("0") or "0" for p in parts]
    return ".".join(parts)


def _version_tuple(v: str) -> tuple:
    norm = _normalize_version_str(v)
    if not norm:
        return ()
    return tuple(int(x) for x in norm.split("."))

# pylint: disable=no-name-in-module
from aioesphomeapi.api_pb2 import (  # type: ignore[attr-defined]
    ListEntitiesMediaPlayerResponse,
    ListEntitiesRequest,
    ListEntitiesSwitchResponse,
    MediaPlayerCommandRequest,
    MediaPlayerStateResponse,
    SubscribeHomeAssistantStatesRequest,
    SwitchCommandRequest,
    SwitchStateResponse,
    ListEntitiesUpdateResponse,
    UpdateStateResponse,
    UpdateCommandRequest,
)
from aioesphomeapi.model import MediaPlayerCommand, MediaPlayerState, UpdateCommand
from google.protobuf import message

from .api_server import APIServer
from .mpv_player import MpvMediaPlayer
from .util import call_all
from . import ota


class ESPHomeEntity:
    def __init__(self, server: APIServer) -> None:
        self.server = server

    @abstractmethod
    def handle_message(self, msg: message.Message) -> Iterable[message.Message]:
        pass


# -----------------------------------------------------------------------------


class MediaPlayerEntity(ESPHomeEntity):
    def __init__(
        self,
        server: APIServer,
        key: int,
        name: str,
        object_id: str,
        music_player: MpvMediaPlayer,
        announce_player: MpvMediaPlayer,
    ) -> None:
        ESPHomeEntity.__init__(self, server)

        self.key = key
        self.name = name
        self.object_id = object_id
        self.state = MediaPlayerState.IDLE
        self.volume = 1.0
        self.muted = False
        self.music_player = music_player
        self.announce_player = announce_player

    def play(
        self,
        url: Union[str, List[str]],
        announcement: bool = False,
        done_callback: Optional[Callable[[], None]] = None,
    ) -> Iterable[message.Message]:
        url_str = url[0] if isinstance(url, list) else url
        is_connection_test = "/api/assist_satellite/connection_test" in url_str

        if announcement:
            if self.music_player.is_playing:
                # Announce, resume music
                self.music_player.pause()
                self.announce_player.play(
                    url,
                    done_callback=lambda: call_all(
                        self.music_player.resume, done_callback
                    ),
                )
            else:
                # Announce, idle
                self.announce_player.play(
                    url,
                    done_callback=lambda: call_all(
                        self.server.send_messages(
                            [self._update_state(MediaPlayerState.IDLE)]
                        ),
                        done_callback,
                    ),
                )
        else:
            # Music
            self.music_player.play(
                url,
                done_callback=lambda: call_all(
                    self.server.send_messages(
                        [self._update_state(MediaPlayerState.IDLE)]
                    ),
                    done_callback,
                ),
            )

        _LOGGER.debug("is_connection_test: %s", is_connection_test)
        if not is_connection_test:
            yield self._update_state(MediaPlayerState.PLAYING)
            _LOGGER.debug("update_state: PLAYING")

    def update_volume_from_external(self, volume_percent: int) -> None:
        
        self.volume = volume_percent / 100.0
        
        loop = None
        if hasattr(self.server, 'loop'):
            loop = self.server.loop
        
        if loop is None:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                pass
        
        if loop and loop.is_running():
            loop.call_soon_threadsafe(
                self.server.send_messages,
                [self._get_state_message()]
            )

    def handle_message(self, msg: message.Message) -> Iterable[message.Message]:
        if isinstance(msg, MediaPlayerCommandRequest) and (msg.key == self.key):
            if msg.has_media_url:
                announcement = msg.has_announcement and msg.announcement
                yield from self.play(msg.media_url, announcement=announcement)
            elif msg.has_command:
                if msg.command == MediaPlayerCommand.PAUSE:
                    self.music_player.pause()
                    yield self._update_state(MediaPlayerState.PAUSED)
                elif msg.command == MediaPlayerCommand.PLAY:
                    self.music_player.resume()
                    yield self._update_state(MediaPlayerState.PLAYING)
            elif msg.has_volume:
                volume = int(msg.volume * 100)
                try:
                    subprocess.run(
                        ["/etc/adckey/adckey_function.sh", "SetVolume", str(volume)],
                        capture_output=True,
                        text=True,
                        timeout=5,
                    )
                    _LOGGER.info("SetVolume via script: %d", volume)
                except Exception as e:
                    _LOGGER.error("SetVolume script failed: %s", e)
        elif isinstance(msg, ListEntitiesRequest):
            yield ListEntitiesMediaPlayerResponse(
                object_id=self.object_id,
                key=self.key,
                name=self.name,
                supports_pause=True,
            )
        elif isinstance(msg, SubscribeHomeAssistantStatesRequest):
            yield self._get_state_message()

    def _update_state(self, new_state: MediaPlayerState) -> MediaPlayerStateResponse:
        self.state = new_state
        return self._get_state_message()

    def _get_state_message(self) -> MediaPlayerStateResponse:
        return MediaPlayerStateResponse(
            key=self.key,
            state=self.state,
            volume=self.volume,
            muted=self.muted,
        )

def _read_mic_muted_from_conf() -> bool | None:
    try:
        with open(SOUND_CONF, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        return cfg.get("mic_mute", 1) == 0
    except Exception as e:
        _LOGGER.warning("Read mic_mute from %s failed: %s", SOUND_CONF, e)
        return None

class MicrophoneMuteEntity(ESPHomeEntity):
    def __init__(
        self,
        server: APIServer,
        key: int,
        name: str,
        object_id: str,
        state: "ServerState",
    ) -> None:
        ESPHomeEntity.__init__(self, server)
        self.key = key
        self.name = name
        self.object_id = object_id
        self.state = state
        self.muted = state.mic_muted

    def set_muted(self, muted: bool) -> None:
        current = _read_mic_muted_from_conf()
        _LOGGER.info("Mic mute request: target=%s, conf=%s", muted, current)

        if current is None or current != muted:
            r = subprocess.run(
                ["/etc/adckey/adckey_function.sh", "Mute"],
                capture_output=True,
                text=True,
                timeout=5,
            )
        
        after = _read_mic_muted_from_conf()
        final_muted = after if after is not None else muted

        self.muted = final_muted
        self.state.mic_muted = final_muted

    def handle_message(self, msg: message.Message) -> Iterable[message.Message]:
        if isinstance(msg, SwitchCommandRequest) and (msg.key == self.key):
            self.set_muted(bool(msg.state))
            yield self._get_state_message()

        elif isinstance(msg, ListEntitiesRequest):
            yield ListEntitiesSwitchResponse(
                object_id=self.object_id,
                key=self.key,
                name=self.name,
                assumed_state=False,
                entity_category=1,
                icon="mdi:microphone-off",
            )
        elif isinstance(msg, SubscribeHomeAssistantStatesRequest):
            yield self._get_state_message()

    def _get_state_message(self) -> SwitchStateResponse:
        return SwitchStateResponse(
            key=self.key,
            state=self.muted,
        )

    def update_muted_from_external(self, muted: bool) -> None:
        self.muted = muted
        self.state.mic_muted = muted

        loop = getattr(self.server, "loop", None)
        if loop and loop.is_running():
            loop.call_soon_threadsafe(
                self.server.send_messages,
                [self._get_state_message()],
            )

class EventEntity(ESPHomeEntity):
    def __init__(
        self,
        server: APIServer,
        key: int,
        name: str,
        object_id: str,
        event_types: List[str],
    ) -> None:
        ESPHomeEntity.__init__(self, server)
        self.key = key
        self.name = name
        self.object_id = object_id
        self.event_types = event_types

    def trigger_event(self, event_type: str) -> None:
        if event_type not in self.event_types:
            _LOGGER.warning("Invalid event_type: %s", event_type)
            return

        loop = getattr(self.server, "loop", None)
        if loop and loop.is_running():
            from aioesphomeapi.api_pb2 import EventResponse
            
            loop.call_soon_threadsafe(
                self.server.send_messages,
                [EventResponse(key=self.key, event_type=event_type)],
            )
            _LOGGER.info("Event triggered: %s", event_type)

    def handle_message(self, msg: message.Message) -> Iterable[message.Message]:
        if isinstance(msg, ListEntitiesRequest):
            from aioesphomeapi.api_pb2 import ListEntitiesEventResponse
            
            yield ListEntitiesEventResponse(
                object_id=self.object_id,
                key=self.key,
                name=self.name,
                event_types=self.event_types,
                icon="mdi:gesture-tap-button",
            )


class UpdateEntity(ESPHomeEntity):
    def __init__(
        self,
        server: APIServer,
        key: int,
        name: str,
        object_id: str,
    ) -> None:
        ESPHomeEntity.__init__(self, server)
        self.key = key
        self.name = name
        self.object_id = object_id
        self._state = UpdateStateResponse(
            key=self.key,
            missing_state=False,
            in_progress=False,
            has_progress=False,
            progress=0.0,
            current_version="unknown",
            latest_version="unknown",
            title="",
            release_summary="",
            release_url="",
        )
        # Start a watcher thread to push OTA status updates to HA when ota_status file changes
        try:
            self._ota_status_mtime = 0.0
            def _watcher():
                import time
                while True:
                    try:
                        st = None
                        try:
                            st = os.stat(OTA_STATUS_FILE)
                        except Exception:
                            st = None
                        if st:
                            m = st.st_mtime
                            if m != getattr(self, '_ota_status_mtime', 0):
                                self._ota_status_mtime = m
                                try:
                                    self._refresh_state()
                                    loop = getattr(self.server, 'loop', None)
                                    if loop and loop.is_running():
                                        loop.call_soon_threadsafe(self.server.send_messages, [self._state])
                                except Exception:
                                    pass
                        time.sleep(1)
                    except Exception:
                        time.sleep(5)

            import os
            t = threading.Thread(target=_watcher, daemon=True)
            t.start()
            # If the process restarted while a download was in progress,
            # resume it automatically: either a partial .tmp file exists or
            # ota_status.json reports "download".
            try:
                import os

                need_resume = False
                try:
                    # Partial download present -> resume
                    if os.path.exists('/data/software.swu.tmp'):
                        _LOGGER.info('Partial SWU detected; will resume OTA on startup')
                        need_resume = True

                    # Completed download present -> verify/install
                    if not need_resume and os.path.exists('/data/software.swu'):
                        _LOGGER.info('Complete SWU detected; will verify/install on startup')
                        need_resume = True

                    # ota_status.json indicates either in-progress download or downloaded
                    if not need_resume:
                        try:
                            with open(OTA_STATUS_FILE, 'r', encoding='utf-8') as sf:
                                s = json.load(sf)
                            st = s.get('ota_status')
                            # If a previous run reported 'install' or 'downloaded', the device
                            # may have rebooted after swupdate. Check the firmware version
                            # against the ota metadata; if they match, mark success. Otherwise
                            # resume/verify/install as appropriate.
                            if st in ('install', 'download'):
                                try:
                                    md = self._load_ota_metadata() or {}
                                    meta_ver = md.get('version') or ''
                                    cur_ver = self._load_current_version() or ''
                                    t_meta = _version_tuple(meta_ver)
                                    t_cur = _version_tuple(cur_ver)
                                    _LOGGER.debug('Startup OTA check: status=%s meta_ver=%s cur_ver=%s t_meta=%s t_cur=%s', st, meta_ver, cur_ver, t_meta, t_cur)
                                    if t_meta and t_meta == t_cur:
                                        _LOGGER.info('Detected completed OTA on boot: versions match -> writing success')
                                        try:
                                            ota._write_status_global('success', 100.0, f'Installation verified after reboot: {meta_ver}')
                                        except Exception:
                                            try:
                                                with open(OTA_STATUS_FILE, 'w', encoding='utf-8') as sfw:
                                                    json.dump({'ota_status': 'success', 'progress': 100.0, 'message': f'Installation verified after reboot: {meta_ver}'}, sfw, ensure_ascii=False)
                                            except Exception:
                                                pass
                                        need_resume = False
                                    else:
                                        _LOGGER.info('OTA status indicates %s but versions differ; will resume/verify/install', st)
                                        need_resume = True
                                except Exception as e:
                                    _LOGGER.debug('Error while checking versions on startup: %s', e)
                                    need_resume = True
                            # elif st in ('download',):
                            #     _LOGGER.info('OTA status file indicates "%s"; will resume download on startup', st)
                            #     need_resume = True
                        except Exception:
                            pass
                except Exception as e:
                    _LOGGER.debug('Failed to probe resume conditions: %s', e)

                if need_resume:
                    try:
                        t2 = threading.Thread(target=self._run_ota_background, daemon=True)
                        t2.start()
                    except Exception:
                        _LOGGER.debug('Failed to start OTA resume thread')
            except Exception:
                pass
        except Exception:
            pass

    def handle_message(self, msg: message.Message) -> Iterable[message.Message]:
        if isinstance(msg, ListEntitiesRequest):
            yield ListEntitiesUpdateResponse(
                object_id=self.object_id,
                key=self.key,
                name=self.name,
                icon="mdi:update",
                entity_category=1,
                device_class="firmware",
            )
        elif isinstance(msg, SubscribeHomeAssistantStatesRequest):
            self._refresh_state()
            yield self._state
        elif isinstance(msg, UpdateCommandRequest) and (msg.key == self.key):
            # Print full incoming protobuf for debugging: text form and serialized base64
            try:
                _LOGGER.debug("Raw UpdateCommandRequest (text): %s", msg)
            except Exception:
                _LOGGER.debug("Raw UpdateCommandRequest: <unprintable>")
            try:
                ser = msg.SerializeToString()
                _LOGGER.debug("Raw UpdateCommandRequest (base64): %s", base64.b64encode(ser).decode("ascii"))
            except Exception:
                _LOGGER.debug("Raw UpdateCommandRequest: failed to serialize")

            try:
                members = [n for n in dir(UpdateCommand) if n.isupper()]
                _LOGGER.debug("Available UpdateCommand enum members: %s", members)
            except Exception:
                _LOGGER.debug("Could not enumerate UpdateCommand members")

            # UpdateCommand enum names can vary between generated packages.
            # Resolve possible attribute names safely.
            def _enum_val(enum, *names):
                for n in names:
                    if hasattr(enum, n):
                        return getattr(enum, n)
                return None
            check_val = _enum_val(UpdateCommand, "UPDATE_COMMAND_CHECK", "CHECK")
            install_val = _enum_val(UpdateCommand, "UPDATE_COMMAND_INSTALL", "INSTALL")

            _LOGGER.debug(
                "Received UpdateCommandRequest: key=%s command=%s resolved_check=%s resolved_install=%s",
                msg.key,
                getattr(msg, "command", None),
                check_val,
                install_val,
            )

            if check_val is not None and msg.command == check_val:
                _LOGGER.info("UpdateCommand: CHECK received - refreshing state")
                self._refresh_state()
                yield self._state
            elif install_val is not None and msg.command == install_val:
                _LOGGER.info("UpdateCommand: INSTALL received - starting OTA background task")

                # Log current OTA metadata (if any) to help debugging
                try:
                    md = self._load_ota_metadata() or {}
                    _LOGGER.debug("OTA metadata before install: %s", md)
                except Exception as e:
                    _LOGGER.debug("Failed to read OTA metadata before install: %s", e)

                t = threading.Thread(target=self._run_ota_background, daemon=True)
                t.start()
                # refresh state immediately so HA shows activity if supervisor reports it
                self._refresh_state()
                yield self._state
            else:
                # Unknown enum layout or unsupported command value.
                # Fallback: if we couldn't resolve an UPDATE enum value, interpret
                # any command value that isn't the CHECK value as UPDATE.
                try:
                    cmd_val = getattr(msg, "command", None)
                    _LOGGER.debug("Fallback enum handling: cmd_val=%s check_val=%s update_val=%s", cmd_val, check_val, update_val)
                    if update_val is None and check_val is not None:
                        if cmd_val != check_val:
                            _LOGGER.info("Fallback: treating command value %s as UPDATE", cmd_val)
                            try:
                                md = self._load_ota_metadata() or {}
                                _LOGGER.debug("OTA metadata before update (fallback): %s", md)
                            except Exception as e:
                                _LOGGER.debug("Failed to read OTA metadata before update (fallback): %s", e)

                            t = threading.Thread(target=self._run_ota_background, daemon=True)
                            t.start()
                            self._refresh_state()
                            yield self._state
                            return
                except Exception:
                    pass

                _LOGGER.warning(
                    "Unhandled UpdateCommandRequest: key=%s command=%s (check_val=%s update_val=%s)",
                    msg.key,
                    getattr(msg, "command", None),
                    check_val,
                    update_val,
                )

    def _run_ota_background(self) -> None:
        _LOGGER.info("OTA background task started")
        try:
            # Run the ota module which downloads and installs
            rc = ota.run_from_metadata()
            _LOGGER.info("OTA background task finished with rc=%s", rc)
        except Exception as e:
            _LOGGER.error("OTA background task failed: %s", e)

        # Refresh state and push to connected clients if possible
        try:
            self._refresh_state()
            loop = getattr(self.server, "loop", None)
            if loop and loop.is_running():
                loop.call_soon_threadsafe(self.server.send_messages, [self._state])
        except Exception as e:
            _LOGGER.debug("Refresh state after OTA failed: %s", e)

    def _load_current_version(self) -> str:
        try:
            with open(DEVICE_INFO_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            device = data.get("device", {})
            return device.get("firmwareVersion", "unknown") or "unknown"
        except Exception as e:
            _LOGGER.debug("Read firmware version failed: %s", e)
            return "unknown"

    def _load_device_info(self) -> dict:
        try:
            with open(DEVICE_INFO_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data.get("device", {})
        except Exception as e:
            _LOGGER.debug("Read device info failed: %s", e)
            return {}

    def _load_ota_metadata(self) -> dict:
        try:
            with open(OTA_INFO_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _fetch_ota_status(self) -> dict:
        # Read OTA status written by local ota.py into OTA_STATUS_FILE
        try:
            with open(OTA_STATUS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}

    def _refresh_state(self) -> None:
        metadata = self._load_ota_metadata()
        if not metadata:
            metadata = self._check_new_firmware() or {}
        ota_status = self._fetch_ota_status()

        current_version = self._load_current_version()
        latest_version = metadata.get("version", current_version) or current_version
        title = metadata.get("title", "")
        release_summary = metadata.get("release_summary", "")
        release_url = metadata.get("release_url", "")

        in_progress = False
        progress = 0.0
        has_progress = False

        status = ota_status.get("ota_status")
        if status == "install":
            in_progress = True
            # install progress may be provided; treat similarly to download
            p = ota_status.get("progress")
            total_bytes = ota_status.get("total_bytes")
            try:
                if p is None:
                    progress = 0.0
                else:
                    progress = float(p)
            except (TypeError, ValueError):
                progress = 0.0

            if total_bytes:
                try:
                    progress = max(0.0, min(1.0, float(progress)))
                    has_progress = True
                except Exception:
                    progress = 0.0
                    has_progress = False
            else:
                try:
                    if 0.0 <= progress <= 1.0:
                        has_progress = True
                    else:
                        has_progress = False
                        progress = 0.0
                except Exception:
                    has_progress = False
                    progress = 0.0
        elif status == "download":
            # Download may be in-progress or already complete. Determine by progress value.
            p = ota_status.get("progress")
            total_bytes = ota_status.get("total_bytes")
            finished = False
            try:
                if p is None:
                    progress = 0.0
                else:
                    progress = float(p)
            except (TypeError, ValueError):
                progress = 0.0

            try:
                if total_bytes:
                    if progress >= 1.0:
                        finished = True
                else:
                    # If progress reported as >1 it's likely a percentage value
                    if progress > 1.0 and progress >= 100.0:
                        finished = True
            except Exception:
                finished = False

            if finished:
                in_progress = False
                has_progress = True
                progress = 100.0
            else:
                in_progress = True
                # determine whether a meaningful progress fraction is available
                if total_bytes:
                    try:
                        progress = max(0.0, min(1.0, float(progress)))
                        has_progress = True
                    except Exception:
                        progress = 0.0
                        has_progress = False
                else:
                    try:
                        if 0.0 <= progress <= 1.0:
                            has_progress = True
                        else:
                            has_progress = False
                            progress = 0.0
                    except Exception:
                        has_progress = False
                        progress = 0.0
        elif status == "success":
            # Installation reported success by installer. Verify by comparing
            # ota metadata version with device current firmwareVersion (normalize
            # both) — only report success to HA if they match.
            in_progress = False
            has_progress = True
            try:
                progress = float(ota_status.get("progress", 100.0))
            except (TypeError, ValueError):
                progress = 100.0
            try:
                if progress > 1.0:
                    progress = max(0.0, min(1.0, progress / 100.0))
            except Exception:
                pass

            try:
                md = self._load_ota_metadata() or {}
                meta_ver = md.get("version") or ""
                cur_ver = self._load_current_version() or ""
                # normalize and compare
                t_meta = _version_tuple(meta_ver)
                t_cur = _version_tuple(cur_ver)
                _LOGGER.debug("OTA verify after install: meta_ver=%s cur_ver=%s norm_meta=%s norm_cur=%s", meta_ver, cur_ver, t_meta, t_cur)
                if t_meta and t_meta == t_cur:
                    # versions match -> report success
                    pass
                else:
                    # version mismatch -> treat as failed
                    _LOGGER.error("OTA install reported success but versions differ: expected=%s got=%s", meta_ver, cur_ver)
                    try:
                        ota._write_status_global("failed", 0.0, f"version mismatch after install: expected={meta_ver} got={cur_ver}")
                    except Exception:
                        # fallback: write local status file
                        try:
                            with open(OTA_STATUS_FILE, 'w', encoding='utf-8') as sf:
                                json.dump({"ota_status": "failed", "progress": 0.0, "message": f"version mismatch after install: expected={meta_ver} got={cur_ver}"}, sf, ensure_ascii=False)
                        except Exception:
                            pass
                    # reflect failure in state
                    has_progress = False
                    progress = 0.0
                    status = "failed"
            except Exception as e:
                _LOGGER.debug("Failed to verify versions after install: %s", e)

        # Home Assistant expects progress as 0..100 (percentage).
        try:
            if has_progress:
                # if progress is a fraction 0..1 convert to percent
                try:
                    pf = float(progress)
                    if 0.0 <= pf <= 1.0:
                        progress = pf * 100.0
                except Exception:
                    pass
        except Exception:
            pass

        self._state = UpdateStateResponse(
            key=self.key,
            missing_state=False,
            in_progress=in_progress,
            has_progress=has_progress,
            progress=progress,
            current_version=current_version,
            latest_version=latest_version,
            title=title,
            release_summary=release_summary,
            release_url=release_url,
        )

    def _check_new_firmware(self) -> dict:
        device = self._load_device_info()
        model_id = device.get("modelID") or ""
        current_version = device.get("firmwareVersion") or ""
        mac_address = device.get("macAddress") or ""
        dsn = mac_address.replace(":", "").upper()

        if not model_id or not current_version or not dsn:
            _LOGGER.warning("OTA check skipped: missing modelID/version/macAddress")
            return {}

        # Check GitHub releases for new version. Owner/repo can be configured
        # in device info; defaults to this repository.
        try:
            owner = device.get("github_owner") or device.get("githubOwner") or "thirdreality"
            repo = device.get("github_repo") or device.get("githubRepo") or "voice-music-assistant"
            token = device.get("githubToken") or device.get("github_token") or None

            # Fetch latest release info from GitHub
            gh = fetch_github_release_info(owner, repo, tag=None, token=token)
            if not gh:
                _LOGGER.debug("No GitHub release info found for %s/%s", owner, repo)
                return {"version": current_version}

            latest_tag = gh.get("tag_name") or gh.get("name") or ""
            latest_norm = _normalize_version_str(latest_tag)
            current_norm = _normalize_version_str(current_version)

            _LOGGER.debug("Compare versions: device=%s normalized=%s github=%s normalized=%s",
                          current_version, current_norm, latest_tag, latest_norm)

            # Compare numeric tuples
            try:
                if _version_tuple(latest_norm) <= _version_tuple(current_norm):
                    return {"version": current_version}
            except Exception:
                # Fallback to string compare
                if latest_norm == current_norm:
                    return {"version": current_version}

            # Newer release found
            # Try to pick a suitable asset download URL (prefer asset matching model_id or .swu)
            url = ""
            assets = gh.get("assets", []) or []
            chosen = None
            if assets:
                # Only accept .swu assets. Prefer model-specific .swu, then any .swu.
                for a in assets:
                    name = (a.get("name") or "").lower()
                    if model_id and model_id.lower() in name and name.endswith(".swu"):
                        chosen = a
                        break
                if not chosen:
                    for a in assets:
                        name = (a.get("name") or "").lower()
                        if name.endswith(".swu"):
                            chosen = a
                            break
                if chosen:
                    url = chosen.get("browser_download_url") or ""
                else:
                    url = ""

            # Only .swu is accepted; if none found, url remains empty.

            metadata = {
                "url": url,
                "version": latest_tag or current_version,
                "title": gh.get("name") or latest_tag or "",
                "release_url": gh.get("html_url") or "",
                "release_summary": gh.get("body") or "",
            }

            try:
                with open(OTA_INFO_FILE, "w", encoding="utf-8") as f:
                    json.dump(metadata, f, ensure_ascii=False, indent=2)
            except Exception as e:
                _LOGGER.debug("Write OTA metadata failed: %s", e)

            return metadata
        except Exception as e:
            _LOGGER.warning("OTA check (GitHub) failed: %s", e)
            return {}

    def _trigger_ota_update(self) -> None:
        # Supervisor integration disabled — perform OTA locally via ota.run_from_metadata()
        try:
            _LOGGER.info("Triggering local OTA via ota.run_from_metadata()")
            rc = ota.run_from_metadata()
            _LOGGER.info("Local OTA runner exited with rc=%s", rc)
        except Exception as e:
            _LOGGER.error("Local OTA trigger failed: %s", e)
