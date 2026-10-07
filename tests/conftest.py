import os
import sys

# Add the project root to sys.path
# This allows imports like 'from src.models.schemas import ...' to work
sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
)
