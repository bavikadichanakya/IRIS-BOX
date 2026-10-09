import logging
from typing import List, Dict, Any, Optional
from src.tools.manager import ToolManager
from src.tools.capability import ToolResult, ExecutionStatus
from src.observability.tracing import TraceContext

logger = logging.getLogger("iris.react")

class ReActLoop:
    """
    Multi-step ReAct (Reason + Act) loop engine.
    Bounded by max_iterations to prevent runaway recursion.
    """
    def __init__(self, tool_manager: ToolManager, max_iterations: int = 5):
        self.tool_manager = tool_manager
        self.max_iterations = max_iterations

    async def execute_step(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        trace_context: Optional[TraceContext] = None,
        context: Optional[Dict[str, Any]] = None
    ) -> ToolResult:
        trace = trace_context or TraceContext()
        ctx = dict(context or {})
        if "device_id" not in ctx and trace.device_id:
            ctx["device_id"] = trace.device_id
        return await self.tool_manager.execute_tool(
            name=tool_name,
            arguments=arguments,
            request_id=trace.request_id,
            trace_id=trace.trace_id,
            context=ctx
        )

    def format_tool_feedback(self, tool_name: str, result: ToolResult) -> Dict[str, Any]:
        return {
            "tool": tool_name,
            "status": result.status.value,
            "output": result.output,
            "error": result.error,
            "duration_ms": result.duration_ms
        }
