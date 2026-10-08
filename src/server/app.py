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

logger = logging.getLogger("iris")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    api_base = os.getenv("OPENAI_API_BASE", "https://openrouter.ai/api/v1")
    api_key = os.getenv("OPENROUTER_API_KEY") or os.getenv("OPENAI_API_KEY", "")
    model = os.getenv("OPENAI_MODEL", "dots-studio/dots-3-note-preview:free")
    
    orchestrator = IRISOrchestrator(api_base=api_base, api_key=api_key, model=model)
    app.state.orchestrator = orchestrator
    
    yield
    
    # Cleanup
    if hasattr(app.state, "orchestrator"):
        del app.state.orchestrator

app = FastAPI(lifespan=lifespan)

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
