import os
import json
import logging
import re
import base64
from typing import Optional
from contextlib import asynccontextmanager

from pydantic import BaseModel
from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Depends, Request
from fastapi.responses import JSONResponse
from src.security import (
    auth_manager,
    verify_api_key,
    redact_sensitive_data,
    SecurityHeadersMiddleware,
    RateLimitMiddleware,
    RequestSizeLimiterMiddleware,
)
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

from src.observability.health import health_supervisor, HealthState
from src.observability.metrics import runtime_metrics

from src.storage.db import Database

import uuid
import time
import asyncio

from src.voice.pipeline import VoicePipeline
from src.server.websocket import ws_manager, WebSocketConnectionManager
from src.server.protocol import (
    InboundConnectPayload,
    InboundAudioFramePayload,
    InboundTextInputPayload,
    InboundPingPayload,
    InboundCancelPayload,
    InboundCommandAckPayload,
    OutboundConnectedPayload,
    OutboundPongPayload,
    OutboundVADPayload,
    OutboundTranscriptPayload,
    OutboundTokenDeltaPayload,
    OutboundToolStatusPayload,
    OutboundAudioOutputPayload,
    OutboundTurnCompletePayload,
    OutboundErrorPayload,
    parse_inbound_message,
)

logger = logging.getLogger("iris")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    db_path = os.getenv("DATABASE_URL", "iris.db")
    db = Database(db_path=db_path)
    await db.connect()

    api_base = os.getenv("OPENAI_API_BASE", "http://localhost:11434/v1")
    api_key = os.getenv("OPENROUTER_API_KEY") or os.getenv("OPENAI_API_KEY") or os.getenv("IRIS_API_KEY", "ollama")
    model = os.getenv("OPENAI_MODEL", "llama3.2")

    orchestrator = IRISOrchestrator(api_base=api_base, api_key=api_key, model=model, database=db)
    fleet_mgr = FleetManager(ws_manager=ws_manager, event_bus=orchestrator.event_bus)
    tts_eng = TTSEngine(online_fallback=False)
    voice_pipe = VoicePipeline(orchestrator=orchestrator, tts=tts_eng)

    app.state.db = db
    app.state.orchestrator = orchestrator
    app.state.tts_engine = tts_eng
    app.state.fleet_manager = fleet_mgr
    app.state.ws_manager = ws_manager
    app.state.voice_pipeline = voice_pipe

    health_supervisor.db_connection = db
    health_supervisor.orchestrator = orchestrator
    health_supervisor.fleet_manager = fleet_mgr
    health_supervisor.ws_manager = ws_manager

    yield

    # Cleanup
    await db.close()
    health_supervisor.db_connection = None
    health_supervisor.ws_manager = None
    if hasattr(app.state, "orchestrator"):
        del app.state.orchestrator
    if hasattr(app.state, "fleet_manager"):
        del app.state.fleet_manager
    if hasattr(app.state, "db"):
        del app.state.db
    if hasattr(app.state, "ws_manager"):
        del app.state.ws_manager
    if hasattr(app.state, "voice_pipeline"):
        del app.state.voice_pipeline


app = FastAPI(lifespan=lifespan)

# Add Security & Protection Middlewares
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(RequestSizeLimiterMiddleware)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    redacted_msg = redact_sensitive_data(str(exc))
    logger.error(f"Unhandled exception on {request.url.path}: {redacted_msg}")
    return JSONResponse(
        status_code=500,
        content={"error": "Internal Server Error", "message": "An unexpected internal error occurred."}
    )


# Protected Fleet API endpoints requiring authentication
app.include_router(fleet_router, dependencies=[Depends(verify_api_key)])
app.include_router(fleet_router, prefix="/api", dependencies=[Depends(verify_api_key)])

class ProcessRequestPayload(BaseModel):
    prompt: str
    session_id: Optional[str] = "default-session"
    device_id: Optional[str] = "unknown"

@app.post("/api/orchestrator/process", dependencies=[Depends(verify_api_key)])
async def process_orchestrator_request(payload: ProcessRequestPayload, request: Request):
    orchestrator = getattr(request.app.state, "orchestrator", None)
    if not orchestrator:
        return JSONResponse(status_code=500, content={"error": "Orchestrator not initialized"})
    
    result = orchestrator.process_request(
        user_prompt=payload.prompt,
        session_id=payload.session_id or "default-session",
        device_id=payload.device_id or "unknown"
    )
    if hasattr(result, "model_dump"):
        return result.model_dump()
    return result

@app.get("/health")
async def health():
    return {"status": "ok"}


async def realtime_ws_handler(websocket: WebSocket, device_id: Optional[str] = "unknown", session_id: Optional[str] = None):
    # Check query param token auth
    token = websocket.query_params.get("token") or websocket.query_params.get("api_key")
    if token and not auth_manager.validate_token(token, device_id=device_id):
        await websocket.close(code=4401, reason="Unauthorized")
        return

    await websocket.accept()
    sess_id = session_id or str(uuid.uuid4())
    dev_id = device_id or "unknown"

    ws_mgr: WebSocketConnectionManager = getattr(websocket.app.state, "ws_manager", ws_manager)
    await ws_mgr.connect(websocket, device_id=dev_id, session_id=sess_id)

    # Send connected envelope
    await ws_mgr.send_payload(sess_id, OutboundConnectedPayload(session_id=sess_id, version="1.0"))

    try:
        while True:
            message = await websocket.receive()

            if message.get("type") == "websocket.disconnect":
                break

            # 1. Handle binary frame
            if "bytes" in message and message["bytes"]:
                raw_bytes = message["bytes"]
                voice_pipe = getattr(websocket.app.state, "voice_pipeline", None)
                if voice_pipe:
                    res = await voice_pipe.process_audio_chunk(raw_bytes)
                    if res.get("is_speech"):
                        await ws_mgr.send_payload(sess_id, OutboundVADPayload(state="SPEECH_START"))
                    else:
                        await ws_mgr.send_payload(sess_id, OutboundVADPayload(state="SPEECH_END"))
                continue

            # 2. Handle text frame
            if "text" in message and message["text"]:
                raw_text = message["text"]
                try:
                    payload_dict = json.loads(raw_text)
                except json.JSONDecodeError:
                    await ws_mgr.send_payload(sess_id, OutboundErrorPayload(code="INVALID_JSON", message="Payload must be valid JSON"))
                    continue

                try:
                    msg = parse_inbound_message(payload_dict)
                except Exception as err:
                    await ws_mgr.send_payload(sess_id, OutboundErrorPayload(code="INVALID_PROTOCOL", message=str(err)))
                    continue

                if isinstance(msg, InboundPingPayload):
                    await ws_mgr.send_payload(sess_id, OutboundPongPayload(timestamp=msg.timestamp))

                elif isinstance(msg, InboundConnectPayload):
                    if msg.device_id and msg.device_id != "unknown":
                        dev_id = msg.device_id
                        ws_mgr.session_to_device[sess_id] = dev_id
                        ws_mgr.device_to_session[dev_id] = sess_id
                    await ws_mgr.send_payload(sess_id, OutboundConnectedPayload(session_id=sess_id, version="1.0"))

                elif isinstance(msg, InboundCancelPayload):
                    count = ws_mgr.cancel_tasks_sync(sess_id)
                    logger.info(f"Cancelled {count} tasks for session {sess_id} via cancel message.")

                elif isinstance(msg, InboundCommandAckPayload):
                    fleet_mgr = getattr(websocket.app.state, "fleet_manager", None)
                    if fleet_mgr:
                        fleet_mgr.handle_command_ack(msg)

                elif isinstance(msg, InboundTextInputPayload):
                    request_id = str(uuid.uuid4())

                    async def process_text_task():
                        start_t = time.time()
                        orchestrator = getattr(websocket.app.state, "orchestrator", None)
                        tts_engine = getattr(websocket.app.state, "tts_engine", None)

                        # Emit final transcript payload
                        await ws_mgr.send_payload(sess_id, OutboundTranscriptPayload(text=msg.text, is_final=True, request_id=request_id))

                        if not orchestrator:
                            await ws_mgr.send_payload(sess_id, OutboundErrorPayload(code="ORCHESTRATOR_UNAVAILABLE", message="Orchestrator not ready"))
                            return

                        sentence_buf = ""
                        delimiters = re.compile(r"([.!?\n]+(?:\s+|$))")

                        async def send_tts_chunk(text_part: str):
                            if not tts_engine:
                                return
                            clean = text_part.strip()
                            if not clean:
                                return
                            try:
                                async for pcm_chunk in tts_engine.stream_audio(clean):
                                    b64_pcm = base64.b64encode(pcm_chunk).decode("utf-8")
                                    await ws_mgr.send_payload(sess_id, OutboundAudioOutputPayload(format="pcm16", data=b64_pcm))
                            except Exception as e:
                                logger.warning(f"TTS synthesis skipped: {e}")

                        try:
                            async for chunk in orchestrator.stream_request(
                                user_prompt=msg.text,
                                session_id=sess_id,
                                device_id=dev_id,
                                request_id=request_id
                            ):
                                if chunk.chunk_type in ("text_delta", "complete") and chunk.delta_text:
                                    await ws_mgr.send_payload(sess_id, OutboundTokenDeltaPayload(delta=chunk.delta_text, request_id=request_id))
                                    sentence_buf += chunk.delta_text
                                    parts = delimiters.split(sentence_buf)
                                    if len(parts) > 2:
                                        ready = "".join(parts[:-1]).strip()
                                        sentence_buf = parts[-1]
                                        if ready:
                                            await send_tts_chunk(ready)

                                elif chunk.chunk_type == "tool_call":
                                    await ws_mgr.send_payload(sess_id, OutboundToolStatusPayload(tool_name=chunk.tool_name or "unknown", status="INVOKING"))
                                elif chunk.chunk_type == "tool_result":
                                    await ws_mgr.send_payload(sess_id, OutboundToolStatusPayload(tool_name=chunk.tool_name or "unknown", status="COMPLETED", output_payload=chunk.tool_output))

                            if sentence_buf.strip():
                                await send_tts_chunk(sentence_buf.strip())

                            duration = (time.time() - start_t) * 1000.0
                            await ws_mgr.send_payload(sess_id, OutboundTurnCompletePayload(request_id=request_id, duration_ms=round(duration, 2)))

                        except asyncio.CancelledError:
                            logger.info(f"Text processing cancelled for request_id '{request_id}'")
                            raise
                        except Exception as err:
                            await ws_mgr.send_payload(sess_id, OutboundErrorPayload(code="PROCESSING_ERROR", message=str(err)))
                            duration = (time.time() - start_t) * 1000.0
                            await ws_mgr.send_payload(sess_id, OutboundTurnCompletePayload(request_id=request_id, duration_ms=round(duration, 2)))

                    t = asyncio.create_task(process_text_task())
                    ws_mgr.register_task(sess_id, t)

                elif isinstance(msg, InboundAudioFramePayload):
                    audio_bytes = base64.b64decode(msg.data)
                    voice_pipe = getattr(websocket.app.state, "voice_pipeline", None)
                    if voice_pipe:
                        res = await voice_pipe.process_audio_chunk(audio_bytes)
                        if res.get("is_speech"):
                            await ws_mgr.send_payload(sess_id, OutboundVADPayload(state="SPEECH_START"))
                        else:
                            await ws_mgr.send_payload(sess_id, OutboundVADPayload(state="SPEECH_END"))

    except WebSocketDisconnect:
        pass
    finally:
        await ws_mgr.disconnect(sess_id)


@app.websocket("/ws")
@app.websocket("/v1/ws")
async def websocket_realtime_endpoint(websocket: WebSocket, device_id: Optional[str] = "unknown", session_id: Optional[str] = None):
    await realtime_ws_handler(websocket, device_id=device_id, session_id=session_id)

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

@app.get("/health/live")
async def health_live():
    report = await health_supervisor.get_health_status(check_readiness=False)
    return {"status": "alive", "report": report.model_dump()}

@app.get("/health/liveness")
async def liveness():
    return {"status": "alive"}

from fastapi.responses import JSONResponse

@app.get("/health/ready")
@app.get("/health/readiness")
async def readiness():
    report = await health_supervisor.get_health_status(check_readiness=True)
    if report.status == HealthState.UNHEALTHY:
        return JSONResponse(status_code=503, content={"status": "unhealthy", "report": report.model_dump()})
    elif report.status == HealthState.DEGRADED:
        return JSONResponse(status_code=200, content={"status": "degraded", "report": report.model_dump()})
    return {"status": "ready", "report": report.model_dump()}


@app.get("/health/detailed", response_model=SystemHealthReport)
async def detailed_health():
    return await health_checker.evaluate_system()

@app.get("/metrics")
async def metrics():
    return runtime_metrics.get_metrics_snapshot()
