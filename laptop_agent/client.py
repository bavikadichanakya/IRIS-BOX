from __future__ import annotations
import asyncio
import json
import logging
import websockets
from typing import Optional

from laptop_agent.config import AgentConfig, load_config
from laptop_agent.dispatcher import ToolDispatcher

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("iris.laptop_agent.client")


class LaptopAgentClient:
    """
    WebSocket client that maintains a resilient connection between this laptop
    and the Phone A / IRIS Hub server.
    """

    def __init__(self, config: Optional[AgentConfig] = None):
        self.config = config or load_config()
        self.dispatcher = ToolDispatcher(device_name=self.config.device_name)
        self.is_running = False

    async def start(self):
        """Start agent connection loop with auto-reconnect."""
        self.is_running = True
        logger.info(f"Starting Laptop Agent for device '{self.config.device_name}'...")
        logger.info(f"Target Hub URL: {self.config.hub_url}")

        while self.is_running:
            try:
                logger.info(f"Connecting to IRIS Hub at {self.config.hub_url}...")
                async with websockets.connect(self.config.hub_url) as ws:
                    logger.info("Successfully connected to IRIS Hub!")

                    # 1. Send registration handshake
                    handshake = {
                        "type": "register",
                        "device": self.config.device_name,
                        "token": self.config.auth_token,
                        "capabilities": [
                            "open_app", "focus_window", "close_window", "type_text", "press_key", "volume",
                            "browser_open", "browser_search", "youtube_play", "claude_send", "browser_type",
                            "click_element", "fullscreen", "system_status", "run_command"
                        ]
                    }
                    await ws.send(json.dumps(handshake))

                    # 2. Start heartbeat & message listener concurrently
                    heartbeat_task = asyncio.create_task(self._heartbeat(ws))
                    receiver_task = asyncio.create_task(self._listen(ws))

                    done, pending = await asyncio.wait(
                        [heartbeat_task, receiver_task],
                        return_when=asyncio.FIRST_COMPLETED
                    )
                    for task in pending:
                        task.cancel()

            except (websockets.ConnectionClosed, ConnectionRefusedError, OSError) as exc:
                logger.warning(f"Connection lost or refused: {exc}. Retrying in {self.config.reconnect_interval_seconds}s...")
                await asyncio.sleep(self.config.reconnect_interval_seconds)
            except Exception as exc:
                logger.error(f"Unexpected error in agent loop: {exc}", exc_info=True)
                await asyncio.sleep(self.config.reconnect_interval_seconds)

    async def _heartbeat(self, ws):
        """Send periodic heartbeat ping to prevent connection timeout."""
        try:
            while True:
                await asyncio.sleep(self.config.heartbeat_seconds)
                ping = {"type": "ping", "device": self.config.device_name}
                await ws.send(json.dumps(ping))
        except asyncio.CancelledError:
            pass

    async def _listen(self, ws):
        """Listen for incoming tool commands from Phone A."""
        async for raw_msg in ws:
            try:
                payload = json.loads(raw_msg)
                msg_type = payload.get("type")

                if msg_type == "pong":
                    continue

                logger.info(f"Received payload: {payload}")
                msg_id = payload.get("id")

                # Dispatch tool call
                result = await self.dispatcher.dispatch(payload)

                # Send execution result back to hub
                response = {
                    "type": "tool_result",
                    "id": msg_id,
                    "device": self.config.device_name,
                    "result": result
                }
                await ws.send(json.dumps(response))
                logger.info(f"Execution complete: {result.get('message', 'done')}")

            except json.JSONDecodeError:
                logger.error(f"Malformed JSON received: {raw_msg}")
            except Exception as exc:
                logger.error(f"Error executing received command: {exc}", exc_info=True)


if __name__ == "__main__":
    client = LaptopAgentClient()
    try:
        asyncio.run(client.start())
    except KeyboardInterrupt:
        logger.info("Agent stopped by user.")
