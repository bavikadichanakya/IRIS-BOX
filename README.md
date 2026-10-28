# IRIS-BOX: Offline, Voice-Controlled AI Computer Operator & Smart Workstation Assistant

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python: 3.12](https://img.shields.io/badge/Python-3.12-green.svg)](https://www.python.org/)
[![Offline: Air-Gapped](https://img.shields.io/badge/Air--Gap-Enforced-success.svg)](dist/airgap_manifest.json)
[![Primary Operator Model: IRIS-Qwen3-4B-Operator](https://img.shields.io/badge/Primary%20Model-IRIS--Qwen3--4B--Operator-blueviolet.svg)](models/Modelfile.iris_qwen3_4b_operator)
[![Validation Benchmark Gate: 100%](https://img.shields.io/badge/Validation%20Gate-100%25%20Passed-brightgreen.svg)](scripts/train_iris_uncensored_master.ipynb)
[![Socket Guard: Zero-Leak](https://img.shields.io/badge/Socket%20Guard-Loopback%20Only-blueviolet.svg)](src/security/airgap.py)

**IRIS-BOX** is an autonomous, privacy-first, Alexa-style **Voice-Controlled AI Computer Operator** built for multi-device workstation automation, local edge hardware, and developer productivity. It operates **100% offline** with zero cloud dependencies for reasoning, application manipulation, desktop telemetry, speech recognition, and neural voice synthesis.

Unlike conventional cloud assistants that send screen captures, audio logs, and sensitive project code to remote cloud vendors, IRIS-BOX executes bounded local actions across one or more laptops (`laptop1`, `laptop2`) using **Universal Computer Operator Primitives** behind a **cryptographic capability approval gate**.

---

## 🏛️ Physical Hardware & Multi-Device Architecture

IRIS-BOX is physically realized as a dual-phone smart hub paired with one or more workstation laptops:

```
┌─────────────────────────────────┐                 ┌─────────────────────────────────┐
│   Phone B: Senses & Voice I/O   │                 │     Phone A: The System Brain   │
│  • Array Microphones & Speaker  │ ──Local Stream─►│  • IRIS-Qwen3-4B-Operator GGUF  │
│  • openWakeWord Detection       │                 │  • Termux llama.cpp / llama-srv │
│  • Faster-Whisper Speech-to-Text│ ◄─Audio Feedback│  • Central WebSocket Action Hub │
│  • Local Piper Neural TTS Voice │  (speech_reply) │  • Multi-Device Action Router   │
└─────────────────────────────────┘                 └────────────────┬────────────────┘
                                                                     │
                                             Local Wi-Fi WebSocket Protocol
                                             {"device": "laptop1"|"laptop2", ...}
                                                                     │
                                      ┌──────────────────────────────┴──────────────────────────────┐
                                      ▼                                                             ▼
                       ┌──────────────────────────────┐                              ┌──────────────────────────────┐
                       │     Workstation: Laptop 1    │                              │     Workstation: Laptop 2    │
                       │  • Win32 OpenDesktopW Focus  │                              │  • Win32 OpenDesktopW Focus  │
                       │  • Persistent Chromium State │                              │  • Persistent Chromium State │
                       │  • Universal Primitives      │                              │  • Universal Primitives      │
                       │  • Native Media & Hotkey (f) │                              │  • Native Media & Hotkey (f) │
                       └──────────────────────────────┘                              └──────────────────────────────┘
```

### Component Roles:
1. **Phone A (The Brain)**:
   - Houses the local LLM runtime via `llama.cpp` / `llama-server` on Android Termux.
   - Executes the fine-tuned, quantized **`IRIS-Qwen3-4B-Operator.Q4_K_M.gguf`** (~2.38 GB), consuming minimal RAM while delivering ultra-low-latency structured tool generation.
   - Runs the central WebSocket routing hub that coordinates actions between voice I/O and target laptops.
2. **Phone B (The Senses & Spoken Voice)**:
   - Provides physical microphone listening and acoustic speaker playback in the room.
   - Runs `openWakeWord` acoustic detection ("Hey Iris"), `Faster-Whisper` streaming STT, and synthesizes spoken natural voice feedback (`speech_reply`) via local `Piper` neural TTS or `edge-tts`.
3. **Laptop Agents (Workstation Actuators)**:
   - Python daemon (`laptop_agent`) running in the background on each workstation (`laptop1`, `laptop2`).
   - Maintains a resilient WebSocket connection with Phone A.
   - Executes arbitrary user tasks via deep Win32 API calls (`OpenDesktopW`, `EnumDesktopWindows`, `SetForegroundWindow`), clipboard Unicode injection (`Ctrl+V`), and persistent Playwright browser automation.

---

## 🧠 The `IRIS-Qwen3-4B-Operator` Model

The core intelligence powering IRIS-BOX is a custom fine-tuned model created specifically for universal computer control and spoken interaction:

- **Base Architecture**: `Qwen/Qwen3-4B-Instruct-2507` (4 Billion parameters).
- **Quantization**: `Q4_K_M` (~2.38 GB GGUF), fitting comfortably within Phone A's Termux memory budget (~3.2 GB peak RAM usage).
- **Training Pipeline**: 4-bit QLoRA with `unsloth` and TRL `SFTTrainer` trained across 220+ high-fidelity multi-turn operator scenarios covering:
  - Multi-turn YouTube search, scroll, ordinal video selection, ad-skipping, and native player fullscreen (`hotkey: "f"`).
  - Claude and ChatGPT web/desktop automation (new conversation, clipboard typing, prompt submission).
  - Multi-window desktop context switching and background window restoration.
  - Cross-service media playback (Spotify, Apple Music, YouTube).
  - Compound action pipelines (`actions: [...]`).
  - Device routing targeting specific workstations (`laptop1`, `laptop2`).
- **Validation Benchmark Gate**: Tested against 8 real-world complex operator scenarios, achieving a **100% pass rate** for valid JSON syntax, correct tool argument extraction, and natural voice speech replies.
- **Colab Training Notebook**: Fully reproducible standalone 5-stage fine-tuning pipeline available in [`scripts/train_iris_uncensored_master.ipynb`](scripts/train_iris_uncensored_master.ipynb) and [`scripts/generate_master_colab.py`](scripts/generate_master_colab.py).

---

## 🛠️ Universal Computer Operator Primitives

Rather than maintaining fragile, site-specific automation scripts, IRIS-BOX operates through an atomic set of **Universal Operator Primitives**:

| Primitive Tool | Key Arguments | Purpose & Example |
| :--- | :--- | :--- |
| `open_or_switch` | `target` (app name or URL) | Brings existing window to front or launches app/URL if not open. *(e.g. `{"tool": "open_or_switch", "args": {"target": "claude"}}`)* |
| `new_chat` | (none) | Clicks new chat/tab button (e.g. Claude `[aria-label="New chat"]`, ChatGPT, or `Ctrl+N`). |
| `type_and_send` | `text`, `submit` (bool) | Pastes Unicode text via system clipboard (`Ctrl+V`) into active input/textarea and submits. |
| `click_label` | `label` (text, aria-label, index) | Clicks element matching visible text, ordinal position (`video_1`, `video_2`), or buttons like `"Skip Ad"`. |
| `hotkey` | `combo` (`f`, `space`, `shift+n`) | Executes keyboard shortcuts. **Uses native YouTube player `'f'` for true player full screen** (never browser zoom). |
| `scroll` | `direction` (`up` / `down`) | Smoothly scrolls the active document or web page viewport. |
| `get_active_context`| (none) | Queries foreground window title, process name, and active browser tab. |
| `volume` | `action` (`up`, `down`, `mute`), `steps` | Controls hardware sound output volume. |
| `search_media` | `service` (`spotify`, `apple_music`, `youtube`), `query` | Cross-service audio and video search dispatcher. |

### Compound Action Pipeline Example
The model can emit single tool calls or an array of sequential compound actions:
```json
{
  "device": "laptop1",
  "actions": [
    {"tool": "open_or_switch", "args": {"target": "youtube"}},
    {"tool": "type_and_send", "args": {"text": "soothing lofi live", "submit": true}},
    {"tool": "click_label", "args": {"label": "video_1"}},
    {"tool": "hotkey", "args": {"combo": "f"}}
  ],
  "speech_reply": "Playing soothing lofi on YouTube in full screen on Laptop 1."
}
```

---

## 🚀 Laptop Agent Setup & Execution

### Prerequisites
- Windows 10/11
- Python 3.12+ (or [uv](https://github.com/astral-sh/uv))
- Playwright Chromium installed (`python -m playwright install chromium`)

### 1. Launching the Laptop Agent
On each workstation:
```powershell
# Clone or navigate to the repository
cd A:\IRISBOX\iris-backend

# Install dependencies
uv sync
# Or with standard pip:
pip install -e .

# Launch the Laptop Agent
python run_agent.py
# Or via module:
python -m laptop_agent.cli
```

### 2. Standalone Testing (Without Phone A)
You can verify all desktop, browser, and media actions immediately using the built-in mock hub or CLI:

- **Interactive Menu**: Run `python -m laptop_agent.cli` and pick any automation scenario.
- **Single Command**:
  ```powershell
  python -m laptop_agent.cli --cmd '{"tool": "open_or_switch", "args": {"target": "youtube"}}'
  ```
- **Simulated WebSocket Hub (Phone A Simulator)**:
  ```powershell
  # Terminal 1: Run mock hub
  python -m laptop_agent.mock_hub

  # Terminal 2: Run laptop client
  python -m laptop_agent.client
  ```
  Type commands into Terminal 1 to watch your laptop execute them in real time.

---

## 📱 Phone A (Termux) & Phone B Deployment

### Phone A Setup (Brain Runtime)
1. Install **Termux** on Phone A.
2. Install `llama.cpp`:
   ```bash
   pkg update && pkg install git cmake clang
   git clone https://github.com/ggerganov/llama.cpp
   cd llama.cpp && cmake -B build && cmake --build build --config Release
   ```
3. Transfer or download `IRIS-Qwen3-4B-Operator.Q4_K_M.gguf` onto Phone A.
4. Start the local inference server:
   ```bash
   ./build/bin/llama-server -m /path/to/IRIS-Qwen3-4B-Operator.Q4_K_M.gguf -c 4096 --host 0.0.0.0 --port 8080
   ```

### Ollama Desktop Alternative
To run the model on a local workstation using Ollama:
```powershell
ollama create iris-qwen3-4b-operator -f models/Modelfile.iris_qwen3_4b_operator
ollama run iris-qwen3-4b-operator
```

---

## 🔒 Security & Cryptographic Trust Architecture

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

## 🧪 Verification & Benchmark Suite

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
IRIS-BOX/
├── laptop_agent/                        # Workstation edge client & universal primitives
│   ├── tools/
│   │   ├── universal_operator.py        # Universal Operator Primitives (open, type, click, hotkey, scroll)
│   │   ├── app_control.py               # Win32 OpenDesktopW window focus & clipboard injection
│   │   ├── browser_control.py           # Persistent Chromium profile Playwright automation
│   │   ├── media_control.py             # YouTube ad-skipping, search, native player 'f' fullscreen
│   │   └── system_control.py            # Hardware volume, CPU/RAM, and sandboxed execution
│   ├── client.py                        # Resilient WebSocket client connecting to Phone A Hub
│   ├── dispatcher.py                    # Multi-action dispatcher handling single and compound actions
│   ├── config.py                        # Device identifier (laptop1, laptop2) and hub configs
│   ├── cli.py                           # Interactive standalone test CLI
│   └── mock_hub.py                      # Standalone Phone A hub simulator
├── models/
│   ├── Modelfile.iris_qwen3_4b_operator # Ollama / llama.cpp definition for Qwen3-4B Operator
│   ├── Modelfile.heretic_iris           # Ollama definition for Heretic uncensored persona
│   ├── piper/                           # Piper ONNX neural TTS voice models
│   ├── whisper/                         # Faster-Whisper base.en model & tokenizer
│   └── wakeword/                        # openWakeWord ONNX acoustic model
├── scripts/
│   ├── train_iris_uncensored_master.ipynb # 5-Stage Google Colab fine-tuning & GGUF quantization
│   ├── train_iris_uncensored_master.py  # Standalone master training pipeline
│   ├── generate_master_colab.py         # Automated Colab notebook generator
│   ├── showcase_operator.py             # 5-Act Live AI Computer Operator showcase
│   └── run_baseline_benchmark.py        # 6-domain deterministic benchmark runner
├── src/
│   ├── agent/                           # ReAct loop, plan manager, and orchestrator
│   ├── operator/                        # Desktop telemetry, workspace resolver, window manager
│   ├── security/                        # AuthManager, socket airgap guard, SSRF protection
│   ├── server/                          # FastAPI app, static assets, PWA service worker
│   ├── storage/                         # SQLite durable audit logs and conversation state
│   └── tools/                           # ToolManager and bounded computer tool implementations
├── run_agent.py                         # One-click launcher for the Laptop Agent
└── tests/                               # Comprehensive unit, integration, and E2E test suites
```

---

## 📄 License
IRIS-BOX is distributed under the [MIT License](LICENSE).
