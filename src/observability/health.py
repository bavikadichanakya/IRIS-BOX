import time
import asyncio
import logging
from enum import Enum
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field

logger = logging.getLogger("iris.observability.health")


class HealthState(str, Enum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    UNHEALTHY = "UNHEALTHY"
    INITIALIZING = "INITIALIZING"


class SubsystemHealth(BaseModel):
    name: str
    status: HealthState
    latency_ms: float = 0.0
    details: Dict[str, Any] = Field(default_factory=dict)
    message: Optional[str] = None


class HealthReport(BaseModel):
    status: HealthState
    timestamp: float = Field(default_factory=time.time)
    uptime_seconds: float = 0.0
    subsystems: Dict[str, SubsystemHealth] = Field(default_factory=dict)
    diagnostics: Optional[str] = None


class HealthSupervisor:
    """
    Centralized Health Supervisor for IRIS-BOX architecture.
    Provides truthful liveness vs. readiness evaluation across API, LLM provider, tools, voice, storage, and fleet subsystems.
    """

    def __init__(
        self,
        orchestrator: Optional[Any] = None,
        tool_manager: Optional[Any] = None,
        fleet_manager: Optional[Any] = None,
        db_connection: Optional[Any] = None,
        ws_manager: Optional[Any] = None,
    ):
        self.start_time = time.time()
        self.orchestrator = orchestrator
        self.tool_manager = tool_manager
        self.fleet_manager = fleet_manager
        self.db_connection = db_connection
        self.ws_manager = ws_manager
        self.subsystems: Dict[str, SubsystemHealth] = {
            "api": SubsystemHealth(name="api", status=HealthState.HEALTHY, message="API service alive"),
            "llm_provider": SubsystemHealth(name="llm_provider", status=HealthState.INITIALIZING),
            "tools": SubsystemHealth(name="tools", status=HealthState.INITIALIZING),
            "voice": SubsystemHealth(name="voice", status=HealthState.INITIALIZING),
            "storage": SubsystemHealth(name="storage", status=HealthState.INITIALIZING),
            "fleet": SubsystemHealth(name="fleet", status=HealthState.INITIALIZING),
        }

    def set_subsystem_status(
        self,
        name: str,
        status: HealthState,
        latency_ms: float = 0.0,
        details: Optional[Dict[str, Any]] = None,
        message: Optional[str] = None,
    ):
        self.subsystems[name] = SubsystemHealth(
            name=name,
            status=status,
            latency_ms=round(latency_ms, 2),
            details=details or {},
            message=message,
        )

    async def check_api(self) -> SubsystemHealth:
        return SubsystemHealth(name="api", status=HealthState.HEALTHY, message="HTTP server running")

    async def check_llm_provider(self) -> SubsystemHealth:
        start = time.perf_counter()
        if not self.orchestrator:
            try:
                import os
                from src.agent.orchestrator import IRISOrchestrator
                api_base = os.getenv("OPENAI_API_BASE", "http://localhost:11434/v1")
                api_key = os.getenv("OPENROUTER_API_KEY") or os.getenv("OPENAI_API_KEY") or os.getenv("IRIS_API_KEY", "ollama")
                model = os.getenv("OPENAI_MODEL", "llama3.2")
                self.orchestrator = IRISOrchestrator(api_base=api_base, api_key=api_key, model=model)
            except Exception:
                pass

        if not self.orchestrator:
            return SubsystemHealth(
                name="llm_provider",
                status=HealthState.DEGRADED,
                message="Orchestrator instance not bound"
            )
        try:
            if hasattr(self.orchestrator, "client") and self.orchestrator.client:
                elapsed = (time.perf_counter() - start) * 1000.0
                return SubsystemHealth(
                    name="llm_provider",
                    status=HealthState.HEALTHY,
                    latency_ms=elapsed,
                    details={
                        "model": getattr(self.orchestrator, "model", "unknown"),
                        "base_url": str(getattr(self.orchestrator.client, "base_url", ""))
                    },
                    message="LLM provider client configured"
                )
            return SubsystemHealth(name="llm_provider", status=HealthState.DEGRADED, message="LLM client unconfigured")
        except Exception as e:
            elapsed = (time.perf_counter() - start) * 1000.0
            return SubsystemHealth(name="llm_provider", status=HealthState.DEGRADED, latency_ms=elapsed, message=str(e))


    async def check_tools(self) -> SubsystemHealth:
        start = time.perf_counter()
        if not self.tool_manager:
            try:
                from src.tools.manager import ToolManager
                self.tool_manager = ToolManager()
            except Exception as exc:
                elapsed = (time.perf_counter() - start) * 1000.0
                return SubsystemHealth(
                    name="tools",
                    status=HealthState.UNHEALTHY,
                    latency_ms=elapsed,
                    message=f"Failed to instantiate ToolManager: {exc}"
                )

        try:
            schemas = self.tool_manager.get_schemas()
            elapsed = (time.perf_counter() - start) * 1000.0
            count = len(schemas)
            status = HealthState.HEALTHY if count > 0 else HealthState.DEGRADED
            msg = f"{count} registered tool capabilities available" if count > 0 else "No tool capabilities registered"
            return SubsystemHealth(
                name="tools",
                status=status,
                latency_ms=elapsed,
                details={"registered_tools_count": count},
                message=msg
            )
        except Exception as exc:
            elapsed = (time.perf_counter() - start) * 1000.0
            return SubsystemHealth(
                name="tools",
                status=HealthState.UNHEALTHY,
                latency_ms=elapsed,
                message=f"Tools check failed: {exc}"
            )

    async def check_voice(self) -> SubsystemHealth:
        start = time.perf_counter()
        details = {}
        try:
            from src.audio.vad import VoiceActivityDetector
            from src.audio.wakeword import WakeWordDetector
            from src.audio.stt import Transcriber
            from src.audio.tts import TTSEngine

            vad = VoiceActivityDetector()
            ww = WakeWordDetector()
            stt = Transcriber()
            tts = TTSEngine()

            details["vad"] = "ready"
            details["wakeword"] = "ready"
            details["stt"] = "mock_mode" if getattr(stt, "mock_mode", False) else "ready"
            details["tts"] = "ready"

            elapsed = (time.perf_counter() - start) * 1000.0
            return SubsystemHealth(
                name="voice",
                status=HealthState.HEALTHY,
                latency_ms=elapsed,
                details=details,
                message="Voice subsystem ready (VAD, Wakeword, STT, TTS)"
            )
        except Exception as e:
            elapsed = (time.perf_counter() - start) * 1000.0
            return SubsystemHealth(
                name="voice",
                status=HealthState.DEGRADED,
                latency_ms=elapsed,
                message=f"Voice subsystem component issue: {e}"
            )

    async def check_storage(self) -> SubsystemHealth:
        start = time.perf_counter()
        try:
            if self.db_connection and getattr(self.db_connection, "_conn", None) is not None:
                if hasattr(self.db_connection, "get_recent_turns"):
                    await self.db_connection.get_recent_turns("health_check_session", limit=1)
                else:
                    await self.db_connection.get_conversations("health_check_session")
                elapsed = (time.perf_counter() - start) * 1000.0
                return SubsystemHealth(
                    name="storage",
                    status=HealthState.HEALTHY,
                    latency_ms=elapsed,
                    details={"database": "SQLite", "connected": True},
                    message="Database query successful"
                )
            else:
                from src.storage.db import Database
                db = Database()
                await db.connect()
                try:
                    await db.get_recent_turns("health_check_session", limit=1)
                    elapsed = (time.perf_counter() - start) * 1000.0
                    return SubsystemHealth(
                        name="storage",
                        status=HealthState.HEALTHY,
                        latency_ms=elapsed,
                        details={"database": "SQLite", "connected": True},
                        message="Database query successful"
                    )
                finally:
                    await db.close()
        except Exception as e:
            elapsed = (time.perf_counter() - start) * 1000.0
            return SubsystemHealth(
                name="storage",
                status=HealthState.UNHEALTHY,
                latency_ms=elapsed,
                message=f"Database connectivity failed: {e}"
            )



    async def check_fleet(self) -> SubsystemHealth:
        start = time.perf_counter()
        if not self.fleet_manager:
            try:
                from src.server.fleet import fleet_manager
                self.fleet_manager = fleet_manager
            except Exception:
                pass

        try:
            connected = 0
            if self.fleet_manager and hasattr(self.fleet_manager, "list_devices"):
                connected = len(self.fleet_manager.list_devices())
            ws_connected = 0
            if self.ws_manager and hasattr(self.ws_manager, "get_active_connection_count"):
                ws_connected = self.ws_manager.get_active_connection_count()
            elapsed = (time.perf_counter() - start) * 1000.0
            return SubsystemHealth(
                name="fleet",
                status=HealthState.HEALTHY,
                latency_ms=elapsed,
                details={"connected_devices": connected, "active_websocket_connections": ws_connected},
                message=f"Fleet manager operational ({connected} devices, {ws_connected} active WS connections)"
            )
        except Exception as e:
            elapsed = (time.perf_counter() - start) * 1000.0
            return SubsystemHealth(
                name="fleet",
                status=HealthState.DEGRADED,
                latency_ms=elapsed,
                message=f"Fleet manager check failed: {e}"
            )

    async def get_health_status(self, check_readiness: bool = True) -> HealthReport:
        uptime = time.time() - self.start_time
        if not check_readiness:
            # Lightweight liveness check
            return HealthReport(
                status=HealthState.HEALTHY,
                uptime_seconds=round(uptime, 2),
                subsystems={"api": SubsystemHealth(name="api", status=HealthState.HEALTHY, message="Alive")}
            )

        # Full readiness evaluation across all subsystems
        results = await asyncio.gather(
            self.check_api(),
            self.check_llm_provider(),
            self.check_tools(),
            self.check_voice(),
            self.check_storage(),
            self.check_fleet(),
            return_exceptions=True
        )

        checks = ["api", "llm_provider", "tools", "voice", "storage", "fleet"]
        subsystems: Dict[str, SubsystemHealth] = {}

        for idx, name in enumerate(checks):
            res = results[idx]
            if isinstance(res, SubsystemHealth):
                subsystems[name] = res
            else:
                subsystems[name] = SubsystemHealth(
                    name=name,
                    status=HealthState.UNHEALTHY,
                    message=f"Check failed with exception: {res}"
                )

        # Allow explicit subsystem status overrides registered on self.subsystems if set manually
        for k, v in self.subsystems.items():
            if k in subsystems and v.status not in (HealthState.INITIALIZING,):
                subsystems[k] = v

        # Aggregate overall status
        if any(s.status == HealthState.UNHEALTHY for s in subsystems.values()):
            overall = HealthState.UNHEALTHY
        elif any(s.status == HealthState.DEGRADED for s in subsystems.values()):
            overall = HealthState.DEGRADED
        else:
            overall = HealthState.HEALTHY

        degraded = [f"{s.name}: {s.message}" for s in subsystems.values() if s.status != HealthState.HEALTHY]
        diag = f"Subsystems requiring attention: {'; '.join(degraded)}" if degraded else "All subsystems operational"

        return HealthReport(
            status=overall,
            uptime_seconds=round(uptime, 2),
            subsystems=subsystems,
            diagnostics=diag
        )


health_supervisor = HealthSupervisor()
