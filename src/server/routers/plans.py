import logging
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel

from src.agent.plan_manager import ExecutionPlan, PlanManager, PlanStatus

logger = logging.getLogger("iris.server.routers.plans")

router = APIRouter(prefix="/plans", tags=["Execution Plans"])


def get_plan_manager(request: Request) -> PlanManager:
    """Retrieve PlanManager from application state or orchestrator."""
    if hasattr(request.app.state, "plan_manager") and request.app.state.plan_manager is not None:
        return request.app.state.plan_manager

    orch = getattr(request.app.state, "orchestrator", None)
    if orch and hasattr(orch, "plan_manager") and orch.plan_manager is not None:
        return orch.plan_manager

    # Fallback to module singleton
    if not hasattr(get_plan_manager, "_instance"):
        get_plan_manager._instance = PlanManager()
    return get_plan_manager._instance


class ApprovePlanPayload(BaseModel):
    token: Optional[str] = None


class RejectPlanPayload(BaseModel):
    reason: Optional[str] = None


@router.get("/active")
async def list_active_plans(request: Request):
    """
    List currently active, staged, or approved plans.
    """
    pm = get_plan_manager(request)
    active_plans = pm.list_active_plans()
    return {
        "plans": [p.model_dump() for p in active_plans],
        "count": len(active_plans),
    }


@router.get("/{plan_id}")
async def get_plan_details(plan_id: str, request: Request):
    """
    Inspect plan details, steps, descriptions, parameters, and statuses.
    """
    pm = get_plan_manager(request)
    plan = pm.get_plan(plan_id)
    if not plan:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Plan '{plan_id}' not found.",
        )
    return plan.model_dump()


@router.post("/{plan_id}/approve")
async def approve_plan(
    plan_id: str,
    request: Request,
    payload: Optional[ApprovePlanPayload] = None,
):
    """
    Approve a staged plan and immediately trigger ordered sequential step execution.
    """
    pm = get_plan_manager(request)
    plan = pm.get_plan(plan_id)
    if not plan:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Plan '{plan_id}' not found.",
        )

    token = payload.token if payload else None
    approved = pm.approve_plan(plan_id, token=token)
    if not approved:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot approve plan '{plan_id}' (current status: {plan.status.value}).",
        )

    orch = getattr(request.app.state, "orchestrator", None)
    try:
        executed_plan = await pm.execute_approved_plan(plan_id=plan_id, orchestrator=orch)
        return executed_plan.model_dump()
    except Exception as exc:
        logger.error(f"Execution failed for approved plan '{plan_id}': {exc}", exc_info=True)
        updated_plan = pm.get_plan(plan_id)
        if updated_plan:
            return updated_plan.model_dump()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error executing plan: {exc}",
        )


@router.post("/{plan_id}/reject")
async def reject_plan(
    plan_id: str,
    request: Request,
    payload: Optional[RejectPlanPayload] = None,
):
    """
    Reject and discard a staged plan.
    """
    pm = get_plan_manager(request)
    plan = pm.get_plan(plan_id)
    if not plan:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Plan '{plan_id}' not found.",
        )

    reason = payload.reason if payload else None
    rejected = pm.reject_plan(plan_id, reason=reason)
    if not rejected:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot reject plan '{plan_id}' (current status: {plan.status.value}).",
        )

    updated_plan = pm.get_plan(plan_id)
    return {
        "status": "REJECTED",
        "plan_id": plan_id,
        "reason": reason,
        "plan": updated_plan.model_dump() if updated_plan else None,
    }
