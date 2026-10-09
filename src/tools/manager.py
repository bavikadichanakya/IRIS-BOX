import asyncio
import logging
import time
from typing import Dict, Any, Optional
from src.tools.capability import Capability, ToolResult, ExecutionStatus, PermissionLevel
from src.tools.permissions import PermissionManager
from src.tools.registry import ToolRegistry
from src.observability.event_bus import EventBus
from src.observability.tracing import TraceContext

logger = logging.getLogger("iris.tools")

class ToolManager:
    """
    Managed boundary between the Orchestrator and concrete tool executors.
    Applies PermissionManager policies, enforces timeouts, publishes telemetry, and guarantees structured ToolResults.
    """

    def __init__(
        self,
        registry: Optional[ToolRegistry] = None,
        permission_manager: Optional[PermissionManager] = None,
        event_bus: Optional[EventBus] = None
    ):
        self.registry = registry or ToolRegistry()
        self.permission_manager = permission_manager or PermissionManager()
        self.event_bus = event_bus or EventBus()
        self._capabilities: Dict[str, Capability] = {}
        self._initialize_capabilities()

    def _initialize_capabilities(self):
        """Map registered tool schemas into rich Capabilities with default safety tiers."""
        schemas = self.registry.get_schemas()
        for s in schemas:
            name = s["name"]
            if "System" in name or "Terminal" in name or "Shell" in name:
                perm = PermissionLevel.SENSITIVE
                requires_conf = True
            elif "Home" in name or "Assistant" in name or "Device" in name:
                perm = PermissionLevel.PROTECTED
                requires_conf = False
            else:
                perm = PermissionLevel.PUBLIC
                requires_conf = False

            self._capabilities[name] = Capability(
                name=name,
                description=s["description"],
                schema=s["parameters"],
                permission_level=perm,
                category=s.get("category", "general"),
                requires_confirmation=requires_conf,
                execution_timeout_sec=10.0
            )

    def register_capability(self, capability: Capability):
        self._capabilities[capability.name] = capability

    def get_capability(self, name: str) -> Optional[Capability]:
        return self._capabilities.get(name)

    def get_schemas(self):
        return self.registry.get_schemas()

    async def execute_tool(
        self,
        name: str,
        arguments: Dict[str, Any],
        request_id: str = "",
        trace_id: str = "",
        context: Optional[Dict[str, Any]] = None
    ) -> ToolResult:
        start_time = time.perf_counter()
        capability = self._capabilities.get(name)
        trace_ctx = TraceContext(request_id=request_id or "", trace_id=trace_id or "")
        await self.event_bus.publish("tool.execution.started", {"tool": name, "args": arguments}, trace=trace_ctx)

        if not capability:
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            return ToolResult(
                status=ExecutionStatus.UNAVAILABLE,
                tool_name=name,
                request_id=request_id,
                trace_id=trace_id,
                error=f"Capability '{name}' is not registered or unavailable.",
                duration_ms=duration_ms
            )

        # 1. Policy Evaluation
        allowed, reason = await self.permission_manager.evaluate(capability, context)
        if not allowed:
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            await self.event_bus.publish("tool.execution.denied", {"tool": name, "reason": reason}, trace=trace_ctx)
            return ToolResult(
                status=ExecutionStatus.DENIED,
                tool_name=name,
                request_id=request_id,
                trace_id=trace_id,
                error=reason or "Action denied by permission policy.",
                duration_ms=duration_ms
            )

        # 2. Execution with Timeout Boundary
        try:
            output = await asyncio.wait_for(
                self.registry.execute(name, arguments),
                timeout=capability.execution_timeout_sec
            )
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            await self.event_bus.publish("tool.execution.succeeded", {"tool": name, "duration_ms": duration_ms}, trace=trace_ctx)
            return ToolResult(
                status=ExecutionStatus.SUCCEEDED,
                tool_name=name,
                request_id=request_id,
                trace_id=trace_id,
                output=output,
                duration_ms=duration_ms
            )
        except asyncio.TimeoutError:
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            logger.error(f"Tool execution timed out: {name} ({capability.execution_timeout_sec}s)")
            await self.event_bus.publish("tool.execution.timeout", {"tool": name, "duration_ms": duration_ms}, trace=trace_ctx)
            return ToolResult(
                status=ExecutionStatus.TIMEOUT,
                tool_name=name,
                request_id=request_id,
                trace_id=trace_id,
                error=f"Execution timed out after {capability.execution_timeout_sec}s",
                duration_ms=duration_ms
            )
        except Exception as exc:
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            logger.error(f"Tool execution failed: {name} -> {exc}", exc_info=True)
            await self.event_bus.publish("tool.execution.failed", {"tool": name, "error": str(exc)}, trace=trace_ctx)
            return ToolResult(
                status=ExecutionStatus.FAILED,
                tool_name=name,
                request_id=request_id,
                trace_id=trace_id,
                error=str(exc),
                duration_ms=duration_ms
            )
