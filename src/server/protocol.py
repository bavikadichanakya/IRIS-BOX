import time
from typing import List, Optional, Union, Dict, Any, Literal
from pydantic import BaseModel, Field


# ------------------------------------------------------------------
# Inbound Client -> Server Message Schemas
# ------------------------------------------------------------------

class InboundConnectPayload(BaseModel):
    type: Literal["connect"] = "connect"
    version: str = "1.0"
    device_id: str = "unknown"
    auth_token: Optional[str] = None
    capabilities: List[str] = Field(default_factory=list)


class InboundAudioFramePayload(BaseModel):
    type: Literal["audio_frame"] = "audio_frame"
    format: str = "pcm16"
    sample_rate: int = 16000
    data: str  # Base64-encoded PCM bytes


class InboundTextInputPayload(BaseModel):
    type: Literal["text_input"] = "text_input"
    text: str
    session_id: Optional[str] = None


class InboundPingPayload(BaseModel):
    type: Literal["ping"] = "ping"
    timestamp: Optional[float] = Field(default_factory=time.time)


class InboundCancelPayload(BaseModel):
    type: Literal["cancel"] = "cancel"
    request_id: Optional[str] = None


InboundMessage = Union[
    InboundConnectPayload,
    InboundAudioFramePayload,
    InboundTextInputPayload,
    InboundPingPayload,
    InboundCancelPayload,
]


# ------------------------------------------------------------------
# Outbound Server -> Client Message Schemas
# ------------------------------------------------------------------

class OutboundConnectedPayload(BaseModel):
    type: Literal["connected"] = "connected"
    version: str = "1.0"
    session_id: str
    server_time: float = Field(default_factory=time.time)


class OutboundPongPayload(BaseModel):
    type: Literal["pong"] = "pong"
    timestamp: Optional[float] = Field(default_factory=time.time)


class OutboundVADPayload(BaseModel):
    type: Literal["vad"] = "vad"
    state: str  # "SPEECH_START", "SPEECH_END", "SPEECH_CONTINUING"


class OutboundTranscriptPayload(BaseModel):
    type: Literal["transcript"] = "transcript"
    text: str
    is_final: bool = False
    request_id: Optional[str] = None


class OutboundTokenDeltaPayload(BaseModel):
    type: Literal["token_delta"] = "token_delta"
    delta: str
    request_id: Optional[str] = None


class OutboundToolStatusPayload(BaseModel):
    type: Literal["tool_status"] = "tool_status"
    tool_name: str
    status: str  # "INVOKING", "COMPLETED", "FAILED", "DENIED"
    error: Optional[str] = None
    output_payload: Optional[Dict[str, Any]] = None


class OutboundAudioOutputPayload(BaseModel):
    type: Literal["audio_output"] = "audio_output"
    format: str = "pcm16"
    data: str  # Base64-encoded audio bytes


class OutboundTurnCompletePayload(BaseModel):
    type: Literal["turn_complete"] = "turn_complete"
    request_id: str
    duration_ms: float = 0.0


class OutboundErrorPayload(BaseModel):
    type: Literal["error"] = "error"
    code: str
    message: str


# ------------------------------------------------------------------
# Protocol Parser Helper
# ------------------------------------------------------------------

def parse_inbound_message(data: Dict[str, Any]) -> InboundMessage:
    """Parse raw JSON dictionary into typed InboundMessage payload."""
    msg_type = data.get("type")
    if msg_type == "connect":
        return InboundConnectPayload(**data)
    elif msg_type == "audio_frame":
        return InboundAudioFramePayload(**data)
    elif msg_type == "text_input":
        return InboundTextInputPayload(**data)
    elif msg_type == "ping":
        return InboundPingPayload(**data)
    elif msg_type == "cancel":
        return InboundCancelPayload(**data)
    else:
        raise ValueError(f"Unknown inbound message type: '{msg_type}'")
