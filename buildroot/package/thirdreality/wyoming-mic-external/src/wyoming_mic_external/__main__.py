#!/usr/bin/env python3
import argparse
import asyncio
import logging
import shlex
import time
from functools import partial
from pathlib import Path

from wyoming.audio import AudioChunk, AudioStart
from wyoming.event import Event
from wyoming.server import AsyncEventHandler, AsyncServer

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
    parser.add_argument("--debug", action="store_true", help="Log DEBUG messages")
    parser.add_argument(
        "--log-format", default=logging.BASIC_FORMAT, help="Format for log messages"
    )

    args = parser.parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO, format=args.log_format
    )
    _LOGGER.debug(args)

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
        self.run_task = asyncio.create_task(self.run_mic())

        _LOGGER.debug("Client connected: %s", self.client_id)

    async def handle_event(self, event: Event) -> bool:
        # Output only
        return True

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
            _LOGGER.info("Streaming audio to server")

            while True:
                audio_bytes = await proc.stdout.readexactly(bytes_per_chunk)
                chunk = AudioChunk(
                    rate=rate,
                    width=width,
                    channels=channels,
                    audio=audio_bytes,
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
