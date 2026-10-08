from pydantic import BaseModel

class TraceContext(BaseModel):
    device_id: str
    session_id: Optional[str] = None
    urn_id: Optional[str] = None
    request_id: Optional[str] = None
    ask_id: Optional[str] = None
    agent_execution_id: Optional[str] = None
    race_id: Optional[str] = None

def create_trace_context(device_id: str, session_id: Optional[str] = None) -> TraceContext:
    return TraceContext(device_id=device_id, session_id=session_id)
