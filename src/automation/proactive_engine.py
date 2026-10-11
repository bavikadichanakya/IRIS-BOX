import asyncio
from datetime import datetime, time as dtime, timezone
import logging
import re
import time
import uuid
from typing import Dict, List, Optional, Any, Union
from pydantic import BaseModel, Field

from src.config.settings import settings
from src.observability.event_bus import EventBus, Event
from src.automation.dispatcher import ProactiveSpeechDispatcher

logger = logging.getLogger("iris.automation.proactive_engine")


class ProactiveRule(BaseModel):
    """
    Specification for matching smart home state changes and generating ambient voice alerts.
    """
    rule_id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str = Field(default="Custom Rule", description="Human-readable rule name")
    entity_id_pattern: str = Field(..., description="Regex or exact entity_id pattern")
    from_state: Optional[str] = Field(default=None, description="Optional previous state to match")
    to_state: Optional[str] = Field(default="on", description="Target new state to match")
    template: str = Field(..., description="Speech template, e.g. 'The {friendly_name} was opened.'")
    cooldown_seconds: float = Field(default=60.0, description="Minimum interval between alerts for this rule")
    severity: str = Field(default="INFO", description="'INFO' | 'WARNING' | 'CRITICAL'")
    enabled: bool = Field(default=True, description="Whether this rule is active")


class ProactiveAnnouncement(BaseModel):
    """
    Generated proactive speech announcement ready for audio synthesis and dispatch.
    """
    announcement_id: str = Field(default_factory=lambda: f"ann_{uuid.uuid4().hex[:8]}")
    rule_id: str
    entity_id: str
    text: str
    severity: str
    timestamp: float = Field(default_factory=time.time)


def get_default_proactive_rules() -> List[ProactiveRule]:
    """Default smart home proactive announcement rules for IRIS-BOX."""
    return [
        ProactiveRule(
            rule_id="rule_door_open",
            name="Exterior Door Opened",
            entity_id_pattern=r"binary_sensor\..*(?:door|entry|garage).*",
            from_state="off",
            to_state="on",
            template="The {friendly_name} was opened.",
            cooldown_seconds=60.0,
            severity="WARNING",
        ),
        ProactiveRule(
            rule_id="rule_water_leak",
            name="Water Leak Detected",
            entity_id_pattern=r"binary_sensor\..*(?:leak|water|moisture).*",
            from_state=None,
            to_state="on",
            template="Critical alert: {friendly_name} detected water moisture!",
            cooldown_seconds=30.0,
            severity="CRITICAL",
        ),
        ProactiveRule(
            rule_id="rule_smoke_co",
            name="Smoke or CO Detected",
            entity_id_pattern=r"binary_sensor\..*(?:smoke|carbon_monoxide|fire).*",
            from_state=None,
            to_state="on",
            template="Emergency alert: {friendly_name} detected smoke or fire danger!",
            cooldown_seconds=30.0,
            severity="CRITICAL",
        ),
        ProactiveRule(
            rule_id="rule_motion",
            name="Motion Detected",
            entity_id_pattern=r"binary_sensor\..*(?:motion|occupancy).*",
            from_state="off",
            to_state="on",
            template="Motion detected by {friendly_name}.",
            cooldown_seconds=120.0,
            severity="INFO",
        ),
    ]


class ProactiveEngine:
    """
    Ambient Rules & Debounce Engine.
    Evaluates Home Assistant state_changed events against configured rules,
    applies quiet hours and cooldown filters, and triggers ProactiveSpeechDispatcher.
    """

    def __init__(
        self,
        event_bus: Optional[EventBus] = None,
        dispatcher: Optional[ProactiveSpeechDispatcher] = None,
        rules: Optional[List[ProactiveRule]] = None,
        database: Optional[Any] = None,
    ):
        self.event_bus = event_bus or EventBus()
        self.dispatcher = dispatcher or ProactiveSpeechDispatcher()
        self.database = database
        self._rules: List[ProactiveRule] = rules if rules is not None else get_default_proactive_rules()

        # Cooldown tracker: key -> last_trigger_timestamp
        self._cooldowns: Dict[str, float] = {}
        self.recent_announcements: List[Dict[str, Any]] = []
        self._subscribed = False

    def add_rule(self, rule: ProactiveRule) -> None:
        """Add or update an ambient rule."""
        self._rules = [r for r in self._rules if r.rule_id != rule.rule_id]
        self._rules.append(rule)

    def remove_rule(self, rule_id: str) -> bool:
        """Remove a rule by ID."""
        initial_len = len(self._rules)
        self._rules = [r for r in self._rules if r.rule_id != rule_id]
        return len(self._rules) < initial_len

    def get_rules(self) -> List[ProactiveRule]:
        """List all registered rules."""
        return list(self._rules)

    def start(self) -> None:
        """Subscribe to Home Assistant state_changed events on EventBus."""
        if not self._subscribed:
            self.event_bus.subscribe("ha.state_changed", self._on_ha_state_changed)
            self._subscribed = True
            logger.info("ProactiveEngine subscribed to 'ha.state_changed' events (%d rules active)", len(self._rules))

    def is_in_quiet_hours(self, current_time: Optional[dtime] = None) -> bool:
        """
        Determines if current_time falls within configured quiet hours.
        Handles overnight spans (e.g. 23:00 to 07:00).
        """
        try:
            start_h, start_m = map(int, settings.PROACTIVE_QUIET_HOURS_START.split(":"))
            end_h, end_m = map(int, settings.PROACTIVE_QUIET_HOURS_END.split(":"))
            t_start = dtime(start_h, start_m)
            t_end = dtime(end_h, end_m)
        except Exception:
            t_start = dtime(23, 0)
            t_end = dtime(7, 0)

        now = current_time or datetime.now().time()

        if t_start <= t_end:
            # Daytime range e.g. 13:00 to 15:00
            return t_start <= now < t_end
        else:
            # Overnight range e.g. 23:00 to 07:00
            return now >= t_start or now < t_end

    def evaluate_event(
        self,
        event_data: Dict[str, Any],
        current_time: Optional[float] = None,
        test_quiet_time: Optional[dtime] = None,
    ) -> Optional[ProactiveAnnouncement]:
        """
        Evaluates a single state_changed event against all rules.
        Returns ProactiveAnnouncement if matched and not suppressed, None otherwise.
        """
        if not settings.PROACTIVE_ENABLED:
            return None

        entity_id = event_data.get("entity_id") or ""
        new_state_obj = event_data.get("new_state") or {}
        old_state_obj = event_data.get("old_state") or {}

        if not entity_id or not new_state_obj:
            return None

        new_val = str(new_state_obj.get("state", "")).lower()
        old_val = str(old_state_obj.get("state", "")).lower() if old_state_obj else None

        # Extract friendly_name attribute with graceful fallback
        attributes = new_state_obj.get("attributes", {})
        friendly_name = attributes.get("friendly_name") or entity_id.split(".")[-1].replace("_", " ").title()

        now_ts = current_time if current_time is not None else time.time()

        for rule in self._rules:
            if not rule.enabled:
                continue

            # 1. Match entity_id pattern
            try:
                if not re.search(rule.entity_id_pattern, entity_id, re.IGNORECASE):
                    continue
            except re.error:
                if rule.entity_id_pattern.lower() not in entity_id.lower():
                    continue

            # 2. Match from_state if specified
            if rule.from_state is not None:
                if old_val != rule.from_state.lower():
                    continue

            # 3. Match to_state if specified
            if rule.to_state is not None:
                if new_val != rule.to_state.lower():
                    continue

            # 4. Debounce / Cooldown check (per rule and entity)
            cooldown_key = f"{rule.rule_id}:{entity_id}"
            last_triggered = self._cooldowns.get(cooldown_key)
            if last_triggered is not None and (now_ts - last_triggered < rule.cooldown_seconds):
                logger.debug(
                    "Proactive alert suppressed by cooldown for %s (%.1fs remaining)",
                    cooldown_key,
                    rule.cooldown_seconds - (now_ts - last_triggered),
                )
                continue


            # 5. Quiet hours check: CRITICAL severity overrides quiet hours
            if rule.severity.upper() != "CRITICAL":
                if self.is_in_quiet_hours(test_quiet_time):
                    logger.info(
                        "Proactive alert for %s muted during quiet hours (%s - %s)",
                        entity_id,
                        settings.PROACTIVE_QUIET_HOURS_START,
                        settings.PROACTIVE_QUIET_HOURS_END,
                    )
                    continue

            # Format announcement text
            try:
                text = rule.template.format(
                    friendly_name=friendly_name,
                    entity_id=entity_id,
                    to_state=new_val,
                    from_state=old_val or "",
                )
            except Exception:
                text = f"{friendly_name} is now {new_val}."

            # Update cooldown timestamp
            self._cooldowns[cooldown_key] = now_ts

            announcement = ProactiveAnnouncement(
                rule_id=rule.rule_id,
                entity_id=entity_id,
                text=text,
                severity=rule.severity.upper(),
                timestamp=now_ts,
            )
            return announcement

        return None

    async def _on_ha_state_changed(self, event: Event) -> None:
        """EventBus handler for 'ha.state_changed' topic."""
        announcement = self.evaluate_event(event.payload)
        if announcement:
            await self._process_announcement(announcement)

    async def _process_announcement(self, announcement: ProactiveAnnouncement) -> None:
        """Dispatches announcement to satellites and records audit log."""
        record = announcement.model_dump()
        self.recent_announcements.append(record)
        if len(self.recent_announcements) > 50:
            self.recent_announcements.pop(0)

        # Dispatch speech
        try:
            await self.dispatcher.dispatch(
                text=announcement.text,
                severity=announcement.severity,
                entity_id=announcement.entity_id,
                timestamp=announcement.timestamp,
            )
        except Exception as e:
            logger.error("Failed to dispatch proactive announcement: %s", e)

        # Record audit log in database if present
        if self.database and hasattr(self.database, "record_audit_event"):
            try:
                await self.database.record_audit_event(
                    event_type="proactive.announcement_dispatched",
                    payload=record,
                    correlation_id=announcement.announcement_id,
                    device_id="proactive_engine",
                )
            except Exception as e:
                logger.debug("Could not record proactive audit event: %s", e)
