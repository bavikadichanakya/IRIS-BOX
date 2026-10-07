import os
import json
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from src.models.schemas import VoiceCommandPayload, AgentExecutionResult
from src.agent.orchestrator import IRISOrchestrator

# Global orchestrator instance
orchestrator: Optional[IRISOrchestrator] = None

app = FastAPI()

@app.on_event("startup")
async def startup_event():
    global orchestrator
    api_base = os.getenv("OPENAI_API_BASE", "http://localhost:8080/v1")
    api_key = os.getenv("OPENAI_API_KEY", "dummy")
    model = os.getenv("OPENAI_MODEL", "gpt-3.5-turbo-16k")
    orchestrator = IRISOrchestrator(api_base=api_base, api_key=api_key, model=model)
    app.state.orchestrator = orchestrator

@app.get("/health")
async def health():
    return {"status": "ok"}

@app.websocket("/ws/voice-stream")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_text()
            # Parse JSON
            try:
                payload_dict = json.loads(data)
            except json.JSONDecodeError:
                await websocket.send_json({"error": "Invalid JSON"})
                continue
            # Validate payload
            try:
                voice_payload = VoiceCommandPayload(**payload_dict)
            except Exception as e:
                await websocket.send_json({"error": f"Invalid payload: {e}"})
                continue
            # Get orchestrator from app state
            orchestrator_instance = getattr(websocket.app.state, 'orchestrator', None)
            if orchestrator_instance is None:
                await websocket.send_json({"error": "Orchestrator not initialized"})
                continue
            # Process with orchestrator
            result = orchestrator_instance.process_request(voice_payload.raw_transcript)
            # Send result back as JSON
            await websocket.send_json(result.model_dump())
    except WebSocketDisconnect:
        # Handle disconnect
        pass
