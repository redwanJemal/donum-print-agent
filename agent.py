"""Donum QMS print agent.

Runs at a store, dials out to the Donum QMS backend over a WebSocket, and
spools the ESC/POS token receipts the backend pushes to a local thermal
printer.

This is a standalone program — it has no dependency on the backend code.
Its only contract is the WebSocket protocol:

    connect:  ws(s)://<host>/ws/print?api_key=<tenant-api-key>
    receive:  {"type": "connected"}
              {"type": "print", "order_number": ..., "payload_base64": ...}

Configure it with a ``.env`` file (copy ``.env.example``), then run::

    python agent.py              # connect and print jobs
    python agent.py --selftest   # print a test slip, no network involved
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import sys
from datetime import datetime
from logging.handlers import RotatingFileHandler
from os import environ

try:  # python-dotenv is convenient but optional — plain env vars also work.
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

import websockets

# --- configuration -------------------------------------------------------

WS_URL = environ.get("CLOUD_WS_URL", "ws://localhost:8000/ws/print").rstrip("/")
API_KEY = environ.get("AGENT_API_KEY", "").strip()
PRINTER_NAME = environ.get("PRINTER_NAME", "").strip()
LOG_LEVEL = environ.get("LOG_LEVEL", "INFO").upper()
HEARTBEAT_SECONDS = int(environ.get("HEARTBEAT_SECONDS", "60"))
RECONNECT_SECONDS = 5

log = logging.getLogger("print-agent")

# Count of jobs handled this run — surfaced in the heartbeat log line.
_jobs_printed = 0


# --- logging -------------------------------------------------------------


def setup_logging() -> None:
    """Log to the console and to a rotating file, so a problem from hours
    ago is still inspectable after the console has scrolled away."""

    log.setLevel(LOG_LEVEL)
    fmt = logging.Formatter(
        "%(asctime)s  %(levelname)-7s %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    log.addHandler(console)
    rotating = RotatingFileHandler(
        "print-agent.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8"
    )
    rotating.setFormatter(fmt)
    log.addHandler(rotating)


# --- printing ------------------------------------------------------------


def print_raw(data: bytes, order_number: str) -> None:
    """Send raw ESC/POS bytes to the configured printer.

    On Windows the bytes go to the spooler as a RAW job. On any other OS —
    or if pywin32 is missing — the agent runs dry: it writes the bytes to a
    ``.bin`` file so the connection can still be tested without a printer.
    """

    global _jobs_printed
    try:
        import win32print
    except ImportError:
        path = f"job-{order_number}.bin"
        with open(path, "wb") as handle:
            handle.write(data)
        log.warning(
            "DRY RUN (no Windows printer): wrote %d bytes to %s",
            len(data),
            path,
        )
        _jobs_printed += 1
        return

    printer = PRINTER_NAME or win32print.GetDefaultPrinter()
    handle = win32print.OpenPrinter(printer)
    try:
        win32print.StartDocPrinter(
            handle, 1, (f"QMS token {order_number}", None, "RAW")
        )
        win32print.StartPagePrinter(handle)
        win32print.WritePrinter(handle, data)
        win32print.EndPagePrinter(handle)
        win32print.EndDocPrinter(handle)
    finally:
        win32print.ClosePrinter(handle)
    _jobs_printed += 1
    log.info("Printed order %s on '%s'.", order_number, printer)


# --- websocket client ----------------------------------------------------


async def heartbeat() -> None:
    """Emit a liveness line periodically so the operator can tell the agent
    is connected and idle rather than hung."""

    while True:
        await asyncio.sleep(HEARTBEAT_SECONDS)
        log.info("link alive -- %d job(s) printed since start", _jobs_printed)


async def handle_messages(ws) -> None:
    """Process every frame the backend sends until the socket closes."""

    async for raw in ws:
        try:
            message = json.loads(raw)
        except (TypeError, ValueError):
            log.warning("Ignored a non-JSON message.")
            continue

        kind = message.get("type")
        if kind == "connected":
            log.info("Connected and authenticated -- waiting for print jobs.")
        elif kind == "print":
            order = message.get("order_number", "?")
            log.info("Print job received: order %s.", order)
            try:
                data = base64.b64decode(message.get("payload_base64", ""))
                print_raw(data, order)
            except Exception as exc:  # one bad job must not kill the agent
                log.error("Print FAILED for order %s: %s", order, exc)
        else:
            log.debug("Ignored message of type %r.", kind)


async def run_once() -> None:
    """Open one WebSocket session and serve it until it drops."""

    log.info("Connecting to %s ...", WS_URL)
    async with websockets.connect(
        f"{WS_URL}?api_key={API_KEY}", open_timeout=15
    ) as ws:
        beat = asyncio.create_task(heartbeat())
        try:
            await handle_messages(ws)
        finally:
            beat.cancel()


def _http_status(exc: Exception) -> int | None:
    """Pull an HTTP status off a websockets handshake error, across library
    versions: v12 exposes ``status_code`` directly; v13+ nests it under a
    ``response`` object."""

    status = getattr(exc, "status_code", None)
    if status is None:
        status = getattr(getattr(exc, "response", None), "status_code", None)
    return status


async def main_loop() -> None:
    """Stay connected: reconnect after any drop. Give up only when the API
    key is rejected -- retrying that just spams the log until .env is fixed."""

    while True:
        try:
            await run_once()
            log.warning(
                "Connection closed by the server. Reconnecting in %ds ...",
                RECONNECT_SECONDS,
            )
        except Exception as exc:
            if _http_status(exc) == 403:
                log.error(
                    "AUTHENTICATION FAILED (HTTP 403) -- AGENT_API_KEY is "
                    "wrong or revoked. Fix .env and restart the agent."
                )
                return
            log.error(
                "Connection problem: %s. Retrying in %ds ...",
                exc,
                RECONNECT_SECONDS,
            )
        await asyncio.sleep(RECONNECT_SECONDS)


# --- self test -----------------------------------------------------------


def selftest() -> None:
    """Print a test slip straight to the printer — proves the printer and
    PRINTER_NAME are right, independent of the network."""

    init = b"\x1b@"
    cut = b"\x1dV\x01"
    body = (
        "\n  DONUM PRINT AGENT\n"
        "  Self-test OK\n"
        f"  {datetime.now():%Y-%m-%d %H:%M:%S}\n\n\n"
    ).encode("ascii")
    print_raw(init + body + cut, "selftest")
    log.info("Self-test slip sent.")


# --- entrypoint ----------------------------------------------------------


def _masked(key: str) -> str:
    if not key:
        return "(not set)"
    if len(key) <= 8:
        return "*" * len(key)
    return f"{key[:4]}...{key[-4:]}"


def main() -> None:
    setup_logging()
    log.info("=== Donum QMS print agent ===")
    log.info("Server  : %s", WS_URL)
    log.info("Printer : %s", PRINTER_NAME or "(system default)")
    log.info("API key : %s", _masked(API_KEY))

    if "--selftest" in sys.argv:
        selftest()
        return

    if not API_KEY:
        log.error(
            "AGENT_API_KEY is not set. Copy .env.example to .env and fill it in."
        )
        sys.exit(1)

    try:
        asyncio.run(main_loop())
    except KeyboardInterrupt:
        log.info("Stopped.")


if __name__ == "__main__":
    main()
