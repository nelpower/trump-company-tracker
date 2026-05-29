"""Ensure the project root is importable as ``src`` regardless of how pytest
is invoked (belt-and-suspenders with pyproject's ``pythonpath``)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
