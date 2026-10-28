# 📦 IRIS-BOX: Physical Voice AI Desk Pod & Multi-Laptop Orchestrator

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python: 3.12 / 3.14](https://img.shields.io/badge/Python-3.12%20|%203.14-green.svg)](https://www.python.org/)
[![Hardware: Multi-Device LAN](https://img.shields.io/badge/Hardware-Multi--Laptop%20LAN-orange.svg)](laptop_agent/)
[![Model: heretic-iris Q8_0](https://img.shields.io/badge/Brain-heretic--iris%20(531%20MB)-blueviolet.svg)](models/Modelfile.heretic_iris)
[![Offline: 100% Air-Gapped](https://img.shields.io/badge/Air--Gap-Enforced-success.svg)](dist/airgap_manifest.json)
[![Platform: Windows 10 / 11](https://img.shields.io/badge/Platform-Windows%2010%20/%2011-0078D6.svg)](https://www.microsoft.com/windows)

> **IRIS-BOX** is an **external physical smart hardware box (pod)** that sits on your desk and acts as your private, 100% offline **Jarvis conductor**. Speak naturally into the room, and the Box controls **multiple laptops (`laptop1`, `laptop2`, workstations)** across your local private network (LAN) simultaneously—opening apps, typing, searching the web, scrolling, adjusting volume, and running terminal commands—with **zero cloud subscriptions**, **zero cloud latency**, and **zero data leaks**.

---

## 🌟 What is IRIS-BOX? (Explained for Beginners)

Imagine you have two laptops on your desk—one for work/coding (`Laptop 1`) and one for research/media (`Laptop 2`). Instead of constantly switching between keyboards and trackpads, you place an **external physical smart box (IRIS-BOX)** on your desk.

```
                                  YOU SPEAK:
      "Iris, on Laptop 1 open the payment project in Antigravity,
             and on Laptop 2 play soothing lofi in full screen."
                                       │
                                       ▼
                       ┌───────────────────────────────┐
                       │       THE PHYSICAL BOX        │
                       │    (External Pod on Desk)     │
                       │ • Room Microphone Array       │
                       │ • Offline heretic-iris Brain  │
                       │ • Central WebSocket Hub       │
                       │ • Desk Camera & Acoustic Voice│
                       └───────────────┬───────────────┘
                                       │
               Private Local Wi-Fi / LAN (Zero Cloud Streaming)
                                       │
                     ┌─────────────────┴─────────────────┐
                     ▼                                   ▼
      ┌─────────────────────────────┐     ┌─────────────────────────────┐
      │          LAPTOP 1           │     │          LAPTOP 2           │
      │    (Workstation / Coding)   │     │    (Media / Research / PR)  │
      │ • Opens Antigravity IDE     │     │ • Opens YouTube in Chrome   │
      │ • Focuses payment-service   │     │ • Searches 'soothing lofi'  │
      │ • Runs unit tests via CLI   │     │ • Hits 'f' for Fullscreen   │
      └─────────────────────────────┘     └─────────────────────────────┘
```

### The 4 Core Principles of IRIS-BOX:
1. **Physical External Hardware Box**: An independent smart box on your desk with dedicated room microphones, acoustic speakers, and local edge computing.
2. **Multi-Laptop Orchestration**: You can control 2, 3, or more laptops on the same Wi-Fi network with a single spoken sentence.
3. **100% Offline & Private (Air-Gapped)**: Your audio, keystrokes, and source code are **never** uploaded to Big Tech clouds. All reasoning runs locally.
4. **Universal Computer Operator**: Controls **ANY** app (Spotify, VS Code, Task Manager, Settings, Explorer), **ANY** browser tab, and Windows system settings.

---

## 🕹️ Two Operational Modes

IRIS-BOX is designed with ultimate flexibility:

### 🌐 Mode A: Multi-Laptop Flagship Mode (The Physical Desk Pod)
- The **Physical Box** sits on your desk running the central WebSocket server (`/ws/agent`) and the local AI brain.
- Each laptop (`laptop1`, `laptop2`) runs a lightweight background daemon (`laptop_agent/client.py`) connected to the Box over your local private Wi-Fi (`ws://<box-ip>:8000/ws/agent`).
- You speak into the room, and the Box coordinates both laptops simultaneously!

### 💻 Mode B: Standalone Workstation Mode (Single-Laptop On the Go)
- Traveling without your physical desk box?
- Simply run `python voice_iris.py` directly on your laptop!
- That single laptop acts as both the listener and the actuator using its built-in microphone, Windows SAPI voice, and local Ollama brain.

---

## 🚀 Step-by-Step Setup Guide

### 📱 Setup Mode A: The Multi-Laptop Physical Box Hub

#### Step 1: Start the Box Hub (On the Box or Primary Machine)
The Box runs the central coordinator and local LLM runtime:
```powershell
# Navigate to the repository
cd A:\IRISBOX\iris-backend

# Start the IRIS Hub server on your local network
python scripts/run_server.py
```
*(By default, the Box listens on port `8000` on your private LAN, e.g. `192.168.1.100:8000`)*

#### Step 2: Connect Laptop 1 (`laptop1` - Workstation)
On your first laptop, configure its identity:
```powershell
cd A:\IRISBOX\iris-backend
# Set this device name to laptop1 and point to the Box IP
$env:IRIS_DEVICE_NAME="laptop1"
$env:IRIS_HUB_URL="ws://192.168.1.100:8000/ws/agent"

# Start the agent daemon
python -m laptop_agent.client
```
*Laptop 1 registers itself with the Box and waits for commands.*

#### Step 3: Connect Laptop 2 (`laptop2` - Secondary / Media)
On your second laptop:
```powershell
cd A:\IRISBOX\iris-backend
# Set this device name to laptop2 and point to the Box IP
$env:IRIS_DEVICE_NAME="laptop2"
$env:IRIS_HUB_URL="ws://192.168.1.100:8000/ws/agent"

# Start the agent daemon
python -m laptop_agent.client
```
*Laptop 2 registers itself with the Box.*

#### Step 4: Speak Commands to the Room!
Now speak to the Box:
- *"Iris, on Laptop 1 open Antigravity, and on Laptop 2 play Carwow reviews on YouTube."*
- Both laptops execute their assigned tasks in parallel!

---

### 💻 Setup Mode B: Standalone Single-Laptop Mode (No Box Needed)

If you only have one laptop and want an instant, zero-setup Jarvis assistant:

1. **Register the local model in Ollama**:
   ```powershell
   cd A:\IRISBOX\models
   ollama create heretic-iris -f Modelfile.heretic_iris
   ```
2. **Install Python dependencies**:
   ```powershell
   pip install sounddevice SpeechRecognition pywin32 pyautogui pyperclip psutil
   ```
3. **Launch the agent**:
   Double-click **[`start_voice_iris.bat`](start_voice_iris.bat)** or run:
   ```powershell
   python voice_iris.py
   ```
   Speak directly into your laptop mic!

---

## 🗣️ Multi-Device Voice Command Examples

### 1. Cross-Laptop Task Delegation
- **"On Laptop 1 open the payment project in VS Code, and on Laptop 2 open my email in Chrome."**
- **"On Laptop 2 increase volume by 4 steps and play music on Spotify."**
- **"Minimize all windows on Laptop 1 and lock Laptop 2."**
- **"On Laptop 1 run pytest in terminal, and on Laptop 2 open YouTube in fullscreen."**

### 2. Universal Single-Machine Commands
- **Software**: *"Open Spotify"*, *"Open Task Manager"*, *"Open Settings"*, *"Open Calculator"*, *"Open Antigravity"*, *"Open Downloads"*.
- **Web Navigation**: *"Open Claude"*, *"Search how to buy a smartphone in Chrome"*, *"New tab"*, *"Close tab"*.
- **UI & Mouse**: *"Scroll down"*, *"Scroll up"*, *"Select the first option on the screen"*, *"Click"*, *"Double click"*.
- **System & Sound**: *"Volume up"*, *"Volume down"*, *"Mute"*, *"Play/Pause"*, *"Next track"*, *"Check battery status"*, *"Lock screen"*.
- **Terminal Execution**: *"Run ipconfig in terminal"*, *"Run dir in terminal"*, *"Run git status"*.

---

## 🏛️ Physical Hardware Architecture: Inside the Box

The physical IRIS-BOX pod can be realized as a dual-phone smart hub or an SBC (Raspberry Pi / Orange Pi) paired with a display:

```
┌─────────────────────────────────┐                 ┌─────────────────────────────────┐
│   Phone B: Senses & Voice I/O   │                 │     Phone A: The System Brain   │
│  • Array Microphones & Speaker  │ ──Local Stream─►│  • heretic-iris / Qwen3-4B GGUF │
│  • openWakeWord Detection       │                 │  • Termux llama-server / Ollama │
│  • Faster-Whisper Streaming STT │ ◄─Audio Feedback│  • Central WebSocket Hub        │
│  • Local Piper Neural TTS Voice │  (speech_reply) │  • Multi-Device Action Router   │
│  • Desk Camera (Hardware Vision)│                 │  • Cryptographic Policy Engine  │
└─────────────────────────────────┘                 └────────────────┬────────────────┘
                                                                     │
                                             Local Wi-Fi WebSocket Protocol (RFC 1918)
                                             {"device": "laptop1"|"laptop2", ...}
                                                                     │
                                      ┌──────────────────────────────┴──────────────────────────────┐
                                      ▼                                                             ▼
                       ┌──────────────────────────────┐                              ┌──────────────────────────────┐
                       │     Workstation: Laptop 1    │                              │     Workstation: Laptop 2    │
                       │  • Win32 OpenDesktopW Focus  │                              │  • Win32 OpenDesktopW Focus  │
                       │  • Active-Tab Chrome Control │                              │  • Active-Tab Chrome Control │
                       │  • Native Scroll & Click     │                              │  • Native Scroll & Click     │
                       │  • Local Shell / Terminal    │                              │  • Local Shell / Terminal    │
                       └──────────────────────────────┘                              └──────────────────────────────┘
```

### Component Roles:
1. **The Brain (Phone A / Local SBC)**:
   - Houses the local LLM runtime (`heretic-iris` 531 MB Q8_0 or `Qwen3-4B-Operator` 2.38 GB Q4_K_M).
   - Coordinates device registration, heartbeat monitoring, and multi-step action dispatch.
   - Enforces cryptographic approval gates so sensitive actions require authorization.
2. **The Senses (Phone B / Desk Sensor Pod)**:
   - Microphones continuously monitor for the wake word ("Hey Iris").
   - Synthesizes spoken natural voice feedback (`speech_reply`) via local SAPI or Piper neural TTS.
   - Houses the **Desk Vision Camera** pointing down at your workspace to inspect physical circuit boards, components, or documents.
3. **The Laptop Actuators (`laptop_agent`)**:
   - Lightweight daemon running in user space on each computer.
   - Connects to the Box via WebSocket with auto-reconnection.
   - Executes mouse clicks, keyboard input, app launching, window focusing, and system commands natively.

---

## 🧠 The `heretic-iris` AI Brain

IRIS-BOX is powered by a custom fine-tuned model optimized for low-latency, uncensored tool execution:

- **Model Identity**: `heretic-iris:latest` (Ollama Q8_0 GGUF).
- **Base Architecture**: `Qwen/Qwen2.5-Coder-0.5B-Instruct` (490 Million parameters).
- **Hardware Footprint**: **Only 531 MB** disk space and **~600 MB RAM** during inference. Runs smoothly on basic laptops with integrated Intel/AMD graphics.
- **LoRA Fine-Tuning**: 8 epochs, rank $r=32$, $\alpha=64$, trained on 220+ multi-device operator datasets.
- **Uncensored Persona**: Stripped of moralizing refusals and conversational preambles. Emits pure, deterministic JSON tool calls conforming to Universal Operator schemas.
- **Multi-Device Target Routing**: Emits target device annotations (`"device": "laptop1"`, `"device": "laptop2"`) to direct traffic over your network.

---

## 🛠️ The Universal Computer Operator Primitives

Each laptop agent executes an atomic set of human-like primitives:

| Primitive Tool | Key Arguments | Action & Purpose |
| :--- | :--- | :--- |
| `open_or_switch` | `target` (app name, URL, path) | Scans Start Menu, PATH, protocol schemes (`ms-settings:`), or active windows. Launches or brings to front. |
| `type_and_send` | `text`, `submit` (bool) | Pastes Unicode text via system clipboard (`Ctrl+V`) into active input/textarea and hits Enter. |
| `do_search_in_active_browser` | `query` | Focuses Chrome/Edge and pulses `Ctrl+L` + paste + Enter. **Zero duplicate tab clutter.** |
| `do_scroll` | `direction` (`up` / `down`), `ticks` | Emits raw Win32 `MOUSEEVENTF_WHEEL` mouse messages + `VK_NEXT` (PageDown). |
| `do_click` | `x`, `y`, `button`, `double` | Simulates physical mouse button events at screen coordinates or primary search results. |
| `do_volume` | `action` (`up`, `down`, `mute`) | Adjusts hardware master sound output. |
| `do_media` | `action` (`play`, `pause`, `next`, `prev`) | Controls media playback across Spotify, YouTube, and desktop players. |
| `do_window_control` | `action` (`maximize`, `minimize`, `show desktop`, `close`) | Full Win32 window lifecycle management. |
| `run_command` | `command` | Executes PowerShell / CMD command, captures stdout/stderr, and speaks the summary. |

---

## 📊 Benchmark & Real-World Validation

Benchmarked on Windows 11 across 4 operational tasks:

| # | Task | Target Tool | Execution Result | LLM Latency | Total Latency | Status |
| :-: | :--- | :--- | :--- | :-: | :-: | :-: |
| **1** | Open MediSync repo & audit | `TerminalOperatorTool` | Commit `1f9a8ed` & audit SQL verified | 7.61s | 8.31s | **PASS** |
| **2** | Open YouTube & search Carwow | `BrowserOperatorTool` | Navigated to search results | 3.29s | 3.50s | **PASS** |
| **3** | Open Antigravity IDE | `TerminalOperatorTool` | Brought IDE window to foreground | 5.75s | 6.39s | **PASS** |
| **4** | Open Chrome & go to Gmail | `BrowserOperatorTool` | Opened `https://mail.google.com` | 3.44s | 3.46s | **PASS** |
| **ALL** | **4-Task Full Pipeline** | **100% Valid JSON** | **Zero crashes, zero refusals** | **Avg: 5.02s** | **21.65s** | **PASS** |

*Verified benchmark receipts saved in [`benchmark_results.json`](benchmark_results.json).*

---

## 🔒 Security & Privacy Architecture

- **RFC 1918 Private LAN Only**: Laptop agents only communicate over local private subnets (`192.168.x.x`, `10.x.x.x`). No external relay servers.
- **HMAC Plan Approval Tokens**: Destructive actions (e.g. system file modification) require cryptographic capability tickets before execution.
- **Loopback Socket Air-Gap Guard**: The central core patches socket creation to disallow outbound non-loopback calls unless instructed by user browser commands.

---

## 📁 Repository Structure

```
IRIS-BOX/
├── voice_iris.py                 # ⭐ Standalone Workstation Voice Operator (Mode B)
├── start_voice_iris.bat          # 🚀 1-Click Windows Launcher for Standalone Voice Agent
├── test_iris.py                  # 💻 Interactive Keyboard/CLI Testing Console
├── scratch_benchmark.py          # 🧪 Deterministic 4-task acceptance benchmark
├── benchmark_results.json        # 📈 Benchmark performance and audit receipts
├── train_iris_colab.ipynb        # 🎓 Colab training notebook for heretic-iris
├── models/
│   ├── Modelfile.heretic_iris    # Ollama specification for heretic-iris Q8_0 (531 MB)
│   └── iris-qwen2.5-coder-0.5b-tuned.Q8_0.gguf
├── laptop_agent/                 # 🌐 Multi-Device Client Daemon (Mode A)
│   ├── client.py                 # WebSocket agent connecting to the Physical Box Hub
│   ├── config.py                 # Device identification (laptop1, laptop2) & Hub URL
│   ├── dispatcher.py             # Multi-tool dispatcher (single & compound actions)
│   └── tools/
│       ├── universal_operator.py # Atomic human-like computer use primitives
│       ├── app_control.py        # Win32 OpenDesktopW window focus & clipboard injection
│       ├── browser_control.py    # Persistent Chromium Playwright automation
│       ├── media_control.py      # Volume, media playback, and streaming controls
│       └── system_control.py     # CPU/RAM/Battery telemetry & safe execution
├── scripts/
│   └── run_server.py             # Central WebSocket Hub Server for the Physical Box
├── src/                          # Backend core services (orchestrator, security, airgap)
└── tests/                        # Acceptance, security, and air-gap test suite
```

---

## ❓ Frequently Asked Questions (FAQ)

<details>
<summary><b>1. What is the difference between IRIS-BOX and software like Siri or Alexa?</b></summary>
Siri and Alexa stream your private voice recordings to cloud data centers, charge subscriptions, and cannot operate desktop software like VS Code, Antigravity, or Task Manager. IRIS-BOX is an external physical pod on your desk that runs 100% locally and can operate multiple laptops simultaneously over your local Wi-Fi.
</details>

<details>
<summary><b>2. How many laptops can one IRIS-BOX control?</b></summary>
As many as you have on your local network! Each computer simply runs `python -m laptop_agent.client` with its own unique name (`laptop1`, `laptop2`, `gaming-pc`, `work-mac`). When you speak, IRIS routes the commands to the specific machine you named.
</details>

<details>
<summary><b>3. Do I need an internet connection to use IRIS-BOX?</b></summary>
<b>No.</b> Voice recognition, AI reasoning, voice synthesis, and desktop automation all work completely offline over a local Wi-Fi router or hotspot without an active internet connection. An internet connection is only needed if you ask IRIS to browse the web (e.g. searching Google or YouTube).
</details>

<details>
<summary><b>4. What happens when I travel without the Physical Box?</b></summary>
You can switch to <b>Mode B (Standalone Workstation Mode)</b>! Just run `python voice_iris.py` directly on your laptop, and your laptop will use its built-in microphone and local Ollama brain to perform all operations independently.
</details>

---

## 📄 License
IRIS-BOX is distributed under the [MIT License](LICENSE).
