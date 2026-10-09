import pytest
import asyncio
from src.health.health_checker import HealthChecker, HealthStatus

@pytest.mark.asyncio
async def test_health_checker_healthy():
    checker = HealthChecker()
    checker.register_probe("db", lambda: {"connected": True})
    
    async def async_probe():
        await asyncio.sleep(0.01)
        return {"status": "ready"}
    
    checker.register_probe("ollama", async_probe)

    report = await checker.evaluate_system()
    assert report.status == HealthStatus.HEALTHY
    assert "db" in report.components
    assert "ollama" in report.components
    assert report.components["db"].status == HealthStatus.HEALTHY
    assert report.components["ollama"].latency_ms > 0

@pytest.mark.asyncio
async def test_health_checker_unhealthy():
    checker = HealthChecker()
    
    def failing_probe():
        raise ConnectionRefusedError("Database connection dropped")

    checker.register_probe("database", failing_probe)

    report = await checker.evaluate_system()
    assert report.status == HealthStatus.UNHEALTHY
    assert report.components["database"].status == HealthStatus.UNHEALTHY
    assert "Database connection dropped" in report.components["database"].error

@pytest.mark.asyncio
async def test_health_checker_timeout_degraded():
    checker = HealthChecker()

    async def slow_probe():
        await asyncio.sleep(4.0)
        return {}

    checker.register_probe("external_service", slow_probe)

    component = await checker.check_component("external_service")
    assert component.status == HealthStatus.DEGRADED
    assert "timed out" in component.error
