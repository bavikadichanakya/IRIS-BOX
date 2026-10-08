import os
import json
import logging
from typing import Optional
from contextlib import asynccontextmanager

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from src.models.schemas import VoiceCommandPayload, AgentExecutionResult
from src.agent.orchestrator import IRISOrchestrator
from src.audio.tts import TTSEngine
from src.server.fleet import FleetManager, router as fleet_router

logger = logging.getLogger("iris")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    api_base = os.getenv("OPENAI_API_BASE", "https://openrouter.ai/api/v1")
    api_key = os.getenv("OPENROUTER_API_KEY") or os.getenv("OPENAI_API_KEY", "")
    model = os.getenv("OPENAI_MODEL", "dots-studio/dots-3-note-preview:free")
    
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

            orchestrator_instance = getattr(websocket.app.state, 'orchestrator', None)
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

            orchestrator_instance = getattr(websocket.app.state, 'orchestrator', None)
            if orchestrator_instance is None:
                await websocket.send_json({"error": "Orchestrator not initialized"})
                continue

            try:
                full_text = []
                async for chunk in orchestrator_instance.stream_request(user_prompt):
                    await websocket.send_json(chunk.model_dump())
                    if hasattr(chunk, 'delta_text') and chunk.delta_text and chunk.chunk_type == 'text_delta':
                        full_text.append(chunk.delta_text)

                # If audio was requested or return_audio is true/default
                if payload_dict.get('return_audio', True):
                    complete_message = ''.join(full_text).strip()
                    tts_engine = getattr(websocket.app.state, 'tts_engine', None)
                    if tts_engine and complete_message:
                        await websocket.send_json({'chunk_type': 'audio_start'})
                        async for audio_chunk in tts_engine.stream_audio(complete_message):
                            import base64
                            b64 = base64.b64encode(audio_chunk).decode('utf-8')
                            await websocket.send_json({'chunk_type': 'audio_chunk', 'data': b64})
                        await websocket.send_json({'chunk_type': 'audio_end'})
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
