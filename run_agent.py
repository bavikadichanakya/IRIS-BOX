import sys
from pathlib import Path

# Ensure A:\IRISBOX is on sys.path
root_dir = Path(__file__).resolve().parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

import asyncio
from laptop_agent.cli import main

if __name__ == "__main__":
    asyncio.run(main())
