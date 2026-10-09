import time
from typing import Dict, Any, List, Optional
from src.observability.event_bus import EventBus, Event


class RuntimeMetrics:
    """
    Centralized operational metrics engine for IRIS-BOX architecture.
    Tracks real runtime metrics by subscribing to EventBus events and recording execution hooks.
    No hardcoded synthetic placeholders; strictly derives metrics from real event streams.
    """

    def __init__(self, event_bus: Optional[EventBus] = None):
        self.event_bus = event_bus
        self.start_time = time.time()

        # Request metrics
        self.total_requests = 0
        self.active_requests = 0
        self.successful_requests = 0
        self.failed_requests = 0
        self.cancelled_requests = 0

        # Tool execution metrics
        self.tool_invocations: Dict[str, int] = {}
        self.tool_successes: Dict[str, int] = {}
        self.tool_denials: Dict[str, int] = {}
        self.tool_failures: Dict[str, int] = {}
        self.tool_latencies: Dict[str, float] = {}

        # Voice metrics
        self.voice_barge_in_count = 0
        self.voice_processing_latencies: List[float] = []
        self.audio_to_response_latencies: List[float] = []

        # Device/Fleet metrics
        self.connected_devices_count = 0
        self.stale_heartbeat_count = 0

        # Provider metrics
        self.llm_request_count = 0
        self.provider_connection_errors = 0
        self.token_stream_latencies: List[float] = []

        if self.event_bus:
            self._subscribe_events()

    def _subscribe_events(self):
        def _on_event(event: Event):
            self.handle_event(event)

        self.event_bus.subscribe("*", _on_event)

    def handle_event(self, event: Event):
        topic = event.topic
        payload = event.payload or {}

        # Request counters
        if topic in ("request.started", "request.invoked"):
            self.total_requests += 1
            self.active_requests += 1
        elif topic in ("request.completed", "request.succeeded"):
            self.active_requests = max(0, self.active_requests - 1)
            self.successful_requests += 1
        elif topic in ("request.failed", "request.error"):
            self.active_requests = max(0, self.active_requests - 1)
            self.failed_requests += 1
        elif topic in ("request.cancelled",):
            self.active_requests = max(0, self.active_requests - 1)
            self.cancelled_requests += 1

        # Tool execution metrics
        if topic in ("tool.invoked", "tool.execution.started"):
            tool_name = payload.get("tool_name") or payload.get("tool") or "unknown"
            self.tool_invocations[tool_name] = self.tool_invocations.get(tool_name, 0) + 1
        elif topic in ("tool.completed", "tool.execution.succeeded"):
            tool_name = payload.get("tool_name") or payload.get("tool") or "unknown"
            self.tool_successes[tool_name] = self.tool_successes.get(tool_name, 0) + 1
            dur = payload.get("duration_ms", 0.0)
            if dur:
                prev = self.tool_latencies.get(tool_name, dur)
                self.tool_latencies[tool_name] = (prev * 0.8) + (dur * 0.2)
        elif topic in ("tool.denied", "tool.execution.denied"):
            tool_name = payload.get("tool_name") or payload.get("tool") or "unknown"
            self.tool_denials[tool_name] = self.tool_denials.get(tool_name, 0) + 1
        elif topic in ("tool.failed", "tool.execution.failed", "tool.execution.timeout"):
            tool_name = payload.get("tool_name") or payload.get("tool") or "unknown"
            self.tool_failures[tool_name] = self.tool_failures.get(tool_name, 0) + 1

        # Voice metrics
        if topic in ("voice.barge_in", "voice.tts.interrupted"):
            self.voice_barge_in_count += 1
        elif topic == "voice.stt.completed":
            dur = payload.get("duration_ms", 0.0)
            if dur:
                self.voice_processing_latencies.append(dur)
        elif topic == "voice.pipeline.completed":
            dur = payload.get("duration_ms", 0.0)
            if dur:
                self.audio_to_response_latencies.append(dur)

        # Device/Fleet metrics
        if topic == "fleet.device.connected":
            self.connected_devices_count += 1
        elif topic == "fleet.device.disconnected":
            self.connected_devices_count = max(0, self.connected_devices_count - 1)
        elif topic == "fleet.heartbeat.stale":
            self.stale_heartbeat_count += 1

        # Provider metrics
        if topic in ("provider.llm.requested", "voice.agent.started"):
            self.llm_request_count += 1
        elif topic == "provider.llm.error":
            self.provider_connection_errors += 1
        elif topic == "provider.llm.latency":
            dur = payload.get("latency_ms", 0.0)
            if dur:
                self.token_stream_latencies.append(dur)

    def record_request(self, status: str = "success"):
        self.total_requests += 1
        if status == "success":
            self.successful_requests += 1
        elif status == "failed":
            self.failed_requests += 1
        elif status == "cancelled":
            self.cancelled_requests += 1

    def record_tool_execution(self, tool_name: str, status: str, duration_ms: float = 0.0):
        self.tool_invocations[tool_name] = self.tool_invocations.get(tool_name, 0) + 1
        if status == "SUCCEEDED":
            self.tool_successes[tool_name] = self.tool_successes.get(tool_name, 0) + 1
            prev = self.tool_latencies.get(tool_name, duration_ms)
            self.tool_latencies[tool_name] = (prev * 0.8) + (duration_ms * 0.2)
        elif status == "DENIED":
            self.tool_denials[tool_name] = self.tool_denials.get(tool_name, 0) + 1
        else:
            self.tool_failures[tool_name] = self.tool_failures.get(tool_name, 0) + 1

    def get_metrics_snapshot(self) -> Dict[str, Any]:
        uptime_sec = time.time() - self.start_time
        total_tool_invocations = sum(self.tool_invocations.values())
        total_tool_successes = sum(self.tool_successes.values())
        total_tool_denials = sum(self.tool_denials.values())
        total_tool_failures = sum(self.tool_failures.values())

        success_rate = (total_tool_successes / total_tool_invocations) if total_tool_invocations > 0 else 1.0
        denial_rate = (total_tool_denials / total_tool_invocations) if total_tool_invocations > 0 else 0.0
        failure_rate = (total_tool_failures / total_tool_invocations) if total_tool_invocations > 0 else 0.0

        avg_voice_latency = (
            (sum(self.voice_processing_latencies) / len(self.voice_processing_latencies))
            if self.voice_processing_latencies else 0.0
        )
        avg_audio_to_resp = (
            (sum(self.audio_to_response_latencies) / len(self.audio_to_response_latencies))
            if self.audio_to_response_latencies else 0.0
        )
        avg_token_latency = (
            (sum(self.token_stream_latencies) / len(self.token_stream_latencies))
            if self.token_stream_latencies else 0.0
        )

        return {
            "uptime_seconds": round(uptime_sec, 2),
            "requests": {
                "total": self.total_requests,
                "active": self.active_requests,
                "successful": self.successful_requests,
                "failed": self.failed_requests,
                "cancelled": self.cancelled_requests,
            },
            "tools": {
                "invocations_by_tool": dict(self.tool_invocations),
                "total_invocations": total_tool_invocations,
                "success_rate": round(success_rate, 4),
                "denial_rate": round(denial_rate, 4),
                "failure_rate": round(failure_rate, 4),
                "latencies_ms": {k: round(v, 2) for k, v in self.tool_latencies.items()}
            },
            "voice": {
                "barge_in_count": self.voice_barge_in_count,
                "avg_processing_latency_ms": round(avg_voice_latency, 2),
                "avg_audio_to_response_latency_ms": round(avg_audio_to_resp, 2)
            },
            "fleet": {
                "connected_devices": self.connected_devices_count,
                "stale_heartbeats": self.stale_heartbeat_count
            },
            "provider": {
                "llm_requests": self.llm_request_count,
                "connection_errors": self.provider_connection_errors,
                "avg_token_latency_ms": round(avg_token_latency, 2)
            }
        }


runtime_metrics = RuntimeMetrics()
