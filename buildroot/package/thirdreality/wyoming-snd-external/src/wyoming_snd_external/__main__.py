#!/usr/bin/env python3
import argparse
import asyncio
import logging
import shlex
import time
from asyncio.subprocess import Process
from functools import partial
from pathlib import Path
from typing import Optional

from wyoming.audio import AudioChunk, AudioChunkConverter, AudioStart, AudioStop
from wyoming.event import Event
from wyoming.server import AsyncEventHandler, AsyncServer
from wyoming.snd import Played

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
        help="Number of samples to write at a time",
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
        self._proc: Optional[Process] = None
        self._chunk_converter = AudioChunkConverter(
            rate=self.cli_args.rate,
            width=self.cli_args.width,
            channels=self.cli_args.channels,
        )

        _LOGGER.debug("Client connected: %s", self.client_id)

    async def handle_event(self, event: Event) -> bool:
        if AudioStart.is_type(event.type):
            await self._start_proc()
        elif AudioStop.is_type(event.type):
            await self.write_event(Played().event())
        elif AudioChunk.is_type(event.type):
            await self._start_proc()

            chunk = AudioChunk.from_event(event)
            chunk = self._chunk_converter.convert(chunk)

            assert self._proc is not None
            assert self._proc.stdin is not None

            self._proc.stdin.write(chunk.audio)
            await self._proc.stdin.drain()

        return True

    async def _start_proc(self) -> None:
        if (self._proc is not None) and (self._proc.returncode is None):
            # Still running
            return

        _LOGGER.debug("Running %s", self.command)
        self._proc = await asyncio.create_subprocess_exec(
            self.command[0], *self.command[1:], stdin=asyncio.subprocess.PIPE
        )
        assert self._proc.stdin is not None

    async def _stop_proc(self) -> None:
        if self._proc is None:
            return

        try:
            self._proc.stdin.write_eof()
            await self._proc.stdin.wait_closed()
        finally:
            self._proc = None

    async def disconnect(self) -> None:
        await self._stop_proc()


# -----------------------------------------------------------------------------

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
