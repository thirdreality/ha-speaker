import subprocess
import json
import logging
import asyncio
from abc import abstractmethod
from collections.abc import Iterable
from typing import Callable, List, Optional, Union

_LOGGER = logging.getLogger(__name__)
SOUND_CONF = "/data/conf/sound.json"

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
)
from aioesphomeapi.model import MediaPlayerCommand, MediaPlayerState
from google.protobuf import message

from .api_server import APIServer
from .mpv_player import MpvMediaPlayer
from .util import call_all


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

        yield self._update_state(MediaPlayerState.PLAYING)

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
