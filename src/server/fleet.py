import time
from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field
from fastapi import APIRouter, HTTPException, Request, status

class SpeakerDevice(BaseModel):
    speaker_id: str
    name: str
    room: str
    ip_address: Optional[str] = None
    status: str = "online"  # "online", "offline", "busy"
    last_heartbeat: float = Field(default_factory=time.time)
    metadata: Dict[str, Any] = Field(default_factory=dict)

class SpeakerRegisterRequest(BaseModel):
    speaker_id: str
    name: str
    room: str
    ip_address: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

class HeartbeatRequest(BaseModel):
    speaker_id: str
    status: Optional[str] = "online"

class BroadcastRequest(BaseModel):
    command: str
    room: Optional[str] = None
    speaker_ids: Optional[List[str]] = None
    payload: Optional[Dict[str, Any]] = None

class BroadcastResult(BaseModel):
    command: str
    target_count: int
    target_speaker_ids: List[str]
    delivered: bool = True
    details: Optional[Dict[str, Any]] = None

class FleetManager:
    """
    Manages multi-speaker fleet devices, room assignments, heartbeats,
    and broadcast routing.
    """
    def __init__(self, heartbeat_timeout_seconds: float = 60.0):
        self._speakers: Dict[str, SpeakerDevice] = {}
        self.heartbeat_timeout_seconds = heartbeat_timeout_seconds

    def register_speaker(
        self,
        speaker_id: str,
        name: str,
        room: str,
        ip_address: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> SpeakerDevice:
        now = time.time()
        device = SpeakerDevice(
            speaker_id=speaker_id,
            name=name,
            room=room.lower().strip(),
            ip_address=ip_address,
            status="online",
            last_heartbeat=now,
            metadata=metadata or {}
        )
        self._speakers[speaker_id] = device
        return device

    def unregister_speaker(self, speaker_id: str) -> bool:
        if speaker_id in self._speakers:
            del self._speakers[speaker_id]
            return True
        return False

    def get_speaker(self, speaker_id: str) -> Optional[SpeakerDevice]:
        return self._speakers.get(speaker_id)

    def record_heartbeat(self, speaker_id: str, status: Optional[str] = "online") -> SpeakerDevice:
        device = self._speakers.get(speaker_id)
        if not device:
            raise KeyError(f"Speaker '{speaker_id}' not found")
        device.last_heartbeat = time.time()
        if status:
            device.status = status
        return device

    def list_speakers(self, room: Optional[str] = None, active_only: bool = False) -> List[SpeakerDevice]:
        speakers = list(self._speakers.values())
        if room:
            room_normalized = room.lower().strip()
            speakers = [s for s in speakers if s.room == room_normalized]
        if active_only:
            now = time.time()
            speakers = [
                s for s in speakers
                if (now - s.last_heartbeat) <= self.heartbeat_timeout_seconds and s.status != "offline"
            ]
        return speakers

    def list_rooms(self) -> List[str]:
        return sorted(list({s.room for s in self._speakers.values()}))

    def get_speakers_by_room(self) -> Dict[str, List[SpeakerDevice]]:
        rooms: Dict[str, List[SpeakerDevice]] = {}
        for speaker in self._speakers.values():
            rooms.setdefault(speaker.room, []).append(speaker)
        return rooms

    def check_stale_speakers(self) -> List[str]:
        """Marks speakers as offline if their heartbeat timed out."""
        now = time.time()
        stale_ids = []
        for speaker_id, device in self._speakers.items():
            if (now - device.last_heartbeat) > self.heartbeat_timeout_seconds:
                device.status = "offline"
                stale_ids.append(speaker_id)
        return stale_ids

    def broadcast(
        self,
        command: str,
        room: Optional[str] = None,
        speaker_ids: Optional[List[str]] = None,
        payload: Optional[Dict[str, Any]] = None
    ) -> BroadcastResult:
        """
        Broadcasts a command to all speakers, a target room, or explicit speaker IDs.
        """
        targets: List[SpeakerDevice] = []
        if speaker_ids is not None:
            targets = [self._speakers[sid] for sid in speaker_ids if sid in self._speakers]
        elif room:
            room_normalized = room.lower().strip()
            targets = [s for s in self._speakers.values() if s.room == room_normalized]
        else:
            targets = list(self._speakers.values())

        target_ids = [s.speaker_id for s in targets]
        return BroadcastResult(
            command=command,
            target_count=len(target_ids),
            target_speaker_ids=target_ids,
            delivered=True,
            details={
                "room": room,
                "payload": payload or {}
            }
        )

# FastAPI Router
router = APIRouter(prefix="/fleet", tags=["Fleet Management"])

def get_fleet_manager(request: Request) -> FleetManager:
    fleet_mgr = getattr(request.app.state, "fleet_manager", None)
    if fleet_mgr is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Fleet manager not initialized"
        )
    return fleet_mgr

@router.post("/register", response_model=SpeakerDevice)
async def register_speaker(payload: SpeakerRegisterRequest, request: Request):
    mgr = get_fleet_manager(request)
    device = mgr.register_speaker(
        speaker_id=payload.speaker_id,
        name=payload.name,
        room=payload.room,
        ip_address=payload.ip_address,
        metadata=payload.metadata
    )
    return device

@router.delete("/speakers/{speaker_id}")
async def unregister_speaker(speaker_id: str, request: Request):
    mgr = get_fleet_manager(request)
    deleted = mgr.unregister_speaker(speaker_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Speaker not found")
    return {"status": "unregistered", "speaker_id": speaker_id}

@router.get("/speakers", response_model=List[SpeakerDevice])
async def list_speakers(request: Request, room: Optional[str] = None, active_only: bool = False):
    mgr = get_fleet_manager(request)
    return mgr.list_speakers(room=room, active_only=active_only)

@router.get("/speakers/{speaker_id}", response_model=SpeakerDevice)
async def get_speaker(speaker_id: str, request: Request):
    mgr = get_fleet_manager(request)
    device = mgr.get_speaker(speaker_id)
    if not device:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Speaker not found")
    return device

@router.post("/heartbeat", response_model=SpeakerDevice)
async def record_heartbeat(payload: HeartbeatRequest, request: Request):
    mgr = get_fleet_manager(request)
    try:
        return mgr.record_heartbeat(speaker_id=payload.speaker_id, status=payload.status)
    except KeyError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))

@router.get("/rooms")
async def list_rooms(request: Request):
    mgr = get_fleet_manager(request)
    return {
        "rooms": mgr.list_rooms(),
        "by_room": {
            room: [s.model_dump() for s in speakers]
            for room, speakers in mgr.get_speakers_by_room().items()
        }
    }

@router.post("/broadcast", response_model=BroadcastResult)
async def broadcast_command(payload: BroadcastRequest, request: Request):
    mgr = get_fleet_manager(request)
    return mgr.broadcast(
        command=payload.command,
        room=payload.room,
        speaker_ids=payload.speaker_ids,
        payload=payload.payload
    )
