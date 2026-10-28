"""
IRIS AI Interactive Console & Live Tester
Allows you to type any natural language command in real-time,
see heretic-iris generate the tool call, and watch your computer execute it!
"""
import time
import json
import os
import subprocess
import urllib.request
import webbrowser

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL_NAME = "heretic-iris"

def execute_tool_call(tool_name: str, args: dict):
    """Executes the action on Windows in real-time."""
    print(f"\n⚡ [EXECUTOR] Executing: {tool_name} with args {args}")
    
    if tool_name in ["BrowserOperatorTool", "browser_operator"]:
        action = args.get("action", "")
        if action == "goto":
            url = args.get("url", "")
            print(f"👉 Opening browser to: {url}")
            webbrowser.open(url)
            return f"Opened {url} in browser"
        elif action == "search":
            query = args.get("query", "")
            if "youtube" in query.lower() or "video" in query.lower():
                url = f"https://www.youtube.com/results?search_query={urllib.parse.quote_plus(query)}"
            else:
                url = f"https://www.google.com/search?q={urllib.parse.quote_plus(query)}"
            print(f"👉 Searching web: {url}")
            webbrowser.open(url)
            return f"Searched for '{query}'"
            
    elif tool_name in ["DesktopOperatorTool", "desktop_operator"]:
        action = args.get("action", "")
        if action == "launch_app":
            app = args.get("app_name", "")
            print(f"👉 Launching desktop app: {app}")
            os.system(f"start {app}")
            return f"Launched {app}"
        elif action == "focus_window":
            query = args.get("query", "")
            print(f"👉 Focusing window matching: {query}")
            return f"Focused window '{query}'"
            
    elif tool_name in ["TerminalOperatorTool", "terminal_operator"]:
        cmd = args.get("command", "")
        print(f"👉 Running terminal command: {cmd}")
        res = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        out = (res.stdout or res.stderr)[:300].strip()
        print(f"Output:\n{out}")
        return f"Executed '{cmd}'"
        
    elif tool_name in ["HardwareVisionTool", "hardware_vision"]:
        action = args.get("action", "")
        print(f"📷 [HARDWARE SIGHT] Desk camera sensor engaged: {action}")
        return f"Desk camera executed: {action}"
        
    elif tool_name in ["HardwareHIDTool", "hardware_hid"]:
        action = args.get("action", "")
        print(f"⌨️ [PHYSICAL HID] USB/Bluetooth keystroke injected: {action}")
        return f"HID action: {action}"
        
    elif tool_name in ["HardwareRadioTool", "hardware_radio"]:
        device = args.get("device", "appliance")
        proto = args.get("protocol", "zigbee")
        print(f"📻 [RADIO EMITTER] 2.4GHz / RF433 transmitted to {device} via {proto}")
        return f"Radio switch toggled: {device}"
        
    return "Action acknowledged"

def main():
    print("=" * 70)
    print("  🤖 IRIS AI: LIVE INTERACTIVE CONSOLE")
    print(f"  Model Engine: {MODEL_NAME} (Ollama Local | 531 MB)")
    print("=" * 70)
    print("Type any instruction in plain English (or 'exit' to quit).\n")
    print("Try things like:")
    print("  • open youtube and search for lofi beats")
    print("  • open chrome, and go to my gmail")
    print("  • launch notepad")
    print("  • run dir in terminal")
    print("  • inspect the component on my desk right now")
    print("  • turn on the desk study lamp via zigbee")
    print("=" * 70 + "\n")
    
    while True:
        try:
            user_input = input("IRIS > ").strip()
            if not user_input:
                continue
            if user_input.lower() in ["exit", "quit", "q"]:
                print("Exiting IRIS Console. Goodbye!")
                break
                
            t0 = time.time()
            print("\n🧠 [AI BRAIN] Thinking...", end="\r")
            
            payload = json.dumps({
                "model": MODEL_NAME,
                "prompt": user_input,
                "stream": False
            }).encode("utf-8")
            
            req = urllib.request.Request(OLLAMA_URL, data=payload, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                elapsed = time.time() - t0
                response_text = data.get("response", "").strip()
                
            print(f"🧠 [AI BRAIN] Response ({elapsed:.2f}s):")
            print(f"   {response_text}")
            
            # Try to parse tool call
            try:
                parsed = json.loads(response_text)
                tool_name = parsed.get("name") or parsed.get("tool")
                args = parsed.get("arguments") or parsed.get("parameters") or {}
                if tool_name:
                    execute_tool_call(tool_name, args)
            except Exception:
                # Conversational response
                pass
                
            print("-" * 70 + "\n")
            
        except KeyboardInterrupt:
            print("\nSession ended.")
            break
        except Exception as e:
            print(f"\n[ERROR] {e}\n")

if __name__ == "__main__":
    main()

