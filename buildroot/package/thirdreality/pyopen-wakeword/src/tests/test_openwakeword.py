"""Tests for openWakeWord."""

import itertools
import wave
from pathlib import Path

import pytest

from pyopen_wakeword import OpenWakeWord, Model, OpenWakeWordFeatures

_DIR = Path(__file__).parent

_MODELS = set(Model)
_NUM_WAVS = 3
_PROB_THRESHOLD = 0.5


def _load_wav(model_name: str, number: int) -> bytes:
    wav_path = _DIR / model_name / f"{number}.wav"
    with wave.open(str(wav_path), "rb") as wav_file:
        assert wav_file.getframerate() == 16000
        assert wav_file.getsampwidth() == 2
        assert wav_file.getnchannels() == 1

        return wav_file.readframes(wav_file.getnframes())


@pytest.mark.parametrize(
    "model,number", list(itertools.product(_MODELS, range(1, _NUM_WAVS + 1)))
)
def test_process_streaming(model: Model, number: int) -> None:
    """Test streaming processing."""
    oww = OpenWakeWord.from_builtin(model)
    oww_features = OpenWakeWordFeatures.from_builtin()

    # positive
    audio_bytes = _load_wav(model.value, number)
    detected = False
    for features in oww_features.process_streaming(audio_bytes):
        for prob in oww.process_streaming(features):
            if prob > _PROB_THRESHOLD:
                detected = True
                break

        if detected:
            break

    assert detected, (model.value, number)

    # Use other wake word samples as negative samples
    for other_model in _MODELS:
        if model == other_model:
            continue

        detected = False
        oww.reset()
        oww_features.reset()

        audio_bytes = _load_wav(other_model.value, number)
        for features in oww_features.process_streaming(audio_bytes):
            for prob in oww.process_streaming(features):
                if prob > _PROB_THRESHOLD:
                    detected = True
                    break

            if detected:
                break

        assert not detected, (model.value, other_model.value, number)


def test_close() -> None:
    """Test releasing of resources."""
    oww = OpenWakeWord.from_builtin(Model.OKAY_NABU)
    oww_features = OpenWakeWordFeatures.from_builtin()

    embs = list(oww_features.process_streaming(bytes(16000 * 2)))
    assert embs

    probs = [p for emb in embs for p in oww.process_streaming(emb)]
    assert probs

    # Release resources
    oww_features.close()
    assert not list(oww_features.process_streaming(bytes(16000 * 2)))

    oww.close()
    assert not [p for emb in embs for p in oww.process_streaming(emb)]
