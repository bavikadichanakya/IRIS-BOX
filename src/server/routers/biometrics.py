import base64
import logging
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from src.security.biometrics import Role, SpeakerProfile, SpeakerIdentificationResult
from src.security.speaker_registry import SpeakerRegistry

logger = logging.getLogger("iris.server.routers.biometrics")

router = APIRouter(prefix="/biometrics", tags=["Speaker Biometrics"])


def get_speaker_registry(request: Request) -> SpeakerRegistry:
    """Retrieve SpeakerRegistry from application state."""
    reg = getattr(request.app.state, "speaker_registry", None)
    if reg is not None:
        return reg
    db = getattr(request.app.state, "db", None)
    if not hasattr(get_speaker_registry, "_instance") or get_speaker_registry._instance is None:
        get_speaker_registry._instance = SpeakerRegistry(db=db)
    return get_speaker_registry._instance


class EnrollSpeakerPayload(BaseModel):
    name: str = Field(..., min_length=1, description="Speaker name")
    role: Role = Field(Role.MEMBER, description="Assigned role: ADMIN, MEMBER, GUEST, RESTRICTED")
    samples: Optional[List[str]] = Field(None, description="List of base64-encoded PCM or WAV audio samples")
    audio_samples: Optional[List[str]] = Field(None, description="Alias for samples")
    speaker_id: Optional[str] = Field(None, description="Optional custom speaker_id")


class IdentifySpeakerPayload(BaseModel):
    audio: str = Field(..., min_length=1, description="Base64-encoded PCM or WAV audio sample")
    threshold: Optional[float] = Field(0.75, description="Cosine similarity threshold")


class UpdateSpeakerRolePayload(BaseModel):
    role: Role


@router.get("/speakers")
async def list_speakers(request: Request):
    """
    List registered speaker profiles and assigned roles (raw embeddings masked).
    """
    registry = get_speaker_registry(request)
    profiles = registry.list_speakers()
    return [
        {
            "speaker_id": p.speaker_id,
            "name": p.name,
            "role": p.role.value if isinstance(p.role, Role) else p.role,
            "enrolled_samples": p.enrolled_samples,
            "created_at": p.created_at,
            "embedding_dim": len(p.embedding) if p.embedding else 0
        }
        for p in profiles
    ]


@router.post("/enroll")
async def enroll_speaker(request: Request, payload: EnrollSpeakerPayload):
    """
    Enroll a new speaker profile with multiple audio samples.
    """
    registry = get_speaker_registry(request)
    input_samples = payload.samples or payload.audio_samples or []
    if not input_samples:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one audio sample ('samples' or 'audio_samples') is required for enrollment."
        )

    raw_samples: List[bytes] = []
    for idx, s in enumerate(input_samples):
        try:
            raw_samples.append(base64.b64decode(s))
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Sample at index {idx} contains invalid base64 data: {e}"
            )

    try:
        profile = await registry.enroll_speaker(
            name=payload.name,
            role=payload.role,
            audio_samples=raw_samples,
            speaker_id=payload.speaker_id
        )
        return {
            "success": True,
            "speaker_id": profile.speaker_id,
            "name": profile.name,
            "role": profile.role.value if isinstance(profile.role, Role) else profile.role,
            "enrolled_samples": profile.enrolled_samples,
            "created_at": profile.created_at
        }
    except Exception as e:
        logger.error("Enrollment failed: %s", e)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to enroll speaker: {e}"
        )


@router.delete("/speakers/{speaker_id}")
async def delete_speaker(request: Request, speaker_id: str):
    """
    Remove an enrolled speaker profile by ID.
    """
    registry = get_speaker_registry(request)
    deleted = await registry.delete_speaker(speaker_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Speaker profile '{speaker_id}' not found."
        )
    return {"success": True, "speaker_id": speaker_id}


@router.patch("/speakers/{speaker_id}/role")
async def update_speaker_role(request: Request, speaker_id: str, payload: UpdateSpeakerRolePayload):
    """
    Update role for an existing enrolled speaker.
    """
    registry = get_speaker_registry(request)
    updated = await registry.update_role(speaker_id, payload.role)
    if not updated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Speaker profile '{speaker_id}' not found."
        )
    return {
        "success": True,
        "speaker_id": updated.speaker_id,
        "role": updated.role.value if isinstance(updated.role, Role) else updated.role
    }


@router.post("/identify")
async def identify_speaker(request: Request, payload: IdentifySpeakerPayload):
    """
    Test identification on an uploaded audio sample against enrolled profiles.
    """
    registry = get_speaker_registry(request)
    try:
        audio_bytes = base64.b64decode(payload.audio)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid base64 audio payload: {e}"
        )

    threshold = payload.threshold if payload.threshold is not None else 0.75
    result = registry.identify_speaker(audio_bytes, threshold=threshold)

    return {
        "identified": result.identified,
        "speaker": {
            "speaker_id": result.speaker.speaker_id,
            "name": result.speaker.name,
            "role": result.speaker.role.value if isinstance(result.speaker.role, Role) else result.speaker.role,
            "enrolled_samples": result.speaker.enrolled_samples,
            "created_at": result.speaker.created_at
        } if result.speaker else None,
        "similarity": result.similarity,
        "role": result.role.value if isinstance(result.role, Role) else result.role
    }
