"""Unit tests for the per-workspace config store.

These cover load/save/delete round-trips, encryption-at-rest, file
permissions, and error paths. ``save_config`` is TODO — the tests that
exercise it are marked so they fail loudly until the contributor
implements it.
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from claw import config as config_mod
from claw.config import (
    CONFIG_DIRNAME,
    ConfigError,
    CorruptConfig,
    MissingEncryptionKey,
    delete_config,
    load_config,
    save_config,
)

SAMPLE: dict = {
    "team_id": "T_TEST",
    "installer_user_id": "U_TEST",
    "reo_api_key": "sk_test_plaintext_do_not_log",
    "tenant_id": "tenant-abc",
    "default_segment_id": "da8416c8-1111-2222-3333-444455556666",
    "digest_channel_id": "C_TEST",
    "schedule": {"cron": "0 9 * * *", "tz": "America/Los_Angeles"},
    "digest_limit": 5,
    "web3_only": True,
    "paused": False,
}


# ─── load_config ──────────────────────────────────────────────


def test_load_returns_none_when_missing(encryption_key: str, volume_dir: Path) -> None:
    assert load_config("T_NONE", volume_dir) is None


def test_load_rejects_bad_team_id(encryption_key: str, volume_dir: Path) -> None:
    with pytest.raises(ValueError):
        load_config("../evil", volume_dir)
    with pytest.raises(ValueError):
        load_config(".hidden", volume_dir)
    with pytest.raises(ValueError):
        load_config("", volume_dir)


def test_load_raises_on_corrupt_json(encryption_key: str, volume_dir: Path) -> None:
    cfg_dir = volume_dir / CONFIG_DIRNAME
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "T_BAD.json").write_text("{not json")
    with pytest.raises(CorruptConfig):
        load_config("T_BAD", volume_dir)


def test_load_raises_on_undecryptable_key(
    encryption_key: str, volume_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg_dir = volume_dir / CONFIG_DIRNAME
    cfg_dir.mkdir(parents=True)
    # Write a blob encrypted under a DIFFERENT key.
    other = Fernet(Fernet.generate_key())
    blob = other.encrypt(b"sk_whatever").decode()
    (cfg_dir / "T_WRONG.json").write_text(json.dumps({"reo_api_key_encrypted": blob}))
    with pytest.raises(CorruptConfig):
        load_config("T_WRONG", volume_dir)


# ─── encryption env var ───────────────────────────────────────


def test_missing_env_raises(monkeypatch: pytest.MonkeyPatch, volume_dir: Path) -> None:
    monkeypatch.delenv(config_mod.ENCRYPTION_KEY_ENV, raising=False)
    cfg_dir = volume_dir / CONFIG_DIRNAME
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "T_X.json").write_text(json.dumps({"reo_api_key_encrypted": "x"}))
    with pytest.raises(MissingEncryptionKey):
        load_config("T_X", volume_dir)


# ─── save_config (requires the TODO implementation) ──────────


def test_save_then_load_roundtrip(encryption_key: str, volume_dir: Path) -> None:
    save_config("T_RT", SAMPLE, volume_dir)
    loaded = load_config("T_RT", volume_dir)
    assert loaded is not None
    assert loaded["reo_api_key"] == SAMPLE["reo_api_key"]
    assert loaded["tenant_id"] == SAMPLE["tenant_id"]
    assert loaded["schedule"] == SAMPLE["schedule"]
    assert "reo_api_key_encrypted" not in loaded  # decrypted on load


def test_save_encrypts_api_key_on_disk(encryption_key: str, volume_dir: Path) -> None:
    save_config("T_ENC", SAMPLE, volume_dir)
    raw = json.loads((volume_dir / CONFIG_DIRNAME / "T_ENC.json").read_text())
    assert "reo_api_key" not in raw, "plaintext key must never hit disk"
    assert "reo_api_key_encrypted" in raw
    assert SAMPLE["reo_api_key"] not in raw["reo_api_key_encrypted"]


def test_save_sets_0600_perms(encryption_key: str, volume_dir: Path) -> None:
    save_config("T_PERM", SAMPLE, volume_dir)
    path = volume_dir / CONFIG_DIRNAME / "T_PERM.json"
    mode = stat.S_IMODE(os.stat(path).st_mode)
    assert mode == 0o600, f"expected 0600, got {oct(mode)}"


def test_save_stamps_timestamps(encryption_key: str, volume_dir: Path) -> None:
    save_config("T_TS", SAMPLE, volume_dir)
    loaded = load_config("T_TS", volume_dir)
    assert loaded is not None
    assert "created_at" in loaded
    assert "updated_at" in loaded


def test_save_does_not_mutate_caller_dict(encryption_key: str, volume_dir: Path) -> None:
    cfg = dict(SAMPLE)
    save_config("T_IMMUT", cfg, volume_dir)
    assert cfg == SAMPLE, "save_config must not mutate the caller's dict"


def test_save_overwrite_preserves_created_at(
    encryption_key: str, volume_dir: Path
) -> None:
    save_config("T_OVER", SAMPLE, volume_dir)
    first = load_config("T_OVER", volume_dir)
    assert first is not None
    save_config("T_OVER", SAMPLE, volume_dir)
    second = load_config("T_OVER", volume_dir)
    assert second is not None
    assert second["created_at"] == first["created_at"]


# ─── delete_config ────────────────────────────────────────────


def test_delete_returns_false_when_missing(
    encryption_key: str, volume_dir: Path
) -> None:
    assert delete_config("T_GONE", volume_dir) is False


def test_delete_removes_file(encryption_key: str, volume_dir: Path) -> None:
    save_config("T_DEL", SAMPLE, volume_dir)
    assert delete_config("T_DEL", volume_dir) is True
    assert load_config("T_DEL", volume_dir) is None


def test_delete_rejects_bad_team_id(encryption_key: str, volume_dir: Path) -> None:
    with pytest.raises(ValueError):
        delete_config("../evil", volume_dir)


# ─── sanity: ConfigError hierarchy ────────────────────────────


def test_error_hierarchy() -> None:
    assert issubclass(MissingEncryptionKey, ConfigError)
    assert issubclass(CorruptConfig, ConfigError)
