# 🎙️ IRIS-BOX: Offline Autonomous Voice AI Computer Operator

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python: 3.12 / 3.14](https://img.shields.io/badge/Python-3.12%20|%203.14-green.svg)](https://www.python.org/)
[![Model: heretic-iris Q8_0](https://img.shields.io/badge/Brain-heretic--iris%20(531%20MB)-blueviolet.svg)](models/Modelfile.heretic_iris)
[![Offline: 100% Air-Gapped](https://img.shields.io/badge/Air--Gap-Enforced-success.svg)](dist/airgap_manifest.json)
[![Platform: Windows 10 / 11](https://img.shields.io/badge/Platform-Windows%2010%20/%2011-0078D6.svg)](https://www.microsoft.com/windows)

> **IRIS-BOX** is your private, 100% offline, voice-controlled AI assistant that operates your computer for you like Jarvis. Speak naturally into your microphone, and IRIS will open any software, search the web, control your browser, adjust volume, scroll through pages, click buttons, and run terminal commands—all running directly on your laptop with **zero cloud dependencies** and **zero data leaks**.

---

## 🌟 What is IRIS-BOX? (Explained for Beginners)

Imagine having an assistant sitting next to you who has their hands on a keyboard and mouse. Whenever you speak:
1. **It Listens**: Your laptop's built-in microphone hears what you say.
2. **It Thinks (Locally)**: A custom fine-tuned AI model called **`heretic-iris`** (531 MB) interprets your instruction in real-time on your computer. Your voice and data **never leave your device**.
3. **It Talks Back**: A natural voice (Windows SAPI) speaks back to confirm what it's doing.
4. **It Operates**: IRIS moves the mouse, presses keys, navigates browser tabs, launches programs, and controls Windows settings directly.

### Why was IRIS-BOX built?
- 🔒 **Total Privacy**: Unlike Siri, Alexa, or cloud AI assistants, IRIS does not stream your voice, screen, or files to external cloud servers.
- ⚡ **Zero Cloud Latency & Zero Subscriptions**: Runs entirely offline on local CPU / integrated graphics.
- 🔓 **Uncensored, Direct Execution**: Built using the `heretic-iris` uncensored system persona that emits precise JSON tool actions without preachy refusals.
- 🖥️ **Full Computer Control**: Works across **ANY** software (Spotify, VS Code, Task Manager, Settings, File Explorer), **ANY** browser tab, and Windows system settings.

---

## 🚀 3-Minute Quickstart Guide

Getting IRIS-BOX up and running on your Windows laptop takes only 3 steps:

### Step 1: Install Ollama & Load the Model
1. Download and install [Ollama for Windows](https://ollama.com/download/windows).
2. Open PowerShell and register the model:
   ```powershell
   cd A:\IRISBOX\models
   ollama create heretic-iris -f Modelfile.heretic_iris
   ```
   *(Or test it by running `ollama run heretic-iris`)*

### Step 2: Install Python Dependencies
Open PowerShell and install the required lightweight libraries:
```powershell
pip install sounddevice SpeechRecognition pywin32 pyautogui pyperclip psutil
```

### Step 3: Run the Voice Agent!
Double-click **[`start_voice_iris.bat`](start_voice_iris.bat)** or run in PowerShell:
```powershell
python voice_iris.py
```

*That's it!* Speak into your microphone and watch IRIS control your laptop.

---

## 🗣️ What You Can Ask IRIS to Do (Example Voice Commands)

| Category | What You Say | What IRIS Does |
| :--- | :--- | :--- |
| **Software & Apps** | *"Open Spotify"* | Launches desktop Spotify or opens Spotify Web. |
| | *"Open Task Manager"* | Launches `taskmgr.exe` instantly. |
| | *"Open Settings"* | Opens Windows Settings (`ms-settings:`). |
| | *"Open Antigravity"* | Discovers the Start Menu shortcut and launches the IDE. |
| | *"Open Downloads"* | Opens your Downloads folder in Windows File Explorer. |
| | *"Open Calculator"* / *"Open Paint"* | Launches the built-in Windows utility. |
| **Web & Browsing** | *"Open Claude"* / *"Open ChatGPT"* | Navigates directly to `claude.ai` or `chatgpt.com`. |
| | *"Search how to buy a smartphone in Chrome"* | Uses `Ctrl+L` to search inside your **active tab** (no tab spam!). |
| | *"Search YouTube for Carwow videos"* | Opens YouTube and searches the query. |
| | *"New tab"* / *"Close tab"* | Pulses `Ctrl+T` or `Ctrl+W`. |
| | *"Refresh page"* / *"Fullscreen"* | Pulses `F5` or `F11`. |
| **Navigation & UI** | *"Scroll down"* / *"Scroll up"* | Sends native Win32 mouse wheel ticks and PageDown/PageUp. |
| | *"Select the first option on the screen"* | Simulates a physical mouse click on the primary search result. |
| | *"Click"* / *"Double click"* / *"Right click"* | Dispatches mouse click events at cursor coordinates. |
| | *"Type hello world"* | Pastes text via Unicode clipboard injection into active field. |
| **System & Media** | *"Volume up"* / *"Volume down"* | Adjusts master hardware audio volume. |
| | *"Mute volume"* / *"Unmute"* | Toggles sound mute. |
| | *"Pause music"* / *"Play"* | Toggles Windows media playback. |
| | *"Next song"* / *"Previous track"* | Skips tracks in Spotify, YouTube, or media players. |
| | *"Maximize window"* / *"Minimize"* | Controls foreground window state. |
| | *"Show desktop"* | Minimizes all windows (`Win + D`). |
| | *"Check battery status"* | Speaks aloud battery %, CPU load, and available RAM. |
| | *"Lock computer"* | Immediately locks the workstation (`LockWorkStation`). |
| **Terminal & Shell** | *"Run ipconfig in terminal"* | Runs command in PowerShell, prints output, and speaks summary. |
| | *"Run dir in terminal"* | Lists directory contents. |
| **Exit** | *"Goodbye"* or *"Exit"* | Speaks farewell and shuts down cleanly. |

---

## 🏛️ System Architecture

```
                                  USER'S VOICE
                                       │
                                       ▼
                       ┌───────────────────────────────┐
                       │   Microphone Array (DMIC)     │
                       │   • 16,000 Hz 16-bit PCM      │
                       │   • Dynamic Noise Floor VAD   │
                       └───────────────┬───────────────┘
                                       │
                                       ▼
                       ┌───────────────────────────────┐
                       │   Acoustic Normalization      │
                       │   • STT Phonetic Corrector    │
                       │   • Intent Sanitizer          │
                       └───────────────┬───────────────┘
                                       │
              ┌────────────────────────┴────────────────────────┐
              ▼                                                 ▼
   [High-Frequency Direct Action]                    [Semantic / Multi-Step]
   Fast Intent Engine (<30ms)                        heretic-iris Brain (Ollama)
   • Scroll down / up                                • Qwen2.5-Coder-0.5B-Instruct
   • Volume / Mute / Media                           • Structured JSON Tool Call
   • Tab / Window Controls                           • Uncensored Persona
              │                                                 │
              └────────────────────────┬────────────────────────┘
                                       │
                                       ▼
                       ┌───────────────────────────────┐
                       │  Universal Computer Operator  │
                       │  • Win32 User32 APIs          │
                       │  • AppControl Window Manager  │
                       │  • Start Menu App Resolver    │
                       │  • Active-Tab Browser Control │
                       └───────────────┬───────────────┘
                                       │
                    ┌──────────────────┴──────────────────┐
                    ▼                                     ▼
        ┌───────────────────────┐             ┌───────────────────────┐
        │ Action on Windows OS  │             │   Spoken SAPI Voice   │
        │ • Physical Click/Scroll│            │ • Microsoft Zira      │
        │ • Launch App / URL    │             │ • Instant Zero-Delay  │
        └───────────────────────┘             └───────────────────────┘
```

---

## 🧠 The `heretic-iris` AI Brain

The core intelligence powering IRIS-BOX is a fine-tuned, quantized model:

- **Base Architecture**: `Qwen/Qwen2.5-Coder-0.5B-Instruct` (490 Million parameters).
- **Quantization**: `Q8_0` GGUF (~531 MB file size).
- **Memory Footprint**: Consumes only ~600 MB of system RAM, running effortlessly on budget laptops with integrated Intel/AMD graphics.
- **LoRA Hyperparameters**:
  - Rank $r=32$, $\alpha=64$, 8 Epochs.
  - Target modules: `q_proj`, `k_proj`, `v_proj`, `o_proj`, `gate_proj`, `up_proj`, `down_proj`.
- **System Prompt**: Enforces strict JSON output conforming to IRIS Universal Operator tool schemas with zero conversational filler or moralizing refusals.
- **Validation Score**: **100% Pass Rate** across real-world workstation benchmark suites.

---

## 🛠️ Key Engine Components

### 1. Universal Application Resolver (`resolve_and_open_target`)
Finds and launches software dynamically without hardcoded paths:
1. **Running Windows**: Queries active window titles using `AppControl.list_windows()`. If running, brings it to front.
2. **Web Services**: Maps popular web apps (`claude.ai`, `chatgpt.com`, `github.com`, `youtube.com`) to direct URLs.
3. **Windows Protocols**: Resolves `ms-settings:`, `calc.exe`, `taskmgr.exe`, `mspaint.exe`, `wt.exe`, and folders (`Downloads`, `Documents`, `Desktop`).
4. **PATH & Start Menu**: Recursively searches `.lnk` shortcuts and `.exe` binaries across `C:\ProgramData\...\Start Menu` and `~\AppData\Local\Programs`.

### 2. Active-Tab In-Browser Navigation (`do_search_in_active_browser`)
Unlike basic assistants that spam 10 new browser tabs:
- IRIS focuses your existing Google Chrome or Edge window.
- Pulses `Ctrl + L` to highlight the address/search bar.
- Pastes your search query or URL and presses `Enter`.
- Updates your **current active tab** seamlessly.

### 3. Native Win32 Scroll & Click Primitives (`do_scroll`, `do_click`)
- Emits raw `MOUSEEVENTF_WHEEL` mouse messages directly to the Windows event queue.
- Also sends `VK_NEXT` (PageDown) and `VK_PRIOR` (PageUp) for universal compatibility with PDF viewers, File Explorer, and code editors.
- Dispatches true hardware mouse button clicks at specified coordinate bounds.

### 4. Acoustic Normalization Layer (`normalize_voice_input`)
Automatically bridges the gap between raw speech recognition and intended technical targets:
- `"open clone"` / `"open cloud"` $\to$ `"open claude"`
- `"open file"` / `"open files"` $\to$ `"open file explorer"`
- `"scroll on files"` $\to$ `"scroll down"`
- `"how to buy a smartphone in the google search bar"` $\to$ `"search how to buy a smartphone"`

---

## 📊 Benchmark & Acceptance Results

IRIS-BOX was benchmarked on a Windows 11 laptop across 4 end-to-end real-world operational tasks:

| # | Task | Tool Generated | Execution Result | LLM Latency | Total Latency | Status |
| :-: | :--- | :--- | :--- | :-: | :-: | :-: |
| **1** | Open MediSync repo & report latest audit | `TerminalOperatorTool` | Extracted commit `1f9a8ed` & audit SQL | 7.61s | 8.31s | **PASS** |
| **2** | Open YouTube & search "Carwow videos" | `BrowserOperatorTool` | Navigated to search results | 3.29s | 3.50s | **PASS** |
| **3** | Open Antigravity IDE | `TerminalOperatorTool` | Brought IDE window to foreground | 5.75s | 6.39s | **PASS** |
| **4** | Open Chrome & go to Gmail | `BrowserOperatorTool` | Opened `https://mail.google.com` | 3.44s | 3.46s | **PASS** |
| **ALL** | **4-Task Full Pipeline** | **100% Valid JSON** | **Zero crashes, zero refusals** | **Avg: 5.02s** | **21.65s** | **PASS** |

*Detailed benchmark receipt saved in [`benchmark_results.json`](benchmark_results.json).*

---

## 📁 Repository Structure

```
IRIS-BOX/
├── voice_iris.py                 # ⭐ Main Real-Time Voice Operator (v3.0 Universal)
├── start_voice_iris.bat          # 🚀 1-Click Windows Launcher for Voice Agent
├── test_iris.py                  # 💻 Interactive Keyboard/CLI Testing Console
├── scratch_benchmark.py          # 🧪 Deterministic 4-task acceptance benchmark
├── benchmark_results.json        # 📈 Benchmark performance and audit receipts
├── train_iris_colab.ipynb        # 🎓 Standalone Colab training notebook for heretic-iris
├── models/
│   ├── Modelfile.heretic_iris    # Ollama specification for heretic-iris Q8_0
│   └── iris-qwen2.5-coder-0.5b-tuned.Q8_0.gguf # (531 MB local GGUF)
├── laptop_agent/                 # Deep OS & Workstation Control Primitives
│   ├── dispatcher.py             # Multi-tool dispatcher (single & compound actions)
│   ├── tools/
│   │   ├── universal_operator.py # Atomic human-like computer use primitives
│   │   ├── app_control.py        # Win32 OpenDesktopW window focus & clipboard injection
│   │   ├── browser_control.py    # Persistent Chromium Playwright automation
│   │   ├── media_control.py      # Volume, media playback, and streaming controls
│   │   └── system_control.py     # CPU/RAM/Battery telemetry & safe execution
├── src/                          # Backend core services (orchestrator, security, airgap)
└── tests/                        # Acceptance, security, and air-gap test suite
```

---

## ❓ Frequently Asked Questions (FAQ)

<details>
<summary><b>1. Does IRIS-BOX send my voice or data to the internet?</b></summary>
<b>No.</b> The core system runs 100% locally on your machine. Voice output uses native Windows SAPI (`Microsoft Zira`) completely offline, and the AI brain (`heretic-iris`) runs on local loopback via Ollama (`http://localhost:11434`). Only user-directed web navigation (e.g., asking to open YouTube or search Google) touches the internet.
</details>

<details>
<summary><b>2. Do I need an expensive NVIDIA GPU?</b></summary>
<b>No.</b> The fine-tuned `heretic-iris` model is an ultra-efficient 0.5-Billion parameter Q8_0 quantized model (531 MB). It runs with low CPU usage and less than 600 MB RAM on standard Windows laptops with integrated Intel/AMD graphics.
</details>

<details>
<summary><b>3. Why did IRIS mishear "Claude" as "cloud" or "clone"?</b></summary>
Standard English speech-to-text models have acoustic priors biased toward common dictionary words like "cloud" or "clone". IRIS-BOX v3.0 includes an automatic **Acoustic Normalization Layer** that maps phonetic misrecognitions back to technical targets like Claude, File Explorer, and active search commands.
</details>

<details>
<summary><b>4. How do I stop or exit the voice agent?</b></summary>
Simply say <b>"Goodbye"</b>, <b>"Exit"</b>, or press `Ctrl + C` in your PowerShell terminal.
</details>

---

## 📄 License
IRIS-BOX is distributed under the [MIT License](LICENSE).
