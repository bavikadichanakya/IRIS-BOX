import os
import json
import logging
import re
import base64
from typing import Optional
from contextlib import asynccontextmanager

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from src.models.schemas import VoiceCommandPayload, AgentExecutionResult
from src.agent.orchestrator import IRISOrchestrator
from src.audio.tts import TTSEngine
from src.server.fleet import FleetManager, router as fleet_router
from src.health.health_checker import (
    health_checker,
    HealthStatus,
    ComponentReport,
    SystemHealthReport,
)

logger = logging.getLogger("iris")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    api_base = os.getenv("OPENAI_API_BASE", "http://localhost:11434/v1")
    api_key = os.getenv("OPENROUTER_API_KEY") or os.getenv("OPENAI_API_KEY") or os.getenv("IRIS_API_KEY", "ollama")
    model = os.getenv("OPENAI_MODEL", "llama3.2")

    orchestrator = IRISOrchestrator(api_base=api_base, api_key=api_key, model=model)
    app.state.orchestrator = orchestrator
    app.state.tts_engine = TTSEngine()
    app.state.fleet_manager = FleetManager()

    yield

    # Cleanup
    if hasattr(app.state, "orchestrator"):
        del app.state.orchestrator
    if hasattr(app.state, "fleet_manager"):
        del app.state.fleet_manager

app = FastAPI(lifespan=lifespan)
app.include_router(fleet_router)

@app.get("/health")
async def health():
    return {"status": "ok"}

@app.websocket("/ws/voice-stream")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_text()

            try:
                payload_dict = json.loads(data)
            except json.JSONDecodeError:
                await websocket.send_json({"error": "Invalid JSON"})
                continue

            # Handle ping/pong heartbeat
            if payload_dict.get("type") == "ping":
                await websocket.send_json({"type": "pong"})
                continue

            try:
                voice_payload = VoiceCommandPayload(**payload_dict)
            except Exception as e:
                await websocket.send_json({"error": f"Invalid payload: {e}"})
                continue

            orchestrator_instance = getattr(websocket.app.state, "orchestrator", None)
            if orchestrator_instance is None:
                await websocket.send_json({"error": "Orchestrator not initialized"})
                continue

            try:
                result = orchestrator_instance.process_request(voice_payload.raw_transcript)
                if hasattr(result, "model_dump"):
                    await websocket.send_json(result.model_dump())
                else:
                    await websocket.send_json({"result": str(result)})
            except Exception as err:
                error_res = AgentExecutionResult(
                    success=False,
                    output=f"LLM API call failed: {err}",
                    execution_time_ms=0
                )
                await websocket.send_json(error_res.model_dump())

    except WebSocketDisconnect:
        pass

@app.websocket("/ws/stream")
async def websocket_stream(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_text()
            try:
                payload_dict = json.loads(data)
            except json.JSONDecodeError:
                await websocket.send_json({"error": "Invalid JSON"})
                continue

            # Support ping/pong
            if payload_dict.get("type") == "ping":
                await websocket.send_json({"type": "pong"})
                continue

            user_prompt = payload_dict.get("prompt")
            if not user_prompt:
                await websocket.send_json({"error": "Missing 'prompt' field"})
                continue

            orchestrator_instance = getattr(websocket.app.state, "orchestrator", None)
            if orchestrator_instance is None:
                await websocket.send_json({"error": "Orchestrator not initialized"})
                continue

            try:
                tts_engine = getattr(websocket.app.state, "tts_engine", None)
                return_audio = payload_dict.get("return_audio", True) and (tts_engine is not None)
                
                sentence_buffer = ""
                delimiters = re.compile(r"([.!?\n]+(?:\s+|$))")

                async def synthesize_and_send(text_segment: str):
                    clean_text = text_segment.strip()
                    if not clean_text or not return_audio:
                        return
                    await websocket.send_json({"chunk_type": "audio_start"})
                    async for audio_chunk in tts_engine.stream_audio(clean_text):
                        b64 = base64.b64encode(audio_chunk).decode("utf-8")
                        await websocket.send_json({"chunk_type": "audio_chunk", "data": b64})
                    await websocket.send_json({"chunk_type": "audio_end"})

                async for chunk in orchestrator_instance.stream_request(user_prompt):
                    await websocket.send_json(chunk.model_dump())
                    if hasattr(chunk, "delta_text") and chunk.delta_text and chunk.chunk_type == "text_delta":
                        sentence_buffer += chunk.delta_text
                        parts = delimiters.split(sentence_buffer)
                        if len(parts) > 2:
                            ready_sentence = "".join(parts[:-1]).strip()
                            sentence_buffer = parts[-1]
                            if ready_sentence:
                                await synthesize_and_send(ready_sentence)

                # Flush trailing text
                if sentence_buffer.strip():
                    await synthesize_and_send(sentence_buffer.strip())

            except WebSocketDisconnect:
                break
            except Exception as err:
                logger.error(f"Streaming error: {err}")
                try:
                    await websocket.send_json({"error": f"Streaming failed: {err}"})
                except Exception:
                    break
    except WebSocketDisconnect:
        pass


@app.get("/health/liveness")
async def liveness():
    return {"status": "alive"}

@app.get("/health/readiness")
async def readiness():
    report = await health_checker.evaluate_system()
    if report.status == HealthStatus.UNHEALTHY:
        return {"status": "degraded", "report": report.model_dump()}, 503
    return {"status": "ready", "report": report.model_dump()}

@app.get("/health/detailed", response_model=SystemHealthReport)
async def detailed_health():
    return await health_checker.evaluate_system()
