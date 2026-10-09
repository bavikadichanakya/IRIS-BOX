import time
import hashlib
import uuid
import asyncio
import logging
from typing import Dict, List, Optional, Any, Union
from pydantic import BaseModel, Field
from fastapi import APIRouter, HTTPException, Request, status

from src.observability.event_bus import EventBus
from src.observability.tracing import create_trace_context, TraceContext
from src.server.protocol import InboundCommandAckPayload, OutboundDeviceCommandPayload

logger = logging.getLogger("iris.fleet.manager")


class SpeakerDevice(BaseModel):
    speaker_id: str
    name: str
    room: str
    ip_address: Optional[str] = None
    status: str = "online"  # "online", "offline", "degraded"
    last_heartbeat: float = Field(default_factory=time.time)
    device_type: str = "speaker"  # "speaker", "display", "sensor"
    capabilities: List[str] = Field(default_factory=list)
    auth_token_hash: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @property
    def device_id(self) -> str:
        return self.speaker_id

    @property
    def last_seen(self) -> float:
        return self.last_heartbeat


DeviceInfo = SpeakerDevice


class SpeakerRegisterRequest(BaseModel):
    speaker_id: str
    name: str
    room: str
    ip_address: Optional[str] = None
    device_type: str = "speaker"
    auth_token: Optional[str] = None
    capabilities: Optional[List[str]] = None
    metadata: Optional[Dict[str, Any]] = None


class HeartbeatRequest(BaseModel):
    speaker_id: str
    status: Optional[str] = "online"


class CommandResult(BaseModel):
    device_id: str
    command_id: str
    delivered: bool
    acknowledged: bool
    latency_ms: float = 0.0
    error: Optional[str] = None
    output: Optional[Dict[str, Any]] = None


class FleetBroadcastResult(BaseModel):
    command: str
    command_id: str = Field(default_factory=lambda: f"cmd-{uuid.uuid4()}")
    target_count: int
    target_speaker_ids: List[str] = Field(default_factory=list)
    sent_count: int = 0
    acknowledged_count: int = 0
    failed_devices: Dict[str, str] = Field(default_factory=dict)
    delivered: bool = True
    results: List[CommandResult] = Field(default_factory=list)
    details: Optional[Dict[str, Any]] = None


BroadcastResult = FleetBroadcastResult


class BroadcastRequest(BaseModel):
    command: str
    room: Optional[str] = None
    speaker_ids: Optional[List[str]] = None
    payload: Optional[Dict[str, Any]] = None
    timeout: float = 5.0


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class FleetManager:
    """
    Manages multi-speaker fleet devices, room assignments, heartbeats,
    token authentication, and real-time bidirectional command delivery over WebSockets.
    """

    def __init__(
        self,
        heartbeat_timeout_seconds: float = 60.0,
        ws_manager: Optional[Any] = None,
        event_bus: Optional[EventBus] = None
    ):
        self._speakers: Dict[str, SpeakerDevice] = {}
        self.heartbeat_timeout_seconds = heartbeat_timeout_seconds
        self.ws_manager = ws_manager
        self.event_bus = event_bus or EventBus()
        self._pending_command_futures: Dict[str, asyncio.Future] = {}

    def register_speaker(
        self,
        speaker_id: str,
        name: str,
        room: str,
        ip_address: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        auth_token: Optional[str] = None,
        capabilities: Optional[List[str]] = None,
        device_type: str = "speaker"
    ) -> SpeakerDevice:
        now = time.time()
        token_hash = _hash_token(auth_token) if auth_token else None
        device = SpeakerDevice(
            speaker_id=speaker_id,
            name=name,
            room=room.lower().strip(),
            ip_address=ip_address,
            status="online",
            last_heartbeat=now,
            device_type=device_type,
            capabilities=capabilities or [],
            auth_token_hash=token_hash,
            metadata=metadata or {}
        )
        self._speakers[speaker_id] = device

        trace = create_trace_context(device_id=speaker_id)
        try:
            asyncio.get_running_loop().create_task(self.event_bus.publish(
                "fleet.device.registered",
                {
                    "device_id": speaker_id,
                    "name": name,
                    "room": device.room,
                    "device_type": device_type,
                    "status": "online",
                },
                trace=trace
            ))
        except RuntimeError:
            pass

        logger.info(f"Registered device '{speaker_id}' ({name}) in room '{device.room}'.")
        return device

    def register_device(self, *args, **kwargs) -> SpeakerDevice:
        return self.register_speaker(*args, **kwargs)

    def unregister_speaker(self, speaker_id: str) -> bool:
        if speaker_id in self._speakers:
            del self._speakers[speaker_id]
            return True
        return False

    def authenticate_device(self, device_id: str, token: str) -> bool:
        device = self._speakers.get(device_id)
        if not device:
            return False
        if not device.auth_token_hash:
            return True
        return device.auth_token_hash == _hash_token(token)

    def get_speaker(self, speaker_id: str) -> Optional[SpeakerDevice]:
        return self._speakers.get(speaker_id)

    def record_heartbeat(self, speaker_id: str, status: Optional[str] = "online") -> SpeakerDevice:
        device = self._speakers.get(speaker_id)
        if not device:
            raise KeyError(f"Speaker '{speaker_id}' not found")
        device.last_heartbeat = time.time()
        if status:
            device.status = status

        trace = create_trace_context(device_id=speaker_id)
        try:
            asyncio.get_running_loop().create_task(self.event_bus.publish(
                "fleet.device.heartbeat",
                {"device_id": speaker_id, "status": device.status, "last_seen": device.last_heartbeat},
                trace=trace
            ))
        except RuntimeError:
            pass
        return device

    def sweep_stale_devices(self, timeout_seconds: Optional[float] = None) -> List[str]:
        """Marks devices as OFFLINE if their heartbeat timed out."""
        now = time.time()
        timeout = timeout_seconds if timeout_seconds is not None else self.heartbeat_timeout_seconds
        stale_ids = []
        for speaker_id, device in self._speakers.items():
            if (now - device.last_heartbeat) > timeout:
                if device.status != "offline":
                    device.status = "offline"
                    stale_ids.append(speaker_id)
                    trace = create_trace_context(device_id=speaker_id)
                    try:
                        asyncio.get_running_loop().create_task(self.event_bus.publish(
                            "fleet.device.offline",
                            {"device_id": speaker_id, "last_seen": device.last_heartbeat, "reason": "heartbeat_timeout"},
                            trace=trace
                        ))
                    except RuntimeError:
                        pass
                    logger.warning(f"Device '{speaker_id}' marked OFFLINE due to heartbeat timeout.")
        return stale_ids

    def check_stale_speakers(self) -> List[str]:
        return self.sweep_stale_devices()

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

    def get_active_devices(self) -> List[SpeakerDevice]:
        return self.list_speakers(active_only=True)

    def get_devices_by_room(self, room_id: Optional[str] = None) -> Dict[str, List[SpeakerDevice]]:
        rooms: Dict[str, List[SpeakerDevice]] = {}
        for speaker in self._speakers.values():
            if room_id and speaker.room != room_id.lower().strip():
                continue
            rooms.setdefault(speaker.room, []).append(speaker)
        return rooms

    def get_speakers_by_room(self) -> Dict[str, List[SpeakerDevice]]:
        return self.get_devices_by_room()

    def list_rooms(self) -> List[str]:
        return sorted(list({s.room for s in self._speakers.values()}))

    def handle_command_ack(self, ack_payload: InboundCommandAckPayload):
        """Forward client ACK payload to waiting command future."""
        cmd_id = ack_payload.command_id
        fut = self._pending_command_futures.get(cmd_id)
        if fut and not fut.done():
            fut.set_result(ack_payload)

    async def send_command(
        self,
        device_id: str,
        command_type: str,
        payload: Optional[Dict[str, Any]] = None,
        timeout: float = 5.0
    ) -> CommandResult:
        cmd_id = f"cmd-{uuid.uuid4()}"
        trace = create_trace_context(device_id=device_id)
        start_time = time.time()

        device = self._speakers.get(device_id)
        if not device or device.status == "offline":
            await self.event_bus.publish(
                "fleet.command.failed",
                {"device_id": device_id, "command_id": cmd_id, "reason": "device_offline"},
                trace=trace
            )
            return CommandResult(
                device_id=device_id,
                command_id=cmd_id,
                delivered=False,
                acknowledged=False,
                latency_ms=0.0,
                error="Device is offline or not registered"
            )

        if not self.ws_manager:
            await self.event_bus.publish(
                "fleet.command.failed",
                {"device_id": device_id, "command_id": cmd_id, "reason": "ws_manager_unavailable"},
                trace=trace
            )
            return CommandResult(
                device_id=device_id,
                command_id=cmd_id,
                delivered=False,
                acknowledged=False,
                latency_ms=0.0,
                error="WebSocket manager unavailable"
            )

        session_id = self.ws_manager.device_to_session.get(device_id)
        if not session_id:
            await self.event_bus.publish(
                "fleet.command.failed",
                {"device_id": device_id, "command_id": cmd_id, "reason": "ws_disconnected"},
                trace=trace
            )
            return CommandResult(
                device_id=device_id,
                command_id=cmd_id,
                delivered=False,
                acknowledged=False,
                latency_ms=0.0,
                error="Device not connected via active WebSocket"
            )

        loop = asyncio.get_running_loop()
        fut: asyncio.Future = loop.create_future()
        self._pending_command_futures[cmd_id] = fut

        cmd_payload = OutboundDeviceCommandPayload(
            command_id=cmd_id,
            action=command_type,
            payload=payload or {}
        )

        sent = await self.ws_manager.send_payload(session_id, cmd_payload)
        if not sent:
            self._pending_command_futures.pop(cmd_id, None)
            await self.event_bus.publish(
                "fleet.command.failed",
                {"device_id": device_id, "command_id": cmd_id, "reason": "send_failed"},
                trace=trace
            )
            return CommandResult(
                device_id=device_id,
                command_id=cmd_id,
                delivered=False,
                acknowledged=False,
                latency_ms=0.0,
                error="Failed to send command down WebSocket"
            )

        await self.event_bus.publish(
            "fleet.command.sent",
            {"device_id": device_id, "command_id": cmd_id, "action": command_type},
            trace=trace
        )

        try:
            ack_msg: InboundCommandAckPayload = await asyncio.wait_for(fut, timeout=timeout)
            elapsed_ms = (time.time() - start_time) * 1000.0

            if ack_msg.status == "OK":
                await self.event_bus.publish(
                    "fleet.command.acknowledged",
                    {"device_id": device_id, "command_id": cmd_id, "latency_ms": round(elapsed_ms, 2)},
                    trace=trace
                )
                return CommandResult(
                    device_id=device_id,
                    command_id=cmd_id,
                    delivered=True,
                    acknowledged=True,
                    latency_ms=round(elapsed_ms, 2),
                    output=ack_msg.output
                )
            else:
                await self.event_bus.publish(
                    "fleet.command.failed",
                    {"device_id": device_id, "command_id": cmd_id, "error": ack_msg.error},
                    trace=trace
                )
                return CommandResult(
                    device_id=device_id,
                    command_id=cmd_id,
                    delivered=True,
                    acknowledged=False,
                    latency_ms=round(elapsed_ms, 2),
                    error=ack_msg.error or "Command failed on device"
                )

        except asyncio.TimeoutError:
            elapsed_ms = (time.time() - start_time) * 1000.0
            await self.event_bus.publish(
                "fleet.command.failed",
                {"device_id": device_id, "command_id": cmd_id, "reason": "ack_timeout"},
                trace=trace
            )
            return CommandResult(
                device_id=device_id,
                command_id=cmd_id,
                delivered=True,
                acknowledged=False,
                latency_ms=round(elapsed_ms, 2),
                error="Command acknowledgment timed out"
            )
        finally:
            self._pending_command_futures.pop(cmd_id, None)

    def broadcast(
        self,
        command: str,
        room: Optional[str] = None,
        speaker_ids: Optional[List[str]] = None,
        payload: Optional[Dict[str, Any]] = None
    ) -> FleetBroadcastResult:
        targets: List[SpeakerDevice] = []
        if speaker_ids is not None:
            targets = [self._speakers[sid] for sid in speaker_ids if sid in self._speakers]
        elif room:
            room_normalized = room.lower().strip()
            targets = [s for s in self._speakers.values() if s.room == room_normalized]
        else:
            targets = list(self._speakers.values())

        target_ids = [s.speaker_id for s in targets]
        return FleetBroadcastResult(
            command=command,
            target_count=len(target_ids),
            target_speaker_ids=target_ids,
            sent_count=len(target_ids),
            acknowledged_count=len(target_ids),
            delivered=True,
            details={
                "room": room,
                "payload": payload or {}
            }
        )

    async def broadcast_command(
        self,
        command: str,
        room: Optional[str] = None,
        speaker_ids: Optional[List[str]] = None,
        payload: Optional[Dict[str, Any]] = None,
        timeout: float = 5.0
    ) -> FleetBroadcastResult:
        targets: List[SpeakerDevice] = []
        if speaker_ids is not None:
            targets = [self._speakers[sid] for sid in speaker_ids if sid in self._speakers]
        elif room:
            room_normalized = room.lower().strip()
            targets = [s for s in self._speakers.values() if s.room == room_normalized]
        else:
            targets = list(self._speakers.values())

        target_ids = [s.speaker_id for s in targets]
        if not targets:
            return FleetBroadcastResult(
                command=command,
                target_count=0,
                target_speaker_ids=[],
                sent_count=0,
                acknowledged_count=0,
                delivered=True,
                failed_devices={},
                results=[]
            )

        cmd_tasks = [
            self.send_command(device_id=t.speaker_id, command_type=command, payload=payload, timeout=timeout)
            for t in targets
        ]
        results: List[CommandResult] = await asyncio.gather(*cmd_tasks)

        sent_count = sum(1 for r in results if r.delivered)
        acknowledged_count = sum(1 for r in results if r.acknowledged)
        failed_devices = {r.device_id: (r.error or "Unacknowledged") for r in results if not r.acknowledged}

        return FleetBroadcastResult(
            command=command,
            target_count=len(target_ids),
            target_speaker_ids=target_ids,
            sent_count=sent_count,
            acknowledged_count=acknowledged_count,
            delivered=(acknowledged_count > 0),
            failed_devices=failed_devices,
            results=results,
            details={"room": room, "payload": payload or {}}
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
@router.post("/devices/register", response_model=SpeakerDevice)
async def register_speaker(payload: SpeakerRegisterRequest, request: Request):
    mgr = get_fleet_manager(request)
    device = mgr.register_speaker(
        speaker_id=payload.speaker_id,
        name=payload.name,
        room=payload.room,
        ip_address=payload.ip_address,
        metadata=payload.metadata,
        auth_token=payload.auth_token,
        capabilities=payload.capabilities,
        device_type=payload.device_type
    )
    return device


@router.delete("/speakers/{speaker_id}")
@router.delete("/devices/{speaker_id}")
async def unregister_speaker(speaker_id: str, request: Request):
    mgr = get_fleet_manager(request)
    deleted = mgr.unregister_speaker(speaker_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Speaker not found")
    return {"status": "unregistered", "speaker_id": speaker_id}


@router.get("/speakers", response_model=List[SpeakerDevice])
@router.get("/devices", response_model=List[SpeakerDevice])
async def list_speakers(request: Request, room: Optional[str] = None, active_only: bool = False):
    mgr = get_fleet_manager(request)
    return mgr.list_speakers(room=room, active_only=active_only)


@router.get("/speakers/{speaker_id}", response_model=SpeakerDevice)
@router.get("/devices/{speaker_id}", response_model=SpeakerDevice)
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


@router.post("/broadcast", response_model=FleetBroadcastResult)
@router.post("/commands", response_model=FleetBroadcastResult)
async def broadcast_command(payload: BroadcastRequest, request: Request):
    mgr = get_fleet_manager(request)
    if mgr.ws_manager and mgr.ws_manager.get_active_connection_count() > 0:
        return await mgr.broadcast_command(
            command=payload.command,
            room=payload.room,
            speaker_ids=payload.speaker_ids,
            payload=payload.payload,
            timeout=payload.timeout
        )
    return mgr.broadcast(
        command=payload.command,
        room=payload.room,
        speaker_ids=payload.speaker_ids,
        payload=payload.payload
    )
