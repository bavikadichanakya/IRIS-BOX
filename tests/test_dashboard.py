import re
import pytest
from fastapi.testclient import TestClient

from src.server.app import app


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


def test_dashboard_route_returns_200_and_html(client):
    """Verify that GET /dashboard serves HTTP 200 with HTML content."""
    response = client.get("/dashboard")
    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")
    html = response.text
    assert "<!DOCTYPE html>" in html or "<html" in html
    assert "IRIS-BOX Control Center" in html
    assert "Subsystem Status Matrix" in html
    assert "Interactive Plan Approval Center" in html
    assert "Skills &amp; Integrations Explorer" in html or "Skills & Integrations Explorer" in html


def test_dashboard_air_gapped_no_external_cdns(client):
    """
    Strict Air-Gapped Constraint Verification:
    Assert that the HTML contains zero external scripts, external stylesheets, or external CDN assets.
    """
    response = client.get("/dashboard")
    assert response.status_code == 200
    html = response.text

    # 1. Regex check for external scripts (src starting with http://, https://, or //)
    external_scripts = re.findall(r'<script[^>]+src=["\'](https?:)?//[^"\']+["\']', html, re.IGNORECASE)
    assert len(external_scripts) == 0, f"Found external scripts: {external_scripts}"

    # 2. Regex check for external stylesheet/link assets (href starting with http://, https://, or //)
    external_links = re.findall(r'<link[^>]+href=["\'](https?:)?//[^"\']+["\']', html, re.IGNORECASE)
    assert len(external_links) == 0, f"Found external link tags: {external_links}"

    # 3. Ensure no external CDN keywords (unpkg, cdnjs, jsdelivr, googleapis, fontawesome)
    cdn_patterns = [
        r"unpkg\.com",
        r"cdnjs\.cloudflare\.com",
        r"cdn\.jsdelivr\.net",
        r"fonts\.googleapis\.com",
        r"fonts\.gstatic\.com",
        r"fontawesome",
    ]
    for pattern in cdn_patterns:
        match = re.search(pattern, html, re.IGNORECASE)
        assert match is None, f"Found forbidden external CDN pattern '{pattern}' in dashboard HTML"

    # 4. Verify linked static assets are strictly local relative or rooted paths
    script_sources = re.findall(r'<script[^>]+src=["\']([^"\']+)["\']', html, re.IGNORECASE)
    for src in script_sources:
        assert src.startswith("/static/") or src.startswith("static/"), f"Script source '{src}' is not local static asset"

    link_hrefs = re.findall(r'<link[^>]+href=["\']([^"\']+)["\']', html, re.IGNORECASE)
    for href in link_hrefs:
        assert href.startswith("/static/") or href.startswith("static/"), f"Link href '{href}' is not local static asset"


def test_root_redirects_to_dashboard(client):
    """Verify that root GET / redirects to /dashboard without requiring credentials."""
    response = client.get("/", follow_redirects=False)
    assert response.status_code in (302, 307)
    assert response.headers.get("location") == "/dashboard"

    # Follow redirect
    followed_response = client.get("/", follow_redirects=True)
    assert followed_response.status_code == 200
    assert "IRIS-BOX Control Center" in followed_response.text


def test_static_asset_delivery(client):
    """Verify that local static CSS and JS files are served correctly by FastAPI."""
    css_res = client.get("/static/css/dashboard.css")
    assert css_res.status_code == 200
    assert len(css_res.text) > 50
    assert "--bg-primary" in css_res.text or "dashboard-container" in css_res.text

    js_res = client.get("/static/js/dashboard.js")
    assert js_res.status_code == 200
    assert len(js_res.text) > 50
    assert "IRIS-BOX Control Center" in js_res.text or "apiFetch" in js_res.text


def test_dashboard_subsystems_status_api(client):
    """Verify that /api/dashboard/status returns all 6 subsystems and telemetry metrics."""
    res = client.get("/api/dashboard/status")
    assert res.status_code == 200
    data = res.json()

    assert "subsystems" in data
    assert "metrics" in data

    subsystems = data["subsystems"]
    expected_subsystems = ["llm", "wakeword", "stt", "tts", "database", "fleet"]
    for sub in expected_subsystems:
        assert sub in subsystems, f"Missing subsystem '{sub}' in dashboard status"
        info = subsystems[sub]
        assert "status" in info
        assert info["status"] in ("HEALTHY", "DEGRADED", "UNAVAILABLE")
        assert "latency_ms" in info
        assert isinstance(info["latency_ms"], (int, float))

    metrics = data["metrics"]
    assert "total_requests" in metrics
    assert "success_rate" in metrics
    assert "avg_latency_ms" in metrics
    assert "tool_invocations" in metrics
