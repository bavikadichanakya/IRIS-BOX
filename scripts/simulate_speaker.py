"""Simulated audio speaker for Iris backend WebSocket."""
import asyncio
import io
import logging
import wave
import websockets

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("simulate_speaker")

WS_URL = "ws://localhost:8000/ws/audio"

def make_chunk(ms=500, rate=16000):
    buf = io.BytesIO()
    with wave.open(buf, 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(b'\x00\x00' * int(rate * (ms / 1000.0)))
    return buf.getvalue()

async def simulate():
    logger.info(f"Connecting to {WS_URL}...")
    try:
        async with websockets.connect(WS_URL) as ws:
            logger.info("Connected. Streaming audio frames...")
            for i in range(3):
                await ws.send(make_chunk())
                logger.info(f"Sent chunk {i+1}/3")
                await asyncio.sleep(0.3)
            logger.info("Stream completed. Awaiting acknowledgement...")
            try:
                res = await asyncio.wait_for(ws.recv(), timeout=4.0)
                logger.info(f"Received: {res}")
            except asyncio.TimeoutError:
                logger.info("Completed wait cycle.")
    except Exception as e:
        logger.warning(f"Speaker simulation note: {e}")

if __name__ == '__main__':
    asyncio.run(simulate())
