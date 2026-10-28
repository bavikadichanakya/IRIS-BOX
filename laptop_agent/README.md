# IRIS-BOX: Laptop Edge Agent & Universal Computer Operator

The **Laptop Agent** runs locally on each workstation or laptop (`laptop1`, `laptop2`) and executes deep desktop, application, browser, and media automation triggered by **Phone A (The IRIS-BOX Brain)** via local WebSocket communication.

---

## 🏛️ Architecture & Routing

```
┌─────────────────────────────────┐                 ┌─────────────────────────────────┐
│     Phone B (Senses & Voice)    │                 │      Phone A (IRIS-BOX Brain)   │
│  • PWA Voice Interface / Mic    │ ──Audio Stream─►│  • IRIS-Qwen3-4B-Operator (GGUF)│
│  • Local Piper Neural TTS Spkr  │ ◄─Audio Feedback│  • Termux / llama.cpp / Hub     │
└─────────────────────────────────┘                 └────────────────┬────────────────┘
                                                                     │
                                                           Local WebSocket Protocol
                                                           (Target: "laptop1"|"laptop2")
                                                                     │
                                                                     ▼
                                                    ┌─────────────────────────────────┐
                                                    │     Laptop Agent (Actuator)     │
                                                    │  • Win32 OpenDesktopW Focus     │
                                                    │  • Persistent Chromium Browser  │
                                                    │  • Universal Operator Primitives│
                                                    │  • Native Media & Hotkey Logic  │
                                                    └─────────────────────────────────┘
```

---

## 🚀 Operator Capabilities

### 1. Universal Operator Primitives (Works Across Any App or Web UI)
Rather than relying on brittle, rigid scripts, the laptop agent implements atomic universal operator primitives:

| Primitive Tool | Arguments | Description & Example |
| :--- | :--- | :--- |
| `open_or_switch` | `target` (e.g. `youtube`, `claude`, `notepad`, `spotify`, URL) | Focuses existing window if running, or launches application/URL. |
| `new_chat` | (none) | Automatically clicks new chat/tab (e.g. Claude `[aria-label="New chat"]`, ChatGPT, or `Ctrl+N`). |
| `type_and_send` | `text`, `submit` (bool, default true) | Pastes Unicode text via system clipboard (`Ctrl+V`) into active prompt/search box and optionally presses Enter. |
| `click_label` | `label` (e.g. `"video_1"`, `"short"`, `"Skip Ad"`, button text) | Clicks element by visual/text label, aria-label, or ordinal index. |
| `hotkey` | `combo` (e.g. `'f'`, `'space'`, `'shift+n'`, `'ctrl+t'`) | Simulates key combinations (e.g. **native YouTube player `'f'`** for true full screen, `'space'` for pause). |
| `scroll` | `direction` (`"up"` or `"down"`), `amount` (default 500) | Smoothly scrolls the active browser or window viewport. |
| `get_active_context`| (none) | Returns current foreground window title, process name, and active browser tab URL. |
| `volume` | `action` (`"up"`, `"down"`, `"mute"`), `steps` (int) | Adjusts hardware master sound level. |
| `search_media` | `service` (`spotify`, `apple_music`, `youtube`), `query` | Cross-service media dispatcher. |

### 2. Compound Actions Support
The agent can execute sequential pipelines in a single JSON payload:
```json
{
  "device": "laptop1",
  "actions": [
    {"tool": "open_or_switch", "args": {"target": "youtube"}},
    {"tool": "type_and_send", "args": {"text": "soothing lofi", "submit": true}},
    {"tool": "click_label", "args": {"label": "video_1"}},
    {"tool": "hotkey", "args": {"combo": "f"}}
  ],
  "speech_reply": "Playing soothing lofi on YouTube in full screen."
}
```

### 3. Persistent Chromium Session
All web automations run inside a persistent user data profile (`~/.iris_browser_profile`). User logins (Google, Claude, GitHub, Spotify, YouTube) persist permanently across restarts without requiring repetitive manual authentication.

---

## 🧪 Quickstart & Testing

### 1. Standalone Interactive CLI
Launch the interactive test operator on your laptop:
```powershell
python run_agent.py
# Or directly via module:
python -m laptop_agent.cli
```
You can choose from pre-built scenarios (YouTube search & fullscreen, Claude new conversation & prompt, Notepad typing, Volume control, System telemetry) or enter raw JSON payloads.

### 2. Single Command Execution
Execute an action immediately from the command line:
```powershell
python -m laptop_agent.cli --cmd '{"tool": "open_or_switch", "args": {"target": "youtube"}}'
```

### 3. End-to-End WebSocket Testing (Simulating Phone A Hub)
Run a simulated Phone A hub and connect the laptop agent:

**Terminal 1 (Mock Phone A Hub):**
```powershell
python -m laptop_agent.mock_hub
```

**Terminal 2 (Laptop Agent Client):**
```powershell
python -m laptop_agent.client
```

Any command typed into Terminal 1 will be routed over WebSocket to Terminal 2, executed on your desktop, and acknowledged with an execution receipt.

---

## ⚙️ Configuration (`config.py`)

Configured via environment variables or `.env`:
* `IRIS_DEVICE_NAME`: Identifies this machine (`laptop1` or `laptop2`, defaults to `laptop1`).
* `IRIS_HUB_URL`: WebSocket URL of Phone A Hub (e.g. `ws://192.168.1.50:8765`).
* `IRIS_AUTH_TOKEN`: Shared pre-shared key for secure handshakes.
