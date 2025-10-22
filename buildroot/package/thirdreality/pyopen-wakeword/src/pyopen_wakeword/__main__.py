"""Command-line utility for openWakeWord."""

import argparse
import sys
import wave

from .const import Model
from .openwakeword import OpenWakeWord, OpenWakeWordFeatures


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--model", required=True, help="Path to TFLite model or name of builtin model"
    )
    parser.add_argument("wav_file", nargs="*")
    parser.add_argument("--probability-threshold", type=float, default=0.5)
    args = parser.parse_args()

    try:
        model = Model(args.model)
        oww = OpenWakeWord.from_builtin(model)
    except ValueError:
        oww = OpenWakeWord.from_model(args.model)

    oww_features = OpenWakeWordFeatures.from_builtin()

    if args.wav_file:
        for wav_path in args.wav_file:
            with wave.open(wav_path, "rb") as wav_file:
                assert wav_file.getframerate() == 16000, "16Khz required"
                assert wav_file.getsampwidth() == 2, "16-bit samples required"
                assert wav_file.getnchannels() == 1, "Mono required"

                audio_bytes = wav_file.readframes(wav_file.getnframes())
                detected = False
                for features in oww_features.process_streaming(audio_bytes):
                    for prob in oww.process_streaming(features):
                        if prob > args.probability_threshold:
                            print(wav_path, "detected")
                            detected = True
                            break

                    if detected:
                        break

                if not detected:
                    print(wav_path, "not-detected")

                oww.reset()
                oww_features.reset()
    else:
        # Live
        try:
            while True:
                chunk = sys.stdin.buffer.read(2048)
                if not chunk:
                    break

                for features in oww_features.process_streaming(chunk):
                    for prob in oww.process_streaming(features):
                        if prob > args.probability_threshold:
                            print(args.model, flush=True)

        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
