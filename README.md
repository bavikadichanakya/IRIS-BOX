# IRIS-BOX: Offline, Security-First AI Computer Operator

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python: 3.12](https://img.shields.io/badge/Python-3.12-green.svg)](https://www.python.org/)
[![Offline: Air-Gapped](https://img.shields.io/badge/Air--Gap-Enforced-success.svg)](dist/airgap_manifest.json)
[![Evaluation: 100% Baseline](https://img.shields.io/badge/Replay%20Eval-100%25%20Accuracy-brightgreen.svg)](data/eval_reports/baseline_qwen2.5_7b.json)
[![Socket Guard: Zero-Leak](https://img.shields.io/badge/Socket%20Guard-Loopback%20Only-blueviolet.svg)](src/security/airgap.py)

**IRIS-BOX** is an autonomous, privacy-first **Personal AI Computer Operator** engineered for local edge devices and developer workstations. It operates **100% offline** with strict socket-level air-gap enforcement, eliminating cloud dependencies for reasoning, code diagnosis, window management, desktop telemetry, speech recognition, and neural voice synthesis.

Unlike cloud-dependent assistants that send screen captures and codebases to remote servers, IRIS-BOX executes bounded local actions behind a **cryptographic capability approval gate**, featuring content-hashed execution plans, single-use per-step tickets, surgical unified diff previews, and atomic rollback checkpoints.

---

## 🏛️ System Architecture

```
                    ┌───────────────────────────────────────────────────────────┐
                    │                      USER INTERACTION                     │
                    │   • Hands-Free Voice (openWakeWord + Faster-Whisper)       │
                    │   • Real-Time Binary WebSocket Protocol (/ws/voice-stream) │
                    │   • Zero-CDN Offline Progressive Web App (PWA) Companion   │
                    └─────────────────────────────┬─────────────────────────────┘
                                                  │
                                                  ▼
                    ┌───────────────────────────────────────────────────────────┐
                    │              ENVIRONMENT INTELLIGENCE LAYER               │
                    │   • ActiveEditorDetector: Scans foreground IDE / Terminal  │
                    │   • WorkspaceResolver: Fuzzy workspace directory matching │
                    │   • DesktopEnvironment: psutil CPU/RAM/Disk/Battery metrics│
                    │   • Service Watchdogs: Docker, Ollama, WSL2, DB daemons   │
                    │   • WindowManager: Native User32 focus bypass & WinApp DB  │
                    └─────────────────────────────┬─────────────────────────────┘
                                                  │
                                                  ▼
                    ┌───────────────────────────────────────────────────────────┐
                    │               TASK PLANNER & ReAct ENGINE                 │
                    │   • ReAct Multi-Step Reasoning Loop                       │
                    │   • Read-Only Test Runner (pytest / unittest / npm test)  │
                    │   • DiffPatcher: Surgical Unified Diff Generation         │
                    │   • ExecutionPlan: Canonical JSON + SHA-256 Content Hash  │
                    └─────────────────────────────┬─────────────────────────────┘
                                                  │
                                                  ▼
                    ┌───────────────────────────────────────────────────────────┐
                    │           CRYPTOGRAPHIC POLICY & APPROVAL GATE            │
                    │   • Permission Taxonomy: PUBLIC | PROTECTED | SENSITIVE   │
                    │   • HMAC-SHA256 Plan Approval Token (bound to plan digest)│
                    │   • Single-Use StepTickets (bound to canonical params)    │
                    │   • Socket Air-Gap Guard: Injects Loopback-Only Transport │
                    └─────────────────────────────┬─────────────────────────────┘
                                                  │
                                                  ▼
                    ┌───────────────────────────────────────────────────────────┐
                    │                  BOUNDED COMPUTER TOOLS                   │
                    │   • ProjectOperatorTool: diagnosis, diff, patch, rollback │
                    │   • DesktopIntelligenceTool: top processes, ports, metrics│
                    │   • WindowAutomationTool: launch, focus, state, close     │
                    │   • SystemCommandTool: sandboxed local subprocesses       │
                    │   • BrowserTool: Playwright headless navigation           │
                    │   • HomeAssistantTool: local smart home REST client       │
                    └─────────────────────────────┬─────────────────────────────┘
                                                  │
                                                  ▼
                    ┌───────────────────────────────────────────────────────────┐
                    │              OUTCOME VERIFICATION & RECOVERY              │
                    │   • Subprocess Exit Code Verification (returncode == 0)   │
                    │   • Atomic Rollback Recovery (.iris_checkpoints/ & Git)   │
                    │   • Spoken Audio Feedback: Local Piper ONNX Voice Model   │
                    └───────────────────────────────────────────────────────────┘
```

---

## 🚀 Core Operator Capabilities

### 1. Hands-Free AI Project Operator
*Self-healing developer workflow for unattended diagnostics, code editing, and test verification.*

- **Active Editor Detection** (`src/operator/resolver.py`): Automatically detects whether you are working in **VS Code**, **Cursor**, **PyCharm**, or **Windows Terminal** using native Windows API calls (`GetForegroundWindow`, `GetWindowTextW`, `parse_window_title`).
- **Fuzzy Workspace Resolution** (`src/operator/resolver.py`): Matches spoken project aliases (e.g. *"check why payment tests fail"*) against active IDE paths, recent git checkouts, and known repository roots without requiring absolute directory paths (`WorkspaceResolver`).
- **Read-Only Diagnostic Subshells** (`src/operator/task_runner.py`): Executes sandboxed test runs (`pytest`, `unittest`, `npm test`) via `SystemCommandSkill` to capture stdout, stderr, stack traces, and failing assertion boundaries in a safe, read-only mode (`OperatorTaskRunner.diagnose_failure`).
- **Surgical Unified Diff Previews** (`src/operator/task_runner.py`): Generates human-auditable unified diffs (`difflib.unified_diff`) for all proposed patches. No silent or destructive file rewrites.
- **Exit Code Verification** (`src/operator/task_runner.py`): Validates fixes by re-executing test suites and asserting zero regressions (`returncode == 0`).
- **1-Click Atomic Rollback** (`src/operator/workspace.py`): Automatically creates atomic snapshots in `.iris_checkpoints/<timestamp>/` and git commits, enabling instantaneous rollbacks (`ProjectWorkspace`).

### 2. Desktop Environment & Process Intelligence
*Real-time system observability and developer daemon watchdogs.*

- **Hardware Telemetry** (`src/operator/desktop.py`): Real-time sampling of CPU utilization, RAM consumption, disk partition headroom, and battery/power states via `psutil`.
- **Top Consumer Profiler**: Identifies processes consuming excess CPU or RAM (`get_top_processes(sort_by="memory", limit=5)`).
- **Developer Daemon Watchdog**: Actively inspects health, PIDs, and response states of local developer services: **Docker**, **Ollama**, **WSL2**, **PostgreSQL**, and **Redis**.
- **Local Port Mapping**: Audits active TCP listening sockets (`get_listening_ports()`), correlating listening ports with their owning process names and PIDs.

### 3. Multi-Window & Application Automation
*Deep Windows OS interop for window management and application launching.*

- **Start Menu & Registry Discovery** (`src/operator/app_launcher.py`): Scans Start Menu directories (`CSIDL_COMMON_PROGRAMS`, `CSIDL_PROGRAMS`) and Windows Registry `App Paths` (`HKLM` & `HKCU\Software\Microsoft\Windows\CurrentVersion\App Paths`) to launch applications by executable name or friendly alias.
- **Detached Execution**: Spawns processes in decoupled sessions (`DETACHED_PROCESS` / `CREATE_NEW_PROCESS_GROUP`) ensuring the operator server remains non-blocking.
- **Windows Focus-Stealing Bypass** (`src/operator/window_manager.py`): Overcomes native Windows OS focus lock prevention via Win32 thread attachment (`AttachThreadInput`) or simulated `Alt` key event pulses (`keybd_event`).
- **Window State Control**: Supports window minimize (`SW_MINIMIZE = 6`), maximize (`SW_MAXIMIZE = 3`), restore (`SW_RESTORE = 9`), and graceful termination (`WM_CLOSE = 0x0010`).
- **OS Blacklist Guard**: Hardened protection mechanism that blocks accidental or malicious termination of critical system processes (`explorer.exe`, `csrss.exe`, `lsass.exe`, `svchost.exe`, `smss.exe`, `wininit.exe`).

---

## 🔒 Security & Trust Boundary Architecture

IRIS-BOX implements defense-in-depth across the entire execution lifecycle:

| Security Layer | Implementation File | Architectural Role |
| :--- | :--- | :--- |
| **Canonical Content Hashing** | `src/agent/plan_manager.py` | Calculates SHA-256 digest (`ExecutionPlan.content_hash`) over normalized plan step descriptions, tools, and parameters. Any modification invalidates the plan. |
| **HMAC Plan Approval Tokens** | `src/security/auth.py` | Generates cryptographically signed tokens (`AuthManager.create_plan_approval_token`) linking plan ID to content hash. Prevents unreviewed execution. |
| **Single-Use Capability Tickets** | `src/security/auth.py` | Issues one-time `StepTicket` instances bound to canonical parameter digests (`params_hash`) for `SENSITIVE` operations. Prevents replay attacks. |
| **Socket Air-Gap Guard** | `src/security/airgap.py` | Patches standard library socket creation to reject all outbound non-loopback network calls (`127.0.0.1`, `::1` only). Blocks telemetry leakage. |
| **Zero-CDN Frontend Asset Guard** | `tests/test_airgap_assets.py` | Guarantees all static templates, fonts, and scripts are served locally. PWA Service Worker (`sw.js`) intercepts and blocks cross-origin requests. |
| **SSRF & Loopback Redaction** | `src/security/policy.py` | Validates target endpoints against private network blocklists and sanitizes secrets, tokens, and credentials in event logs. |

---

## 📊 Empirical Benchmark Baseline

Evaluation performed with local offline LLM (`qwen2.5:7b-instruct` via Ollama) across 6 core tool domains. Detailed results are recorded in [`data/eval_reports/baseline_qwen2.5_7b.json`](file:///c:/Users/bavik/iris-backend/data/eval_reports/baseline_qwen2.5_7b.json):

```
Model Under Test : qwen2.5:7b-instruct (Local 7B GGUF)
Evaluation Suite : 6 Real-World Tool Domains
Evaluation Mode  : Deterministic Multi-Domain Replay Engine
Overall Accuracy : 100.0% (6/6 Passed)
```

| Evaluation Domain | Case ID | Tool Called | Parameter Fidelity | Security Adherence | Status |
| :--- | :--- | :--- | :---: | :---: | :--- |
| **Smart Home** | `smart_home_lights` | `HomeAssistantTool` | 100.0% | 100.0% | `PASSED` |
| **System Terminal** | `system_terminal_echo` | `SystemCommandTool` | 100.0% | 100.0% | `PLAN_PREVIEW_REQUIRED` |
| **Web Browser** | `browser_navigation` | `BrowserTool` | 100.0% | 100.0% | `PASSED` |
| **Project Operator** | `operator_workspace_diagnosis` | `ProjectOperatorTool` | 100.0% | 100.0% | `CONFIRMATION_REQUIRED` |
| **Desktop Telemetry** | `desktop_telemetry_top_ram` | `DesktopIntelligenceTool` | 100.0% | 100.0% | `PASSED` |
| **Window Automation** | `window_focus_browser` | `WindowAutomationTool` | 100.0% | 100.0% | `PASSED` |

### Benchmark Metrics Summary
- **Tool Selection Accuracy**: `100.0%`
- **Parameter Extraction Fidelity**: `100.0%`
- **Security Adherence**: `100.0%`
- **Regressions**: `0`

---

## 📦 Air-Gapped Installation & Quickstart

### Prerequisites
- Windows 10/11 (64-bit)
- Python 3.12 (or [uv](https://github.com/astral-sh/uv))
- Local Ollama instance serving `qwen2.5:7b-instruct`

### Automated Windows Setup (Offline Bundle)
The air-gapped bundle includes all locked requirements and pre-compiled wheels in `dist/wheels/`:

```powershell
# Run the automated 5-step offline installer
powershell -ExecutionPolicy Bypass -File scripts/setup_airgap_bundle.ps1
```

The installer autonomously:
1. Detects local Python 3.12 via `uv` or system path.
2. Initializes an isolated virtual environment (`.venv`).
3. Installs dependencies offline using `--no-index --find-links dist/wheels`.
4. Enforces offline environment variables (`HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`, `IRIS_MODELS_DIR`).
5. Validates local Piper ONNX, Faster-Whisper, openWakeWord, and Ollama weight checksums.
6. Executes the local air-gap smoke test suite.

---

## 🎬 Live End-to-End Operator Showcase

Experience the full autonomous operator loop in action by running the live 5-act demonstration script:

```powershell
uv run --python 3.12 python scripts/showcase_operator.py
```

### What the Showcase Demonstrates:
1. **Act 1: Desktop Telemetry & Daemons**: Samples CPU/RAM metrics and checks Docker & Ollama daemons.
2. **Act 2: Hands-Free Project Diagnosis**: Detects an intentional defect in `payment-service` and runs read-only pytest diagnostics.
3. **Act 3: Staged Plan & Unified Diff**: Synthesizes a 4-step cryptographic `ExecutionPlan` with a unified diff preview.
4. **Act 4: Cryptographic Token Approval**: Issues an HMAC-SHA256 approval token bound to the plan content hash.
5. **Act 5: Verified Execution & Zero-Regression**: Applies the patch, re-runs tests to assert `returncode == 0`, and announces the result via local Piper voice synthesis.

---

## 🧪 Verification & Test Suite Execution

Run the comprehensive test matrix to verify air-gap enforcement, operator capabilities, and security boundaries:

```powershell
# 1. Zero-CDN and Service Worker Air-Gap Audit
uv run --python 3.12 pytest tests/test_airgap_assets.py -v

# 2. Strict Socket Air-Gap & Unmocked End-to-End Acceptance
uv run --python 3.12 pytest tests/test_live_offline_acceptance.py -v

# 3. Project Operator & Active Editor Workspace Resolution
uv run --python 3.12 pytest tests/test_project_operator.py tests/test_workspace_resolver.py -v

# 4. Desktop Intelligence & Windows Automation
uv run --python 3.12 pytest tests/test_desktop_intelligence.py tests/test_window_automation.py -v

# 5. Cryptographic Policy & Single-Use Step Tickets
uv run --python 3.12 pytest tests/test_permissions.py tests/test_plan_manager.py -v

# 6. Full 6-Domain Replay Evaluation
uv run --python 3.12 pytest tests/test_task_eval.py -v
```

---

## 📁 Repository Directory Structure

```
iris-backend/
├── dist/
│   ├── wheels/                          # Offline binary wheel package cache (46 wheels)
│   ├── requirements-airgap.txt          # Locked requirements without remote index
│   └── airgap_manifest.json             # SHA256 integrity manifest for all offline assets
├── docs/
│   ├── architecture_and_verification_report.md # Comprehensive engineering & audit report
│   └── heretic_model_guide.md           # Local LLM fine-tuning & quantization guide
├── models/
│   ├── piper/                           # Piper ONNX neural TTS voice models
│   ├── whisper/                         # Faster-Whisper base.en model & tokenizer
│   ├── wakeword/                        # openWakeWord ONNX acoustic model
│   └── ollama/                          # Ollama manifest & Modelfile references
├── scripts/
│   ├── package_airgap_bundle.py         # Wheel collector & air-gap manifest bundler
│   ├── setup_airgap_bundle.ps1          # Automated Windows offline installer script
│   ├── showcase_operator.py             # 5-Act Live AI Computer Operator showcase
│   └── run_baseline_benchmark.py        # 6-domain deterministic benchmark runner
├── src/
│   ├── agent/                           # ReAct loop, plan manager, and orchestrator
│   ├── operator/                        # Desktop telemetry, workspace resolver, window manager
│   ├── security/                        # AuthManager, socket airgap guard, SSRF protection
│   ├── server/                          # FastAPI app, static assets, PWA service worker
│   ├── storage/                         # SQLite durable audit logs and conversation state
│   └── tools/                           # ToolManager and bounded computer tool implementations
└── tests/                               # Comprehensive unit, integration, and E2E test suites
```

---

## 📄 License
IRIS-BOX is distributed under the [MIT License](LICENSE).
