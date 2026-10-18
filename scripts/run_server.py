#!/usr/bin/env python3
"""
IRIS-BOX Autonomous Computer Operator — Air-Gapped API Server Launcher.
Starts FastAPI application via Uvicorn on 127.0.0.1:8000 with socket air-gap guard
and API key authentication enabled.
"""

import sys
import os
import argparse
import logging
from pathlib import Path

# Add project root to sys.path
root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from dotenv import load_dotenv
load_dotenv()

import uvicorn
from src.security.airgap import socket_air_gap_guard
from src.security.auth import auth_manager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("iris.server.launcher")


def main():
    parser = argparse.ArgumentParser(
        description="Launch IRIS-BOX Control Center & Operator API Server with strict air-gap enforcement."
    )
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Host interface (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000, help="Listen port (default: 8000)")
    parser.add_argument("--reload", action="store_true", default=False, help="Enable Uvicorn auto-reload")
    parser.add_argument("--no-airgap", action="store_true", default=False, help="Disable socket air-gap guard (testing only)")

    args = parser.parse_args()

    master_key = auth_manager.get_master_key()
    masked_key = f"{master_key[:4]}...{master_key[-4:]}" if len(master_key) > 8 else "***"

    print("=" * 72)
    print("  IRIS-BOX: Personal AI Computer Operator — Live Server Launch")
    print("=" * 72)
    print(f"  Bind Address:       http://{args.host}:{args.port}")
    print(f"  Control Dashboard:  http://{args.host}:{args.port}/dashboard")
    print(f"  PWA Mobile Shell:   http://{args.host}:{args.port}/mobile")
    print(f"  API Authentication: ENABLED (X-API-Key / Bearer Token)")
    print(f"  Active Master Key:  {masked_key}")
    print(f"  Socket Air-Gap:     {'DISABLED' if args.no_airgap else 'ENFORCED (Loopback Only)'}")
    print("=" * 72)

    if args.no_airgap:
        logger.warning("AIR-GAP GUARD IS DISABLED VIA CLI FLAG.")
        uvicorn.run("src.server.app:app", host=args.host, port=args.port, reload=args.reload)
    else:
        logger.info("Activating strict socket air-gap guard (zero external network egress).")
        with socket_air_gap_guard():
            uvicorn.run("src.server.app:app", host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[IRIS-BOX] Server stopped by user.")
        sys.exit(0)
