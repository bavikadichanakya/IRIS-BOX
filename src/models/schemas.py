from typing import Dict, Literal, Optional

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
    action_type: Literal["launch", "file", "terminal"]
    timeout_sec: int = 10


class BrowserAction(BaseModel):
    """
    Schema for a browser action.
    """
    url: str
    action: Literal["goto", "click", "extract"]
    selector: Optional[str] = None


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
    output_payload: Dict
    error: Optional[str] = None
