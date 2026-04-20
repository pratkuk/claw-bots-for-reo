"""Shared fixtures for the claw/ host-layer test suite."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))
# Make claw_mcp importable too — it lives under workspace/projects/.
_PROJECTS = _REPO / "workspace" / "projects"
if str(_PROJECTS) not in sys.path:
    sys.path.insert(0, str(_PROJECTS))

from claw import config as config_mod  # noqa: E402


@pytest.fixture
def encryption_key(monkeypatch: pytest.MonkeyPatch) -> str:
    key = Fernet.generate_key().decode()
    monkeypatch.setenv(config_mod.ENCRYPTION_KEY_ENV, key)
    return key


@pytest.fixture
def volume_dir(tmp_path: Path) -> Path:
    return tmp_path / "volume"
