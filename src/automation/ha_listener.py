import asyncio
import json
import logging
from typing import Optional, Dict, Any

import websockets

from src.config.settings import settings
from src.observability.event_bus import EventBus
from src.observability.tracing import create_trace_context

logger = logging.getLogger("iris.automation.ha_listener")


class HomeAssistantWSClient:
    """
    Persistent Home Assistant WebSocket Client.
    Connects to native /api/websocket endpoint, authenticates via Long-Lived Access Token,
    and streams state_changed events onto the IRIS EventBus.
    Enforces strict zero-mock policy: without valid credentials, sets status to DISABLED.
    """

    def __init__(
        self,
        url: Optional[str] = None,
        token: Optional[str] = None,
        event_bus: Optional[EventBus] = None,
        reconnect_interval_min: float = 1.0,
        reconnect_interval_max: float = 30.0,
    ):
        self.url = url or settings.HA_WS_URL
        self.token = token if token is not None else settings.HA_TOKEN
        self.event_bus = event_bus or EventBus()
        self.reconnect_interval_min = reconnect_interval_min
        self.reconnect_interval_max = reconnect_interval_max

        self.status = "DISABLED" if not self.token or not settings.PROACTIVE_ENABLED else "DISCONNECTED"
        self._stopped = False
        self._task: Optional[asyncio.Task] = None
        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._sub_id = 1
        self._events_received_count = 0

    @property
    def is_connected(self) -> bool:
        return self.status == "CONNECTED" and self._ws is not None

    async def start(self) -> None:
        """Starts the persistent WebSocket connection task."""
        if not self.token or not settings.PROACTIVE_ENABLED:
            self.status = "DISABLED"
            logger.info(
                "Home Assistant WebSocket listener is DISABLED (missing HA_TOKEN or PROACTIVE_ENABLED=False). "
                "Adhering to strict zero-mock policy; no synthetic events will be emitted."
            )
            return

        self._stopped = False
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run_loop())
            logger.info("Home Assistant WebSocket listener task started for %s", self.url)

    async def _run_loop(self) -> None:
        """Main connection and auto-reconnection loop with exponential backoff."""
        delay = self.reconnect_interval_min
        while not self._stopped:
            self.status = "CONNECTING"
            try:
                logger.debug("Connecting to Home Assistant WebSocket at %s...", self.url)
                async with websockets.connect(self.url) as ws:
                    self._ws = ws
                    # Step 1: Wait for auth_required message from HA
                    raw_init = await ws.recv()
                    init_msg = json.loads(raw_init)
                    if init_msg.get("type") != "auth_required":
                        logger.error("Unexpected initial HA message: %s", init_msg)
                        self.status = "DISCONNECTED"
                        await asyncio.sleep(delay)
                        delay = min(delay * 2, self.reconnect_interval_max)
                        continue

                    # Step 2: Send auth credentials
                    auth_payload = {"type": "auth", "access_token": self.token}
                    await ws.send(json.dumps(auth_payload))

                    # Step 3: Receive auth_ok or auth_invalid
                    raw_auth = await ws.recv()
                    auth_resp = json.loads(raw_auth)
                    if auth_resp.get("type") != "auth_ok":
                        logger.error("Home Assistant authentication failed: %s", auth_resp)
                        self.status = "DISCONNECTED"
                        await asyncio.sleep(delay)
                        delay = min(delay * 2, self.reconnect_interval_max)
                        continue

                    # Step 4: Successfully authenticated -> Subscribe to state_changed events
                    self.status = "CONNECTED"
                    delay = self.reconnect_interval_min
                    logger.info("Authenticated with Home Assistant at %s. Subscribing to state_changed...", self.url)

                    self._sub_id = 1
                    sub_payload = {
                        "id": self._sub_id,
                        "type": "subscribe_events",
                        "event_type": "state_changed",
                    }
                    await ws.send(json.dumps(sub_payload))

                    # Publish connection event on EventBus
                    trace = create_trace_context(device_id="ha_bridge", session_id="ha_ws")
                    await self.event_bus.publish(
                        "ha.connected",
                        {"url": self.url, "status": "CONNECTED"},
                        trace=trace,
                    )

                    # Step 5: Read event loop
                    async for raw_msg in ws:
                        if self._stopped:
                            break
                        try:
                            msg = json.loads(raw_msg)
                            msg_type = msg.get("type")
                            if msg_type == "event":
                                evt = msg.get("event", {})
                                if evt.get("event_type") == "state_changed":
                                    event_data = evt.get("data", {})
                                    self._events_received_count += 1
                                    trace_evt = create_trace_context(device_id="ha_bridge", session_id="ha_ws")
                                    await self.event_bus.publish(
                                        "ha.state_changed",
                                        event_data,
                                        trace=trace_evt,
                                    )
                        except json.JSONDecodeError:
                            logger.warning("Failed to decode HA message: %s", raw_msg)
                        except Exception as ex:
                            logger.error("Error processing HA state change event: %s", ex)

            except (websockets.ConnectionClosed, OSError, asyncio.CancelledError, Exception) as exc:
                if self._stopped:
                    break
                self.status = "DISCONNECTED"
                logger.warning("Home Assistant WS connection lost: %s. Reconnecting in %.1fs...", exc, delay)
                await asyncio.sleep(delay)
                delay = min(delay * 2, self.reconnect_interval_max)
            finally:
                self._ws = None

        if self._stopped:
            self.status = "DISCONNECTED"
            logger.info("Home Assistant WebSocket listener loop terminated.")

    async def stop(self) -> None:
        """Gracefully shuts down connection and background task."""
        self._stopped = True
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None

        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

        self.status = "DISCONNECTED" if self.token and settings.PROACTIVE_ENABLED else "DISABLED"
        logger.info("Home Assistant WebSocket client stopped.")
