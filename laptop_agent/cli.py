from __future__ import annotations
import sys
import os
import json
import asyncio
import argparse
from pathlib import Path

# Add IRISBOX root to pythonpath
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from laptop_agent.dispatcher import ToolDispatcher
from laptop_agent.config import load_config
from laptop_agent.client import LaptopAgentClient

CATALOG_PATH = Path(__file__).resolve().parent / "test_commands.json"


def print_banner():
    banner = """
================================================================================
           IRIS-BOX Laptop Agent: Interactive Command Verification
================================================================================
Control any application, website, and desktop tool using structured JSON.
================================================================================
"""
    print(banner)


async def run_single_command(dispatcher: ToolDispatcher, payload: dict):
    """Execute a single JSON command and display formatted output."""
    print(f"\n>> Executing command: {json.dumps(payload, indent=2)}")
    result = await dispatcher.dispatch(payload)
    print("\n<< Execution Result:")
    print(json.dumps(result, indent=2))
    return result


async def interactive_loop(device_name: str = "laptop1"):
    dispatcher = ToolDispatcher(device_name=device_name)
    print_banner()

    # Load catalog if exists
    catalog = {}
    if CATALOG_PATH.exists():
        try:
            with open(CATALOG_PATH, "r", encoding="utf-8") as f:
                catalog = json.load(f)
        except Exception:
            pass

    while True:
        print("\n--- Granular Step-by-Step Flow ---")
        print("  [1] Step 1: Open YouTube")
        print("  [2] Step 2: Search YouTube (type query in search bar)")
        print("  [3] Step 3: Scroll Down / Up (browse search results)")
        print("  [4] Step 4: Play specific video (1st, 2nd, nth result)")
        print("  [5] Step 5: Play YouTube Short (clicks short from results)")
        print("  [6] Step 6: Native Player Fullscreen (YouTube player 'f')")
        print("  [7] Skip Ad (clicks YouTube ad skip button)")
        print("\n--- Multi-Service Music & Other Apps ---")
        print("  [8] Search & Play on Spotify (desktop or web)")
        print("  [9] Search & Play on Apple Music")
        print(" [10] All-in-One Compound: Open -> Search -> Play -> Fullscreen")
        print(" [11] Open Claude and send prompt")
        print(" [12] Open Notepad and type text")
        print(" [13] Adjust Master Volume Up / Down")
        print(" [14] Type custom raw JSON command")
        print(" [15] Start WebSocket Agent (connect to Phone A / IRIS Hub)")
        print("  [q] Quit")

        choice = input("\nEnter choice (1-15 or q): ").strip()
        if choice in ("q", "quit", "exit"):
            print("Exiting interactive tester.")
            break

        if choice == "1":
            await run_single_command(dispatcher, {"tool": "open_youtube"})

        elif choice == "2":
            q = input("Search query [soothing songs]: ").strip() or "soothing songs"
            await run_single_command(dispatcher, {"tool": "search_youtube", "args": {"query": q}})

        elif choice == "3":
            d = input("Direction (down/up) [down]: ").strip().lower() or "down"
            await run_single_command(dispatcher, {"tool": "scroll", "args": {"direction": d, "amount": 600}})

        elif choice == "4":
            n = int(input("Play video result # (1, 2, 3...) [1]: ").strip() or "1")
            await run_single_command(dispatcher, {"tool": "play_video", "args": {"nth": n}})

        elif choice == "5":
            n = int(input("Play Short # [1]: ").strip() or "1")
            await run_single_command(dispatcher, {"tool": "play_short", "args": {"nth": n}})

        elif choice == "6":
            await run_single_command(dispatcher, {"tool": "fullscreen"})

        elif choice == "7":
            await run_single_command(dispatcher, {"tool": "skip_ad"})

        elif choice == "8":
            q = input("Song or artist to search on Spotify: ").strip() or "soothing piano"
            await run_single_command(dispatcher, {"tool": "search_media", "args": {"service": "spotify", "query": q}})

        elif choice == "9":
            q = input("Song or artist to search on Apple Music: ").strip() or "chill acoustic"
            await run_single_command(dispatcher, {"tool": "search_media", "args": {"service": "apple_music", "query": q}})

        elif choice == "10":
            q = input("Song name or vibe [soothing lofi beats]: ").strip() or "soothing lofi beats"
            svc = input("Service (youtube/spotify/apple_music) [youtube]: ").strip().lower() or "youtube"
            await run_single_command(dispatcher, {
                "tool": "play_music",
                "args": {"service": svc, "query": q, "nth": 1, "fullscreen": True}
            })

        elif choice == "11":
            prompt = input("Enter prompt for Claude: ").strip() or "what is the population of earth"
            await run_single_command(dispatcher, {"tool": "claude_send", "args": {"prompt": prompt}})

        elif choice == "12":
            notepad_cmds = [
                {"tool": "open_app", "args": {"name": "notepad"}},
                {"tool": "type_text", "args": {"text": "Hello from IRIS Laptop Agent!\nTesting multi-turn commands.\n", "press_enter": True}}
            ]
            for cmd in notepad_cmds:
                await run_single_command(dispatcher, cmd)
                await asyncio.sleep(0.5)

        elif choice == "13":
            direction = input("Volume direction (up/down/mute) [up]: ").strip().lower() or "up"
            steps = int(input("Steps (1-10) [4]: ").strip() or "4")
            await run_single_command(dispatcher, {"tool": "volume", "args": {"action": direction, "steps": steps}})

        elif choice == "14":
            print("\nEnter or paste your JSON command:")
            raw_input = input("> ").strip()
            if raw_input:
                try:
                    payload = json.loads(raw_input)
                    await run_single_command(dispatcher, payload)
                except json.JSONDecodeError as e:
                    print(f"Error: Invalid JSON syntax ({e})")

        elif choice == "15":
            client = LaptopAgentClient()
            print(f"Starting WebSocket agent connecting to {client.config.hub_url}...")
            print("Press Ctrl+C to return to menu.")
            try:
                await client.start()
            except KeyboardInterrupt:
                print("\nAgent stopped.")


async def main():
    parser = argparse.ArgumentParser(description="IRIS-BOX Laptop Agent CLI")
    parser.add_argument("--device", default="laptop1", help="Device identifier (default: laptop1)")
    parser.add_argument("--cmd", type=str, help="Raw JSON command string to execute directly")
    parser.add_argument("--file", type=str, help="Path to JSON file containing command")
    parser.add_argument("--agent", action="store_true", help="Start continuous WebSocket agent client")
    args = parser.parse_args()

    dispatcher = ToolDispatcher(device_name=args.device)

    # Check for piped input from stdin
    if not sys.stdin.isatty() and not args.cmd and not args.file and not args.agent:
        raw_stdin = sys.stdin.read().strip()
        if raw_stdin:
            try:
                payload = json.loads(raw_stdin)
                await run_single_command(dispatcher, payload)
                return
            except json.JSONDecodeError as exc:
                print(f"Failed to parse stdin JSON: {exc}", file=sys.stderr)
                sys.exit(1)

    if args.file:
        file_path = Path(args.file)
        if not file_path.exists():
            print(f"Error: file not found: {args.file}", file=sys.stderr)
            sys.exit(1)
        with open(file_path, "r", encoding="utf-8") as f:
            payload = json.load(f)
        await run_single_command(dispatcher, payload)
    elif args.cmd:
        try:
            payload = json.loads(args.cmd)
            await run_single_command(dispatcher, payload)
        except json.JSONDecodeError as exc:
            print(f"Failed to parse JSON command: {exc}", file=sys.stderr)
            sys.exit(1)
    elif args.agent:
        client = LaptopAgentClient()
        await client.start()
    else:
        await interactive_loop(device_name=args.device)


if __name__ == "__main__":
    asyncio.run(main())
