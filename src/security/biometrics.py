import time
from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field


class Role(str, Enum):
    ADMIN = "ADMIN"
    MEMBER = "MEMBER"
    GUEST = "GUEST"
    RESTRICTED = "RESTRICTED"


class SpeakerProfile(BaseModel):
    speaker_id: str
    name: str
    role: Role
    embedding: List[float]
    enrolled_samples: int = 1
    created_at: float = Field(default_factory=time.time)


class SpeakerIdentificationResult(BaseModel):
    identified: bool
    speaker: Optional[SpeakerProfile] = None
    similarity: float = 0.0
    role: Role = Role.GUEST


class AuthorizationDecision(BaseModel):
    authorized: bool
    reason: Optional[str] = None
    required_role: Role
    speaker_role: Role
