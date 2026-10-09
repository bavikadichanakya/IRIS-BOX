import asyncio
import time
from typing import Dict, List, Callable, Any, Optional
from pydantic import BaseModel, Field
from src.observability.tracing import TraceContext

class Event(BaseModel):
    topic: str
    payload: Dict[str, Any]
    trace: TraceContext
    timestamp: float = Field(default_factory=time.time)

class EventLedger:
    """Sequential append-only audit ledger for system events."""
    def __init__(self, max_history: int = 1000):
        self.max_history = max_history
        self._records: List[Event] = []

    def record(self, event: Event):
        self._records.append(event)
        if len(self._records) > self.max_history:
            self._records.pop(0)

    def get_events(self, topic_prefix: Optional[str] = None) -> List[Event]:
        if not topic_prefix:
            return list(self._records)
        return [e for e in self._records if e.topic.startswith(topic_prefix)]

class EventBus:
    """Asynchronous publish-subscribe event bus with ledger audit."""
    def __init__(self, ledger: Optional[EventLedger] = None):
        self._subscribers: Dict[str, List[Callable[[Event], Any]]] = {}
        self.ledger = ledger or EventLedger()

    def subscribe(self, topic: str, handler: Callable[[Event], Any]):
        if topic not in self._subscribers:
            self._subscribers[topic] = []
        self._subscribers[topic].append(handler)

    async def publish(self, topic: str, payload: Dict[str, Any], trace: Optional[TraceContext] = None):
        trace_ctx = trace or TraceContext()
        event = Event(topic=topic, payload=payload, trace=trace_ctx)
        self.ledger.record(event)

        handlers = list(self._subscribers.get(topic, []))
        if "*" in self._subscribers:
            handlers.extend(self._subscribers["*"])

        for handler in handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(event)
                else:
                    handler(event)
            except Exception:
                pass
