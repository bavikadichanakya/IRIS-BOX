import pytest
import asyncio
from src.storage.db import Database


@pytest.fixture
async def db():
    """Create an in-memory database for testing."""
    db = Database(":memory:")
    await db.connect()
    yield db
    await db.close()


@pytest.mark.asyncio
async def test_add_and_get_conversation(db):
    """Test adding and retrieving a conversation message."""
    conv_id = await db.add_conversation("session1", "user", "hello")
    assert conv_id > 0

    convs = await db.get_conversations("session1")
    assert len(convs) == 1
    assert convs[0]["role"] == "user"
    assert convs[0]["content"] == "hello"
    assert convs[0]["session_id"] == "session1"


@pytest.mark.asyncio
async def test_add_and_get_latency_metric(db):
    """Test adding and retrieving a latency metric."""
    metric_id = await db.add_latency_metric("session1", 100.0, 50.0, 200.0, 350.0)
    assert metric_id > 0

    metrics = await db.get_latency_metrics("session1")
    assert len(metrics) == 1
    assert metrics[0]["llm_time_ms"] == 100.0
    assert metrics[0]["tool_time_ms"] == 50.0
    assert metrics[0]["audio_latency_ms"] == 200.0
    assert metrics[0]["total_time_ms"] == 350.0


@pytest.mark.asyncio
async def test_add_and_get_error(db):
    """Test adding and retrieving an error record."""
    err_id = await db.add_error("session1", "ValueError", "test error", "traceback")
    assert err_id > 0

    errors = await db.get_errors("session1")
    assert len(errors) == 1
    assert errors[0]["error_type"] == "ValueError"
    assert errors[0]["error_message"] == "test error"
    assert errors[0]["stack_trace"] == "traceback"


@pytest.mark.asyncio
async def test_get_all_errors(db):
    """Test retrieving all errors across sessions."""
    await db.add_error("session1", "ValueError", "error1")
    await db.add_error("session2", "KeyError", "error2")

    errors = await db.get_errors()
    assert len(errors) == 2
    assert errors[0]["error_type"] in ("ValueError", "KeyError")
    assert errors[1]["error_type"] in ("ValueError", "KeyError")


@pytest.mark.asyncio
async def test_get_all_latency_metrics(db):
    """Test retrieving all latency metrics across sessions."""
    await db.add_latency_metric("session1", 100.0, 50.0, 200.0, 350.0)
    await db.add_latency_metric("session2", 150.0, 75.0, 250.0, 475.0)

    metrics = await db.get_latency_metrics()
    assert len(metrics) == 2


@pytest.mark.asyncio
async def test_conversation_with_tool_calls(db):
    """Test storing conversation with tool calls."""
    tool_calls = [{"name": "test_tool", "arguments": {"key": "value"}}]
    await db.add_conversation("session1", "assistant", "using tool", tool_calls)

    convs = await db.get_conversations("session1")
    assert len(convs) == 1
    assert convs[0]["tool_calls"] is not None
    # Verify JSON serialization worked
    import json
    parsed = json.loads(convs[0]["tool_calls"])
    assert parsed == tool_calls


@pytest.mark.asyncio
async def test_empty_session_conversations(db):
    """Test getting conversations for a non-existent session."""
    convs = await db.get_conversations("nonexistent")
    assert len(convs) == 0


@pytest.mark.asyncio
async def test_multiple_conversations_ordering(db):
    """Test that conversations are returned in timestamp order."""
    await db.add_conversation("session1", "user", "first")
    await db.add_conversation("session1", "assistant", "second")
    await db.add_conversation("session1", "user", "third")

    convs = await db.get_conversations("session1")
    assert len(convs) == 3
    assert convs[0]["content"] == "first"
    assert convs[1]["content"] == "second"
    assert convs[2]["content"] == "third"
