"""Slack handler logic as plain functions, decoupled from Bolt.

Bolt decorators in ``claw/slack_app.py`` call thin wrappers that call
these. Keeping the logic pure lets tests invoke handlers without
spinning up an HTTP server.

Modal design (v1):
  ``/setup`` opens a two-step modal. Step 1 collects API key + tenant ID,
  validates against Reo (``list_segments``). On success, step 2 is pushed
  with a populated segment dropdown, channel picker, schedule, limit,
  web3 flag. Submit → save config + first-run DM.

  ``/run-digest`` opens a single segment-picker modal pre-selected to
  ``default_segment_id``. Submit → run the agent against the chosen
  segment, post to ``digest_channel_id`` (NOT the channel the command was
  invoked from), update ``default_segment_id`` to the chosen one.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from . import config as config_store
from .errors import (
    list_segments_safe,
    map_reo_error,
    validate_api_key,
)

# ─────────────────────────────────────────────────────────────
# Callback IDs (stable strings — referenced by Bolt view matchers)
# ─────────────────────────────────────────────────────────────

SETUP_STEP1_CALLBACK = "claw_setup_step1"
SETUP_STEP2_CALLBACK = "claw_setup_step2"
RUN_DIGEST_CALLBACK = "claw_run_digest_picker"

# Block / action IDs — used to read values out of submission payloads.
API_KEY_BLOCK = "api_key_block"
API_KEY_ACTION = "api_key_input"
TENANT_BLOCK = "tenant_block"
TENANT_ACTION = "tenant_input"
SEGMENT_BLOCK = "segment_block"
SEGMENT_ACTION = "segment_select"
CHANNEL_BLOCK = "channel_block"
CHANNEL_ACTION = "channel_select"
SCHEDULE_TIME_BLOCK = "schedule_time_block"
SCHEDULE_TIME_ACTION = "schedule_time_select"
SCHEDULE_TZ_BLOCK = "schedule_tz_block"
SCHEDULE_TZ_ACTION = "schedule_tz_select"
LIMIT_BLOCK = "limit_block"
LIMIT_ACTION = "limit_input"
WEB3_BLOCK = "web3_block"
WEB3_ACTION = "web3_checkbox"

SCHEDULE_TIME_MANUAL = "manual"
DEFAULT_TIMEZONES = [
    ("America/Los_Angeles", "Los Angeles"),
    ("America/New_York", "New York"),
    ("Europe/London", "London"),
    ("Europe/Berlin", "Berlin"),
    ("Asia/Singapore", "Singapore"),
    ("Asia/Tokyo", "Tokyo"),
    ("Asia/Kolkata", "Mumbai / Bangalore"),
]
DEFAULT_SCHEDULE_TIMES = [
    (SCHEDULE_TIME_MANUAL, "Manual only (no schedule)"),
    ("09:00", "9 AM"),
    ("10:00", "10 AM"),
    ("14:00", "2 PM"),
    ("17:00", "5 PM"),
]


# ─────────────────────────────────────────────────────────────
# Block builders
# ─────────────────────────────────────────────────────────────


def build_setup_step1_view(error: str | None = None) -> dict[str, Any]:
    """First-step modal: API key + tenant ID."""
    blocks: list[dict[str, Any]] = []
    if error:
        blocks.append(
            {"type": "section", "text": {"type": "mrkdwn", "text": f":warning: {error}"}}
        )
    blocks.extend(
        [
            {
                "type": "input",
                "block_id": API_KEY_BLOCK,
                "label": {"type": "plain_text", "text": "Reo API key"},
                "element": {
                    "type": "plain_text_input",
                    "action_id": API_KEY_ACTION,
                    "placeholder": {"type": "plain_text", "text": "sk_..."},
                },
            },
            {
                "type": "input",
                "block_id": TENANT_BLOCK,
                "label": {"type": "plain_text", "text": "Reo tenant ID"},
                "element": {
                    "type": "plain_text_input",
                    "action_id": TENANT_ACTION,
                },
            },
        ]
    )
    return {
        "type": "modal",
        "callback_id": SETUP_STEP1_CALLBACK,
        "title": {"type": "plain_text", "text": "Claw setup · 1 of 2"},
        "submit": {"type": "plain_text", "text": "Next"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": blocks,
    }


def build_setup_step2_view(
    api_key: str,
    tenant_id: str,
    segments: list[dict[str, Any]],
    existing: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Second-step modal: segment, channel, schedule, limit, web3.

    ``api_key`` and ``tenant_id`` ride in ``private_metadata`` as JSON so
    the submission handler can persist them without re-prompting.
    """
    existing = existing or {}
    segment_options = [
        {
            "text": {"type": "plain_text", "text": s["name"][:75]},
            "value": s["id"],
        }
        for s in segments
    ]
    if not segment_options:
        segment_options = [
            {"text": {"type": "plain_text", "text": "(no segments)"}, "value": "none"}
        ]

    time_options = [
        {"text": {"type": "plain_text", "text": label}, "value": value}
        for value, label in DEFAULT_SCHEDULE_TIMES
    ]
    tz_options = [
        {"text": {"type": "plain_text", "text": label}, "value": value}
        for value, label in DEFAULT_TIMEZONES
    ]

    private = json.dumps({"api_key": api_key, "tenant_id": tenant_id})

    initial_segment = existing.get("default_segment_id") or segment_options[0]["value"]
    initial_segment_opt = next(
        (o for o in segment_options if o["value"] == initial_segment), segment_options[0]
    )
    initial_time = existing.get("schedule", {}).get("cron_time") or "09:00"
    initial_time_opt = next(
        (o for o in time_options if o["value"] == initial_time), time_options[1]
    )
    initial_tz = existing.get("schedule", {}).get("tz") or "America/Los_Angeles"
    initial_tz_opt = next(
        (o for o in tz_options if o["value"] == initial_tz), tz_options[0]
    )
    initial_limit = str(existing.get("digest_limit", 5))
    initial_web3 = existing.get("web3_only", True)

    blocks: list[dict[str, Any]] = [
        {
            "type": "input",
            "block_id": SEGMENT_BLOCK,
            "label": {"type": "plain_text", "text": "Default segment"},
            "element": {
                "type": "static_select",
                "action_id": SEGMENT_ACTION,
                "options": segment_options,
                "initial_option": initial_segment_opt,
            },
        },
        {
            "type": "input",
            "block_id": CHANNEL_BLOCK,
            "label": {"type": "plain_text", "text": "Digest channel"},
            "element": {
                "type": "channels_select",
                "action_id": CHANNEL_ACTION,
                **(
                    {"initial_channel": existing["digest_channel_id"]}
                    if existing.get("digest_channel_id")
                    else {}
                ),
            },
        },
        {
            "type": "input",
            "block_id": SCHEDULE_TIME_BLOCK,
            "label": {"type": "plain_text", "text": "Schedule"},
            "element": {
                "type": "static_select",
                "action_id": SCHEDULE_TIME_ACTION,
                "options": time_options,
                "initial_option": initial_time_opt,
            },
        },
        {
            "type": "input",
            "block_id": SCHEDULE_TZ_BLOCK,
            "label": {"type": "plain_text", "text": "Timezone"},
            "element": {
                "type": "static_select",
                "action_id": SCHEDULE_TZ_ACTION,
                "options": tz_options,
                "initial_option": initial_tz_opt,
            },
        },
        {
            "type": "input",
            "block_id": LIMIT_BLOCK,
            "label": {"type": "plain_text", "text": "Digest limit"},
            "element": {
                "type": "plain_text_input",
                "action_id": LIMIT_ACTION,
                "initial_value": initial_limit,
            },
        },
        {
            "type": "input",
            "block_id": WEB3_BLOCK,
            "optional": True,
            "label": {"type": "plain_text", "text": "Filter"},
            "element": {
                "type": "checkboxes",
                "action_id": WEB3_ACTION,
                "options": [
                    {
                        "text": {"type": "plain_text", "text": "Web3 companies only"},
                        "value": "web3_only",
                    }
                ],
                **(
                    {
                        "initial_options": [
                            {
                                "text": {
                                    "type": "plain_text",
                                    "text": "Web3 companies only",
                                },
                                "value": "web3_only",
                            }
                        ]
                    }
                    if initial_web3
                    else {}
                ),
            },
        },
    ]

    return {
        "type": "modal",
        "callback_id": SETUP_STEP2_CALLBACK,
        "title": {"type": "plain_text", "text": "Claw setup · 2 of 2"},
        "submit": {"type": "plain_text", "text": "Save"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "private_metadata": private,
        "blocks": blocks,
    }


def build_run_digest_view(
    segments: list[dict[str, Any]], default_segment_id: str
) -> dict[str, Any]:
    options = [
        {
            "text": {"type": "plain_text", "text": s["name"][:75]},
            "value": s["id"],
        }
        for s in segments
    ] or [
        {"text": {"type": "plain_text", "text": "(no segments)"}, "value": "none"}
    ]
    initial = next(
        (o for o in options if o["value"] == default_segment_id), options[0]
    )
    return {
        "type": "modal",
        "callback_id": RUN_DIGEST_CALLBACK,
        "title": {"type": "plain_text", "text": "Run digest"},
        "submit": {"type": "plain_text", "text": "Run"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": [
            {
                "type": "input",
                "block_id": SEGMENT_BLOCK,
                "label": {"type": "plain_text", "text": "Segment"},
                "element": {
                    "type": "static_select",
                    "action_id": SEGMENT_ACTION,
                    "options": options,
                    "initial_option": initial,
                },
            }
        ],
    }


# ─────────────────────────────────────────────────────────────
# Submission readers
# ─────────────────────────────────────────────────────────────


def _values(view: dict[str, Any]) -> dict[str, Any]:
    return view.get("state", {}).get("values", {})


def read_step1(view: dict[str, Any]) -> tuple[str, str]:
    v = _values(view)
    api_key = v[API_KEY_BLOCK][API_KEY_ACTION]["value"].strip()
    tenant_id = v[TENANT_BLOCK][TENANT_ACTION]["value"].strip()
    return api_key, tenant_id


def read_step2(view: dict[str, Any]) -> dict[str, Any]:
    v = _values(view)
    meta = json.loads(view.get("private_metadata", "{}"))
    web3_selected = bool(
        v.get(WEB3_BLOCK, {}).get(WEB3_ACTION, {}).get("selected_options") or []
    )
    limit_raw = v[LIMIT_BLOCK][LIMIT_ACTION]["value"].strip()
    try:
        digest_limit = int(limit_raw)
    except ValueError as exc:
        raise ValueError(f"digest_limit must be an integer, got {limit_raw!r}") from exc
    time_val = v[SCHEDULE_TIME_BLOCK][SCHEDULE_TIME_ACTION]["selected_option"]["value"]
    tz_val = v[SCHEDULE_TZ_BLOCK][SCHEDULE_TZ_ACTION]["selected_option"]["value"]
    schedule: dict[str, Any] | None
    if time_val == SCHEDULE_TIME_MANUAL:
        schedule = None
    else:
        hour, _minute = time_val.split(":")
        schedule = {"cron": f"0 {int(hour)} * * *", "tz": tz_val, "cron_time": time_val}
    return {
        "reo_api_key": meta["api_key"],
        "tenant_id": meta["tenant_id"],
        "default_segment_id": v[SEGMENT_BLOCK][SEGMENT_ACTION]["selected_option"][
            "value"
        ],
        "digest_channel_id": v[CHANNEL_BLOCK][CHANNEL_ACTION]["selected_channel"],
        "schedule": schedule,
        "digest_limit": digest_limit,
        "web3_only": web3_selected,
    }


def read_run_digest_segment(view: dict[str, Any]) -> str:
    return _values(view)[SEGMENT_BLOCK][SEGMENT_ACTION]["selected_option"]["value"]


# ─────────────────────────────────────────────────────────────
# Handlers (pure — Bolt wrappers in slack_app.py call these)
# ─────────────────────────────────────────────────────────────


def handle_setup_step1_submit(
    view: dict[str, Any],
    *,
    validate_fn: Callable[[str], None] = validate_api_key,
    list_segments_fn: Callable[[str], list[dict[str, Any]]] = list_segments_safe,
) -> dict[str, Any]:
    """Validate API key, list segments, return either the step-2 view or an error.

    Returns a Slack ``views.update``-compatible dict. On error, re-renders
    step 1 with the error banner; on success, returns the step-2 view.
    """
    try:
        api_key, tenant_id = read_step1(view)
    except (KeyError, AttributeError, ValueError):
        return build_setup_step1_view(error="Please fill in both fields.")

    if not api_key or not tenant_id:
        return build_setup_step1_view(error="Please fill in both fields.")

    try:
        validate_fn(api_key)
        segments = list_segments_fn(api_key)
    except Exception as exc:
        return build_setup_step1_view(error=map_reo_error(exc))

    return build_setup_step2_view(api_key=api_key, tenant_id=tenant_id, segments=segments)


def handle_setup_step2_submit(
    view: dict[str, Any],
    team_id: str,
    installer_user_id: str,
    volume_dir: Path,
) -> dict[str, Any]:
    """Persist config for ``team_id``. Returns the saved (decrypted) record."""
    fields = read_step2(view)
    existing = config_store.load_config(team_id, volume_dir) or {}
    record = {
        **existing,
        **fields,
        "team_id": team_id,
        "installer_user_id": installer_user_id,
        "paused": existing.get("paused", False),
    }
    config_store.save_config(team_id, record, volume_dir)
    return config_store.load_config(team_id, volume_dir)  # type: ignore[return-value]


def handle_run_digest_command(
    team_id: str,
    volume_dir: Path,
    *,
    list_segments_fn: Callable[[str], list[dict[str, Any]]] = list_segments_safe,
) -> dict[str, Any]:
    """Return the segment-picker modal view, or a no-config error view.

    Raises ``LookupError`` with a user-facing message if no config exists.
    """
    cfg = config_store.load_config(team_id, volume_dir)
    if cfg is None:
        raise LookupError("Run `/setup` first — no config for this workspace.")
    segments = list_segments_fn(cfg["reo_api_key"])
    return build_run_digest_view(
        segments=segments, default_segment_id=cfg.get("default_segment_id", "")
    )


def handle_run_digest_submit(
    view: dict[str, Any],
    team_id: str,
    volume_dir: Path,
) -> tuple[dict[str, Any], str]:
    """Return ``(config, chosen_segment_id)`` and update the default.

    Caller is responsible for running the agent and posting to
    ``config["digest_channel_id"]`` — that work is threaded and doesn't
    fit in the 3-second Slack ack window.
    """
    cfg = config_store.load_config(team_id, volume_dir)
    if cfg is None:
        raise LookupError("Run `/setup` first — no config for this workspace.")
    segment_id = read_run_digest_segment(view)
    if segment_id != cfg.get("default_segment_id"):
        cfg["default_segment_id"] = segment_id
        config_store.save_config(team_id, cfg, volume_dir)
        cfg = config_store.load_config(team_id, volume_dir)  # type: ignore[assignment]
    return cfg, segment_id
