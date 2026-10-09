import asyncio
import time
import pytest
import openai
import httpx

from src.agent.recovery import (
    ResilientLLMProvider,
    CircuitState,
    ProviderUnavailableError,
    is_retryable_error,
)
from src.observability.event_bus import EventBus
from src.observability.health import HealthSupervisor, HealthState


def mock_response(status_code: int = 500) -> httpx.Response:
    request = httpx.Request("POST", "http://localhost/v1/chat/completions")
    return httpx.Response(status_code=status_code, request=request)


def test_is_retryable_error_classification():
    """Verify error classification distinguishes retryable from non-retryable errors."""
    # Retryable errors
    assert is_retryable_error(asyncio.TimeoutError()) is True
    assert is_retryable_error(ConnectionResetError()) is True
    assert is_retryable_error(openai.RateLimitError(message="Rate limit", response=mock_response(429), body=None)) is True
    assert is_retryable_error(openai.APIConnectionError(request=httpx.Request("POST", "http://localhost"))) is True
    assert is_retryable_error(openai.InternalServerError(message="500 Internal Error", response=mock_response(500), body=None)) is True

    # Non-retryable errors
    auth_err = openai.APIStatusError(message="401 Unauthorized", response=mock_response(401), body=None)
    auth_err.status_code = 401
    assert is_retryable_error(auth_err) is False

    bad_req_err = openai.APIStatusError(message="400 Bad Request", response=mock_response(400), body=None)
    bad_req_err.status_code = 400
    assert is_retryable_error(bad_req_err) is False


@pytest.mark.asyncio
async def test_transient_failure_retry_success():
    """Verify transient failures trigger backoff retries and succeed on subsequent attempt."""
    bus = EventBus()
    events = []

    bus.subscribe("provider.request.retrying", lambda e: events.append(e))
    bus.subscribe("provider.request.succeeded", lambda e: events.append(e))

    provider = ResilientLLMProvider(event_bus=bus, max_retries=3, base_delay=0.01)

    attempts = 0

    async def flaky_llm_call():
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise openai.RateLimitError(message="Rate limit exceeded", response=mock_response(429), body=None)
        return "SUCCESS_RESPONSE"

    result = await provider.execute_with_recovery(flaky_llm_call, request_id="req-retry")
    assert result == "SUCCESS_RESPONSE"
    assert attempts == 3
    assert len([e for e in events if e.topic == "provider.request.retrying"]) == 2
    assert any(e.topic == "provider.request.succeeded" for e in events)


@pytest.mark.asyncio
async def test_non_retryable_error_fails_fast():
    """Verify non-retryable errors fail immediately without retrying."""
    bus = EventBus()
    provider = ResilientLLMProvider(event_bus=bus, max_retries=3, base_delay=0.01)

    attempts = 0

    async def non_retryable_llm_call():
        nonlocal attempts
        attempts += 1
        err = openai.APIStatusError(message="401 Unauthorized", response=mock_response(401), body=None)
        err.status_code = 401
        raise err

    with pytest.raises(openai.APIStatusError):
        await provider.execute_with_recovery(non_retryable_llm_call, request_id="req-fast-fail")

    assert attempts == 1


@pytest.mark.asyncio
async def test_circuit_breaker_state_transitions():
    """Test Circuit Breaker transitions: CLOSED -> OPEN -> HALF_OPEN -> CLOSED."""
    bus = EventBus()
    state_changes = []
    bus.subscribe("provider.circuit_breaker.state_changed", lambda e: state_changes.append(e))

    provider = ResilientLLMProvider(
        event_bus=bus,
        max_retries=1,
        base_delay=0.01,
        failure_threshold=3,
        recovery_timeout=0.1
    )

    assert provider.state == CircuitState.CLOSED

    # 1. Cause 3 failures to trip circuit breaker to OPEN
    for i in range(3):
        try:
            await provider.execute_with_recovery(
                lambda: (_ for _ in ()).throw(openai.InternalServerError("Server Error", response=mock_response(500), body=None)),
                request_id=f"req-fail-{i}"
            )
        except openai.InternalServerError:
            pass

    assert provider.state == CircuitState.OPEN
    assert any(e.payload["new_state"] == "OPEN" for e in state_changes)

    # 2. Subsequent call during OPEN cooldown raises ProviderUnavailableError
    with pytest.raises(ProviderUnavailableError):
        await provider.execute_with_recovery(lambda: "SHOULD_NOT_RUN")

    # 3. Wait for recovery timeout -> next call probes in HALF_OPEN state and resets to CLOSED on success
    await asyncio.sleep(0.15)

    async def healthy_probe():
        return "PROBE_SUCCESS"

    result = await provider.execute_with_recovery(healthy_probe, request_id="req-probe")
    assert result == "PROBE_SUCCESS"
    assert provider.state == CircuitState.CLOSED
    assert provider.consecutive_failures == 0


@pytest.mark.asyncio
async def test_generation_id_tracking_stale_token_discarding():
    """Verify stale tokens from outdated generation IDs are discarded during streaming."""
    bus = EventBus()
    provider = ResilientLLMProvider(event_bus=bus)

    async def mock_stream_factory():
        async def fake_generator():
            yield "Token 1 "
            await asyncio.sleep(0.05)
            # Advance generation during stream execution
            provider.increment_generation()
            yield "Stale Token 2"

        return fake_generator()

    generator = provider.stream_with_recovery(mock_stream_factory, request_id="req-stream-gen")
    collected_tokens = []

    async for token in generator:
        collected_tokens.append(token)

    assert collected_tokens == ["Token 1 "]
    assert "Stale Token 2" not in collected_tokens


@pytest.mark.asyncio
async def test_cancellation_cleanup():
    """Verify cancelled requests raise CancelledError cleanly without retrying."""
    provider = ResilientLLMProvider(max_retries=3, base_delay=0.01)

    async def hanging_call():
        await asyncio.sleep(10)

    task = asyncio.create_task(provider.execute_with_recovery(hanging_call))
    await asyncio.sleep(0.02)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_health_supervisor_circuit_breaker_reporting():
    """Verify HealthSupervisor reports UNHEALTHY when circuit breaker is OPEN."""
    from src.agent.orchestrator import IRISOrchestrator

    bus = EventBus()
    provider = ResilientLLMProvider(event_bus=bus, failure_threshold=1)
    provider.state = CircuitState.OPEN

    orchestrator = IRISOrchestrator(
        api_base="http://localhost:11434/v1",
        api_key="ollama",
        resilient_provider=provider
    )

    supervisor = HealthSupervisor(orchestrator=orchestrator)
    report = await supervisor.check_llm_provider()

    assert report.status == HealthState.UNHEALTHY
    assert "OPEN" in report.message
    assert report.details["circuit_breaker_state"] == "OPEN"
