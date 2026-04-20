"""Per-workspace config store.

One file per Slack ``team_id`` on the Railway volume:

    {volume_dir}/.claw_configs/{team_id}.json

On disk the file is plain JSON with one exception: ``reo_api_key`` is
encrypted with Fernet (key sourced from ``CLAW_CONFIG_ENCRYPTION_KEY``)
and stored under ``reo_api_key_encrypted``. Everything else (tenant_id,
segment_id, channel, schedule, flags) stays readable so an operator
SSHing into the volume can debug without a decryption key.

Files are written with perms ``0600``. See DECISIONS.md 2026-04-20 D1.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

CONFIG_DIRNAME = ".claw_configs"
ENCRYPTION_KEY_ENV = "CLAW_CONFIG_ENCRYPTION_KEY"
_ENCRYPTED_FIELDS = ("reo_api_key",)  # plaintext key -> stored as <field>_encrypted


class ConfigError(Exception):
    """Base class for config store errors."""


class MissingEncryptionKey(ConfigError):
    """CLAW_CONFIG_ENCRYPTION_KEY is unset or empty."""


class CorruptConfig(ConfigError):
    """Config file exists but cannot be decrypted or parsed."""


# ─────────────────────────────────────────────────────────────
# Fernet helpers
# ─────────────────────────────────────────────────────────────


def _fernet() -> Fernet:
    key = os.environ.get(ENCRYPTION_KEY_ENV, "").strip()
    if not key:
        raise MissingEncryptionKey(
            f"{ENCRYPTION_KEY_ENV} is unset. Generate once with "
            "`python -c 'from cryptography.fernet import Fernet; "
            "print(Fernet.generate_key().decode())'` and set it on Railway."
        )
    return Fernet(key.encode())


def _encrypt(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def _decrypt(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken as exc:
        raise CorruptConfig("reo_api_key_encrypted failed to decrypt") from exc


# ─────────────────────────────────────────────────────────────
# Paths
# ─────────────────────────────────────────────────────────────


def _config_dir(volume_dir: Path) -> Path:
    return volume_dir / CONFIG_DIRNAME


def _config_path(volume_dir: Path, team_id: str) -> Path:
    if not team_id or "/" in team_id or team_id.startswith("."):
        raise ValueError(f"invalid team_id: {team_id!r}")
    return _config_dir(volume_dir) / f"{team_id}.json"


# ─────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────


def load_config(team_id: str, volume_dir: Path) -> dict[str, Any] | None:
    """Return the decrypted config for ``team_id``, or ``None`` if missing.

    The returned dict has ``reo_api_key`` (plaintext) rather than
    ``reo_api_key_encrypted``. Callers should treat it as sensitive and
    never log it.
    """
    path = _config_path(volume_dir, team_id)
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise CorruptConfig(f"{path} is not valid JSON") from exc

    for field in _ENCRYPTED_FIELDS:
        enc_key = f"{field}_encrypted"
        if enc_key in raw:
            raw[field] = _decrypt(raw.pop(enc_key))
    return raw


def save_config(team_id: str, config: dict[str, Any], volume_dir: Path) -> None:
    """Write ``config`` for ``team_id`` with ``0600`` perms, encrypting secrets.

    Atomic: writes to a temp file (created with ``0600`` perms at the syscall
    level) then ``os.replace``s into place, so a concurrent reader never sees
    a half-written file. ``created_at`` is preserved across overwrites.
    """
    path = _config_path(volume_dir, team_id)
    cfg_dir = _config_dir(volume_dir)
    cfg_dir.mkdir(parents=True, exist_ok=True, mode=0o700)

    to_write: dict[str, Any] = dict(config)  # don't mutate caller
    for field in _ENCRYPTED_FIELDS:
        if field in to_write:
            to_write[f"{field}_encrypted"] = _encrypt(to_write.pop(field))

    now = _utcnow_iso()
    to_write["updated_at"] = now
    if "created_at" not in to_write:
        if path.exists():
            try:
                prior = json.loads(path.read_text())
                to_write["created_at"] = prior.get("created_at", now)
            except json.JSONDecodeError:
                to_write["created_at"] = now
        else:
            to_write["created_at"] = now

    tmp = path.with_suffix(path.suffix + ".tmp")
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(to_write, f, indent=2, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        import contextlib

        with contextlib.suppress(FileNotFoundError):
            tmp.unlink()
        raise


def delete_config(team_id: str, volume_dir: Path) -> bool:
    """Remove the config file for ``team_id``.

    Returns ``True`` if a file was deleted, ``False`` if none existed.
    Used by the Slack ``app_uninstalled`` handler (plan §8).
    """
    path = _config_path(volume_dir, team_id)
    try:
        path.unlink()
        return True
    except FileNotFoundError:
        return False


def _utcnow_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
