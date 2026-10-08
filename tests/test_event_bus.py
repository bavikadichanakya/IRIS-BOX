from src.observability.event_bus import EventBus
from src.observability.tracing import create_trace_context
from typing import Callable
import asyncio

class TestEventBus:
    def test_subscribe_and_publish(self):
        event_bus = EventBus()
        callback = lambda event: print(f"Received event: {event}")
        event_bus.subscribe("test_topic", callback)
        event = Event(topic="test_topic", payload={"key": "value"})
        asyncio.run(event_bus.publish(event))
        assert len(event_bus.event_ledger.events) == 1
        assert event_bus.event_ledger.events[0].topic == "test_topic"
        assert event_bus.event_ledger.events[0].payload == {"key": "value"}

    def test_multiple_subscribers(self):
        event_bus = EventBus()
        callback1 = lambda event: print(f"Received event: {event}")
        callback2 = lambda event: print(f"Received event: {event}")
        event_bus.subscribe("test_topic", callback1)
        event_bus.subscribe("test_topic", callback2)
        event = Event(topic="test_topic", payload={"key": "value"})
        asyncio.run(event_bus.publish(event))
        assert len(event_bus.event_ledger.events) == 1
        assert event_bus.event_ledger.events[0].topic == "test_topic"
        assert event_bus.event_ledger.events[0].payload == {"key": "value"}

    def test_trace_context_propagation(self):
        event_bus = EventBus()
        callback = lambda event: print(f"Received event: {event}")
        event_bus.subscribe("test_topic", callback)
        trace_context = create_trace_context("device-123", session_id="session-456")
        event = Event(topic="test_topic", payload={"trace_context": trace_context.dict()})
        asyncio.run(event_bus.publish(event))
        assert len(event_bus.event_ledger.events) == 1
        assert event_bus.event_ledger.events[0].topic == "test_topic"
        assert event_bus.event_ledger.events[0].payload == {"trace_context": trace_context.dict()}
