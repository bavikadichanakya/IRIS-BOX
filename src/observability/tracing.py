import uuid
from typing import Optional
from pydantic import BaseModel, Field

class TraceContext(BaseModel):
    device_id: str = "local"
    session_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    turn_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    request_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    task_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    agent_execution_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    trace_id: str = Field(default_factory=lambda: str(uuid.uuid4()))

def create_trace_context(
    device_id: str = "local",
    session_id: Optional[str] = None,
    turn_id: Optional[str] = None
) -> TraceContext:
    return TraceContext(
        device_id=device_id or "local",
        session_id=session_id or str(uuid.uuid4()),
        turn_id=turn_id or str(uuid.uuid4())
    )
