import time
import random
import asyncio
import logging
from enum import Enum
from typing import Callable, Any, Optional, Dict, List, AsyncGenerator
import openai

from src.observability.event_bus import EventBus
from src.observability.tracing import create_trace_context, TraceContext

logger = logging.getLogger("iris.agent.recovery")


class CircuitState(str, Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class ProviderUnavailableError(Exception):
    """Raised when the LLM provider circuit breaker is in OPEN state."""
    pass


def is_retryable_error(exc: Exception) -> bool:
    """
    Classify whether an exception is retryable (transient network drops, rate limits, timeouts, 5xx server errors)
    or non-retryable (400 Bad Request, 401 Unauthorized, 403 Forbidden, 404 Not Found, context length exceeded).
    """
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError, ConnectionResetError, ConnectionRefusedError, OSError)):
        return True

    if isinstance(exc, (openai.RateLimitError, openai.APIConnectionError, openai.APITimeoutError, openai.InternalServerError)):
        return True

    if isinstance(exc, openai.APIStatusError):
        if exc.status_code in (429, 502, 503, 504):
            return True
        if exc.status_code in (400, 401, 403, 404):
            return False

    msg = str(exc).lower()
    if any(term in msg for term in ["rate limit", "429", "502", "503", "504", "timeout", "connection refused", "reset by peer"]):
        return True

    return False


class ResilientLLMProvider:
    """
    Resilient LLM Provider recovery engine implementing:
    1. Exponential backoff with jitter for retryable transient errors.
    2. Circuit breaker state machine (CLOSED -> OPEN -> HALF_OPEN -> CLOSED).
    3. Generation ID tracking to discard stale tokens from cancelled or retried requests.
    4. Structured EventBus telemetry dispatches.
    """

    def __init__(
        self,
        event_bus: Optional[EventBus] = None,
        max_retries: int = 3,
        base_delay: float = 0.5,
        max_delay: float = 10.0,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
    ):
        self.event_bus = event_bus or EventBus()
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout

        self.state: CircuitState = CircuitState.CLOSED
        self.consecutive_failures: int = 0
        self.last_failure_time: float = 0.0
        self.current_generation_id: int = 0
        self._lock = asyncio.Lock()

    def get_generation_id(self) -> int:
        return self.current_generation_id

    def increment_generation(self) -> int:
        self.current_generation_id += 1
        return self.current_generation_id

    def _check_circuit_breaker_sync(self):
        now = time.time()
        if self.state == CircuitState.OPEN:
            if (now - self.last_failure_time) >= self.recovery_timeout:
                self.state = CircuitState.HALF_OPEN
            else:
                raise ProviderUnavailableError("Circuit breaker is OPEN. LLM provider unavailable.")

    def record_success_sync(self):
        if self.state in (CircuitState.HALF_OPEN, CircuitState.OPEN):
            self.state = CircuitState.CLOSED
        self.consecutive_failures = 0

    def record_failure_sync(self, exc: Exception):
        self.consecutive_failures += 1
        self.last_failure_time = time.time()
        if self.consecutive_failures >= self.failure_threshold or self.state == CircuitState.HALF_OPEN:
            self.state = CircuitState.OPEN

    async def _transition_state(self, new_state: CircuitState, reason: str = ""):
        old_state = self.state
        if old_state != new_state:
            self.state = new_state
            logger.warning(f"Circuit breaker state changed: {old_state} -> {new_state}. Reason: {reason}")
            await self.event_bus.publish(
                "provider.circuit_breaker.state_changed",
                {"old_state": old_state.value, "new_state": new_state.value, "reason": reason}
            )
            if new_state == CircuitState.OPEN:
                await self.event_bus.publish(
                    "provider.circuit_breaker.tripped",
                    {"failures": self.consecutive_failures, "cooldown_seconds": self.recovery_timeout}
                )

    async def check_circuit_breaker(self):
        """Evaluate circuit breaker state before making a request."""
        now = time.time()
        if self.state == CircuitState.OPEN:
            if (now - self.last_failure_time) >= self.recovery_timeout:
                await self._transition_state(CircuitState.HALF_OPEN, "Recovery timeout elapsed; probing health.")
            else:
                raise ProviderUnavailableError("Circuit breaker is OPEN. LLM provider unavailable.")

    async def record_success(self):
        """Record a successful request execution."""
        async with self._lock:
            if self.state in (CircuitState.HALF_OPEN, CircuitState.OPEN):
                await self._transition_state(CircuitState.CLOSED, "Probe request succeeded.")
            self.consecutive_failures = 0

    async def record_failure(self, exc: Exception):
        """Record a request failure and transition circuit breaker if threshold exceeded."""
        async with self._lock:
            self.consecutive_failures += 1
            self.last_failure_time = time.time()
            if self.consecutive_failures >= self.failure_threshold or self.state == CircuitState.HALF_OPEN:
                await self._transition_state(CircuitState.OPEN, f"Failure threshold reached ({self.consecutive_failures} errors): {exc}")

    def execute_with_recovery_sync(
        self,
        func: Callable[..., Any],
        *args: Any,
        request_id: str = "",
        trace_id: str = "",
        device_id: str = "",
        **kwargs: Any
    ) -> Any:
        self._check_circuit_breaker_sync()
        gen_id = self.increment_generation()
        attempt = 0
        last_exception = None

        while attempt < self.max_retries:
            attempt += 1
            try:
                res = func(*args, **kwargs)
                self.record_success_sync()
                return res
            except Exception as exc:
                last_exception = exc
                retryable = is_retryable_error(exc)
                self.record_failure_sync(exc)

                if not retryable or attempt >= self.max_retries:
                    raise exc

                delay = min(self.max_delay, self.base_delay * (2 ** (attempt - 1)) + random.uniform(0.0, 0.1 * self.base_delay))
                time.sleep(delay)

        if last_exception:
            raise last_exception

    async def execute_with_recovery(
        self,
        func: Callable[..., Any],
        *args: Any,
        request_id: str = "",
        trace_id: str = "",
        device_id: str = "",
        **kwargs: Any
    ) -> Any:
        await self.check_circuit_breaker()
        trace = create_trace_context(device_id=device_id or "local", session_id=request_id or None)

        gen_id = self.increment_generation()
        await self.event_bus.publish(
            "provider.request.started",
            {"request_id": request_id, "generation_id": gen_id},
            trace=trace
        )

        attempt = 0
        last_exception = None

        while attempt < self.max_retries:
            attempt += 1
            try:
                res = func(*args, **kwargs)
                if asyncio.iscoroutine(res) or hasattr(res, "__await__"):
                    res = await res
                await self.record_success()
                await self.event_bus.publish(
                    "provider.request.succeeded",
                    {"request_id": request_id, "attempt": attempt, "generation_id": gen_id},
                    trace=trace
                )
                return res
            except asyncio.CancelledError:
                logger.info(f"LLM request {request_id} (gen {gen_id}) was cancelled.")
                raise
            except Exception as exc:
                last_exception = exc
                retryable = is_retryable_error(exc)
                await self.record_failure(exc)

                if not retryable or attempt >= self.max_retries:
                    await self.event_bus.publish(
                        "provider.request.failed",
                        {
                            "request_id": request_id,
                            "attempt": attempt,
                            "error": str(exc),
                            "retryable": retryable,
                            "generation_id": gen_id,
                        },
                        trace=trace
                    )
                    raise exc

                delay = min(self.max_delay, self.base_delay * (2 ** (attempt - 1)) + random.uniform(0.0, 0.1 * self.base_delay))
                await self.event_bus.publish(
                    "provider.request.retrying",
                    {
                        "request_id": request_id,
                        "attempt": attempt,
                        "next_attempt": attempt + 1,
                        "delay_seconds": round(delay, 2),
                        "error": str(exc),
                        "generation_id": gen_id,
                    },
                    trace=trace
                )
                logger.warning(f"LLM call attempt {attempt} failed ({exc}). Retrying in {delay:.2f}s...")
                await asyncio.sleep(delay)

        if last_exception:
            raise last_exception

    async def stream_with_recovery(
        self,
        create_stream_func: Callable[..., Any],
        *args: Any,
        request_id: str = "",
        trace_id: str = "",
        device_id: str = "",
        **kwargs: Any
    ) -> AsyncGenerator[Any, None]:
        await self.check_circuit_breaker()
        trace = create_trace_context(device_id=device_id or "local", session_id=request_id or None)

        stream = await self.execute_with_recovery(
            create_stream_func,
            *args,
            request_id=request_id,
            trace_id=trace_id,
            device_id=device_id,
            **kwargs
        )

        gen_id = self.current_generation_id

        try:
            if hasattr(stream, "__aiter__"):
                async for chunk in stream:
                    if gen_id != self.current_generation_id:
                        logger.warning(f"Discarding stale token from generation {gen_id} (current: {self.current_generation_id})")
                        break
                    yield chunk
            else:
                for chunk in stream:
                    if gen_id != self.current_generation_id:
                        logger.warning(f"Discarding stale token from generation {gen_id} (current: {self.current_generation_id})")
                        break
                    yield chunk
            await self.record_success()
        except asyncio.CancelledError:
            logger.info(f"Stream {request_id} (gen {gen_id}) cancelled by client.")
            raise
        except Exception as exc:
            await self.record_failure(exc)
            await self.event_bus.publish(
                "provider.request.failed",
                {"request_id": request_id, "error": str(exc), "generation_id": gen_id},
                trace=trace
            )
            raise
