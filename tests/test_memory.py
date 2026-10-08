import json
from unittest.mock import patch, MagicMock, AsyncMock

import pytest
from pydantic import BaseModel

from src.agent.orchestrator import IRISOrchestrator, SessionMemory
from src.models.schemas import AgentExecutionResult
from src.tools.registry import BaseTool, ToolRegistry


class FakeMessage:
    def __init__(self, content=None, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls


class FakeChoice:
    def __init__(self, message):
        self.message = message


class FakeResponse:
    def __init__(self, message):
        self.choices = [FakeChoice(message)]


class FakeFunction:
    def __init__(self, name=None, arguments=None):
        self.name = name
        self.arguments = arguments


class FakeToolCall:
    def __init__(self, function):
        self.function = function


@pytest.fixture
def orchestrator():
    with patch('openai.OpenAI') as mock_openai:
        mock_client = mock_openai.return_value
        mock_client.base_url = "http://fake"
        mock_client.api_key = "fake"
        orch = IRISOrchestrator(api_base="http://fake", api_key="fake")
        return orch


def test_session_memory_sliding_window():
    mem = SessionMemory(max_messages=3)
    sid = "s1"
    for i in range(5):
        mem.add_message(sid, "user", f"msg{i}")
    history = mem.get_history(sid)
    assert len(history) == 3
    assert history[0]["content"] == "msg2"
    assert history[-1]["content"] == "msg4"


def test_process_request_retains_context(orchestrator):
    # Register a dummy tool with annotated payload
    class DummyPayload(BaseModel):
        pass

    class DummyTool(BaseTool):
        def execute(self, payload: DummyPayload):
            return AgentExecutionResult(
                success=True,
                tool_name="DummyTool",
                output_payload={"result": "ok"}
            )

    ToolRegistry._tool_classes.clear()
    ToolRegistry.register_tool("DummyTool")(DummyTool)

    with patch.object(orchestrator.client.chat.completions, 'create') as mock_create:
        # First call returns a tool call for DummyTool
        first_message = FakeMessage(
            content="",
            tool_calls=[
                FakeToolCall(FakeFunction(name="DummyTool", arguments="{}"))
            ]
        )
        first_response = FakeResponse(first_message)
        mock_create.return_value = first_response

        result1 = orchestrator.process_request("Hi", session_id="test_session")
        assert result1.success

        # Second call – we expect the messages to include the previous user and assistant turns
        second_message = FakeMessage(
            content="",
            tool_calls=[
                FakeToolCall(FakeFunction(name="DummyTool", arguments="{}"))
            ]
        )
        second_response = FakeResponse(second_message)
        mock_create.return_value = second_response

        result2 = orchestrator.process_request("What did I just say?", session_id="test_session")
        assert result2.success

        # Inspect the messages passed to the second call
        args, kwargs = mock_create.call_args
        messages = kwargs.get("messages", [])
        # The system prompt is first, then history, then new user message
        assert any(m["role"] == "user" and m["content"] == "Hi" for m in messages)
        assert any(m["role"] == "assistant" and m["content"] == "" for m in messages)
        # The assistant message should have tool_calls
        assistant_msgs = [m for m in messages if m["role"] == "assistant"]
        assert len(assistant_msgs) > 0
        assert "tool_calls" in assistant_msgs[0]
        assert messages[-1]["role"] == "user" and messages[-1]["content"] == "What did I just say?"


def test_stream_request_retains_context(orchestrator):
    import asyncio

    async def fake_stream():
        # Yield a couple of text deltas
        chunk1 = MagicMock()
        chunk1.choices = [MagicMock()]
        chunk1.choices[0].delta.content = "Hello"
        chunk1.choices[0].delta.tool_calls = None
        yield chunk1
        chunk2 = MagicMock()
        chunk2.choices = [MagicMock()]
        chunk2.choices[0].delta.content = " world"
        chunk2.choices[0].delta.tool_calls = None
        yield chunk2

    async def run_test():
        with patch('openai.AsyncOpenAI') as mock_async:
            mock_instance = mock_async.return_value
            mock_create = AsyncMock()
            mock_create.return_value = fake_stream()
            mock_instance.chat.completions.create = mock_create

            # First streaming call
            chunks1 = []
            async for chunk in orchestrator.stream_request("Hello", session_id="stream_session"):
                chunks1.append(chunk)
            # Second streaming call – should include history
            mock_create.return_value = fake_stream()
            chunks2 = []
            async for chunk in orchestrator.stream_request("Repeat that", session_id="stream_session"):
                chunks2.append(chunk)

            # Verify that the second call's messages include previous user and assistant content
            args, kwargs = mock_create.call_args
            messages = kwargs.get("messages", [])
            assert any(m["role"] == "user" and m["content"] == "Hello" for m in messages)
            assert any(m["role"] == "assistant" and m["content"] == "Hello world" for m in messages)
            assert messages[-1]["role"] == "user" and messages[-1]["content"] == "Repeat that"

    asyncio.run(run_test())
