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

    token = (payload.token if payload else None) or request.query_params.get("token") or request.headers.get("X-Plan-Token")
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


@router.post("/{plan_id}/rollback")
async def rollback_plan(plan_id: str, request: Request):
    """
    Rollback a plan by reverting to its safety checkpoint if available.
    """
    pm = get_plan_manager(request)
    plan = pm.get_plan(plan_id)
    if not plan:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Plan '{plan_id}' not found.",
        )

    checkpoint_id = plan.checkpoint_id or (plan.metadata.get("checkpoint_id") if plan.metadata else None)
    project_path = plan.project_path or (plan.metadata.get("project_path") if plan.metadata else None)

    if not checkpoint_id or not project_path:
        for step in plan.steps:
            if step.result and isinstance(step.result.get("output"), dict) and "checkpoint_id" in step.result["output"]:
                checkpoint_id = step.result["output"]["checkpoint_id"]
                project_path = step.result["output"].get("project_path", project_path)
                break

    if not checkpoint_id or not project_path:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Plan '{plan_id}' does not have an associated safety checkpoint.",
        )

    from src.operator.workspace import ProjectWorkspace
    success = ProjectWorkspace.revert_checkpoint(project_path, checkpoint_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to revert checkpoint '{checkpoint_id}'.",
        )

    return {
        "status": "ROLLED_BACK",
        "plan_id": plan_id,
        "checkpoint_id": checkpoint_id,
        "project_path": project_path,
        "message": f"Successfully reverted to checkpoint '{checkpoint_id}'.",
    }

