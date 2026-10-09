import pytest
from httpx import AsyncClient, ASGITransport
from src.server.app import app

@pytest.mark.asyncio
async def test_health_liveness_endpoint():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.get("/health/liveness")
    assert response.status_code == 200
    assert response.json() == {"status": "alive"}

@pytest.mark.asyncio
async def test_health_readiness_endpoint():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.get("/health/readiness")
    assert response.status_code == 200
    data = response.json()
    assert "status" in data
    assert "report" in data

@pytest.mark.asyncio
async def test_health_detailed_endpoint():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.get("/health/detailed")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] in ["HEALTHY", "DEGRADED", "UNHEALTHY"]
    assert "components" in data
