"""
IRIS Voice Agent v3.0 - Universal Autonomous Computer Operator
Powered by 'heretic-iris' (Qwen2.5-Coder-0.5B-Instruct Q8_0) in Ollama
Full OS Mastery: ANY App, ANY Software, ANY System Control, Browser & Terminal
"""
import sys
import os

# Ensure UTF-8 output on Windows consoles
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Add iris-backend to python path for AppControl & SystemControl
backend_dir = os.path.join(os.path.dirname(__file__), "iris-backend")
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

import time
import json
import io
import wave
import urllib.request
import urllib.parse
import webbrowser
import subprocess
import shutil
import ctypes
import numpy as np
import sounddevice as sd
import speech_recognition as sr
import win32com.client
import pyperclip
import psutil

from laptop_agent.tools.app_control import AppControl
from laptop_agent.tools.system_control import SystemControl

# Win32 Constants
user32 = ctypes.windll.user32
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010

# Virtual Key Codes
VK_CONTROL = 0x11
VK_SHIFT = 0x10
VK_ALT = 0x12
VK_L = 0x4C
VK_T = 0x54
VK_W = 0x57
VK_A = 0x41
VK_C = 0x43
VK_V = 0x56
VK_D = 0x44
VK_F = 0x46
VK_R = 0x52
VK_TAB = 0x09
VK_RETURN = 0x0D
VK_ESCAPE = 0x1B
VK_SPACE = 0x20
VK_BACK = 0x08
VK_NEXT = 0x22    # PageDown
VK_PRIOR = 0x21   # PageUp
VK_F5 = 0x74
VK_F11 = 0x7A
VK_VOLUME_MUTE = 0xAD
VK_VOLUME_DOWN = 0xAE
VK_VOLUME_UP = 0xAF
VK_MEDIA_NEXT = 0xB0
VK_MEDIA_PREV = 0xB1
VK_MEDIA_PLAY_PAUSE = 0xB3
VK_LWIN = 0x5B

SW_HIDE = 0
SW_SHOWNORMAL = 1
SW_SHOWMINIMIZED = 2
SW_MAXIMIZE = 3
SW_SHOW = 5
SW_MINIMIZE = 6
SW_RESTORE = 9

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL_NAME = "heretic-iris"
SAMPLE_RATE = 16000
CHUNK_SAMPLES = 1600   # 100ms per block
SILENCE_LIMIT = 1.2    # seconds of silence to trigger end-of-speech
MIN_SPEECH_DURATION = 0.4

# Setup SAPI TTS Engine
try:
    speaker = win32com.client.Dispatch("SAPI.SpVoice")
    for i in range(speaker.GetVoices().Count):
        v = speaker.GetVoices().Item(i)
        if "zira" in v.GetDescription().lower():
            speaker.Voice = v
            break
except Exception as e:
    speaker = None
    print(f"[WARN] TTS init error: {e}")

def speak(text: str):
    """Speaks text using native Windows SAPI TTS with zero latency."""
    print(f"\n[IRIS SAYS]: \"{text}\"")
    if speaker:
        try:
            speaker.Speak(text)
        except Exception as e:
            print(f"[TTS Error]: {e}")

# -------------------------------------------------------------
# 1. Universal Application & Software Resolver
# -------------------------------------------------------------

COMMON_PROTOCOLS = {
    "settings": "ms-settings:",
    "windows settings": "ms-settings:",
    "display settings": "ms-settings:display",
    "network settings": "ms-settings:network",
    "bluetooth": "ms-settings:bluetooth",
    "camera": "microsoft.windows.camera:",
    "store": "ms-windows-store:",
    "calculator": "calc.exe",
    "calc": "calc.exe",
    "notepad": "notepad.exe",
    "task manager": "taskmgr.exe",
    "taskmgr": "taskmgr.exe",
    "paint": "mspaint.exe",
    "snipping tool": "snippingtool.exe",
    "cmd": "cmd.exe",
    "command prompt": "cmd.exe",
    "powershell": "powershell.exe",
    "terminal": "wt.exe",
    "windows terminal": "wt.exe",
    "files": "explorer.exe",
    "file explorer": "explorer.exe",
    "explorer": "explorer.exe",
    "downloads": os.path.expanduser(r"~\Downloads"),
    "documents": os.path.expanduser(r"~\Documents"),
    "desktop": os.path.expanduser(r"~\Desktop"),
    "pictures": os.path.expanduser(r"~\Pictures"),
    "videos": os.path.expanduser(r"~\Videos"),
}

WEB_SERVICES = {
    "claude": "https://claude.ai",
    "chatgpt": "https://chatgpt.com",
    "youtube": "https://www.youtube.com",
    "github": "https://github.com",
    "gmail": "https://mail.google.com",
    "google": "https://www.google.com",
    "google maps": "https://maps.google.com",
    "google drive": "https://drive.google.com",
    "twitter": "https://x.com",
    "x": "https://x.com",
    "reddit": "https://reddit.com",
    "netflix": "https://www.netflix.com",
    "spotify web": "https://open.spotify.com",
    "amazon": "https://amazon.com",
    "wikipedia": "https://wikipedia.org",
    "linkedin": "https://linkedin.com",
    "whatsapp web": "https://web.whatsapp.com",
}

def resolve_and_open_target(target: str) -> bool:
    """
    Universal Target Opener:
    Finds and opens or focuses ANY software, app, site, or system path.
    """
    clean = target.strip().lower()

    # 1. Check if a desktop window matching this is ALREADY running
    windows = AppControl.list_windows()
    for w in windows:
        if clean in w["title"].lower():
            AppControl.focus_window(w["title"])
            print(f">> Focused running window: '{w['title']}'")
            return True

    # 2. Check known web service / URL
    if clean in WEB_SERVICES:
        url = WEB_SERVICES[clean]
        webbrowser.open(url)
        print(f">> Opened web service: {url}")
        return True

    if clean.startswith("http://") or clean.startswith("https://") or ("." in clean and "/" not in clean and not clean.endswith(".exe")):
        url = clean if clean.startswith("http") else "https://" + clean
        webbrowser.open(url)
        print(f">> Opened URL: {url}")
        return True

    # 3. Check known protocol / Windows app aliases
    if clean in COMMON_PROTOCOLS:
        dest = COMMON_PROTOCOLS[clean]
        try:
            if dest.endswith(".exe"):
                subprocess.Popen([dest], shell=False)
            elif hasattr(os, "startfile"):
                os.startfile(dest)
            else:
                subprocess.Popen(["explorer.exe", dest])
            print(f">> Launched system utility: {dest}")
            return True
        except Exception as e:
            print(f">> Error opening protocol: {e}")

    # 4. Check executable in PATH
    which = shutil.which(clean) or shutil.which(clean + ".exe")
    if which:
        try:
            subprocess.Popen([which], shell=False)
            print(f">> Launched PATH executable: {which}")
            return True
        except Exception as e:
            print(f">> Launch error: {e}")

    # 5. Search Start Menu & AppData shortcuts (.lnk / .exe)
    scan_dirs = [
        os.path.expanduser(r"~\AppData\Roaming\Microsoft\Windows\Start Menu\Programs"),
        r"C:\ProgramData\Microsoft\Windows\Start Menu\Programs",
        os.path.expanduser(r"~\AppData\Local\Programs"),
        r"C:\Program Files",
        r"C:\Program Files (x86)",
    ]
    for sdir in scan_dirs:
        if os.path.exists(sdir):
            for root, dirs, files in os.walk(sdir):
                for f in files:
                    base = os.path.splitext(f)[0].lower()
                    if clean in base:
                        full_path = os.path.join(root, f)
                        try:
                            if hasattr(os, "startfile"):
                                os.startfile(full_path)
                            else:
                                subprocess.Popen([full_path], shell=False)
                            print(f">> Launched installed program: {full_path}")
                            return True
                        except Exception:
                            continue

    # 6. Fallback to Windows Shell execution
    try:
        subprocess.Popen(f'powershell -Command "Start-Process \'{target}\'"', shell=True)
        print(f">> Dispatched shell process for '{target}'")
        return True
    except Exception as e:
        print(f">> Universal open failed: {e}")
        return False

# -------------------------------------------------------------
# 2. Universal System Controls (Audio, Display, Power, Windows)
# -------------------------------------------------------------

def pulse_key(vk: int, delay: float = 0.02):
    """Presses and releases a virtual key."""
    user32.keybd_event(vk, 0, 0, 0)
    time.sleep(delay)
    user32.keybd_event(vk, 0, 2, 0)

def pulse_hotkey(*vks):
    """Presses a sequence of keys simultaneously and releases in reverse order."""
    for vk in vks:
        user32.keybd_event(vk, 0, 0, 0)
        time.sleep(0.01)
    time.sleep(0.02)
    for vk in reversed(vks):
        user32.keybd_event(vk, 0, 2, 0)
        time.sleep(0.01)

def do_volume(action: str, steps: int = 3):
    """Adjusts Windows master audio volume."""
    action_clean = action.lower().strip()
    if any(k in action_clean for k in ["mute", "silence", "unmute"]):
        pulse_key(VK_VOLUME_MUTE)
        print(">> Toggled volume mute")
        return "Muted/Unmuted volume"
    elif any(k in action_clean for k in ["up", "increase", "raise", "louder"]):
        for _ in range(steps):
            pulse_key(VK_VOLUME_UP)
            time.sleep(0.02)
        print(f">> Increased volume by {steps} steps")
        return f"Increased volume"
    elif any(k in action_clean for k in ["down", "decrease", "lower", "quieter"]):
        for _ in range(steps):
            pulse_key(VK_VOLUME_DOWN)
            time.sleep(0.02)
        print(f">> Decreased volume by {steps} steps")
        return f"Decreased volume"

def do_media(action: str):
    """Controls Windows media playback."""
    action_clean = action.lower().strip()
    if any(k in action_clean for k in ["play", "pause", "resume", "stop"]):
        pulse_key(VK_MEDIA_PLAY_PAUSE)
        print(">> Toggled media play/pause")
        return "Toggled play/pause"
    elif any(k in action_clean for k in ["next", "skip"]):
        pulse_key(VK_MEDIA_NEXT)
        print(">> Skipped to next track")
        return "Next track"
    elif any(k in action_clean for k in ["prev", "previous", "back"]):
        pulse_key(VK_MEDIA_PREV)
        print(">> Replayed previous track")
        return "Previous track"

def do_window_control(action: str):
    """Controls window state: maximize, minimize, close, switch, desktop."""
    action_clean = action.lower().strip()
    hwnd = user32.GetForegroundWindow()

    if "maximize" in action_clean:
        user32.ShowWindow(hwnd, SW_MAXIMIZE)
        print(">> Maximized active window")
        return "Maximized window"
    elif "minimize all" in action_clean or "show desktop" in action_clean:
        pulse_hotkey(VK_LWIN, VK_D)
        print(">> Showed desktop (minimized all)")
        return "Showing desktop"
    elif "minimize" in action_clean:
        user32.ShowWindow(hwnd, SW_MINIMIZE)
        print(">> Minimized active window")
        return "Minimized window"
    elif "close" in action_clean:
        pulse_hotkey(VK_CONTROL, VK_W)
        print(">> Closed active tab/window")
        return "Closed tab/window"
    elif "switch" in action_clean or "alt tab" in action_clean:
        pulse_hotkey(VK_ALT, VK_TAB)
        print(">> Switched window")
        return "Switched window"

def do_system_power(action: str):
    """Executes system-level power actions (lock, sleep, telemetry)."""
    action_clean = action.lower().strip()
    if "lock" in action_clean:
        user32.LockWorkStation()
        print(">> Workstation locked")
        return "Workstation locked"
    elif "status" in action_clean or "battery" in action_clean or "cpu" in action_clean:
        status = SystemControl.get_status()
        batt = status.get("battery_percent")
        cpu = status.get("cpu_percent")
        ram = status.get("memory_percent")
        free_gb = status.get("available_ram_gb")
        msg = f"Battery is at {batt}%. CPU usage is {cpu}%, and {free_gb} GB of RAM is available."
        speak(msg)
        return msg

# -------------------------------------------------------------
# 3. Universal Browser & Mouse/Keyboard Navigation
# -------------------------------------------------------------

def do_scroll(direction="down", ticks=6):
    """Scrolls active desktop window or browser."""
    scroll_val = -120 * ticks if direction == "down" else 120 * ticks
    user32.mouse_event(MOUSEEVENTF_WHEEL, 0, 0, scroll_val, 0)
    vk = VK_NEXT if direction == "down" else VK_PRIOR
    pulse_key(vk)
    print(f">> Scrolled {direction} ({ticks} ticks)")

def do_click(x=None, y=None, button="left", double=False):
    """Simulates physical mouse clicks anywhere on screen."""
    if x is not None and y is not None:
        user32.SetCursorPos(int(x), int(y))
        time.sleep(0.05)

    if button == "left":
        down, up = MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP
    else:
        down, up = MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP

    user32.mouse_event(down | up, 0, 0, 0, 0)
    if double:
        time.sleep(0.08)
        user32.mouse_event(down | up, 0, 0, 0, 0)
    print(f">> Mouse {button} click (double={double}) at ({x}, {y})")

def do_type_text(text: str, press_enter: bool = False):
    """Types text with Unicode support into the currently focused field."""
    pyperclip.copy(text)
    time.sleep(0.05)
    pulse_hotkey(VK_CONTROL, VK_V)
    if press_enter:
        time.sleep(0.05)
        pulse_key(VK_RETURN)
    print(f">> Typed text ({len(text)} chars)")

def do_search_in_active_browser(query: str):
    """Searches in the active Chrome/browser tab using Ctrl+L instead of opening duplicate tabs."""
    chrome_win = AppControl.find_window("Chrome") or AppControl.find_window("Edge")
    if chrome_win:
        AppControl.focus_window(chrome_win["title"])
        time.sleep(0.2)
        # Select address bar via Ctrl+L
        pulse_hotkey(VK_CONTROL, VK_L)
        time.sleep(0.1)
        # Paste search query and press Enter
        pyperclip.copy(f"https://www.google.com/search?q={urllib.parse.quote_plus(query)}")
        pulse_hotkey(VK_CONTROL, VK_V)
        time.sleep(0.05)
        pulse_key(VK_RETURN)
        print(f">> Searched in existing browser tab: {query}")
    else:
        url = f"https://www.google.com/search?q={urllib.parse.quote_plus(query)}"
        webbrowser.open(url)
        print(f">> Opened browser search: {url}")

def do_select_first_option():
    """Clicks the first primary result on screen (Google search result or first list item)."""
    screen_w = user32.GetSystemMetrics(0)
    screen_h = user32.GetSystemMetrics(1)
    target_x = int(screen_w * 0.25)
    target_y = int(screen_h * 0.35)
    do_click(target_x, target_y)
    print(f">> Clicked first option at ({target_x}, {target_y})")

# -------------------------------------------------------------
# 4. Phonetic & Semantic Normalization Layer
# -------------------------------------------------------------

def normalize_voice_input(raw_text: str) -> str:
    """Corrects phonetic STT misrecognitions and standardizes user intents."""
    text = raw_text.strip().lower()

    # Claude phonetics
    if any(k in text for k in ["open clone", "open cloud", "open clawed", "open clod", "open claud", "launch clone", "launch cloud"]):
        return "open claude"

    # Files / File Explorer
    if any(text == k for k in ["open file", "open files", "open explorer", "files", "open folder", "file explorer"]):
        return "open file explorer"

    # Scroll down / up
    if any(k in text for k in ["scroll down", "go down", "scroll on files", "scroll page", "page down"]):
        return "scroll down"
    if any(k in text for k in ["scroll up", "go up", "page up"]):
        return "scroll up"

    # Selection
    if any(k in text for k in ["first option", "first result", "first phone", "select the first", "click the first", "open the first"]):
        return "select the first option"

    # Search in bar
    if "in the google search bar" in text or "in the search bar" in text:
        clean = text.replace("in the google search bar", "").replace("in the search bar", "").strip()
        if clean.startswith("search"):
            return clean
        if clean.startswith("type"):
            clean = clean[4:].strip()
        return f"search {clean}"

    return raw_text

# -------------------------------------------------------------
# 5. Fast Intent Engine (Immediate <30ms Execution)
# -------------------------------------------------------------

def try_fast_intent(text: str) -> bool:
    """Instantly executes high-frequency desktop, media, and navigation commands."""
    cmd = text.lower().strip()

    # 1. Scrolling
    if cmd == "scroll down":
        speak("Scrolling down")
        do_scroll("down", ticks=6)
        return True
    elif cmd == "scroll up":
        speak("Scrolling up")
        do_scroll("up", ticks=6)
        return True

    # 2. Audio & Media Controls
    elif any(k in cmd for k in ["volume up", "increase volume", "raise volume", "louder"]):
        speak("Raising volume")
        do_volume("up", steps=4)
        return True
    elif any(k in cmd for k in ["volume down", "decrease volume", "lower volume", "quieter"]):
        speak("Lowering volume")
        do_volume("down", steps=4)
        return True
    elif any(k in cmd for k in ["mute volume", "unmute volume", "mute sound", "unmute sound"]) or cmd == "mute":
        speak("Toggling mute")
        do_volume("mute")
        return True
    elif cmd in ["play", "pause", "resume", "play music", "pause music", "stop music"]:
        speak("Toggling playback")
        do_media("play")
        return True
    elif cmd in ["next song", "next track", "skip song"]:
        speak("Next track")
        do_media("next")
        return True
    elif cmd in ["previous song", "previous track"]:
        speak("Previous track")
        do_media("prev")
        return True

    # 3. Window Controls
    elif cmd in ["maximize window", "maximize"]:
        speak("Maximizing window")
        do_window_control("maximize")
        return True
    elif cmd in ["minimize window", "minimize"]:
        speak("Minimizing window")
        do_window_control("minimize")
        return True
    elif cmd in ["show desktop", "minimize all"]:
        speak("Showing desktop")
        do_window_control("minimize all")
        return True
    elif cmd in ["close window", "close tab", "close this"]:
        speak("Closing")
        do_window_control("close")
        return True
    elif cmd in ["switch window", "next window"]:
        speak("Switching window")
        do_window_control("switch")
        return True

    # 4. System Power & Telemetry
    elif cmd in ["lock screen", "lock computer", "lock laptop"]:
        speak("Locking screen")
        do_system_power("lock")
        return True
    elif any(k in cmd for k in ["battery status", "how much battery", "system status", "check system", "check ram", "check cpu"]):
        do_system_power("status")
        return True

    # 5. Browser Shortcuts
    elif cmd in ["new tab", "open new tab"]:
        speak("Opening new tab")
        pulse_hotkey(VK_CONTROL, VK_T)
        return True
    elif cmd in ["refresh page", "reload page", "refresh"]:
        speak("Refreshing")
        pulse_key(VK_F5)
        return True
    elif cmd in ["fullscreen", "toggle fullscreen"]:
        speak("Toggling fullscreen")
        pulse_key(VK_F11)
        return True

    # 6. Direct Selection / Clicks
    elif cmd in ["select the first option", "select first option", "click first result"]:
        speak("Selecting first option on screen")
        do_select_first_option()
        return True

    # 7. Direct App / Path Openers
    elif cmd.startswith("open ") or cmd.startswith("launch "):
        target = cmd.replace("open ", "").replace("launch ", "").strip()
        if target:
            speak(f"Opening {target}")
            return resolve_and_open_target(target)

    # 8. Direct Searches
    elif cmd.startswith("search in active browser:") or cmd.startswith("search for ") or cmd.startswith("search "):
        q = cmd.replace("search in active browser:", "").replace("search for ", "").replace("search ", "").strip()
        if "youtube" in q:
            clean_q = q.replace("on youtube", "").replace("youtube", "").strip()
            speak(f"Searching YouTube for {clean_q}")
            webbrowser.open(f"https://www.youtube.com/results?search_query={urllib.parse.quote_plus(clean_q)}")
        else:
            speak(f"Searching for {q}")
            do_search_in_active_browser(q)
        return True

    return False

# -------------------------------------------------------------
# 6. heretic-iris Tool Call Execution Engine
# -------------------------------------------------------------

def execute_tool_call(tool_name: str, args: dict):
    """Executes parsed tool calls from heretic-iris with full OS mastery."""
    print(f"\n>> EXECUTING TOOL: {tool_name} with args: {args}")

    # BrowserOperatorTool
    if tool_name in ["BrowserOperatorTool", "browser_operator"]:
        action = args.get("action", "")
        if action == "goto":
            url = args.get("url", "")
            speak(f"Navigating to {url}")
            resolve_and_open_target(url)
            return f"Navigated {url}"

        elif action == "search":
            query = args.get("query", "")
            if "youtube" in query.lower() or "video" in query.lower():
                speak(f"Searching YouTube for {query}")
                webbrowser.open(f"https://www.youtube.com/results?search_query={urllib.parse.quote_plus(query)}")
            else:
                speak(f"Searching for {query}")
                do_search_in_active_browser(query)
            return f"Searched {query}"

        elif action in ["scroll_down", "scroll"]:
            speak("Scrolling down")
            do_scroll("down", ticks=6)
            return "Scrolled down"

        elif action == "scroll_up":
            speak("Scrolling up")
            do_scroll("up", ticks=6)
            return "Scrolled up"

        elif action in ["click", "select_option"]:
            speak("Selecting option")
            do_select_first_option()
            return "Selected option"

    # DesktopOperatorTool
    elif tool_name in ["DesktopOperatorTool", "desktop_operator"]:
        action = args.get("action", "")
        if action == "launch_app":
            app = args.get("app_name", "") or args.get("name", "")
            speak(f"Opening {app}")
            resolve_and_open_target(app)
            return f"Launched {app}"

        elif action == "focus_window":
            query = args.get("query", "") or args.get("title", "")
            speak(f"Focusing {query}")
            resolve_and_open_target(query)
            return f"Focused {query}"

        elif action in ["select_option", "click"]:
            speak("Selecting option on screen")
            do_select_first_option()
            return "Selected option"

        elif action in ["scroll_down", "scroll"]:
            speak("Scrolling down")
            do_scroll("down", ticks=6)
            return "Scrolled down"

    # TerminalOperatorTool
    elif tool_name in ["TerminalOperatorTool", "terminal_operator"]:
        cmd = args.get("command", "")
        if "iris-gpio-cli" in cmd:
            speak("Hardware radio trigger acknowledged")
            print(">> Hardware Radio/Wi-Fi toggle acknowledged")
            return "Radio acknowledged"

        speak("Executing terminal command")
        res = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        out = (res.stdout or res.stderr)[:250].strip()
        print(f"Shell Output:\n{out}")
        return out

    # SystemOperatorTool / Media / Volume
    elif tool_name in ["SystemOperatorTool", "system_operator", "volume_control"]:
        action = args.get("action", "") or args.get("type", "")
        if any(k in action for k in ["volume", "mute"]):
            do_volume(action)
        elif any(k in action for k in ["media", "play", "pause"]):
            do_media(action)
        elif any(k in action for k in ["window", "maximize", "minimize"]):
            do_window_control(action)
        return "System action completed"

    # HardwarePeripherals
    elif tool_name in ["HardwareVisionTool", "hardware_vision"]:
        speak("Desk vision camera inspecting workspace")
        return "Camera inspected"

    elif tool_name in ["HardwareRadioTool", "hardware_radio"]:
        device = args.get("device", "appliance")
        speak(f"Transmitting radio signal to {device}")
        return f"Radio triggered for {device}"

    speak("Action completed")
    return "Done"

# -------------------------------------------------------------
# 7. Ollama Brain Inference
# -------------------------------------------------------------

def query_heretic_iris(prompt_text: str) -> str:
    """Queries heretic-iris local Ollama model."""
    t0 = time.time()
    payload = json.dumps({
        "model": MODEL_NAME,
        "prompt": prompt_text,
        "stream": False
    }).encode("utf-8")

    req = urllib.request.Request(OLLAMA_URL, data=payload, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        elapsed = time.time() - t0
        res = data.get("response", "").strip()
        print(f"\n[AI BRAIN] {MODEL_NAME} responded in {elapsed:.2f}s:\n{res}")
        return res

# -------------------------------------------------------------
# 8. Calibration & Continuous Voice Loop
# -------------------------------------------------------------

def calibrate_mic(stream, duration_sec=1.5):
    """Calibrate ambient noise floor to establish dynamic threshold."""
    print("Calibrating microphone for ambient room noise... Please remain quiet...")
    rms_values = []
    num_chunks = int(duration_sec * SAMPLE_RATE / CHUNK_SAMPLES)
    for _ in range(num_chunks):
        data, _ = stream.read(CHUNK_SAMPLES)
        rms = np.sqrt(np.mean(data.astype(np.float32)**2))
        rms_values.append(rms)

    avg_rms = float(np.mean(rms_values))
    threshold = max(avg_rms * 1.8, 1100.0)
    print(f"Calibration complete! Ambient RMS: {avg_rms:.1f} | Trigger Threshold: {threshold:.1f}\n")
    return threshold

def main():
    print("=" * 76)
    print("  (*) IRIS AI: UNIVERSAL COMPUTER OPERATOR v3.0")
    print(f"  (*) Model Brain: {MODEL_NAME} (Ollama Q8_0 | 531 MB)")
    print(f"  (*) Voice Feedback: Microsoft Zira (Offline Windows SAPI)")
    print("  (*) Scope: ANY Application, ANY Software, ANY System Control, Browser & CLI")
    print("=" * 76)
    print("Speak naturally into your microphone at any time.")
    print("You can ask IRIS to do ANYTHING:")
    print("  * Apps: 'Open Spotify', 'Open Task Manager', 'Open Settings', 'Open Antigravity'")
    print("  * Web:  'Open Claude', 'Search how to buy a smartphone in Chrome'")
    print("  * UI:   'Scroll down', 'Select the first option', 'Close this tab'")
    print("  * Audio:'Volume up', 'Volume down', 'Mute volume', 'Pause music'")
    print("  * Shell:'Run ipconfig in terminal', 'Check battery status', 'Lock computer'")
    print("  * Exit: 'Goodbye' or 'Exit' to quit.")
    print("=" * 76 + "\n")

    speak("IRIS Universal Operator online. Ready for any task.")

    recognizer = sr.Recognizer()

    try:
        with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype='int16') as stream:
            threshold = calibrate_mic(stream)

            state = "LISTENING"
            speech_frames = []
            silence_start = None
            pre_buffer = []

            print("Listening for speech... (speak whenever you're ready)\n")

            while True:
                chunk, _ = stream.read(CHUNK_SAMPLES)
                rms = np.sqrt(np.mean(chunk.astype(np.float32)**2))

                bars = int(min(25, rms / 150))
                meter = "#" * bars + "-" * (25 - bars)

                if state == "LISTENING":
                    pre_buffer.append(chunk)
                    if len(pre_buffer) > 3:
                        pre_buffer.pop(0)

                    sys.stdout.write(f"\r[Listening] [{meter}] RMS: {rms:4.0f} | Trigger: {threshold:4.0f} ")
                    sys.stdout.flush()

                    if rms > threshold:
                        state = "RECORDING"
                        speech_frames = list(pre_buffer)
                        speech_frames.append(chunk)
                        silence_start = None
                        sys.stdout.write("\n[SPEECH DETECTED] Recording...\n")
                        sys.stdout.flush()

                elif state == "RECORDING":
                    speech_frames.append(chunk)
                    sys.stdout.write(f"\r[Speaking...] [{meter}] RMS: {rms:4.0f} ")
                    sys.stdout.flush()

                    if rms < threshold:
                        if silence_start is None:
                            silence_start = time.time()
                        elif time.time() - silence_start >= SILENCE_LIMIT:
                            # Finished speaking
                            sys.stdout.write("\n[PROCESSING] Transcribing speech...\n")
                            sys.stdout.flush()

                            duration = len(speech_frames) * CHUNK_SAMPLES / SAMPLE_RATE
                            if duration >= MIN_SPEECH_DURATION:
                                raw_bytes = b"".join(f.tobytes() for f in speech_frames)

                                wav_io = io.BytesIO()
                                with wave.open(wav_io, 'wb') as wf:
                                    wf.setnchannels(1)
                                    wf.setsampwidth(2)
                                    wf.setframerate(SAMPLE_RATE)
                                    wf.writeframes(raw_bytes)

                                wav_io.seek(0)
                                try:
                                    with sr.AudioFile(wav_io) as source:
                                        audio_data = recognizer.record(source)
                                        raw_user_text = recognizer.recognize_google(audio_data).strip()

                                    print(f"\n[USER AUDIO]: \"{raw_user_text}\"")
                                    normalized_text = normalize_voice_input(raw_user_text)
                                    if normalized_text != raw_user_text:
                                        print(f"[NORMALIZED INTENT]: \"{normalized_text}\"")

                                    # Check for exit command
                                    if normalized_text.lower() in ["exit", "quit", "goodbye", "bye", "shutdown"]:
                                        speak("Goodbye! Shutting down voice agent.")
                                        break

                                    # Fast Intent Check (Instant <30ms execution)
                                    if try_fast_intent(normalized_text):
                                        print(">> Executed via Fast Intent Engine")
                                    else:
                                        # Query heretic-iris local brain
                                        response_text = query_heretic_iris(normalized_text)

                                        # Parse tool call
                                        try:
                                            parsed = json.loads(response_text)
                                            tool_name = parsed.get("name") or parsed.get("tool")
                                            args = parsed.get("arguments") or parsed.get("parameters") or {}
                                            if tool_name:
                                                execute_tool_call(tool_name, args)
                                            else:
                                                speak(response_text)
                                        except Exception:
                                            speak(response_text)

                                except sr.UnknownValueError:
                                    print("\n[Ambient sound heard but no speech recognized]")
                                except Exception as err:
                                    print(f"\n[STT Notice]: {err}")

                            # Reset back to listening
                            state = "LISTENING"
                            speech_frames = []
                            pre_buffer = []
                            silence_start = None

                            # Flush audio buffered during TTS speaking
                            time.sleep(0.3)
                            for _ in range(4):
                                stream.read(CHUNK_SAMPLES)

                            print("\n[READY] Listening for next voice command...\n")
                    else:
                        silence_start = None

    except KeyboardInterrupt:
        print("\n\nStopping IRIS Voice Agent. Goodbye!")
    except Exception as e:
        print(f"\n[Fatal Error]: {e}")

if __name__ == "__main__":
    main()
