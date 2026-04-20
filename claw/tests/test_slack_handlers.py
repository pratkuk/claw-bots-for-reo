"""Integration tests for the Slack handler chain.

These prove the full `/setup` → `/run-digest` round-trip against a real
config store on a tmpdir volume, with Reo and the agent stubbed. Slack
API calls are not made — we invoke the pure handler functions directly.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from claw_mcp.reo_client import ReoAuthError

from claw import config as config_store
from claw import slack_handlers as h

SEGMENTS = [
    {"id": "seg-1", "name": "Web3 infra shoppers"},
    {"id": "seg-2", "name": "Dormant accounts"},
]


# ─── helpers to build Slack view payloads ────────────────────


def _step1_view(api_key: str, tenant: str) -> dict:
    return {
        "state": {
            "values": {
                h.API_KEY_BLOCK: {h.API_KEY_ACTION: {"value": api_key}},
                h.TENANT_BLOCK: {h.TENANT_ACTION: {"value": tenant}},
            }
        }
    }


def _step2_view(
    *,
    api_key: str,
    tenant: str,
    segment_id: str,
    channel: str = "C_DIGEST",
    time_val: str = "09:00",
    tz: str = "America/Los_Angeles",
    limit: str = "5",
    web3: bool = True,
) -> dict:
    import json as _json

    web3_opts = (
        [{"value": "web3_only", "text": {"type": "plain_text", "text": "Web3"}}]
        if web3
        else []
    )
    return {
        "private_metadata": _json.dumps({"api_key": api_key, "tenant_id": tenant}),
        "state": {
            "values": {
                h.SEGMENT_BLOCK: {
                    h.SEGMENT_ACTION: {
                        "selected_option": {
                            "value": segment_id,
                            "text": {"type": "plain_text", "text": "x"},
                        }
                    }
                },
                h.CHANNEL_BLOCK: {h.CHANNEL_ACTION: {"selected_channel": channel}},
                h.SCHEDULE_TIME_BLOCK: {
                    h.SCHEDULE_TIME_ACTION: {
                        "selected_option": {
                            "value": time_val,
                            "text": {"type": "plain_text", "text": "x"},
                        }
                    }
                },
                h.SCHEDULE_TZ_BLOCK: {
                    h.SCHEDULE_TZ_ACTION: {
                        "selected_option": {
                            "value": tz,
                            "text": {"type": "plain_text", "text": "x"},
                        }
                    }
                },
                h.LIMIT_BLOCK: {h.LIMIT_ACTION: {"value": limit}},
                h.WEB3_BLOCK: {h.WEB3_ACTION: {"selected_options": web3_opts}},
            }
        },
    }


def _run_digest_view(segment_id: str) -> dict:
    return {
        "state": {
            "values": {
                h.SEGMENT_BLOCK: {
                    h.SEGMENT_ACTION: {
                        "selected_option": {
                            "value": segment_id,
                            "text": {"type": "plain_text", "text": "x"},
                        }
                    }
                }
            }
        }
    }


# ─── /setup step 1 ───────────────────────────────────────────


def test_setup_step1_bad_key_re_renders_error(
    encryption_key: str, volume_dir: Path
) -> None:
    def bad_validate(_key: str) -> None:
        raise ReoAuthError("401")

    result = h.handle_setup_step1_submit(
        _step1_view("sk_wrong", "tenant-1"),
        validate_fn=bad_validate,
        list_segments_fn=lambda _k: SEGMENTS,
    )
    assert result["callback_id"] == h.SETUP_STEP1_CALLBACK
    # Error banner is a section block above the inputs.
    assert any(
        b.get("type") == "section" and "Invalid Reo API key" in b["text"]["text"]
        for b in result["blocks"]
    )


def test_setup_step1_empty_fields_re_renders_error(
    encryption_key: str, volume_dir: Path
) -> None:
    result = h.handle_setup_step1_submit(
        _step1_view("", ""),
        validate_fn=lambda _k: None,
        list_segments_fn=lambda _k: SEGMENTS,
    )
    assert result["callback_id"] == h.SETUP_STEP1_CALLBACK


def test_setup_step1_success_pushes_step2(encryption_key: str) -> None:
    result = h.handle_setup_step1_submit(
        _step1_view("sk_good", "tenant-1"),
        validate_fn=lambda _k: None,
        list_segments_fn=lambda _k: SEGMENTS,
    )
    assert result["callback_id"] == h.SETUP_STEP2_CALLBACK
    # API key + tenant carried in private_metadata.
    import json as _json

    meta = _json.loads(result["private_metadata"])
    assert meta == {"api_key": "sk_good", "tenant_id": "tenant-1"}
    # Segment dropdown populated.
    seg_block = next(b for b in result["blocks"] if b["block_id"] == h.SEGMENT_BLOCK)
    opt_values = [o["value"] for o in seg_block["element"]["options"]]
    assert opt_values == ["seg-1", "seg-2"]


# ─── /setup step 2 ───────────────────────────────────────────


def test_setup_step2_persists_config(encryption_key: str, volume_dir: Path) -> None:
    view = _step2_view(
        api_key="sk_good",
        tenant="tenant-1",
        segment_id="seg-1",
        channel="C_DIGEST",
        time_val="09:00",
        tz="America/Los_Angeles",
    )
    cfg = h.handle_setup_step2_submit(
        view, team_id="T_XYZ", installer_user_id="U_ME", volume_dir=volume_dir
    )
    assert cfg["team_id"] == "T_XYZ"
    assert cfg["installer_user_id"] == "U_ME"
    assert cfg["reo_api_key"] == "sk_good"  # decrypted on load
    assert cfg["tenant_id"] == "tenant-1"
    assert cfg["default_segment_id"] == "seg-1"
    assert cfg["digest_channel_id"] == "C_DIGEST"
    assert cfg["schedule"] == {
        "cron": "0 9 * * *",
        "tz": "America/Los_Angeles",
        "cron_time": "09:00",
    }
    assert cfg["digest_limit"] == 5
    assert cfg["web3_only"] is True
    assert cfg["paused"] is False

    # Persistence check: a fresh load from disk returns the same data.
    persisted = config_store.load_config("T_XYZ", volume_dir)
    assert persisted == cfg


def test_setup_step2_manual_schedule(encryption_key: str, volume_dir: Path) -> None:
    view = _step2_view(
        api_key="sk_good",
        tenant="tenant-1",
        segment_id="seg-1",
        time_val=h.SCHEDULE_TIME_MANUAL,
    )
    cfg = h.handle_setup_step2_submit(
        view, team_id="T_M", installer_user_id="U_M", volume_dir=volume_dir
    )
    assert cfg["schedule"] is None


def test_setup_step2_rejects_bad_limit(encryption_key: str, volume_dir: Path) -> None:
    view = _step2_view(
        api_key="sk", tenant="t", segment_id="seg-1", limit="not-a-number"
    )
    with pytest.raises(ValueError):
        h.handle_setup_step2_submit(
            view, team_id="T", installer_user_id="U", volume_dir=volume_dir
        )


# ─── /run-digest ─────────────────────────────────────────────


def test_run_digest_no_config_raises(encryption_key: str, volume_dir: Path) -> None:
    with pytest.raises(LookupError) as ei:
        h.handle_run_digest_command(
            "T_UNSET", volume_dir, list_segments_fn=lambda _k: SEGMENTS
        )
    assert "/setup" in str(ei.value)


def test_run_digest_opens_picker_with_default_preselected(
    encryption_key: str, volume_dir: Path
) -> None:
    # Seed config.
    h.handle_setup_step2_submit(
        _step2_view(api_key="sk", tenant="t", segment_id="seg-2"),
        team_id="T_RD",
        installer_user_id="U_RD",
        volume_dir=volume_dir,
    )
    view = h.handle_run_digest_command(
        "T_RD", volume_dir, list_segments_fn=lambda _k: SEGMENTS
    )
    assert view["callback_id"] == h.RUN_DIGEST_CALLBACK
    seg_block = next(b for b in view["blocks"] if b["block_id"] == h.SEGMENT_BLOCK)
    assert seg_block["element"]["initial_option"]["value"] == "seg-2"


def test_run_digest_submit_updates_default_when_switched(
    encryption_key: str, volume_dir: Path
) -> None:
    h.handle_setup_step2_submit(
        _step2_view(api_key="sk", tenant="t", segment_id="seg-1"),
        team_id="T_RD2",
        installer_user_id="U_RD2",
        volume_dir=volume_dir,
    )
    cfg_before = config_store.load_config("T_RD2", volume_dir)
    assert cfg_before["default_segment_id"] == "seg-1"

    cfg_after, chosen = h.handle_run_digest_submit(
        _run_digest_view("seg-2"), team_id="T_RD2", volume_dir=volume_dir
    )
    assert chosen == "seg-2"
    assert cfg_after["default_segment_id"] == "seg-2"
    assert (
        config_store.load_config("T_RD2", volume_dir)["default_segment_id"] == "seg-2"
    )


def test_run_digest_submit_no_change_when_same_segment(
    encryption_key: str, volume_dir: Path
) -> None:
    h.handle_setup_step2_submit(
        _step2_view(api_key="sk", tenant="t", segment_id="seg-1"),
        team_id="T_SAME",
        installer_user_id="U",
        volume_dir=volume_dir,
    )
    before = config_store.load_config("T_SAME", volume_dir)
    cfg_after, chosen = h.handle_run_digest_submit(
        _run_digest_view("seg-1"), team_id="T_SAME", volume_dir=volume_dir
    )
    assert chosen == "seg-1"
    # updated_at should NOT have been re-stamped — we didn't re-save.
    assert cfg_after["updated_at"] == before["updated_at"]


# ─── end-to-end: install → setup → run-digest ────────────────


def test_e2e_setup_then_run_digest_uses_configured_channel(
    encryption_key: str, volume_dir: Path
) -> None:
    """Full happy path: a workspace with no config runs /setup, then
    /run-digest, and the digest would post to the configured channel
    (not the channel the slash command was invoked from).
    """
    team_id = "T_E2E"
    installer = "U_E2E"

    # Step 1 passes validation.
    step2 = h.handle_setup_step1_submit(
        _step1_view("sk_e2e", "tenant-e2e"),
        validate_fn=lambda _k: None,
        list_segments_fn=lambda _k: SEGMENTS,
    )
    assert step2["callback_id"] == h.SETUP_STEP2_CALLBACK

    # Step 2 saves config.
    cfg = h.handle_setup_step2_submit(
        _step2_view(
            api_key="sk_e2e", tenant="tenant-e2e", segment_id="seg-1", channel="C_REAL"
        ),
        team_id=team_id,
        installer_user_id=installer,
        volume_dir=volume_dir,
    )
    assert cfg["digest_channel_id"] == "C_REAL"

    # /run-digest loads the same config.
    picker = h.handle_run_digest_command(
        team_id, volume_dir, list_segments_fn=lambda _k: SEGMENTS
    )
    assert picker["callback_id"] == h.RUN_DIGEST_CALLBACK

    # On submit we get back the config — slack_app.py would thread this
    # into run_digest_agent + chat_postMessage(channel=digest_channel_id).
    cfg_after, chosen = h.handle_run_digest_submit(
        _run_digest_view("seg-1"), team_id=team_id, volume_dir=volume_dir
    )
    assert cfg_after["digest_channel_id"] == "C_REAL"
    assert chosen == "seg-1"
