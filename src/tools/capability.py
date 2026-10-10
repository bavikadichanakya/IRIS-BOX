from enum import Enum
from typing import Any, Optional, Dict, List
from pydantic import BaseModel, Field, ConfigDict

class PermissionLevel(str, Enum):
    PUBLIC = "PUBLIC"          # Safe lookup (time, weather, facts)
    PROTECTED = "PROTECTED"    # Smart home actions, status reads
    SENSITIVE = "SENSITIVE"    # Shell execution, deletes, config mutations

class ExecutionStatus(str, Enum):
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    DENIED = "DENIED"
    TIMEOUT = "TIMEOUT"
    UNAVAILABLE = "UNAVAILABLE"
    CANCELLED = "CANCELLED"

class Capability(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: str
    description: str
    schema_def: Dict[str, Any] = Field(default_factory=dict, alias="schema")
    permission_level: PermissionLevel = PermissionLevel.PUBLIC
    category: str = "general"
    supported_devices: List[str] = Field(default_factory=lambda: ["pod", "laptop", "phone"])
    requires_confirmation: bool = False
    execution_timeout_sec: float = 10.0

class ToolResult(BaseModel):
    status: ExecutionStatus
    tool_name: str
    request_id: str = ""
    trace_id: str = ""
    output: Optional[Any] = None
    error: Optional[str] = None
    duration_ms: float = 0.0
    confirmation_token: Optional[str] = None
    pending_action: Optional[Dict[str, Any]] = None
