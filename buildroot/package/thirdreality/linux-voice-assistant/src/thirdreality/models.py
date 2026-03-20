"""ThirdReality model extensions for sound.json compatibility."""

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, Optional

from linux_voice_assistant.models import Preferences as BasePreferences
from linux_voice_assistant.models import ServerState as BaseServerState

if TYPE_CHECKING:
    from thirdreality.home_button import TRHomeButtonEventEntity

_LOGGER = logging.getLogger(__name__)
_SOUND_CONFIG_NAME = "sound.json"


def _clamp_normalized_volume(volume: float) -> float:
    """Clamp a normalized volume into the 0.0-1.0 range."""
    return max(0.0, min(1.0, float(volume)))


def _normalized_to_percent(volume: float) -> int:
    """Convert a normalized volume into a 0-100 integer."""
    return int(round(_clamp_normalized_volume(volume) * 100))


def _coerce_int(value: Any, default: int) -> int:
    """Best-effort integer conversion with a fallback default."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


@dataclass
class TRPreferences(BasePreferences):
    mic_gain: int = 30
    mic_mute: int = 1  # 0 = muted, 1 = unmuted
    _storage_format: str = field(default="preferences", init=False, repr=False)
    _raw_data: Dict[str, Any] = field(default_factory=dict, init=False, repr=False)

    @classmethod
    def from_dict(cls, data: Dict[str, Any], *, storage_path: Optional[Path] = None) -> "TRPreferences":
        """Build preferences from a JSON object, accepting both legacy and sound.json formats."""
        prefs = cls()
        prefs._storage_format = prefs._detect_storage_format(data, storage_path)
        prefs._raw_data = dict(data)

        active_wake_words = data.get("active_wake_words")
        if isinstance(active_wake_words, list):
            prefs.active_wake_words = [str(item) for item in active_wake_words]

        raw_volume = data.get("volume")
        if isinstance(raw_volume, (int, float)):
            if prefs._storage_format == "sound":
                prefs.volume = _clamp_normalized_volume(float(raw_volume) / 100.0)
            else:
                prefs.volume = _clamp_normalized_volume(float(raw_volume))

        prefs.thinking_sound = 1 if _coerce_int(data.get("thinking_sound", 0), 0) else 0
        prefs.mic_gain = _coerce_int(data.get("mic_gain", 30), 30)
        prefs.mic_mute = 0 if _coerce_int(data.get("mic_mute", 1), 1) == 0 else 1
        return prefs

    @classmethod
    def for_path(cls, storage_path: Path) -> "TRPreferences":
        """Create default preferences using the expected storage format for the target path."""
        prefs = cls()
        prefs._storage_format = "sound" if storage_path.name == _SOUND_CONFIG_NAME else "preferences"
        return prefs

    @staticmethod
    def _detect_storage_format(data: Dict[str, Any], storage_path: Optional[Path]) -> str:
        if any(key in data for key in ("mic_gain", "mic_mute")):
            return "sound"
        if storage_path is not None and storage_path.name == _SOUND_CONFIG_NAME:
            return "sound"
        return "preferences"

    def is_mic_muted(self) -> bool:
        return self.mic_mute == 0

    def set_mic_muted(self, muted: bool) -> None:
        self.mic_mute = 0 if muted else 1

    def to_file_dict(self, base_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Merge current preferences into an existing JSON object without dropping unrelated fields."""
        data: Dict[str, Any] = dict(base_data or self._raw_data)

        data["active_wake_words"] = list(self.active_wake_words)
        data["thinking_sound"] = 1 if self.thinking_sound else 0

        if self._storage_format == "sound":
            normalized_volume = 1.0 if self.volume is None else self.volume
            data["volume"] = _normalized_to_percent(normalized_volume)
            data["mic_gain"] = _coerce_int(self.mic_gain, 30)
            data["mic_mute"] = 0 if self.is_mic_muted() else 1
        else:
            data["volume"] = None if self.volume is None else _clamp_normalized_volume(self.volume)

        return data

    def remember_saved_data(self, data: Dict[str, Any]) -> None:
        self._raw_data = dict(data)


@dataclass
class TRServerState(BaseServerState):
    preferences: TRPreferences
    home_button_entity: Optional["TRHomeButtonEventEntity"] = None

    def save_preferences(self) -> None:
        """Save preferences while preserving unrelated sound.json keys."""
        if not isinstance(self.preferences, TRPreferences):
            super().save_preferences()
            return

        _LOGGER.debug("Saving preferences: %s", self.preferences_path)
        self.preferences_path.parent.mkdir(parents=True, exist_ok=True)

        existing_data: Dict[str, Any] = {}
        if self.preferences_path.exists():
            try:
                with open(self.preferences_path, "r", encoding="utf-8") as preferences_file:
                    loaded_data = json.load(preferences_file)
                if isinstance(loaded_data, dict):
                    existing_data = loaded_data
                else:
                    _LOGGER.warning("Preferences file does not contain a JSON object: %s", self.preferences_path)
            except Exception:
                _LOGGER.warning("Failed to load existing preferences from %s", self.preferences_path, exc_info=True)

        preferences_data = self.preferences.to_file_dict(existing_data)
        with open(self.preferences_path, "w", encoding="utf-8") as preferences_file:
            json.dump(
                preferences_data,
                preferences_file,
                ensure_ascii=False,
                indent=4,
            )
        self.preferences.remember_saved_data(preferences_data)
