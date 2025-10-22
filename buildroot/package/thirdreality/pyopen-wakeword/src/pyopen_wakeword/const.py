from enum import Enum


class Model(str, Enum):
    """Built-in openWakeWord models."""

    OKAY_NABU = "okay_nabu"
    HEY_JARVIS = "hey_jarvis"
    HEY_MYCROFT = "hey_mycroft"
    ALEXA = "alexa"
    HEY_RHASSPY = "hey_rhasspy"
