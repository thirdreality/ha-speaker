"""ThirdReality Home button event entity and input monitor."""

import logging
import select
import struct
import time
from collections.abc import Iterable
from typing import List, Optional

from aioesphomeapi.api_pb2 import (  # type: ignore[attr-defined]
    EventResponse,
    ListEntitiesEventResponse,
    ListEntitiesRequest,
)
from google.protobuf import message

from linux_voice_assistant.api_server import APIServer
from linux_voice_assistant.entity import ESPHomeEntity

_LOGGER = logging.getLogger(__name__)
_HOME_BUTTON_CODE = 102
_INPUT_EVENT_FORMAT = "llHHI"
_MULTI_CLICK_WINDOW_SECONDS = 0.5


class TRHomeButtonEventEntity(ESPHomeEntity):
    """Event entity for ThirdReality Home button multi-click actions."""

    def __init__(
        self,
        server: APIServer,
        key: int,
        name: str,
        object_id: str,
        event_types: List[str],
    ) -> None:
        super().__init__(server)
        self.key = key
        self.name = name
        self.object_id = object_id
        self.event_types = event_types
        self._log = logging.getLogger(f"{self.__class__.__name__}[{self.key}]")

    def trigger_event(self, event_type: str) -> None:
        if event_type not in self.event_types:
            self._log.warning("Invalid event type: %s", event_type)
            return

        self.server.send_messages([EventResponse(key=self.key, event_type=event_type)])
        self._log.info("Triggered event: %s", event_type)

    def handle_message(self, msg: message.Message) -> Iterable[message.Message]:
        if isinstance(msg, ListEntitiesRequest):
            yield ListEntitiesEventResponse(
                object_id=self.object_id,
                key=self.key,
                name=self.name,
                event_types=self.event_types,
                icon="mdi:gesture-tap-button",
            )


def monitor_home_button(state, input_device: str = "/dev/input/event0") -> None:
    """Monitor the hardware Home button and emit single/double/triple press events."""

    _LOGGER.info("[TR][home] starting home button monitor: %s", input_device)

    while getattr(state, "home_button_entity", None) is None:
        time.sleep(0.1)

    try:
        with open(input_device, "rb") as input_file:
            event_size = struct.calcsize(_INPUT_EVENT_FORMAT)
            click_count = 0
            last_release_time: Optional[float] = None

            def flush_clicks() -> None:
                nonlocal click_count, last_release_time

                if click_count == 1:
                    event_type = "single_press"
                elif click_count == 2:
                    event_type = "double_press"
                elif click_count >= 3:
                    event_type = "triple_press"
                else:
                    return

                _LOGGER.info("[TR][home] %d click(s) -> %s", click_count, event_type)
                entity = getattr(state, "home_button_entity", None)
                if entity is not None:
                    entity.trigger_event(event_type)

                click_count = 0
                last_release_time = None

            while True:
                if click_count > 0 and last_release_time is not None:
                    if (time.time() - last_release_time) >= _MULTI_CLICK_WINDOW_SECONDS:
                        flush_clicks()

                if not select.select([input_file], [], [], 0.1)[0]:
                    continue

                event_data = input_file.read(event_size)
                if len(event_data) < event_size:
                    continue

                _, _, ev_type, code, value = struct.unpack(_INPUT_EVENT_FORMAT, event_data)

                # EV_KEY=1, KEY_HOME=102, value 0 means release.
                if ev_type != 1 or code != _HOME_BUTTON_CODE or value != 0:
                    continue

                current_time = time.time()
                if last_release_time is not None and (current_time - last_release_time) < _MULTI_CLICK_WINDOW_SECONDS:
                    click_count += 1
                else:
                    if click_count > 0:
                        flush_clicks()
                    click_count = 1

                last_release_time = current_time
    except FileNotFoundError:
        _LOGGER.error("[TR][home] input device not found: %s", input_device)
    except PermissionError:
        _LOGGER.error("[TR][home] permission denied reading input device: %s", input_device)
    except Exception:
        _LOGGER.exception("[TR][home] unexpected error monitoring home button")
