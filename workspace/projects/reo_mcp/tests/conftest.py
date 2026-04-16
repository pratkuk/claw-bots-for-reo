"""Shared pytest fixtures for the reo_mcp test suite."""

from __future__ import annotations

import sys
from pathlib import Path

# Make `reo_mcp` importable when running `pytest` from the repo root.
_PROJECTS = Path(__file__).resolve().parents[2]
if str(_PROJECTS) not in sys.path:
    sys.path.insert(0, str(_PROJECTS))
