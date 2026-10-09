import asyncio
import time
from enum import Enum
from typing import Dict, Any, Callable, Optional
from pydantic import BaseModel, Field

class HealthStatus(str, Enum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    UNHEALTHY = "UNHEALTHY"

class ComponentReport(BaseModel):
    name: str
    status: HealthStatus
    latency_ms: float
    details: Optional[Dict[str, Any]] = None
    error: Optional[str] = None

class SystemHealthReport(BaseModel):
    status: HealthStatus
    timestamp: float = Field(default_factory=time.time)
    components: Dict[str, ComponentReport] = Field(default_factory=dict)

class HealthChecker:
    """
    Proactive health monitor and diagnostic engine for all IRIS subsystems.
    """
    def __init__(self):
        self._probes: Dict[str, Callable[[], Any]] = {}

    def register_probe(self, name: str, probe_fn: Callable[[], Any]):
        self._probes[name] = probe_fn

    async def check_component(self, name: str) -> ComponentReport:
        probe = self._probes.get(name)
        if not probe:
            return ComponentReport(
                name=name,
                status=HealthStatus.UNHEALTHY,
                latency_ms=0.0,
                error="Probe not registered"
            )

        start = time.perf_counter()
        try:
            if asyncio.iscoroutinefunction(probe):
                res = await asyncio.wait_for(probe(), timeout=3.0)
            else:
                res = probe()
            elapsed_ms = (time.perf_counter() - start) * 1000.0

            details = res if isinstance(res, dict) else {"info": str(res)}
            return ComponentReport(
                name=name,
                status=HealthStatus.HEALTHY,
                latency_ms=round(elapsed_ms, 2),
                details=details
            )
        except asyncio.TimeoutError:
            elapsed_ms = (time.perf_counter() - start) * 1000.0
            return ComponentReport(
                name=name,
                status=HealthStatus.DEGRADED,
                latency_ms=round(elapsed_ms, 2),
                error="Health check timed out (>3000ms)"
            )
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - start) * 1000.0
            return ComponentReport(
                name=name,
                status=HealthStatus.UNHEALTHY,
                latency_ms=round(elapsed_ms, 2),
                error=str(exc)
            )

    async def evaluate_system(self) -> SystemHealthReport:
        components: Dict[str, ComponentReport] = {}
        for name in self._probes:
            components[name] = await self.check_component(name)

        # Overall status aggregation
        if any(c.status == HealthStatus.UNHEALTHY for c in components.values()):
            overall = HealthStatus.UNHEALTHY
        elif any(c.status == HealthStatus.DEGRADED for c in components.values()):
            overall = HealthStatus.DEGRADED
        else:
            overall = HealthStatus.HEALTHY

        return SystemHealthReport(status=overall, components=components)


# Singleton and aliases for server integration
health_checker = HealthChecker()
ComponentHealth = ComponentReport
