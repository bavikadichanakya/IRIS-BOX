"""Simulated speaker client for IRIS WebSocket."""
import asyncio
import base64
import json
import logging
import sys

import websockets

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("simulate_speaker")

WS_URL = "ws://localhost:8000/ws/stream"

async def simulate():
    prompt = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "Say hello and introduce yourself"
    logger.info(f"Connecting to {WS_URL}...")

    try:
        async with websockets.connect(WS_URL) as ws:
            logger.info(f"Sending prompt: '{prompt}'")
            await ws.send(json.dumps({
                "prompt": prompt,
                "return_audio": True
            }))

            print("\n--- Iris Response ---")
            audio_buffer = bytearray()

            while True:
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=30.0)
                    data = json.loads(msg)
                    chunk_type = data.get("chunk_type")

                    if chunk_type == "text_delta":
                        print(data.get("delta_text", ""), end="", flush=True)
                    elif chunk_type == "complete":
                        print("\n\n[Text Generation Completed]")
                    elif chunk_type == "audio_start":
                        print("[Generating & Receiving Audio Stream...]")
                    elif chunk_type == "audio_chunk":
                        raw_bytes = base64.b64decode(data.get("data", ""))
                        audio_buffer.extend(raw_bytes)
                    elif chunk_type == "audio_end":
                        output_path = "iris_response.mp3"
                        with open(output_path, "wb") as f:
                            f.write(audio_buffer)
                        print(f"[Audio Stream Received: {len(audio_buffer)} bytes -> saved to {output_path}]")
                        break
                    elif "error" in data:
                        print(f"\n[Server Error]: {data['error']}")
                        break
                except asyncio.TimeoutError:
                    print("\n[Stream finished/timed out]")
                    break

    except Exception as e:
        logger.error(f"Speaker simulation failed: {e}")

if __name__ == '__main__':
    asyncio.run(simulate())
