"""ThirdReality supervisor — embedded HTTP API server."""

import logging

_LOGGER = logging.getLogger(__name__)


def start_supervisor_server() -> None:
    """Start the supervisor HTTP server in a background thread.

    Call this once during LVA startup. The server runs on port 8086
    and provides device info, OTA, and system command APIs.
    """
    try:
        from .supervisor import Supervisor

        supervisor = Supervisor()
        supervisor.start()
        _LOGGER.info("Supervisor HTTP server started on port 8086")
    except Exception:
        _LOGGER.warning("Failed to start supervisor HTTP server", exc_info=True)
