import pytest
import asyncio
from unittest.mock import patch, AsyncMock

from pydantic import BaseModel

from src.agent.orchestrator import IRISOrchestrator
from src.models.schemas import StreamChunkPayload, AgentExecutionResult
from src.tools.registry import ToolRegistry, BaseTool


def test_stream_chunk_payload():
    payload = StreamChunkPayload(
        chunk_type="text_delta",
        delta_text="hello",
        session_id="123"
    )
    assert payload.chunk_type == "text_delta"
    assert payload.delta_text == "hello"
    assert payload.session_id == "123"


def test_stream_chunk_payload_invalid_type():
    with pytest.raises(Exception):
        StreamChunkPayload(
            chunk_type="invalid",
            delta_text="hello",
            session_id="123"
        )


def test_stream_request_text_only():
    async def run_test():
        # Mock AsyncOpenAI
        with patch('openai.AsyncOpenAI') as mock_async:
            mock_instance = mock_async.return_value
            mock_create = AsyncMock()

            class FakeDelta:
                def __init__(self, content=None, tool_calls=None):
                    self.content = content
                    self.tool_calls = tool_calls

            class FakeChoice:
                def __init__(self, delta):
                    self.delta = delta

            class FakeChunk:
                def __init__(self, delta):
                    self.choices = [FakeChoice(delta)]

            async def fake_stream():
                yield FakeChunk(FakeDelta(content="Hello"))
                yield FakeChunk(FakeDelta(content=" world"))

            mock_create.return_value = fake_stream()
            mock_instance.chat.completions.create = mock_create

            orchestrator = IRISOrchestrator(
                api_base="http://test",
                api_key="test",
                model="test"
            )
            chunks = []
            async for chunk in orchestrator.stream_request("hi"):
                chunks.append(chunk)
            return chunks

    chunks = asyncio.run(run_test())

    assert len(chunks) == 3
    assert chunks[0].chunk_type == "text_delta"
    assert chunks[0].delta_text == "Hello"
    assert chunks[1].chunk_type == "text_delta"
    assert chunks[1].delta_text == " world"
    assert chunks[2].chunk_type == "complete"
    assert chunks[2].delta_text == "Hello world"


def test_stream_request_tool_call():
    # Register a dummy tool
    class DummyPayload(BaseModel):
        pass

    class DummyTool(BaseTool):
        def execute(self, payload):
            return AgentExecutionResult(
                success=True,
                tool_name="DummyTool",
                output_payload={"result": "ok"}
            )

    ToolRegistry._tool_classes.clear()
    ToolRegistry.register_tool("DummyTool")(DummyTool)

    async def run_test():
        with patch('openai.AsyncOpenAI') as mock_async:
            mock_instance = mock_async.return_value
            mock_create = AsyncMock()

            class FakeDelta:
                def __init__(self, content=None, tool_calls=None):
                    self.content = content
                    self.tool_calls = tool_calls

            class FakeFunction:
                def __init__(self, name=None, arguments=None):
                    self.name = name
                    self.arguments = arguments

            class FakeToolCall:
                def __init__(self, function):
                    self.function = function

            class FakeChoice:
                def __init__(self, delta):
                    self.delta = delta

            class FakeChunk:
                def __init__(self, delta):
                    self.choices = [FakeChoice(delta)]

            async def fake_stream():
                # First chunk with tool call name
                yield FakeChunk(FakeDelta(tool_calls=[
                    FakeToolCall(FakeFunction(name="DummyTool", arguments="{}"))
                ]))

            mock_create.return_value = fake_stream()
            mock_instance.chat.completions.create = mock_create

            orchestrator = IRISOrchestrator(
                api_base="http://test",
                api_key="test",
                model="test"
            )
            chunks = []
            async for chunk in orchestrator.stream_request("call tool"):
                chunks.append(chunk)
            return chunks

    chunks = asyncio.run(run_test())

    # Expect at least a tool_call chunk
    assert any(c.chunk_type == "tool_call" for c in chunks)
    tool_call_chunk = next(c for c in chunks if c.chunk_type == "tool_call")
    assert "DummyTool" in tool_call_chunk.delta_text
