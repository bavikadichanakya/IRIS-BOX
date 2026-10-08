"""
Simple script to simulate a speaker client.

It connects to the WebSocket endpoint ``ws://localhost:8000/ws/audio``,
streams a short piece of synthetic audio (as raw bytes) and prints any
responses received from the server.

The script is deliberately lightweight – it does **not** depend on any
audio hardware or external services, making it suitable for CI runs
or local debugging.

Usage
-----
    python scripts/simulate_speaker.py

If you want to customise the message or the endpoint, set the
environment variables ``SIM_SPEAKER_WS_URL`` and ``SIM_SPEAKER_TEXT``.
"""

import asyncio
import os
import json
import logging
import sys

try:
    import websockets
except ImportError:  # pragma: no cover
    sys.stderr.write(
        "The 'websockets' package is required to run this script. "
        "Install it with: pip install websockets\n"
    )
    raise

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #
DEFAULT_WS_URL = "ws://localhost:8000/ws/audio"
DEFAULT_TEXT = "Hello, this is a simulated speaker sending synthetic audio."

WS_URL = os.getenv("SIM_SPEAKER_WS_URL", DEFAULT_WS_URL)
TEXT = os.getenv("SIM_SPEAKER_TEXT", DEFAULT_TEXT)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s - %(message)s",
)
log = logging.getLogger("simulate_speaker")


async def _send_synthetic_audio(ws):
    """
    Sends a very small, synthetic “audio” payload.

    The server expects binary data – we simply send the UTF‑8 encoded
    text as a placeholder. In a real scenario you would stream PCM or
    Opus frames.
    """
    # Encode the text as bytes; this is just a stand‑in for real audio.
    audio_bytes = TEXT.encode("utf-8")
    log.info("Sending %d bytes of synthetic audio to %s", len(audio_bytes), WS_URL)
    await ws.send(audio_bytes)


async def _receive_loop(ws):
    """
    Continuously receives messages from the server and logs them.
    The loop exits when the server closes the connection.
    """
    try:
        async for message in ws:
            if isinstance(message, bytes):
                log.info("Received binary message (%d bytes)", len(message))
            else:
                # Assume JSON/text payload
                try:
                    payload = json.loads(message)
                    log.info("Received JSON message: %s", json.dumps(payload, indent=2))
                except json.JSONDecodeError:
                    log.info("Received text message: %s", message)
    except websockets.ConnectionClosedOK:
        log.info("WebSocket connection closed cleanly.")
    except Exception as exc:  # pragma: no cover
        log.exception("Error while receiving messages: %s", exc)


async def main():
    log.info("Connecting to %s", WS_URL)
    async with websockets.connect(WS_URL) as ws:
        # Fire‑and‑forget the receiver so we can both send and listen.
        receive_task = asyncio.create_task(_receive_loop(ws))

        await _send_synthetic_audio(ws)

        # Give the server a moment to respond before we close.
        await asyncio.sleep(1)

        # Gracefully close the connection.
        await ws.close()
        await receive_task


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:  # pragma: no cover
        log.info("Simulation interrupted by user.")
