from __future__ import annotations
import logging
from typing import Optional, Dict, Any, List
from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from src.operator.desktop import DesktopEnvironment
from src.operator.app_launcher import AppLauncher
from src.operator.window_manager import WindowManager

logger = logging.getLogger("iris.server.routers.desktop")

router = APIRouter(prefix="/desktop", tags=["Desktop Intelligence"])


class ProcessKillPayload(BaseModel):
    pid: int = Field(..., description="Process ID to terminate")


class WindowFocusPayload(BaseModel):
    hwnd: Optional[int] = Field(None, description="Window handle (HWND) to focus")
    query: Optional[str] = Field(None, description="Window title or process name substring to focus")


class AppLaunchPayload(BaseModel):
    app_name: str = Field(..., description="Name of application to launch (e.g. notepad, chrome, code)")


class WindowQueryPayload(BaseModel):
    query: Optional[str] = Field(None, description="Window title or process name to match")
    hwnd: Optional[int] = Field(None, description="Window handle (HWND)")


class WindowStatePayload(BaseModel):
    query: Optional[str] = Field(None, description="Window title or process name to match")
    hwnd: Optional[int] = Field(None, description="Window handle (HWND)")
    state: str = Field("maximize", description="Target window state: 'maximize', 'minimize', or 'restore'")


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


@router.post("/apps/launch")
async def launch_application(payload: AppLaunchPayload):
    """
    Launch target application cleanly detached from current Python process.
    """
    try:
        res = AppLauncher.launch_app(payload.app_name)
        return {"status": "SUCCESS", "app_name": payload.app_name, "result": res}
    except FileNotFoundError as fnf:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(fnf),
        )
    except Exception as exc:
        logger.error(f"Failed to launch app '{payload.app_name}': {exc}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to launch application: {str(exc)}",
        )


@router.post("/windows/focus")
async def focus_window_advanced(payload: WindowFocusPayload):
    """
    Switch active focus to the specified application window by HWND or title query.
    """
    target = payload.hwnd or payload.query
    if target is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing 'query' or 'hwnd' parameter.",
        )
    try:
        focused = WindowManager.focus_window(target)
        if not focused:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Window matching '{target}' could not be focused.",
            )
        matched = WindowManager.find_window(target)
        return {"status": "SUCCESS", "target": target, "window": matched}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Failed to focus window '{target}': {exc}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to focus window: {str(exc)}",
        )


@router.post("/focus")
async def focus_window_legacy(payload: WindowFocusPayload):
    """Legacy focus endpoint for HWND focus."""
    return await focus_window_advanced(payload)


@router.post("/windows/state")
async def set_window_state(payload: WindowStatePayload):
    """
    Change window state: 'maximize', 'minimize', or 'restore'.
    """
    target = payload.hwnd or payload.query
    if target is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing 'query' or 'hwnd' parameter.",
        )
    try:
        ok = WindowManager.set_window_state(target, payload.state)
        if not ok:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Window matching '{target}' could not be found or updated.",
            )
        return {"status": "SUCCESS", "target": target, "state": payload.state}
    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ve))
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Failed to set window state for '{target}': {exc}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to set window state: {str(exc)}",
        )


@router.post("/windows/close")
async def close_window(payload: WindowQueryPayload):
    """
    Gracefully request window close with system blacklist protection.
    """
    target = payload.hwnd or payload.query
    if target is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing 'query' or 'hwnd' parameter.",
        )
    try:
        ok = WindowManager.close_window(target)
        return {"status": "CLOSED", "target": target, "success": ok}
    except LookupError as le:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(le))
    except PermissionError as pe:
        logger.warning(f"Security rejection on close_window '{target}': {pe}")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(pe))
    except Exception as exc:
        logger.error(f"Failed to close window '{target}': {exc}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to close window: {str(exc)}",
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
