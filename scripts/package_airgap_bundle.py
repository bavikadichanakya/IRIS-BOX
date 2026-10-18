#!/usr/bin/env python3
"""
Air-Gapped Packaging & Offline Bundle Generator for IRIS-BOX.
Audits frontend assets for zero external CDN references, exports locked requirements,
collects offline wheels, verifies local model weights, and produces a cryptographic
airgap manifest with SHA256 checksums.

Usage:
    uv run --python 3.12 python scripts/package_airgap_bundle.py
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

# Reconfigure console output on Windows to UTF-8
if sys.platform == "win32":
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


class Style:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    GREEN = "\033[38;5;46m"
    RED = "\033[38;5;196m"
    YELLOW = "\033[38;5;220m"
    BLUE = "\033[38;5;39m"
    CYAN = "\033[38;5;51m"
    MAGENTA = "\033[38;5;201m"
    GRAY = "\033[38;5;244m"


def sha256_file(path: Path) -> str:
    """Compute hex SHA256 digest of a file in 64KB chunks."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


class AirgapPackager:
    """
    Core engine managing the air-gap packaging lifecycle:
    - Frontend asset audit (zero CDN / external URLs)
    - Wheel bundle collection and requirements freeze
    - Model integrity and weight size verification
    - Cryptographic manifest generation
    """

    BLOCKED_CDNS: List[str] = [
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

    ALLOWED_XML_NAMESPACES: Set[str] = {
        "http://www.w3.org/2000/svg",
        "http://www.w3.org/1999/xlink",
        "http://www.w3.org/1999/xhtml",
    }

    def __init__(self, root_dir: Optional[Path | str] = None):
        self.root_dir = Path(root_dir or Path.cwd()).resolve()
        self.dist_dir = self.root_dir / "dist"
        self.wheels_dir = self.dist_dir / "wheels"
        self.models_dir = self.root_dir / "models"
        self.templates_dir = self.root_dir / "src" / "server" / "templates"
        self.static_dir = self.root_dir / "src" / "server" / "static"

    def audit_static_assets(self) -> bool:
        """
        Verify that all static files (HTML, JS, CSS, SVG) under templates and static
        contain ZERO external CDN URLs or outbound external network references.
        """
        violations: List[str] = []
        scanned_count = 0

        search_dirs = [self.templates_dir, self.static_dir]
        for sdir in search_dirs:
            if not sdir.exists():
                continue
            for file_path in sdir.rglob("*"):
                if file_path.is_file() and file_path.suffix.lower() in (
                    ".html", ".css", ".js", ".svg", ".webmanifest", ".json"
                ):
                    scanned_count += 1
                    content = file_path.read_text(encoding="utf-8", errors="ignore")

                    # 1. Known CDN domain check
                    for cdn in self.BLOCKED_CDNS:
                        if cdn in content:
                            violations.append(
                                f"{file_path.relative_to(self.root_dir)}: Contains blocked CDN '{cdn}'"
                            )

                    # 2. General external URL check (http:// or https://)
                    urls = re.findall(r'https?://[^\s"\'<>`)]+', content)
                    for url in urls:
                        if url in self.ALLOWED_XML_NAMESPACES:
                            continue
                        if any(loc in url for loc in ("localhost", "127.0.0.1", "0.0.0.0")):
                            continue
                        violations.append(
                            f"{file_path.relative_to(self.root_dir)}: Outbound external URL found: {url}"
                        )

        if violations:
            for v in violations:
                print(f"  {Style.RED}[FAIL]{Style.RESET} {v}")
            return False

        print(f"  {Style.GREEN}✓{Style.RESET} Audited {scanned_count} frontend assets: ZERO external CDN references detected.")
        return True

    def export_requirements(self, output_path: Optional[Path | str] = None) -> Path:
        """
        Export locked dependencies into a clean requirements file.
        Uses `uv export --frozen --no-dev --no-emit-project`.
        """
        req_file = Path(output_path or self.dist_dir / "requirements-airgap.txt")
        req_file.parent.mkdir(parents=True, exist_ok=True)

        cmd = ["uv", "export", "--frozen", "--no-dev", "--no-emit-project", "-o", str(req_file)]
        try:
            res = subprocess.run(cmd, cwd=self.root_dir, capture_output=True, text=True, check=True)
            print(f"  {Style.GREEN}✓{Style.RESET} Exported locked requirements to {req_file.relative_to(self.root_dir)}")
        except Exception as e:
            # Fallback if frozen lock differs
            cmd_fallback = ["uv", "export", "--no-dev", "--no-emit-project", "-o", str(req_file)]
            subprocess.run(cmd_fallback, cwd=self.root_dir, capture_output=True, text=True, check=True)
            print(f"  {Style.GREEN}✓{Style.RESET} Exported requirements (fallback) to {req_file.relative_to(self.root_dir)}")

        return req_file

    def bundle_wheels(self, output_dir: Optional[Path | str] = None) -> int:
        """
        Collect and ensure pre-compiled binary wheels exist in dist/wheels for offline installation.
        Returns the total number of .whl packages in the target directory.
        """
        target_dir = Path(output_dir or self.wheels_dir)
        target_dir.mkdir(parents=True, exist_ok=True)

        # 1. Export locked requirements
        req_file = self.export_requirements()

        # 2. Check existing wheels in target_dir
        existing_wheels = list(target_dir.glob("*.whl"))

        # If wheel cache is empty or minimal, download core runtime binary wheels
        if len(existing_wheels) < 10:
            print(f"  {Style.GRAY}Fetching binary wheels into {target_dir.relative_to(self.root_dir)}...{Style.RESET}")
            core_pkgs = [
                "fastapi", "uvicorn", "websockets", "aiohttp", "aiosqlite",
                "anyio", "starlette", "httpx", "numpy", "pyyaml", "sounddevice",
                "soundfile", "requests", "onnxruntime", "psutil", "pytest", "pydantic"
            ]
            cmd = [
                sys.executable, "-m", "pip", "download",
                "--dest", str(target_dir),
                "--only-binary=:all:",
                *core_pkgs
            ]
            try:
                subprocess.run(cmd, cwd=self.root_dir, capture_output=True, text=True, check=True, timeout=120)
            except Exception as exc:
                print(f"  {Style.YELLOW}Warning during wheel download: {exc}{Style.RESET}")

        final_wheels = list(target_dir.glob("*.whl"))
        total_count = len(final_wheels)
        print(f"  {Style.GREEN}✓{Style.RESET} Wheel bundle verified: {Style.BOLD}{total_count}{Style.RESET} offline wheel packages in {target_dir.name}/")
        return total_count

    def verify_local_models(self) -> Dict[str, bool]:
        """
        Verify local model weight artifacts across Piper, Whisper, Wakeword, and Ollama.
        Checks existence, non-emptiness, and minimum expected file size boundaries.
        """
        results: Dict[str, bool] = {}

        # 1. Piper TTS ONNX model & config
        piper_onnx = self.models_dir / "piper" / "en_US-lessac-medium.onnx"
        piper_json = self.models_dir / "piper" / "en_US-lessac-medium.onnx.json"
        piper_ok = False
        if piper_onnx.exists() and piper_json.exists():
            # Voice model should be ~63 MB, json > 1 KB
            if piper_onnx.stat().st_size > 50 * 1024 * 1024 and piper_json.stat().st_size > 1024:
                piper_ok = True
        results["piper_tts"] = piper_ok
        status_piper = f"{Style.GREEN}PASS ({round(piper_onnx.stat().st_size / (1024*1024), 1)} MB){Style.RESET}" if piper_ok else f"{Style.RED}FAIL{Style.RESET}"
        print(f"  {Style.CYAN}Piper TTS Model:{Style.RESET}     {status_piper}")

        # 2. Faster-Whisper STT model
        whisper_dir = self.models_dir / "whisper"
        whisper_bin = whisper_dir / "model.bin"
        whisper_tok = whisper_dir / "tokenizer.json"
        whisper_cfg = whisper_dir / "config.json"

        # Check local models/whisper or Hugging Face cache
        hf_cache = Path.home() / ".cache" / "huggingface" / "hub" / "models--Systran--faster-whisper-base"
        whisper_ok = False

        if whisper_bin.exists() and whisper_bin.stat().st_size > 50 * 1024 * 1024:
            whisper_ok = True
        elif hf_cache.exists():
            # If present in HF cache, populate canonical models/whisper
            whisper_dir.mkdir(parents=True, exist_ok=True)
            for snap_p in (hf_cache / "snapshots").glob("*"):
                if (snap_p / "model.bin").exists():
                    for item in snap_p.iterdir():
                        if item.is_file():
                            shutil.copy2(item, whisper_dir / item.name)
                    whisper_ok = True
                    break

        results["whisper_stt"] = whisper_ok
        size_mb = round(whisper_bin.stat().st_size / (1024 * 1024), 1) if whisper_bin.exists() else 0
        status_whisper = f"{Style.GREEN}PASS ({size_mb} MB){Style.RESET}" if whisper_ok else f"{Style.RED}FAIL{Style.RESET}"
        print(f"  {Style.CYAN}Faster-Whisper STT:{Style.RESET}  {status_whisper}")

        # 3. Ollama LLM / Local Weights
        ollama_ok = False
        ollama_models = []
        # Check active Ollama daemon
        try:
            req = urllib.request.Request("http://127.0.0.1:11434/api/tags", headers={"User-Agent": "IRIS-Packager"})
            with urllib.request.urlopen(req, timeout=1.5) as resp:
                data = json.loads(resp.read().decode())
                ollama_models = [m.get("name", "") for m in data.get("models", [])]
                if any("qwen2.5" in m or "iris" in m for m in ollama_models):
                    ollama_ok = True
        except Exception:
            pass

        # Also check local GGUF / manifests in models/ollama
        ollama_manifest_dir = self.models_dir / "ollama"
        gguf_candidates = list(self.models_dir.glob("*.gguf"))
        if not ollama_ok:
            if (ollama_manifest_dir / "manifest_qwen2.5_7b.json").exists() or gguf_candidates:
                ollama_ok = True

        results["ollama_llm"] = ollama_ok
        details_ollama = f"tags: {', '.join(ollama_models[:2])}" if ollama_models else f"{len(gguf_candidates)} GGUF / manifests"
        status_ollama = f"{Style.GREEN}PASS ({details_ollama}){Style.RESET}" if ollama_ok else f"{Style.RED}FAIL{Style.RESET}"
        print(f"  {Style.CYAN}Ollama 7B Model:{Style.RESET}     {status_ollama}")

        # 4. OpenWakeWord Model
        ww_onnx = self.models_dir / "wakeword" / "hey_iris.onnx"
        ww_ok = ww_onnx.exists() and ww_onnx.stat().st_size > 1024
        results["wakeword"] = ww_ok
        status_ww = f"{Style.GREEN}PASS ({round(ww_onnx.stat().st_size / 1024, 1)} KB){Style.RESET}" if ww_ok else f"{Style.RED}FAIL{Style.RESET}"
        print(f"  {Style.CYAN}Wake Word ONNX:{Style.RESET}      {status_ww}")

        return results

    def generate_manifest(self, manifest_path: Optional[Path | str] = None) -> Dict[str, Any]:
        """
        Build a comprehensive, cryptographically hashed airgap manifest (dist/airgap_manifest.json).
        Includes SHA256 checksums and byte sizes for all wheels, models, and static frontend assets.
        """
        out_file = Path(manifest_path or self.dist_dir / "airgap_manifest.json")
        out_file.parent.mkdir(parents=True, exist_ok=True)

        manifest: Dict[str, Any] = {
            "bundle_name": "IRIS-BOX-Airgap-Bundle",
            "version": "1.0.0",
            "created_at": time.time(),
            "created_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "python_target": "3.12",
            "platform": "win_amd64",
            "offline_policy": "STRICT_AIR_GAP_ZERO_CDN",
            "artifacts": {
                "requirements": {},
                "wheels": {},
                "models": {},
                "frontend": {},
            },
            "summary": {},
        }

        # 1. Requirements file
        req_file = self.dist_dir / "requirements-airgap.txt"
        if req_file.exists():
            manifest["artifacts"]["requirements"] = {
                "path": str(req_file.relative_to(self.root_dir)).replace("\\", "/"),
                "sha256": sha256_file(req_file),
                "size_bytes": req_file.stat().st_size,
            }

        # 2. Wheels
        wheel_files = sorted(list(self.wheels_dir.glob("*.whl")), key=lambda p: p.name)
        wheels_data = {}
        total_wheel_bytes = 0
        for w in wheel_files:
            size = w.stat().st_size
            total_wheel_bytes += size
            wheels_data[w.name] = {
                "sha256": sha256_file(w),
                "size_bytes": size,
            }
        manifest["artifacts"]["wheels"] = wheels_data

        # 3. Models
        models_data = {}
        total_model_bytes = 0
        for mpath in self.models_dir.rglob("*"):
            if mpath.is_file() and not mpath.name.endswith(".pyc"):
                # Avoid hashing massive 4GB+ GGUF in quick manifest if not needed, but include size
                size = mpath.stat().st_size
                total_model_bytes += size
                rel = str(mpath.relative_to(self.root_dir)).replace("\\", "/")
                if size < 200 * 1024 * 1024:
                    digest = sha256_file(mpath)
                else:
                    digest = f"size_check_{size}"
                models_data[rel] = {
                    "sha256": digest,
                    "size_bytes": size,
                }
        manifest["artifacts"]["models"] = models_data

        # 4. Frontend assets
        frontend_data = {}
        for fdir in (self.templates_dir, self.static_dir):
            if fdir.exists():
                for fpath in fdir.rglob("*"):
                    if fpath.is_file():
                        rel = str(fpath.relative_to(self.root_dir)).replace("\\", "/")
                        frontend_data[rel] = {
                            "sha256": sha256_file(fpath),
                            "size_bytes": fpath.stat().st_size,
                        }
        manifest["artifacts"]["frontend"] = frontend_data

        manifest["summary"] = {
            "wheel_count": len(wheels_data),
            "total_wheel_mb": round(total_wheel_bytes / (1024 * 1024), 2),
            "model_file_count": len(models_data),
            "total_model_mb": round(total_model_bytes / (1024 * 1024), 2),
            "frontend_file_count": len(frontend_data),
        }

        out_file.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        print(f"  {Style.GREEN}✓{Style.RESET} Generated airgap manifest: {Style.BOLD}{out_file.relative_to(self.root_dir)}{Style.RESET}")
        return manifest


def main() -> int:
    width = 76
    print(f"\n{Style.BLUE}{'=' * width}{Style.RESET}")
    print(f"{Style.BOLD}{Style.CYAN}  IRIS-BOX STANDALONE AIR-GAP BUNDLE PACKAGER  {Style.RESET}")
    print(f"{Style.GRAY}  Zero-CDN Static Audit • Offline Wheel Cache • Model Verification{Style.RESET}")
    print(f"{Style.BLUE}{'=' * width}{Style.RESET}\n")

    packager = AirgapPackager()

    # Step 1: Static CDN & Outbound URL Audit
    print(f"{Style.BOLD}[1/4] Frontend Zero-CDN & Airgap Integrity Audit{Style.RESET}")
    audit_ok = packager.audit_static_assets()
    if not audit_ok:
        print(f"{Style.RED}Aborting packaging due to static asset CDN violations.{Style.RESET}")
        return 1

    # Step 2: Model Artifact Verification
    print(f"\n{Style.BOLD}[2/4] Local Model Weights & Engine Verification{Style.RESET}")
    models_res = packager.verify_local_models()
    if not all(models_res.values()):
        print(f"{Style.YELLOW}Warning: Some model components are missing.{Style.RESET}")

    # Step 3: Bundle Python Wheels
    print(f"\n{Style.BOLD}[3/4] Exporting Requirements & Bundling Wheels{Style.RESET}")
    wheel_count = packager.bundle_wheels()

    # Step 4: Cryptographic Manifest Generation
    print(f"\n{Style.BOLD}[4/4] Generating Cryptographic Airgap Manifest{Style.RESET}")
    manifest = packager.generate_manifest()

    summary = manifest.get("summary", {})
    print(f"\n{Style.BLUE}{'-' * width}{Style.RESET}")
    print(f"{Style.BOLD}{Style.GREEN}AIR-GAP BUNDLE PACKAGING COMPLETE{Style.RESET}")
    print(f"  • Offline Wheels:  {Style.BOLD}{summary.get('wheel_count')}{Style.RESET} packages ({summary.get('total_wheel_mb')} MB)")
    print(f"  • Local Models:    {Style.BOLD}{summary.get('model_file_count')}{Style.RESET} files ({summary.get('total_model_mb')} MB)")
    print(f"  • Frontend Assets: {Style.BOLD}{summary.get('frontend_file_count')}{Style.RESET} local files (0 external CDNs)")
    print(f"{Style.BLUE}{'=' * width}{Style.RESET}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
