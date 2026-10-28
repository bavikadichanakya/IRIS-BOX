from __future__ import annotations
import asyncio
import json
import logging
import websockets
from typing import Dict, Any

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("iris.mock_hub")

# Map of registered devices: device_name -> websocket
CONNECTED_DEVICES: Dict[str, websockets.WebSocketServerProtocol] = {}


async def ws_handler(websocket, path):
    """Handle connection from Laptop Agent."""
    device_name = "unknown"
    try:
        async for raw_msg in websocket:
            try:
                data = json.loads(raw_msg)
                msg_type = data.get("type")

                if msg_type == "register":
                    device_name = data.get("device", "unknown")
                    token = data.get("token")
                    logger.info(f"==> Device '{device_name}' connected with token '{token}'")
                    CONNECTED_DEVICES[device_name] = websocket
                    ack = {"type": "registered", "device": device_name, "status": "ok"}
                    await websocket.send(json.dumps(ack))

                elif msg_type == "ping":
                    pong = {"type": "pong", "device": device_name}
                    await websocket.send(json.dumps(pong))

                elif msg_type == "tool_result":
                    tool_id = data.get("id")
                    result = data.get("result", {})
                    logger.info(f"<== Received result from [{device_name}] (ID: {tool_id}):")
                    print("\n" + "=" * 60)
                    print(f"RESULT FROM {device_name.upper()} (Tool: {result.get('tool')}):")
                    print(json.dumps(result, indent=2))
                    print("=" * 60 + "\n")

            except json.JSONDecodeError:
                logger.error(f"Malformed JSON: {raw_msg}")

    except websockets.ConnectionClosed:
        logger.info(f"Device '{device_name}' disconnected.")
    finally:
        if device_name in CONNECTED_DEVICES:
            del CONNECTED_DEVICES[device_name]


async def cli_sender():
    """Terminal loop allowing manual dispatch of commands to connected laptops."""
    await asyncio.sleep(1.0)
    print("\n" + "=" * 60)
    print("  MOCK PHONE A HUB SERVER RUNNING ON ws://127.0.0.1:8000/ws/agent")
    print("=" * 60)
    print("Waiting for laptop agents to connect...")

    loop = asyncio.get_running_loop()

    while True:
        # Prompt user for JSON command in an async-friendly way
        user_input = await loop.run_in_executor(
            None,
            lambda: input("\n[Phone A Hub] Enter JSON command (or 'help' / 'devices' / 'q'): ").strip()
        )

        if not user_input:
            continue
        if user_input.lower() in ("q", "quit", "exit"):
            print("Stopping mock hub...")
            break
        if user_input.lower() == "devices":
            print(f"Connected devices: {list(CONNECTED_DEVICES.keys())}")
            continue
        if user_input.lower() == "help":
            print("""
Sample commands:
1. YouTube:
   {"device": "laptop1", "tool": "youtube_play", "args": {"query": "soothing lofi", "nth": 1, "fullscreen": true}}
2. Claude:
   {"device": "laptop1", "tool": "claude_send", "args": {"prompt": "what is the population of earth"}}
3. Any Website:
   {"device": "laptop1", "tool": "browser_open", "args": {"url": "https://wikipedia.org"}}
4. Open Notepad:
   {"device": "laptop1", "tool": "open_app", "args": {"name": "notepad"}}
5. Type Text:
   {"device": "laptop1", "tool": "type_text", "args": {"text": "Hello from Phone A!\n", "press_enter": true}}
6. Volume:
   {"device": "laptop1", "tool": "volume", "args": {"action": "up", "steps": 3}}
7. System Status:
   {"device": "laptop1", "tool": "system_status"}
            """)
            continue

        try:
            payload = json.loads(user_input)
            target = payload.get("device", "laptop1")

            if target in CONNECTED_DEVICES:
                ws = CONNECTED_DEVICES[target]
                payload["id"] = f"cmd-{int(asyncio.get_event_loop().time())}"
                await ws.send(json.dumps(payload))
                logger.info(f"Sent command to {target} (ID: {payload['id']})")
            else:
                print(f"Error: Target device '{target}' is not connected. Connected: {list(CONNECTED_DEVICES.keys())}")
        except json.JSONDecodeError as e:
            print(f"Error: Invalid JSON ({e})")


async def main():
    server = await websockets.serve(ws_handler, "127.0.0.1", 8000)
    logger.info("Mock Hub WebSocket server listening on ws://127.0.0.1:8000")
    try:
        await cli_sender()
    finally:
        server.close()
        await server.wait_closed()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nHub stopped.")
