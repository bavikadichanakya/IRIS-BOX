from typing import Dict, Literal, Optional, Any, Union

from pydantic import BaseModel, Field


class SmartHomeAction(BaseModel):
    """
    Schema for a smart home action.
    """
    entity_id: str
    domain: str
    action: Literal["on", "off", "toggle"]
    attributes: Optional[Dict] = None


class LaptopSystemAction(BaseModel):
    """
    Schema for a laptop system action.
    """
    command: str
    action_type: Literal["launch", "file", "terminal", "test", "execution"] = "terminal"
    timeout_sec: int = 10
    cwd: Optional[str] = None


class BrowserAction(BaseModel):
    """
    Schema for a browser action.
    """
    url: str
    action: Literal["goto", "navigate", "open", "click", "type_text", "extract", "extract_text", "screenshot"]
    selector: Optional[str] = None
    input_text: Optional[str] = None
    timeout_ms: Optional[int] = None


class ProjectOperatorAction(BaseModel):
    """
    Schema for an AI Project Operator action (checkpoint, patch, test, verification, rollback).
    """
    action: str = "diagnose"
    project_path: Optional[str] = None
    project_name: Optional[str] = None
    spoken_reference: Optional[str] = None
    checkpoint_name: Optional[str] = "checkpoint"
    checkpoint_id: Optional[str] = None
    file_path: Optional[str] = None
    patch: Optional[Union[str, Dict[str, Any]]] = None
    diff: Optional[str] = None
    find_content: Optional[str] = None
    replace_content: Optional[str] = None
    test_command: Optional[str] = None
    command: Optional[str] = None
    timeout_sec: int = 30


class DesktopAction(BaseModel):
    """
    Schema for a Desktop Intelligence action (telemetry, processes, services, windows, kill).
    """
    action: str = Field("get_system_metrics", description="Action to perform: get_system_metrics, get_top_processes, check_service, get_visible_windows, focus_window, kill_process")
    sort_by: str = Field("cpu", description="Sort by 'cpu' or 'memory'")
    limit: int = Field(5, description="Number of items to return")
    service_name: Optional[str] = Field(None, description="Name of service to inspect (e.g. docker, ollama, wsl, postgres, redis)")
    pid: Optional[int] = Field(None, description="Process ID to terminate")
    hwnd: Optional[int] = Field(None, description="Window handle to focus")


class WindowAutomationAction(BaseModel):
    """
    Schema for Multi-Window Application Automation & Window Focus Control.
    """
    action: str = Field("focus_window", description="Action: launch_app, focus_window, set_window_state, close_window")
    app_name: Optional[str] = Field(None, description="Name of application to launch (e.g. chrome, code, spotify, notepad)")
    query: Optional[str] = Field(None, description="Window title, process name, or query to match window")
    hwnd: Optional[int] = Field(None, description="Window handle (HWND)")
    state: Optional[str] = Field(None, description="Target window state: 'maximize', 'minimize', or 'restore'")


class VoiceCommandPayload(BaseModel):
    """
    Schema for a voice command payload.
    """
    raw_transcript: str
    confidence: float
    timestamp: str


class AgentExecutionResult(BaseModel):
    """
    Schema for the result of an agent's tool execution.
    """
    success: bool
    tool_name: str
    output_payload: Dict = Field(default_factory=dict)
    error: Optional[str] = None
    confirmation_token: Optional[str] = None
    pending_action: Optional[Dict] = None
    status: Optional[str] = None
    plan_id: Optional[str] = None
    tool_arguments: Optional[Dict[str, Any]] = None

    def __getitem__(self, item: str) -> Any:
        if hasattr(self, item):
            val = getattr(self, item)
            if val is not None:
                return val
        if isinstance(self.output_payload, dict) and item in self.output_payload:
            return self.output_payload[item]
        raise KeyError(item)


class StreamChunkPayload(BaseModel):
    """
    Schema for a streaming chunk.
    """
    chunk_type: Literal["text_delta", "tool_call", "tool_result", "complete"]
    delta_text: str = ""
    session_id: str
    tool_name: Optional[str] = None
    tool_output: Optional[Dict] = None
    confirmation_token: Optional[str] = None
