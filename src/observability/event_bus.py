from typing import Dict, List, Optional
from pydantic import BaseModel
import asyncio

class Event(BaseModel):
    topic: str
    payload: dict

class EventLedger:
    def __init__(self):
        self.events: List[Event] = []

    def record_event(self, event: Event):
        self.events.append(event)

    def get_events(self) -> List[Event]:
        return self.events

class EventBus:
    def __init__(self):
        self.subscribers: Dict[str, List[Callable[[Event], None]]] = {}

    async def subscribe(self, topic: str, callback: Callable[[Event], None]):
        if topic not in self.subscribers:
            self.subscribers[topic] = []
        self.subscribers[topic].append(callback)

    async def publish(self, event: Event):
        if event.topic in self.subscribers:
            for callback in self.subscribers[event.topic]:
                await callback(event)
        self.event_ledger.record_event(event)

    @property
    def event_ledger(self) -> EventLedger:
        return EventLedger()
