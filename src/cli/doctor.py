import os
import sys
import json
import time
import shutil
import sqlite3
import urllib.request
import urllib.error
import subprocess
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from dotenv import load_dotenv

load_dotenv()


@dataclass
class CheckResult:
    name: str
    category: str
    phase: str  # "INSTALLED", "LOADED", "TESTED"
    status: str  # "PASS", "WARN", "FAIL"
    message: str
    details: Dict[str, Any] = field(default_factory=dict)
    resolution: Optional[str] = None
    is_fatal: bool = True


class SystemDoctor:
    """
    Verified Offline Setup Doctor & Diagnostics Engine for IRIS-BOX.
    Audits local models, binaries, storage, security, and hardware with zero remote cloud dependency.
    """

    def __init__(self, root_dir: Optional[str] = None):
        self.root_dir = root_dir or os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

    def check_local_llm(self) -> CheckResult:
        """1. Local LLM: Queries loopback endpoint, Ollama tags, and model presence."""
        base_url = (
            os.getenv("IRIS_LLM_BASE_URL")
            or os.getenv("OPENAI_API_BASE")
            or "http://localhost:11434"
        ).rstrip("/")

        # Normalize loopback URL
        if not (base_url.startswith("http://127.0.0.1") or base_url.startswith("http://localhost")):
            return CheckResult(
                name="Local LLM Endpoint",
                category="Inference",
                phase="INSTALLED",
                status="FAIL",
                message=f"Configured LLM endpoint '{base_url}' is not a local loopback address.",
                resolution="Set IRIS_LLM_BASE_URL to 'http://localhost:11434/v1' for strict offline operation.",
                is_fatal=True,
            )

        target_model = os.getenv("IRIS_LLM_MODEL") or os.getenv("OPENAI_MODEL") or "qwen2.5:7b-instruct"
        tags_url = f"{base_url}/api/tags" if not base_url.endswith("/v1") else base_url.replace("/v1", "/api/tags")

        try:
            req = urllib.request.Request(tags_url, headers={"User-Agent": "IRIS-Doctor/1.0"})
            with urllib.request.urlopen(req, timeout=3.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                models = [m.get("name", "") for m in data.get("models", [])]

                has_target = any(target_model in m for m in models)
                if has_target:
                    return CheckResult(
                        name="Local LLM (Ollama)",
                        category="Inference",
                        phase="TESTED",
                        status="PASS",
                        message=f"Endpoint responding at {base_url}; target model '{target_model}' verified.",
                        details={"endpoint": base_url, "target_model": target_model, "installed_models": models},
                        is_fatal=True,
                    )
                else:
                    return CheckResult(
                        name="Local LLM (Ollama)",
                        category="Inference",
                        phase="LOADED",
                        status="WARN",
                        message=f"Ollama running at {base_url}, but target model '{target_model}' not found.",
                        details={"installed_models": models, "target_model": target_model},
                        resolution=f"Run 'ollama pull {target_model}' to install required model weights.",
                        is_fatal=False,
                    )
        except Exception as exc:
            return CheckResult(
                name="Local LLM (Ollama)",
                category="Inference",
                phase="INSTALLED",
                status="FAIL",
                message=f"Could not connect to local LLM endpoint at {base_url}: {exc}",
                details={"endpoint": base_url, "error": str(exc)},
                resolution="Ensure Ollama is running locally: run 'ollama serve' in your terminal.",
                is_fatal=True,
            )

    def check_wake_word(self) -> CheckResult:
        """2. Wake-Word: Checks file existence, size, and test-loads ONNX runtime session."""
        candidates = [
            os.path.join(self.root_dir, "models", "wakeword", "hey_iris.onnx"),
            os.path.join(self.root_dir, "src", "audio", "models", "hey_iris.onnx"),
        ]

        model_path = next((p for p in candidates if os.path.exists(p)), None)
        if not model_path:
            return CheckResult(
                name="Wake-Word Engine (hey_iris.onnx)",
                category="Audio",
                phase="INSTALLED",
                status="FAIL",
                message="Wake-word model not found at 'models/wakeword/hey_iris.onnx'.",
                resolution="Place the trained 'hey_iris.onnx' file in 'models/wakeword/hey_iris.onnx'.",
                is_fatal=True,
            )

        size_bytes = os.path.getsize(model_path)
        if size_bytes < 10000:
            return CheckResult(
                name="Wake-Word Engine (hey_iris.onnx)",
                category="Audio",
                phase="INSTALLED",
                status="FAIL",
                message=f"Wake-word model file is suspiciously small ({size_bytes} bytes).",
                resolution="Download complete 'hey_iris.onnx' weights.",
                is_fatal=True,
            )

        try:
            import onnxruntime as ort
            start = time.perf_counter()
            sess = ort.InferenceSession(model_path)
            elapsed_ms = round((time.perf_counter() - start) * 1000.0, 2)
            inputs = [i.name for i in sess.get_inputs()]
            outputs = [o.name for o in sess.get_outputs()]

            return CheckResult(
                name="Wake-Word Engine (hey_iris.onnx)",
                category="Audio",
                phase="TESTED",
                status="PASS",
                message=f"Model loaded and verified via ONNX Runtime in {elapsed_ms}ms ({round(size_bytes / 1024, 1)} KB).",
                details={"path": model_path, "size_bytes": size_bytes, "inputs": inputs, "outputs": outputs, "load_time_ms": elapsed_ms},
                is_fatal=True,
            )
        except Exception as exc:
            return CheckResult(
                name="Wake-Word Engine (hey_iris.onnx)",
                category="Audio",
                phase="LOADED",
                status="WARN",
                message=f"ONNX session load failed: {exc}",
                resolution="Ensure onnxruntime is installed and 'hey_iris.onnx' is an uncorrupted ONNX model.",
                is_fatal=False,
            )

    def check_stt_weights(self) -> CheckResult:
        """3. STT Weights: Verifies faster-whisper local model weights in cache / models/whisper."""
        hf_cache_dir = os.path.expanduser("~/.cache/huggingface/hub")
        whisper_cache_candidates = [
            os.path.join(self.root_dir, "models", "whisper"),
            os.path.join(hf_cache_dir, "models--Systran--faster-whisper-base"),
            os.path.join(hf_cache_dir, "models--Systran--faster-whisper-tiny"),
            os.path.join(hf_cache_dir, "models--Systran--faster-whisper-small"),
        ]

        found_path = next((p for p in whisper_cache_candidates if os.path.exists(p)), None)
        if found_path:
            # Check faster-whisper package
            try:
                import faster_whisper
                version = getattr(faster_whisper, "__version__", "installed")
                return CheckResult(
                    name="Faster-Whisper STT",
                    category="Audio",
                    phase="LOADED",
                    status="PASS",
                    message=f"faster-whisper (v{version}) local weights located at {found_path}.",
                    details={"path": found_path, "version": version},
                    is_fatal=True,
                )
            except ImportError:
                return CheckResult(
                    name="Faster-Whisper STT",
                    category="Audio",
                    phase="INSTALLED",
                    status="WARN",
                    message=f"Model weights found at {found_path}, but 'faster-whisper' package is not installed.",
                    resolution="Run 'pip install faster-whisper' to enable offline speech-to-text.",
                    is_fatal=False,
                )
        else:
            return CheckResult(
                name="Faster-Whisper STT",
                category="Audio",
                phase="INSTALLED",
                status="WARN",
                message="No cached faster-whisper model weights found in '~/.cache/huggingface/hub' or 'models/whisper'.",
                resolution="Model weights will automatically download on first run, or download manually to 'models/whisper'.",
                is_fatal=False,
            )

    def check_tts_engine(self) -> CheckResult:
        """4. TTS Engine: Checks piper.exe, test synthesizes in-memory, and verifies binary WAV header."""
        piper_candidates = [
            os.path.join(self.root_dir, "models", "piper", "piper.exe"),
            os.path.join(self.root_dir, "models", "piper", "piper"),
            shutil.which("piper"),
            shutil.which("piper.exe"),
            os.environ.get("PIPER_PATH"),
        ]
        piper_bin = next((p for p in piper_candidates if p and os.path.exists(p)), None)

        model_candidates = [
            os.path.join(self.root_dir, "models", "piper", "en_US-lessac-medium.onnx"),
            os.path.join(self.root_dir, "models", "en_US-lessac-medium.onnx"),
            os.environ.get("PIPER_MODEL_PATH"),
        ]
        model_path = next((m for m in model_candidates if m and os.path.exists(m)), None)

        if not piper_bin or not model_path:
            return CheckResult(
                name="Piper Offline TTS",
                category="Audio",
                phase="INSTALLED",
                status="FAIL",
                message=f"Piper binary ({piper_bin or 'missing'}) or voice model ({model_path or 'missing'}) not found.",
                resolution="Ensure 'models/piper/piper.exe' and 'models/piper/en_US-lessac-medium.onnx' are present.",
                is_fatal=True,
            )

        # Test synthesis in-memory
        try:
            start = time.perf_counter()
            proc = subprocess.run(
                [piper_bin, "--model", model_path, "--output_file", "-"],
                input=b"IRIS doctor audio verification test.",
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=5.0,
            )
            elapsed_ms = round((time.perf_counter() - start) * 1000.0, 2)

            if proc.returncode != 0:
                err_text = proc.stderr.decode("utf-8", errors="ignore")[:200]
                return CheckResult(
                    name="Piper Offline TTS",
                    category="Audio",
                    phase="LOADED",
                    status="FAIL",
                    message=f"Synthesis failed with code {proc.returncode}: {err_text}",
                    resolution="Verify piper dependencies (espeak-ng.dll and onnxruntime.dll).",
                    is_fatal=True,
                )

            wav_data = proc.stdout
            if len(wav_data) < 44 or not (wav_data[:4] == b"RIFF" and wav_data[8:12] == b"WAVE"):
                return CheckResult(
                    name="Piper Offline TTS",
                    category="Audio",
                    phase="LOADED",
                    status="FAIL",
                    message="Synthesized audio stream missing valid RIFF/WAVE header.",
                    resolution="Check Piper audio export pipeline.",
                    is_fatal=True,
                )

            return CheckResult(
                name="Piper Offline TTS",
                category="Audio",
                phase="TESTED",
                status="PASS",
                message=f"Offline synthesis verified in {elapsed_ms}ms ({len(wav_data)} bytes WAV header validated).",
                details={"piper_bin": piper_bin, "model_path": model_path, "wav_bytes": len(wav_data), "latency_ms": elapsed_ms},
                is_fatal=True,
            )
        except Exception as exc:
            return CheckResult(
                name="Piper Offline TTS",
                category="Audio",
                phase="LOADED",
                status="FAIL",
                message=f"Test synthesis execution error: {exc}",
                resolution="Ensure piper binary has execute permissions and required runtime libraries.",
                is_fatal=True,
            )

    def check_sqlite_storage(self) -> CheckResult:
        """5. SQLite Storage: Checks iris.db read/write, schema migrations, and session persistence."""
        db_path = os.getenv("DATABASE_URL", "iris.db")
        if not os.path.isabs(db_path):
            db_path = os.path.join(self.root_dir, db_path)

        try:
            conn = sqlite3.connect(db_path, timeout=5.0)
            cursor = conn.cursor()

            # Verify tables
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
            tables = {row[0] for row in cursor.fetchall()}

            expected_tables = {"sessions", "user_preferences", "inferred_facts"}
            missing = expected_tables - tables
            if missing:
                conn.close()
                return CheckResult(
                    name="SQLite Storage (iris.db)",
                    category="Storage",
                    phase="LOADED",
                    status="WARN",
                    message=f"Connected to {db_path}, but missing table(s): {', '.join(missing)}.",
                    resolution="Run application server once to apply migrations or initialize database schema.",
                    is_fatal=False,
                )

            # Test write & read
            test_session_id = f"doctor_diag_{int(time.time())}"
            cursor.execute(
                "INSERT OR REPLACE INTO sessions (session_id, device_id, metadata_json) VALUES (?, ?, ?);",
                (test_session_id, "doctor_cli", json.dumps({"test": True})),
            )
            conn.commit()

            cursor.execute("SELECT session_id, metadata_json FROM sessions WHERE session_id = ?;", (test_session_id,))
            row = cursor.fetchone()

            # Cleanup
            cursor.execute("DELETE FROM sessions WHERE session_id = ?;", (test_session_id,))
            conn.commit()
            conn.close()

            if row and row[0] == test_session_id:
                return CheckResult(
                    name="SQLite Storage (iris.db)",
                    category="Storage",
                    phase="TESTED",
                    status="PASS",
                    message=f"Read/write, schema integrity, and session persistence verified ({os.path.basename(db_path)}).",
                    details={"path": db_path, "tables": list(tables)},
                    is_fatal=True,
                )
            else:
                return CheckResult(
                    name="SQLite Storage (iris.db)",
                    category="Storage",
                    phase="LOADED",
                    status="FAIL",
                    message="Session persistence test failed: wrote record but could not read back.",
                    resolution="Check SQLite database permissions and disk health.",
                    is_fatal=True,
                )
        except Exception as exc:
            return CheckResult(
                name="SQLite Storage (iris.db)",
                category="Storage",
                phase="INSTALLED",
                status="FAIL",
                message=f"SQLite check failed: {exc}",
                resolution=f"Ensure '{db_path}' directory is writable.",
                is_fatal=True,
            )

    def check_security_and_permissions(self) -> CheckResult:
        """6. Security & Permissions: Validates IRIS_MASTER_TOKEN, .env exclusion, and loopback socket constraints."""
        issues: List[str] = []
        resolutions: List[str] = []

        # 1. Master Token Check
        token = os.getenv("IRIS_MASTER_TOKEN") or os.getenv("IRIS_API_KEY")
        if not token:
            issues.append("No IRIS_MASTER_TOKEN or IRIS_API_KEY configured in environment.")
            resolutions.append("Set a secure random IRIS_MASTER_TOKEN (>= 16 characters) in .env.")
        elif token.lower() in ("default", "secret", "ollama", "admin", "123456", "password"):
            issues.append(f"Insecure/trivial master token value ('{token}') detected.")
            resolutions.append("Replace weak token with a strong 32+ character random hex token.")
        elif len(token) < 12:
            issues.append(f"Master token is too short ({len(token)} chars).")
            resolutions.append("Use a master token with at least 16 characters of entropy.")

        # 2. .gitignore .env check
        gitignore_path = os.path.join(self.root_dir, ".gitignore")
        if os.path.exists(gitignore_path):
            with open(gitignore_path, "r", encoding="utf-8") as f:
                content = f.read()
                if not any(line.strip() == ".env" or line.strip() == "/.env" for line in content.splitlines()):
                    issues.append(".env file is not explicitly listed in .gitignore.")
                    resolutions.append("Add '.env' to .gitignore to prevent leaking master credentials.")
        else:
            issues.append("Missing .gitignore file.")
            resolutions.append("Create .gitignore and add '.env'.")

        # 3. Offline Cloud Policy check
        allow_cloud = os.getenv("IRIS_ALLOW_CLOUD", "false").lower() in ("true", "1")
        if allow_cloud:
            issues.append("IRIS_ALLOW_CLOUD is enabled (strict offline isolation violated).")
            resolutions.append("Set IRIS_ALLOW_CLOUD=false for pure air-gapped operation.")

        if not issues:
            return CheckResult(
                name="Security & Permissions",
                category="Security",
                phase="TESTED",
                status="PASS",
                message="Master token validated, .env safely ignored in git, and strict offline policy active.",
                details={"offline_only": True, "token_configured": bool(token)},
                is_fatal=True,
            )
        else:
            status = "FAIL" if any("token" in i.lower() for i in issues) else "WARN"
            return CheckResult(
                name="Security & Permissions",
                category="Security",
                phase="LOADED",
                status=status,
                message="; ".join(issues),
                resolution=" | ".join(resolutions),
                is_fatal=True,
            )

    def check_audio_hardware(self) -> CheckResult:
        """7. Audio Hardware: Enumerates host audio input and output devices."""
        try:
            import sounddevice as sd
            devices = sd.query_devices()

            input_devs = [d for d in devices if d.get("max_input_channels", 0) > 0]
            output_devs = [d for d in devices if d.get("max_output_channels", 0) > 0]

            default_in = None
            default_out = None
            try:
                def_in_idx, def_out_idx = sd.default.device
                if def_in_idx >= 0 and def_in_idx < len(devices):
                    default_in = devices[def_in_idx].get("name")
                if def_out_idx >= 0 and def_out_idx < len(devices):
                    default_out = devices[def_out_idx].get("name")
            except Exception:
                pass

            if input_devs and output_devs:
                return CheckResult(
                    name="Host Audio Hardware",
                    category="Hardware",
                    phase="LOADED",
                    status="PASS",
                    message=f"Found {len(input_devs)} input (mic) and {len(output_devs)} output (speaker) devices.",
                    details={
                        "input_count": len(input_devs),
                        "output_count": len(output_devs),
                        "default_input": default_in,
                        "default_output": default_out,
                    },
                    is_fatal=False,
                )
            elif not input_devs:
                return CheckResult(
                    name="Host Audio Hardware",
                    category="Hardware",
                    phase="INSTALLED",
                    status="WARN",
                    message="No microphone input audio devices detected on host.",
                    resolution="Connect a USB or analog microphone.",
                    is_fatal=False,
                )
            else:
                return CheckResult(
                    name="Host Audio Hardware",
                    category="Hardware",
                    phase="INSTALLED",
                    status="WARN",
                    message="No speaker audio output devices detected on host.",
                    resolution="Connect an audio output device or headphones.",
                    is_fatal=False,
                )
        except Exception as exc:
            return CheckResult(
                name="Host Audio Hardware",
                category="Hardware",
                phase="INSTALLED",
                status="WARN",
                message=f"Audio hardware query error: {exc}",
                resolution="Install portaudio / sounddevice and grant audio device access permissions.",
                is_fatal=False,
            )

    def run_all_checks(self) -> List[CheckResult]:
        """Execute all 7 diagnostic checks in order."""
        return [
            self.check_local_llm(),
            self.check_wake_word(),
            self.check_stt_weights(),
            self.check_tts_engine(),
            self.check_sqlite_storage(),
            self.check_security_and_permissions(),
            self.check_audio_hardware(),
        ]

    def generate_report(self, results: List[CheckResult]) -> str:
        """Format an informative, color-coded terminal report with resolution guidance."""
        lines = [
            "================================================================================",
            "                 IRIS-BOX Setup Doctor & Hardware Bring-Up Diagnostics          ",
            "================================================================================",
            f"Environment Root: {self.root_dir}",
            f"Timestamp:        {time.strftime('%Y-%m-%d %H:%M:%S')}",
            "--------------------------------------------------------------------------------",
        ]

        # Safe indicators that render across all Windows cmd/PowerShell codepages
        can_utf8 = sys.stdout.encoding and "utf" in sys.stdout.encoding.lower()
        icons = {
            "PASS": "[✓] PASS" if can_utf8 else "[+] PASS",
            "WARN": "[!] WARN",
            "FAIL": "[✗] FAIL" if can_utf8 else "[X] FAIL",
        }

        for r in results:
            icon = icons.get(r.status, "[?]")
            lines.append(f"{icon:<10} [{r.phase:<9}] {r.name}")
            lines.append(f"             Details: {r.message}")
            if r.status in ("WARN", "FAIL") and r.resolution:
                lines.append(f"             Action:  --> {r.resolution}")
            lines.append("")

        lines.append("--------------------------------------------------------------------------------")

        failures = [r for r in results if r.status == "FAIL"]
        warnings = [r for r in results if r.status == "WARN"]

        pass_icon = "[✓]" if can_utf8 else "[+]"
        fail_icon = "[✗]" if can_utf8 else "[X]"

        if not failures and not warnings:
            lines.append(f"OVERALL STATUS: {pass_icon} ALL SUBSYSTEMS HEALTHY & VERIFIED FOR OFFLINE OPERATION")
        elif not failures:
            lines.append(f"OVERALL STATUS: [!] OPERATIONAL WITH {len(warnings)} WARNING(S) (See suggestions above)")
        else:
            lines.append(f"OVERALL STATUS: {fail_icon} FAILED ({len(failures)} Subsystem Failure(s) require attention)")

        lines.append("================================================================================")
        return "\n".join(lines)


def main() -> int:
    """CLI entrypoint: runs doctor, prints report, and exits with 0 or 1."""
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    doctor = SystemDoctor()
    results = doctor.run_all_checks()
    report = doctor.generate_report(results)
    print(report)

    # Return 1 if any fatal subsystem check failed
    fatal_failures = [r for r in results if r.status == "FAIL" and r.is_fatal]
    return 1 if fatal_failures else 0


if __name__ == "__main__":
    sys.exit(main())
