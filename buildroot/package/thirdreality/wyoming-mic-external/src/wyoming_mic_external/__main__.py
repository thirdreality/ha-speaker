#!/usr/bin/env python3
import argparse
import asyncio
import logging
import shlex
import struct
import time
from functools import partial
from pathlib import Path

from wyoming.audio import AudioChunk, AudioStart
from wyoming.event import Event
from wyoming.server import AsyncEventHandler, AsyncServer

# Import WebRTC Audio Processing
try:
    from webrtc_audio_processing import AudioProcessingModule as AP
    HAS_WEBRTC_AP = True
except ImportError:
    HAS_WEBRTC_AP = False
    logging.warning("webrtc_audio_processing not available, AFE disabled")

_LOGGER = logging.getLogger()
_DIR = Path(__file__).parent


async def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--program", required=True, help="Program to run with arguments"
    )
    parser.add_argument(
        "--rate", required=True, type=int, help="Sample rate of audio (hertz)"
    )
    parser.add_argument(
        "--width", required=True, type=int, help="Sample width of audio (bytes)"
    )
    parser.add_argument(
        "--channels", required=True, type=int, help="Number of channels in audio"
    )
    parser.add_argument(
        "--samples-per-chunk",
        type=int,
        default=1024,
        help="Number of samples to read at a time",
    )
    parser.add_argument("--uri", default="stdio://", help="unix:// or tcp://")
    #
    # AFE (Audio Front-End) options
    parser.add_argument(
        "--enable-afe", action="store_true", help="Enable Audio Front-End processing"
    )
    parser.add_argument(
        "--afe-ns-level", type=int, default=3, choices=[0, 1, 2, 3],
        help="Noise suppression level (0=off, 1=low, 2=moderate, 3=high, default=3)"
    )
    parser.add_argument(
        "--afe-agc", action="store_true", help="Enable Automatic Gain Control"
    )
    parser.add_argument(
        "--afe-agc-target", type=int, default=6,
        help="AGC target level in dBFs (0-31, lower=more gain, default=6)"
    )
    parser.add_argument(
        "--afe-vad", action="store_true", help="Enable Voice Activity Detection"
    )
    parser.add_argument(
        "--afe-vad-level", type=int, default=2, choices=[0, 1, 2, 3],
        help="VAD sensitivity (0=low, 3=high, default=2)"
    )
    parser.add_argument(
        "--afe-log-vad", action="store_true",
        help="Log voice activity detection statistics"
    )
    #
    parser.add_argument("--debug", action="store_true", help="Log DEBUG messages")
    parser.add_argument(
        "--log-format", default=logging.BASIC_FORMAT, help="Format for log messages"
    )

    args = parser.parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO, format=args.log_format
    )
    _LOGGER.debug(args)

    if args.enable_afe and not HAS_WEBRTC_AP:
        _LOGGER.error("AFE requested but webrtc_audio_processing not available")
        return

    _LOGGER.info("Ready")

    # Start server
    server = AsyncServer.from_uri(args.uri)

    try:
        await server.run(partial(ExternalEventHandler, args))
    except KeyboardInterrupt:
        pass


# -----------------------------------------------------------------------------


class ExternalEventHandler(AsyncEventHandler):
    """Event handler for clients."""

    def __init__(
        self,
        cli_args: argparse.Namespace,
        *args,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)

        self.cli_args = cli_args
        self.client_id = str(time.monotonic_ns())
        self.command = shlex.split(self.cli_args.program)

        # Initialize AFE if enabled
        self.afe_enabled = cli_args.enable_afe and HAS_WEBRTC_AP
        self.afe_log_vad = cli_args.afe_log_vad if cli_args.enable_afe else False
        self.vad_frame_count = 0
        self.voice_frame_count = 0
        self.ap = None

        if self.afe_enabled:
            try:
                # Determine AGC type: 0=off, 1=digital, 2=analog
                agc_type = 1 if cli_args.afe_agc else 0

                self.ap = AP(
                    aec_type=0,  # No echo cancellation
                    enable_ns=(cli_args.afe_ns_level > 0),
                    agc_type=agc_type,  # 0=off, 1=adaptive digital
                    enable_vad=cli_args.afe_vad
                )

                # WebRTC AP processes mono audio at the specified rate
                self.ap.set_stream_format(cli_args.rate, 1)

                # Set NS level (0-3) - Higher = more aggressive noise suppression
                if cli_args.afe_ns_level > 0:
                    self.ap.set_ns_level(cli_args.afe_ns_level)

                # Set AGC target level (lower dBFs = more gain)
                # Default is 30 dBFs, we use lower values (3-9) for better far-field detection
                if agc_type > 0:
                    agc_target = max(0, min(31, cli_args.afe_agc_target))
                    self.ap.set_agc_target(agc_target)
                    _LOGGER.info("AGC target set to %d dBFs (lower=more gain)", agc_target)

                # Set VAD level (0-3) - Higher = more sensitive
                if cli_args.afe_vad:
                    vad_level = cli_args.afe_vad_level
                    self.ap.set_vad_level(vad_level)
                    _LOGGER.info("VAD level set to %d (higher=more sensitive)", vad_level)

                _LOGGER.info(
                    "AFE initialized successfully: NS=%d, AGC=%s (target=%ddBFs), VAD=%s (level=%d)",
                    cli_args.afe_ns_level,
                    "digital" if agc_type == 1 else "off",
                    cli_args.afe_agc_target if agc_type > 0 else 0,
                    "enabled" if cli_args.afe_vad else "disabled",
                    cli_args.afe_vad_level if cli_args.afe_vad else 0
                )
            except Exception as e:
                _LOGGER.error("Failed to initialize AFE: %s", e)
                _LOGGER.exception("AFE initialization error details")
                self.afe_enabled = False

        self.run_task = asyncio.create_task(self.run_mic())
        _LOGGER.debug("Client connected: %s", self.client_id)

    async def handle_event(self, event: Event) -> bool:
        # Output only
        return True

    def _process_audio_chunk(self, audio_bytes: bytes) -> bytes:
        """Process audio through AFE (WebRTC Audio Processing)."""
        if not self.afe_enabled or not self.ap:
            return audio_bytes

        try:
            rate = self.cli_args.rate
            width = self.cli_args.width
            channels = self.cli_args.channels

            # If stereo, convert to mono by averaging channels
            if channels == 2:
                # Convert bytes to samples (16-bit signed integers)
                num_samples = len(audio_bytes) // width
                samples = struct.unpack(f'<{num_samples}h', audio_bytes)
                # Average stereo channels to mono
                mono_samples = [(samples[i] + samples[i+1]) // 2 
                               for i in range(0, len(samples), 2)]
                # Convert back to bytes
                mono_bytes = struct.pack(f'<{len(mono_samples)}h', *mono_samples)
            else:
                mono_bytes = audio_bytes

            # Process in 10ms chunks (WebRTC AP requirement)
            processed_chunks = []
            chunk_size_mono = int(rate * 0.01) * width  # 10ms in bytes
            voice_detected_in_chunk = False

            for i in range(0, len(mono_bytes), chunk_size_mono):
                chunk = mono_bytes[i:i + chunk_size_mono]
                if len(chunk) == chunk_size_mono:
                    # Process full 10ms chunk
                    processed_chunk = self.ap.process_stream(chunk)
                    processed_chunks.append(processed_chunk)

                    # Check VAD if enabled
                    if self.cli_args.afe_vad:
                        if self.ap.has_voice():
                            voice_detected_in_chunk = True
                            self.voice_frame_count += 1
                        self.vad_frame_count += 1
                else:
                    # Pad incomplete chunk with silence
                    padded_chunk = chunk + b'\x00' * (chunk_size_mono - len(chunk))
                    processed_chunk = self.ap.process_stream(padded_chunk)
                    # Only keep the original length
                    processed_chunks.append(processed_chunk[:len(chunk)])

            # Log VAD statistics periodically
            if self.afe_log_vad and self.vad_frame_count > 0:
                if self.vad_frame_count % 1000 == 0:  # Every 10 seconds at 16kHz
                    voice_ratio = (self.voice_frame_count / self.vad_frame_count) * 100
                    _LOGGER.info(
                        "VAD stats: %.1f%% voice detected (%d/%d frames)",
                        voice_ratio, self.voice_frame_count, self.vad_frame_count
                    )

            processed_mono = b''.join(processed_chunks)

            # Convert mono back to stereo if needed
            if channels == 2:
                num_mono_samples = len(processed_mono) // width
                mono_samples = struct.unpack(f'<{num_mono_samples}h', processed_mono)
                # Duplicate mono to stereo (L=R)
                stereo_samples = []
                for sample in mono_samples:
                    stereo_samples.extend([sample, sample])
                processed_audio = struct.pack(f'<{len(stereo_samples)}h', *stereo_samples)
            else:
                processed_audio = processed_mono

            return processed_audio

        except Exception as e:
            _LOGGER.exception("Error processing audio through AFE: %s", e)
            return audio_bytes

    async def run_mic(self) -> None:
        try:
            _LOGGER.debug("Running %s", self.command)
            proc = await asyncio.create_subprocess_exec(
                self.command[0], *self.command[1:], stdout=asyncio.subprocess.PIPE
            )
            assert proc.stdout is not None

            rate = self.cli_args.rate
            width = self.cli_args.width
            channels = self.cli_args.channels
            await self.write_event(
                AudioStart(
                    rate=rate,
                    width=width,
                    channels=channels,
                    timestamp=time.monotonic_ns(),
                ).event()
            )

            bytes_per_chunk = self.cli_args.samples_per_chunk * width * channels
            _LOGGER.info("Streaming audio to server (AFE: %s)", 
                        "enabled" if self.afe_enabled else "disabled")

            while True:
                audio_bytes = await proc.stdout.readexactly(bytes_per_chunk)

                # Process through AFE if enabled
                processed_audio = self._process_audio_chunk(audio_bytes)

                chunk = AudioChunk(
                    rate=rate,
                    width=width,
                    channels=channels,
                    audio=processed_audio,
                    timestamp=time.monotonic_ns(),
                )
                await self.write_event(chunk.event())
        except Exception:
            _LOGGER.exception("Unexpected error in run_mic")


# -----------------------------------------------------------------------------

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass