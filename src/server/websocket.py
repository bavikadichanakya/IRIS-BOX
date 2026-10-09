import asyncio
import logging
import base64
import json
import time
import uuid
from typing import Dict, Set, Optional, Any, Union
from pydantic import BaseModel
from fastapi import WebSocket, WebSocketDisconnect

from src.server.protocol import (
    InboundConnectPayload,
    InboundAudioFramePayload,
    InboundTextInputPayload,
    InboundPingPayload,
    InboundCancelPayload,
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
from src.observability.event_bus import EventBus
from src.observability.tracing import create_trace_context, TraceContext

logger = logging.getLogger("iris.server.websocket")


class WebSocketConnectionManager:
    """
    Manages client WebSocket connections, active task lifecycle, cancellation on disconnect,
    and EventBus telemetry correlation for IRIS-BOX devices.
    """

    def __init__(self, event_bus: Optional[EventBus] = None):
        self.event_bus = event_bus or EventBus()
        self.active_connections: Dict[str, WebSocket] = {}  # session_id -> WebSocket
        self.session_to_device: Dict[str, str] = {}         # session_id -> device_id
        self.device_to_session: Dict[str, str] = {}         # device_id -> session_id
        self.active_tasks: Dict[str, Set[asyncio.Task]] = {} # session_id -> Set[Task]
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket, device_id: str, session_id: str):
        """Register an active client connection."""
        async with self._lock:
            self.active_connections[session_id] = websocket
            self.session_to_device[session_id] = device_id
            self.device_to_session[device_id] = session_id
            self.active_tasks[session_id] = set()

        trace = create_trace_context(device_id=device_id, session_id=session_id)
        await self.event_bus.publish(
            "device.connected",
            {"device_id": device_id, "session_id": session_id, "status": "online"},
            trace=trace
        )
        logger.info(f"WebSocket connected: device_id='{device_id}', session_id='{session_id}'")

    async def disconnect(self, session_id: str):
        """Cleanly disconnect client and cancel all active background tasks."""
        async with self._lock:
            device_id = self.session_to_device.get(session_id, "unknown")
            
            # 1. Cancel all active background tasks
            cancelled_count = self.cancel_tasks_sync(session_id)
            if cancelled_count > 0:
                logger.info(f"Cancelled {cancelled_count} active tasks on disconnect for session '{session_id}'.")

            # 2. Cleanup tracking maps
            self.active_connections.pop(session_id, None)
            self.session_to_device.pop(session_id, None)
            if device_id in self.device_to_session:
                self.device_to_session.pop(device_id, None)
            self.active_tasks.pop(session_id, None)

        trace = create_trace_context(device_id=device_id, session_id=session_id)
        await self.event_bus.publish(
            "device.disconnected",
            {"device_id": device_id, "session_id": session_id, "status": "offline"},
            trace=trace
        )
        logger.info(f"WebSocket disconnected cleanly: device_id='{device_id}', session_id='{session_id}'")

    def register_task(self, session_id: str, task: asyncio.Task):
        """Register a background asyncio Task for a session."""
        if session_id in self.active_tasks:
            self.active_tasks[session_id].add(task)
            task.add_done_callback(lambda t: self.unregister_task(session_id, t))

    def unregister_task(self, session_id: str, task: asyncio.Task):
        """Remove a task from session registry when done."""
        if session_id in self.active_tasks:
            self.active_tasks[session_id].discard(task)

    def cancel_tasks_sync(self, session_id: str) -> int:
        """Synchronously cancel all tasks registered for session_id."""
        tasks = self.active_tasks.get(session_id, set())
        count = 0
        for task in list(tasks):
            if not task.done():
                task.cancel()
                count += 1
        tasks.clear()
        return count

    async def send_payload(self, session_id: str, payload: BaseModel) -> bool:
        """Send a JSON payload model down the WebSocket."""
        websocket = self.active_connections.get(session_id)
        if not websocket:
            return False
        try:
            await websocket.send_json(payload.model_dump())
            return True
        except (WebSocketDisconnect, RuntimeError):
            await self.disconnect(session_id)
            return False

    async def send_bytes(self, session_id: str, raw_bytes: bytes) -> bool:
        """Send binary bytes down the WebSocket."""
        websocket = self.active_connections.get(session_id)
        if not websocket:
            return False
        try:
            await websocket.send_bytes(raw_bytes)
            return True
        except (WebSocketDisconnect, RuntimeError):
            await self.disconnect(session_id)
            return False

    def get_active_connection_count(self) -> int:
        """Return total active WebSocket connections."""
        return len(self.active_connections)


ws_manager = WebSocketConnectionManager()
