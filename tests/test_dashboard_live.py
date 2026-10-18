import re
import socket
import threading
import time
from pathlib import Path

import pytest
import httpx
from starlette.testclient import TestClient
import uvicorn

from src.server.app import app
from src.security.auth import auth_manager
from src.security.airgap import socket_air_gap_guard, AirGapViolationError


def find_free_port() -> int:
    """Locate an open ephemeral port on 127.0.0.1."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def api_headers():
    master_key = auth_manager.get_master_key()
    return {"X-API-Key": master_key}


def test_dashboard_html_and_zero_cdn_references():
    """
    Smoke test: GET / and GET /dashboard serve Control Center HTML with zero external CDNs.
    """
    with TestClient(app) as client:
        # 1. GET / (following redirect to /dashboard)
        res_root = client.get("/", follow_redirects=True)
        assert res_root.status_code == 200
        assert "text/html" in res_root.headers.get("content-type", "")
        html = res_root.text
        assert "IRIS-BOX Control Center" in html
        assert "Subsystem Status Matrix" in html
        assert "Interactive Plan Approval Center" in html

        # 2. GET /dashboard directly
        res_dash = client.get("/dashboard")
        assert res_dash.status_code == 200
        assert "IRIS-BOX Control Center" in res_dash.text

        # 3. Air-gap integrity: Zero external CDN scripts, stylesheets, or fonts
        external_scripts = re.findall(r'<script[^>]+src=["\'](https?:)?//[^"\']+["\']', html, re.IGNORECASE)
        assert len(external_scripts) == 0, f"Found external scripts: {external_scripts}"

        external_links = re.findall(r'<link[^>]+href=["\'](https?:)?//[^"\']+["\']', html, re.IGNORECASE)
        assert len(external_links) == 0, f"Found external stylesheets/links: {external_links}"

        cdn_patterns = [
            r"unpkg\.com",
            r"cdnjs\.cloudflare\.com",
            r"cdn\.jsdelivr\.net",
            r"fonts\.googleapis\.com",
            r"fonts\.gstatic\.com",
            r"fontawesome",
        ]
        for pattern in cdn_patterns:
            assert not re.search(pattern, html, re.IGNORECASE), f"Found forbidden CDN pattern '{pattern}'"

        # 4. Local static delivery
        res_css = client.get("/static/css/dashboard.css")
        assert res_css.status_code == 200
        assert len(res_css.text) > 50

        res_js = client.get("/static/js/dashboard.js")
        assert res_js.status_code == 200
        assert len(res_js.text) > 50


def test_auth_protection_on_operator_and_desktop_routers():
    """
    Ensure all sensitive API endpoints reject unauthenticated or tampered requests with 401.
    """
    with TestClient(app) as client:
        endpoints = [
            ("GET", "/api/desktop/metrics"),
            ("GET", "/api/desktop/services"),
            ("POST", "/api/operator/snapshot", {"project_path": "."}),
            ("GET", "/api/plans/pending"),
        ]

        for method, endpoint, *payload in endpoints:
            # Missing auth header
            res_no_auth = client.request(method, endpoint, json=payload[0] if payload else None)
            assert res_no_auth.status_code == 401, f"Expected 401 for unauthenticated {method} {endpoint}"

            # Invalid auth header
            res_bad_auth = client.request(
                method,
                endpoint,
                headers={"X-API-Key": "invalid-tampered-token-999"},
                json=payload[0] if payload else None,
            )
            assert res_bad_auth.status_code == 401, f"Expected 401 for bad auth on {method} {endpoint}"


def test_operator_and_desktop_endpoints_with_x_api_key(api_headers):
    """
    Smoke test: Validate responses across desktop telemetry, services, operator snapshot, and pending plans.
    """
    with TestClient(app) as client:
        # 1. GET /api/desktop/metrics -> CPU, RAM, Disk telemetry
        res_metrics = client.get("/api/desktop/metrics", headers=api_headers)
        assert res_metrics.status_code == 200
        metrics = res_metrics.json()
        assert "cpu_percent" in metrics
        assert "memory_percent" in metrics
        assert "total_ram_gb" in metrics
        assert "disk_percent" in metrics

        # 2. GET /api/desktop/services -> Docker/Ollama daemon status
        res_services = client.get("/api/desktop/services", headers=api_headers)
        assert res_services.status_code == 200
        services = res_services.json()
        assert "docker" in services or "ollama" in services

        # 3. POST /api/operator/snapshot -> Workspace discovery snapshot
        proj_root = str(Path(".").resolve())
        res_snapshot = client.post(
            "/api/operator/snapshot",
            json={"project_path": proj_root},
            headers=api_headers,
        )
        assert res_snapshot.status_code == 200
        snapshot = res_snapshot.json()
        assert snapshot["project_type"]["language"] == "python"
        assert "files" in snapshot
        assert len(snapshot["files"]) > 0

        # 4. GET /api/plans/pending -> Pending cryptographic execution plans
        # Stage a test plan first
        pm = client.app.state.plan_manager
        test_plan = pm.create_plan(
            summary="Live verification test plan",
            steps=[],
        )
        res_pending = client.get("/api/plans/pending", headers=api_headers)
        assert res_pending.status_code == 200
        pending_data = res_pending.json()
        assert "plans" in pending_data
        assert "count" in pending_data
        assert pending_data["count"] >= 1
        plan_ids = [p["plan_id"] for p in pending_data["plans"]]
        assert test_plan.plan_id in plan_ids


def test_live_uvicorn_server_with_airgap_guard(api_headers):
    """
    Live Server Integration Test:
    Spins up FastAPI on a real loopback socket (127.0.0.1:port) with socket_air_gap_guard enabled.
    Performs live HTTP requests, validates X-API-Key auth, verifies zero external egress,
    and cleanly terminates the server.
    """
    port = find_free_port()
    config = uvicorn.Config(
        app=app,
        host="127.0.0.1",
        port=port,
        log_level="warning",
        access_log=False,
    )
    server = uvicorn.Server(config)

    server_thread = threading.Thread(target=server.run, daemon=True)

    with socket_air_gap_guard():
        server_thread.start()

        # Wait for live server socket to accept connections
        base_url = f"http://127.0.0.1:{port}"
        started = False
        for _ in range(30):
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                    started = True
                    break
            except (ConnectionRefusedError, OSError):
                time.sleep(0.1)

        assert started, f"Live Uvicorn server failed to bind to {base_url} within 3s."

        try:
            with httpx.Client(base_url=base_url, timeout=10.0) as http_client:
                # 1. GET / -> Live Control Center Dashboard HTML
                resp_root = http_client.get("/", follow_redirects=True)
                assert resp_root.status_code == 200
                assert "text/html" in resp_root.headers.get("content-type", "")
                assert "IRIS-BOX Control Center" in resp_root.text

                # 2. GET /api/desktop/metrics -> Live real-time CPU, RAM, Disk
                resp_metrics = http_client.get("/api/desktop/metrics", headers=api_headers)
                assert resp_metrics.status_code == 200
                metrics_data = resp_metrics.json()
                assert "cpu_percent" in metrics_data
                assert "memory_percent" in metrics_data

                # 3. GET /api/desktop/services -> Live daemon inspection
                resp_services = http_client.get("/api/desktop/services", headers=api_headers)
                assert resp_services.status_code == 200
                assert "ollama" in resp_services.json()

                # 4. POST /api/operator/snapshot -> Live workspace snapshot
                proj_path = str(Path(".").resolve())
                resp_snap = http_client.post(
                    "/api/operator/snapshot",
                    json={"project_path": proj_path},
                    headers=api_headers,
                )
                assert resp_snap.status_code == 200
                assert resp_snap.json()["project_type"]["language"] == "python"

                # 5. GET /api/plans/pending -> Live pending plans list
                resp_plans = http_client.get("/api/plans/pending", headers=api_headers)
                assert resp_plans.status_code == 200
                assert "plans" in resp_plans.json()

                # 6. Air-Gap Guard Enforcement Verification:
                # Direct non-loopback connections MUST be intercepted and raise AirGapViolationError
                with pytest.raises(AirGapViolationError):
                    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                        s.connect(("8.8.8.8", 53))

        finally:
            server.should_exit = True
            server_thread.join(timeout=5.0)
