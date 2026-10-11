import logging
import time
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Request, HTTPException, status
from pydantic import BaseModel, Field

from src.automation.proactive_engine import ProactiveRule, ProactiveEngine

logger = logging.getLogger("iris.server.routers.automation")

router = APIRouter(prefix="/automation/proactive", tags=["Ambient Proactive Engine"])


class ProactiveTestPayload(BaseModel):
    text: str = Field(..., min_length=1, description="Announcement speech text to test")
    severity: Optional[str] = Field("INFO", description="'INFO' | 'WARNING' | 'CRITICAL'")
    entity_id: Optional[str] = Field("manual.test", description="Optional source entity_id")


def get_proactive_engine(request: Request) -> Optional[ProactiveEngine]:
    engine = getattr(request.app.state, "proactive_engine", None)
    if engine is None:
        try:
            from src.automation.proactive_engine import ProactiveEngine
            from src.automation.dispatcher import ProactiveSpeechDispatcher
            disp = getattr(request.app.state, "proactive_dispatcher", None) or ProactiveSpeechDispatcher()
            engine = ProactiveEngine(dispatcher=disp)
            request.app.state.proactive_engine = engine
        except Exception:
            return None
    return engine



@router.get("/rules")
async def list_proactive_rules(request: Request):
    """List all configured ambient proactive rules and their cooldown settings."""
    engine = get_proactive_engine(request)
    if not engine:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Proactive engine is not initialized or unavailable.",
        )
    rules = engine.get_rules()
    return {
        "count": len(rules),
        "rules": [r.model_dump() for r in rules],
        "cooldowns": engine._cooldowns,
    }


@router.post("/test", status_code=status.HTTP_200_OK)
async def test_proactive_announcement(
    payload: ProactiveTestPayload,
    request: Request,
):
    """Trigger a manual test proactive speech announcement broadcast."""
    engine = get_proactive_engine(request)
    if not engine or not engine.dispatcher:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Proactive engine dispatcher is not available.",
        )

    res = await engine.dispatcher.dispatch(
        text=payload.text,
        severity=payload.severity or "INFO",
        entity_id=payload.entity_id or "manual.test",
        timestamp=time.time(),
    )
    return {
        "status": "triggered",
        "result": res,
    }


@router.get("/status")
async def get_proactive_status(request: Request):
    """Retrieve operational status, connection state, quiet hours state, and recent announcements."""
    engine = get_proactive_engine(request)
    ha_client = getattr(request.app.state, "ha_client", None)

    ha_status = getattr(ha_client, "status", "DISABLED") if ha_client else "DISABLED"
    rules_count = len(engine.get_rules()) if engine else 0
    in_quiet = engine.is_in_quiet_hours() if engine else False
    recent = engine.recent_announcements if engine else []

    return {
        "engine_status": "ACTIVE" if ha_status == "CONNECTED" else ("DISABLED" if ha_status == "DISABLED" else "DISCONNECTED"),
        "ha_connection_status": ha_status,
        "active_rules_count": rules_count,
        "is_quiet_hours": in_quiet,
        "recent_announcements": recent[-20:],
    }
