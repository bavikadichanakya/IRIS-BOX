from __future__ import annotations

import json
import re
from pathlib import Path
import pytest

# Canonical external CDN domains that must NEVER appear in air-gapped frontend assets
BLOCKED_CDN_DOMAINS = [
    "cdn.jsdelivr.net",
    "fonts.googleapis.com",
    "fonts.gstatic.com",
    "cdnjs.cloudflare.com",
    "unpkg.com",
    "ajax.googleapis.com",
    "stackpath.bootstrapcdn.com",
    "cdn.tailwindcss.com",
    "code.jquery.com",
    "cdn.skypack.dev",
    "esm.sh",
]

ALLOWED_XML_NAMESPACES = {
    "http://www.w3.org/2000/svg",
    "http://www.w3.org/1999/xlink",
    "http://www.w3.org/1999/xhtml",
}


def get_frontend_asset_files() -> list[Path]:
    """Collect all HTML, CSS, JS, and SVG files under templates and static directories."""
    repo_root = Path(__file__).resolve().parent.parent
    targets = [
        repo_root / "src" / "server" / "templates",
        repo_root / "src" / "server" / "static",
    ]
    files: list[Path] = []
    for t in targets:
        if t.exists() and t.is_dir():
            for p in t.rglob("*"):
                if p.is_file() and p.suffix.lower() in (".html", ".css", ".js", ".svg", ".webmanifest", ".json"):
                    files.append(p)
    return files


def test_zero_external_cdn_references():
    """
    Assert that no HTML, JS, or CSS file in src/server/templates or src/server/static
    references external CDN domains.
    """
    asset_files = get_frontend_asset_files()
    assert len(asset_files) > 0, "No frontend asset files found to audit."

    violations: list[str] = []

    for file_path in asset_files:
        content = file_path.read_text(encoding="utf-8", errors="ignore")
        for cdn in BLOCKED_CDN_DOMAINS:
            if cdn in content:
                violations.append(f"{file_path.name} contains reference to external CDN '{cdn}'")

        # Check for any generic external URLs (http:// or https://)
        url_matches = re.findall(r'https?://[^\s"\'<>`)]+', content)
        for url in url_matches:
            if url in ALLOWED_XML_NAMESPACES:
                continue
            # Allow loopback/local references if present
            if any(local in url for local in ("localhost", "127.0.0.1", "0.0.0.0")):
                continue
            violations.append(f"{file_path.name} contains external URL: {url}")

    assert not violations, f"Air-gap audit failed with external URL violations:\n" + "\n".join(violations)


def test_service_worker_local_asset_caching():
    """
    Verify that the PWA Service Worker (sw.js) only caches local application shell assets
    and that all declared app shell files physically exist on disk.
    """
    repo_root = Path(__file__).resolve().parent.parent
    sw_file = repo_root / "src" / "server" / "static" / "mobile" / "sw.js"
    assert sw_file.exists(), "Service Worker (sw.js) not found."

    content = sw_file.read_text(encoding="utf-8")

    # Extract APP_SHELL_URLS
    match = re.search(r"APP_SHELL_URLS\s*=\s*\[(.*?)\]", content, re.DOTALL)
    assert match, "APP_SHELL_URLS array not found in sw.js"

    urls_raw = match.group(1)
    urls = [u.strip().strip("'\"") for u in urls_raw.split(",") if u.strip().strip("'\"")]

    assert len(urls) > 0, "APP_SHELL_URLS is empty."

    for url in urls:
        # Every cached asset must be a local origin-relative path starting with '/'
        assert url.startswith("/"), f"App shell URL '{url}' is not relative to origin"
        assert not url.startswith("//"), f"App shell URL '{url}' looks like protocol-relative CDN"
        assert "://" not in url, f"App shell URL '{url}' contains external protocol"

        # Verify static files exist on disk
        if url.startswith("/static/"):
            rel_disk_path = url.replace("/static/", "")
            file_on_disk = repo_root / "src" / "server" / "static" / rel_disk_path
            assert file_on_disk.exists(), f"App shell cached file not found on disk: {file_on_disk}"


def test_service_worker_airgap_domain_guard():
    """
    Verify that the Service Worker contains an active runtime guard
    that intercepts and rejects external origin requests.
    """
    repo_root = Path(__file__).resolve().parent.parent
    sw_file = repo_root / "src" / "server" / "static" / "mobile" / "sw.js"
    content = sw_file.read_text(encoding="utf-8")

    # Verifies check for external origin
    assert "url.origin !== self.location.origin" in content or "url.origin != self.location.origin" in content, (
        "Service Worker is missing air-gap origin isolation check"
    )
    # Verifies rejection of external requests
    assert "Air-gapped policy violation" in content or "403" in content, (
        "Service Worker does not reject external origin requests with 403 or policy violation"
    )


def test_manifest_offline_readiness():
    """
    Verify that manifest.webmanifest is valid JSON and only references local assets.
    """
    repo_root = Path(__file__).resolve().parent.parent
    manifest_file = repo_root / "src" / "server" / "static" / "mobile" / "manifest.webmanifest"
    assert manifest_file.exists(), "Web App Manifest not found."

    manifest_data = json.loads(manifest_file.read_text(encoding="utf-8"))
    assert manifest_data.get("name"), "Manifest missing name"
    assert manifest_data.get("start_url", "").startswith("/"), "Manifest start_url must be local"

    icons = manifest_data.get("icons", [])
    assert len(icons) > 0, "Manifest has no icons defined"
    for icon in icons:
        src = icon.get("src", "")
        assert src.startswith("/"), f"Manifest icon '{src}' must be local path"
        if src.startswith("/static/"):
            disk_path = repo_root / "src" / "server" / "static" / src.replace("/static/", "")
            assert disk_path.exists(), f"Manifest icon does not exist on disk: {disk_path}"
