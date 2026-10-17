import logging
from typing import Optional, Dict, Any
from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from src.agent.plan_manager import PlanManager
from src.operator.workspace import ProjectWorkspace, ProjectSnapshot
from src.operator.task_runner import OperatorTaskRunner, DiagnosticReport

logger = logging.getLogger("iris.server.routers.operator")

router = APIRouter(prefix="/operator", tags=["Project Operator"])


def get_plan_manager(request: Request) -> PlanManager:
    """Retrieve PlanManager from application state or orchestrator."""
    if hasattr(request.app.state, "plan_manager") and request.app.state.plan_manager is not None:
        return request.app.state.plan_manager

    orch = getattr(request.app.state, "orchestrator", None)
    if orch and hasattr(orch, "plan_manager") and orch.plan_manager is not None:
        return orch.plan_manager

    if not hasattr(get_plan_manager, "_instance"):
        get_plan_manager._instance = PlanManager()
    return get_plan_manager._instance


class ProjectDiagnosePayload(BaseModel):
    project_path: str = Field(..., description="Absolute path to target local project")
    test_command: Optional[str] = Field(None, description="Optional custom test suite command")


class ProjectPlanFixPayload(BaseModel):
    project_path: str = Field(..., description="Absolute path to target local project")
    test_command: Optional[str] = Field(None, description="Optional custom test suite command")


class ProjectRollbackPayload(BaseModel):
    project_path: str = Field(..., description="Absolute path to target local project")
    checkpoint_id: str = Field(..., description="Checkpoint identifier to restore")


class ProjectSnapshotPayload(BaseModel):
    project_path: str = Field(..., description="Absolute path to target local project")


@router.post("/snapshot")
async def snapshot_project(payload: ProjectSnapshotPayload):
    """
    Inspect project workspace and return environment intelligence snapshot.
    """
    try:
        snapshot = ProjectWorkspace.snapshot_environment(payload.project_path)
        return snapshot.model_dump()
    except Exception as exc:
        logger.error(f"Failed to snapshot workspace '{payload.project_path}': {exc}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to snapshot workspace: {str(exc)}",
        )


@router.post("/diagnose")
async def diagnose_project(payload: ProjectDiagnosePayload, request: Request):
    """
    Run the project test suite in read-only mode and return diagnostic report.
    """
    pm = get_plan_manager(request)
    runner = OperatorTaskRunner(plan_manager=pm)
    try:
        report = await runner.diagnose_failure(
            project_path=payload.project_path,
            test_command=payload.test_command,
        )
        return report.model_dump()
    except Exception as exc:
        logger.error(f"Diagnostic failure on '{payload.project_path}': {exc}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Diagnostic failure: {str(exc)}",
        )


@router.post("/plan-fix")
async def plan_project_fix(payload: ProjectPlanFixPayload, request: Request):
    """
    Diagnose project test failures, generate surgical patch, and stage cryptographic ExecutionPlan.
    """
    pm = get_plan_manager(request)
    runner = OperatorTaskRunner(plan_manager=pm)
    try:
        diagnostic = await runner.diagnose_failure(
            project_path=payload.project_path,
            test_command=payload.test_command,
        )
        plan = runner.propose_patch(diagnostic=diagnostic)
        return {
            "diagnostic": diagnostic.model_dump(),
            "plan": plan.model_dump(),
        }
    except Exception as exc:
        logger.error(f"Fix planning failure on '{payload.project_path}': {exc}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Fix planning failure: {str(exc)}",
        )


@router.post("/rollback")
async def rollback_project(payload: ProjectRollbackPayload):
    """
    Immediately revert project workspace cleanly to the specified pre-task checkpoint.
    """
    try:
        success = ProjectWorkspace.revert_checkpoint(
            path=payload.project_path,
            checkpoint_id=payload.checkpoint_id,
        )
        if not success:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Failed to revert checkpoint '{payload.checkpoint_id}'. Checkpoint directory or metadata missing.",
            )
        return {
            "status": "ROLLED_BACK",
            "success": True,
            "project_path": payload.project_path,
            "checkpoint_id": payload.checkpoint_id,
            "message": f"Successfully reverted workspace to checkpoint '{payload.checkpoint_id}'.",
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Rollback error on '{payload.project_path}' (chk: {payload.checkpoint_id}): {exc}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Rollback execution failed: {str(exc)}",
        )
