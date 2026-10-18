from __future__ import annotations
import logging
from typing import Optional, Dict, Any, List
from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from src.operator.desktop import DesktopEnvironment

logger = logging.getLogger("iris.server.routers.desktop")

router = APIRouter(prefix="/desktop", tags=["Desktop Intelligence"])


class ProcessKillPayload(BaseModel):
    pid: int = Field(..., description="Process ID to terminate")


class WindowFocusPayload(BaseModel):
    hwnd: int = Field(..., description="Window handle (HWND) to focus")


@router.get("/metrics")
async def get_system_metrics():
    """
    Returns real-time desktop telemetry: CPU %, RAM %, Disk capacity, and Battery state.
    """
    try:
        metrics = DesktopEnvironment.get_system_metrics()
        return metrics
    except Exception as exc:
        logger.error(f"Failed to fetch system metrics: {exc}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch system metrics: {str(exc)}",
        )


@router.get("/processes")
async def get_top_processes(
    sort_by: str = Query("cpu", description="Metric to sort by ('cpu' or 'memory')"),
    limit: int = Query(5, ge=1, le=50, description="Maximum number of processes to return"),
):
    """
    Enumerate top resource-consuming processes sorted by CPU or memory.
    """
    try:
        procs = DesktopEnvironment.get_top_processes(limit=limit, sort_by=sort_by)
        return {
            "sort_by": sort_by,
            "limit": limit,
            "processes": procs,
        }
    except Exception as exc:
        logger.error(f"Failed to fetch top processes: {exc}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch top processes: {str(exc)}",
        )


@router.get("/services")
async def get_services(
    service: Optional[str] = Query(None, description="Optional service name to inspect (e.g. docker, ollama, wsl)"),
):
    """
    Check operational status of local developer services (Docker, Ollama, WSL, Postgres, Redis).
    """
    try:
        if service:
            details = DesktopEnvironment.inspect_service(service)
            return details
        else:
            services = DesktopEnvironment.inspect_common_services()
            return services
    except Exception as exc:
        logger.error(f"Failed to inspect services: {exc}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to inspect services: {str(exc)}",
        )


@router.get("/windows")
async def get_visible_windows():
    """
    Enumerate visible desktop application windows with titles, HWNDs, and owning processes.
    """
    try:
        windows = DesktopEnvironment.get_visible_windows()
        return {
            "count": len(windows),
            "windows": windows,
        }
    except Exception as exc:
        logger.error(f"Failed to enumerate windows: {exc}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to enumerate windows: {str(exc)}",
        )


@router.post("/focus")
async def focus_window(payload: WindowFocusPayload):
    """
    Switch active focus to the specified application window.
    """
    try:
        focused = DesktopEnvironment.focus_window(payload.hwnd)
        if not focused:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Window with HWND {payload.hwnd} could not be focused.",
            )
        return {"status": "SUCCESS", "hwnd": payload.hwnd}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Failed to focus window {payload.hwnd}: {exc}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to focus window: {str(exc)}",
        )


@router.post("/kill")
async def kill_process(payload: ProcessKillPayload):
    """
    Safely terminate a process by PID with system process blacklist protection.
    """
    try:
        killed = DesktopEnvironment.kill_process(payload.pid)
        return {"status": "TERMINATED", "pid": payload.pid, "success": killed}
    except PermissionError as pe:
        logger.warning(f"Security rejection on kill_process {payload.pid}: {pe}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(pe),
        )
    except ProcessLookupError as ple:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(ple),
        )
    except Exception as exc:
        logger.error(f"Failed to terminate PID {payload.pid}: {exc}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to terminate process: {str(exc)}",
        )
