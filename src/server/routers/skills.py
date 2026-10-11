import logging
from typing import Any, Dict, Optional
from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from src.skills.registry import SkillRegistry
from src.tools.capability import PermissionLevel
from src.tools.permissions import confirmation_manager

logger = logging.getLogger("iris.server.routers.skills")

router = APIRouter(prefix="/skills", tags=["Skills & Plugins"])


def get_skill_registry(request: Request) -> SkillRegistry:
    """Retrieve SkillRegistry from app state or orchestrator."""
    if hasattr(request.app.state, "skill_registry") and request.app.state.skill_registry is not None:
        return request.app.state.skill_registry

    orch = getattr(request.app.state, "orchestrator", None)
    if orch and hasattr(orch, "skill_registry") and orch.skill_registry is not None:
        return orch.skill_registry

    # Singleton fallback
    if not hasattr(get_skill_registry, "_instance"):
        get_skill_registry._instance = SkillRegistry()
    return get_skill_registry._instance


class SkillExecutePayload(BaseModel):
    parameters: Dict[str, Any] = Field(default_factory=dict)
    confirmation_token: Optional[str] = None
    device_id: Optional[str] = "unknown"
    session_id: Optional[str] = "default-session"


@router.get("")
@router.get("/")
async def list_skills(request: Request):
    """
    List all registered skills with their formal manifests and current health states.
    """
    registry = get_skill_registry(request)
    health_results = await registry.check_all_health()
    manifests = registry.list_skills()

    items = []
    for m in manifests:
        h = health_results.get(m.name)
        items.append({
            "name": m.name,
            "manifest": m.model_dump(),
            "health": h.model_dump() if h else {"healthy": False, "message": "Unknown status"},
        })

    return {
        "skills": items,
        "count": len(items),
    }


@router.get("/{name}")
async def get_skill(name: str, request: Request):
    """
    Retrieve manifest and current health status for a specific skill.
    """
    registry = get_skill_registry(request)
    skill = registry.get_skill(name)
    if not skill:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Skill '{name}' not found."
        )

    health = await skill.check_health()
    return {
        "name": skill.name,
        "manifest": skill.manifest.model_dump(),
        "health": health.model_dump(),
    }


@router.post("/{name}/health")
async def run_skill_health_check(name: str, request: Request):
    """
    Trigger an on-demand runtime health check for a specific skill.
    """
    registry = get_skill_registry(request)
    skill = registry.get_skill(name)
    if not skill:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Skill '{name}' not found."
        )

    health = await skill.check_health()
    return {
        "skill_name": skill.name,
        "health": health.model_dump(),
    }


@router.post("/{name}/execute")
async def execute_skill_endpoint(
    name: str,
    request: Request,
    payload: Optional[SkillExecutePayload] = None,
):
    """
    Directly execute a registered skill, strictly validating permission levels
    and confirmation tokens.
    """
    registry = get_skill_registry(request)
    skill = registry.get_skill(name)
    if not skill:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Skill '{name}' not found."
        )

    data = payload or SkillExecutePayload()
    device_id = data.device_id or "unknown"
    session_id = data.session_id or "default-session"
    params = data.parameters

    # Permission Boundary Enforcement
    if skill.manifest.permission_level == PermissionLevel.PROTECTED:
        if not device_id or device_id == "unknown":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"PROTECTED skill '{name}' requires a verified device_id."
            )

    if skill.manifest.permission_level == PermissionLevel.SENSITIVE:
        if not data.confirmation_token:
            ticket = confirmation_manager.create_pending_action(
                tool_name=name,
                action_payload=params,
                device_id=device_id,
                session_id=session_id
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "error": "CONFIRMATION_REQUIRED",
                    "message": f"Action '{name}' requires explicit single-use approval token.",
                    "confirmation_token": ticket["confirmation_token"],
                    "ticket": ticket,
                }
            )
        else:
            valid = confirmation_manager.consume_token(
                token=data.confirmation_token,
                tool_name=name,
                action_payload=params,
                device_id=device_id
            )
            if not valid:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="SECURITY_DENIED: Invalid, expired, or previously consumed confirmation token."
                )

    context = {
        "device_id": device_id,
        "session_id": session_id,
        "confirmed": bool(data.confirmation_token),
    }

    result = await registry.execute_skill(
        name=name,
        params=params,
        context=context
    )

    return result.model_dump()
