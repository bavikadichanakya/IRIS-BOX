import pytest
from unittest.mock import AsyncMock
from src.agent.react_loop import ReActLoop
from src.tools.manager import ToolManager
from src.observability.tracing import create_trace_context

@pytest.mark.asyncio
async def test_react_loop_step_execution():
    class MockReg:
        def __init__(self):
            self.execute = AsyncMock(return_value={"temperature": 22})
        def get_schemas(self):
            return [{"name": "WeatherTool", "description": "Get weather", "parameters": {}}]

    tm = ToolManager(registry=MockReg())
    loop = ReActLoop(tool_manager=tm, max_iterations=3)

    trace = create_trace_context("device-01")
    result = await loop.execute_step("WeatherTool", {"location": "Living Room"}, trace_context=trace)

    assert result.status.value == "SUCCEEDED"
    assert result.output == {"temperature": 22}

    feedback = loop.format_tool_feedback("WeatherTool", result)
    assert feedback["tool"] == "WeatherTool"
    assert feedback["status"] == "SUCCEEDED"
    assert feedback["output"] == {"temperature": 22}
