import asyncio
import json
import logging
import time
import uuid
from typing import AsyncGenerator, Dict, List, Optional, Set
from fastapi import APIRouter, HTTPException, Request, Depends, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from src.security.auth import auth_manager
from src.observability.event_bus import EventBus

logger = logging.getLogger("iris.server.routers.notifications")

router = APIRouter(prefix="/notifications", tags=["LAN Notifications & SSE"])


class NotificationMessage(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    topic: str
    title: str
    message: str
    severity: str = "INFO"  # INFO, WARNING, CRITICAL
    data: Dict = Field(default_factory=dict)
    timestamp: float = Field(default_factory=time.time)


class NotificationBroadcaster:
    """
    Taps EventBus topics and broadcasts real-time SSE notifications to mobile companion clients.
    """

    def __init__(self, event_bus: Optional[EventBus] = None):
        self.event_bus = event_bus or EventBus()
        self._subscribers: Set[asyncio.Queue] = set()
        self._recent_buffer: List[Dict] = []
        self._max_recent = 30
        self._subscribed_bus = False

    def init_bus_subscriptions(self, event_bus: Optional[EventBus] = None):
        if event_bus:
            self.event_bus = event_bus
        if self._subscribed_bus:
            return
        self._subscribed_bus = True

        async def on_proactive_event(evt):
            title = "Ambient Announcement"
            text = evt.payload.get("text") or "Smart home update"
            sev = evt.payload.get("severity") or "INFO"
            await self.publish_notification(
                topic="proactive.announcement",
                title=title,
                message=text,
                severity=sev,
                data=evt.payload
            )

        async def on_ha_event(evt):
            entity_id = evt.payload.get("entity_id", "smart_device")
            state = evt.payload.get("new_state", "changed")
            await self.publish_notification(
                topic="ha.state_changed",
                title="Home Assistant Event",
                message=f"{entity_id} changed to {state}",
                severity="INFO",
                data=evt.payload
            )

        async def on_plan_event(evt):
            plan_id = evt.payload.get("plan_id", "unknown")
            await self.publish_notification(
                topic="plan.confirmation_required",
                title="Execution Approval Required",
                message=f"Plan {plan_id} is awaiting your confirmation.",
                severity="WARNING",
                data=evt.payload
            )

        async def on_voice_denied(evt):
            tool = evt.payload.get("tool", "system_tool")
            reason = evt.payload.get("reason", "Voice authorization denied.")
            await self.publish_notification(
                topic="security.voice_auth.denied",
                title="Voice Gate Triggered",
                message=f"Blocked {tool}: {reason}",
                severity="WARNING",
                data=evt.payload
            )

        self.event_bus.subscribe("proactive.announcement.emitted", on_proactive_event)
        self.event_bus.subscribe("ha.state_changed", on_ha_event)
        self.event_bus.subscribe("plan.confirmation_required", on_plan_event)
        self.event_bus.subscribe("security.voice_auth.denied", on_voice_denied)

    async def publish_notification(
        self,
        topic: str,
        title: str,
        message: str,
        severity: str = "INFO",
        data: Optional[Dict] = None
    ) -> NotificationMessage:
        notif = NotificationMessage(
            topic=topic,
            title=title,
            message=message,
            severity=severity,
            data=data or {}
        )
        notif_dict = notif.model_dump()

        # Update recent buffer
        self._recent_buffer.append(notif_dict)
        if len(self._recent_buffer) > self._max_recent:
            self._recent_buffer = self._recent_buffer[-self._max_recent:]

        # Broadcast to active queues
        dead_queues = set()
        for q in list(self._subscribers):
            try:
                q.put_nowait(notif_dict)
            except Exception:
                dead_queues.add(q)
        self._subscribers.difference_update(dead_queues)

        return notif

    def get_recent(self) -> List[Dict]:
        return list(self._recent_buffer)

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue):
        self._subscribers.discard(q)


broadcaster = NotificationBroadcaster()


def verify_notification_token(request: Request) -> str:
    """
    Authenticate SSE stream request via Authorization header, X-API-Key, or query param 'token'.
    Browser EventSource often requires token in query param.
    """
    auth_header = request.headers.get("authorization") or ""
    bearer_token = auth_header.replace("Bearer ", "").strip() if "Bearer " in auth_header else ""
    token = (
        bearer_token
        or request.headers.get("x-api-key")
        or request.query_params.get("token")
        or request.query_params.get("api_key")
    )
    device_id = request.headers.get("x-device-id") or request.query_params.get("device_id")

    if not token or not auth_manager.validate_token(token, device_id=device_id):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized: Valid authentication token required for notification stream."
        )
    return token


@router.get("/stream")
async def notification_stream(request: Request):
    """
    Server-Sent Events (SSE) notification stream.
    Pushes real-time smart home events, plan approvals, and security alerts to mobile companions.
    """
    verify_notification_token(request)

    # Ensure broadcaster is bound to app's event bus
    eb = getattr(request.app.state, "event_bus", None)
    if eb:
        broadcaster.init_bus_subscriptions(eb)

    queue = broadcaster.subscribe()

    async def event_generator() -> AsyncGenerator[str, None]:
        # Send initial connection confirmation event
        init_payload = json.dumps({"connected": True, "server_time": time.time()})
        yield f"event: connect\ndata: {init_payload}\n\n"

        try:
            while True:
                try:
                    # Wait for next event or send ping keepalive every 15s
                    msg = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield f"event: notification\ndata: {json.dumps(msg)}\n\n"
                except asyncio.TimeoutError:
                    yield f": ping\n\n"
                except asyncio.CancelledError:
                    break
        finally:
            broadcaster.unsubscribe(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


class TestNotificationPayload(BaseModel):
    title: str = Field(..., min_length=1)
    message: str = Field(..., min_length=1)
    severity: Optional[str] = "INFO"
    data: Optional[Dict] = None


@router.post("/test")
async def trigger_test_notification(payload: TestNotificationPayload, request: Request):
    """Dispatch a test notification to all connected SSE clients."""
    verify_notification_token(request)
    notif = await broadcaster.publish_notification(
        topic="manual.test",
        title=payload.title,
        message=payload.message,
        severity=payload.severity or "INFO",
        data=payload.data or {}
    )
    return {"success": True, "notification": notif.model_dump()}


@router.get("/recent")
async def get_recent_notifications(request: Request):
    """Retrieve recent notifications buffer."""
    verify_notification_token(request)
    return {"recent": broadcaster.get_recent()}
