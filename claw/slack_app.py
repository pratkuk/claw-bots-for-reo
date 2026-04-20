"""Bolt app factory: wires handlers from ``slack_handlers`` to Slack.

This replaces the monolithic ``scripts/spike_slack_live.py``. All logic
lives in ``slack_handlers`` (pure) and ``agent`` (agent runner) so this
file stays a shallow adapter.

Environment:
  SLACK_CLIENT_ID, SLACK_CLIENT_SECRET, SLACK_SIGNING_SECRET — OAuth.
  CLAW_CONFIG_ENCRYPTION_KEY — Fernet key for config-at-rest.
  CLAW_VOLUME_DIR — path to the persistent volume (default: ./workspace).
"""

from __future__ import annotations

import logging
import os
import threading
import traceback
from datetime import date
from pathlib import Path

from flask import Flask, request
from slack_bolt import App
from slack_bolt.adapter.flask import SlackRequestHandler
from slack_bolt.oauth.oauth_settings import OAuthSettings
from slack_sdk import WebClient
from slack_sdk.oauth.installation_store.file import FileInstallationStore
from slack_sdk.oauth.state_store.file import FileOAuthStateStore

from . import slack_handlers as handlers
from .agent import run_digest_agent

log = logging.getLogger("claw.slack_app")


def _volume_dir() -> Path:
    return Path(
        os.environ.get(
            "CLAW_VOLUME_DIR",
            str(Path(__file__).resolve().parents[1] / "workspace"),
        )
    )


def build_app() -> tuple[App, Flask]:
    volume_dir = _volume_dir()
    install_dir = volume_dir / ".slack_installations"
    state_dir = volume_dir / ".slack_oauth_state"
    install_dir.mkdir(parents=True, exist_ok=True)
    state_dir.mkdir(parents=True, exist_ok=True)

    oauth_settings = OAuthSettings(
        client_id=os.environ["SLACK_CLIENT_ID"],
        client_secret=os.environ["SLACK_CLIENT_SECRET"],
        scopes=["chat:write", "commands", "channels:read", "channels:history"],
        installation_store=FileInstallationStore(base_dir=str(install_dir)),
        state_store=FileOAuthStateStore(
            expiration_seconds=600, base_dir=str(state_dir)
        ),
    )

    app = App(
        signing_secret=os.environ["SLACK_SIGNING_SECRET"],
        oauth_settings=oauth_settings,
    )

    # ─── /setup ────────────────────────────────────────────
    @app.command("/setup")
    def cmd_setup(ack, body, client):
        ack()
        client.views_open(
            trigger_id=body["trigger_id"], view=handlers.build_setup_step1_view()
        )

    @app.view(handlers.SETUP_STEP1_CALLBACK)
    def submit_setup_step1(ack, view):
        next_view = handlers.handle_setup_step1_submit(view)
        if next_view["callback_id"] == handlers.SETUP_STEP1_CALLBACK:
            # Re-render step 1 with inline error.
            errors: dict[str, str] = {}
            for block in next_view["blocks"]:
                if block.get("type") == "input":
                    errors[block["block_id"]] = "See error above"
                    break
            ack(response_action="update", view=next_view)
            return
        ack(response_action="update", view=next_view)

    @app.view(handlers.SETUP_STEP2_CALLBACK)
    def submit_setup_step2(ack, view, body, client):
        team_id = body["team"]["id"]
        user_id = body["user"]["id"]
        try:
            cfg = handlers.handle_setup_step2_submit(
                view, team_id=team_id, installer_user_id=user_id, volume_dir=_volume_dir()
            )
        except Exception as exc:
            log.exception("setup step 2 failed")
            ack(response_action="errors", errors={handlers.SEGMENT_BLOCK: str(exc)[:150]})
            return
        ack()
        # First-run digest as DM — fire and forget.
        threading.Thread(
            target=_run_digest_and_post,
            args=(client.token, cfg, user_id, cfg["default_segment_id"], True),
            daemon=True,
        ).start()

    # ─── /run-digest ───────────────────────────────────────
    @app.command("/run-digest")
    def cmd_run_digest(ack, body, client):
        ack()
        team_id = body["team_id"]
        try:
            view = handlers.handle_run_digest_command(team_id, _volume_dir())
        except LookupError as exc:
            client.chat_postEphemeral(
                channel=body["channel_id"], user=body["user_id"], text=str(exc)
            )
            return
        except Exception as exc:
            from .errors import map_reo_error

            client.chat_postEphemeral(
                channel=body["channel_id"], user=body["user_id"], text=map_reo_error(exc)
            )
            return
        client.views_open(trigger_id=body["trigger_id"], view=view)

    @app.view(handlers.RUN_DIGEST_CALLBACK)
    def submit_run_digest(ack, view, body, client):
        team_id = body["team"]["id"]
        try:
            cfg, segment_id = handlers.handle_run_digest_submit(
                view, team_id=team_id, volume_dir=_volume_dir()
            )
        except LookupError as exc:
            ack(response_action="errors", errors={handlers.SEGMENT_BLOCK: str(exc)[:150]})
            return
        ack()
        threading.Thread(
            target=_run_digest_and_post,
            args=(client.token, cfg, cfg["digest_channel_id"], segment_id, False),
            daemon=True,
        ).start()

    flask_app = Flask(__name__)
    handler = SlackRequestHandler(app)

    @flask_app.route("/slack/events", methods=["POST"])
    def slack_events():
        return handler.handle(request)

    @flask_app.route("/slack/install", methods=["GET"])
    def slack_install():
        return handler.handle(request)

    @flask_app.route("/slack/oauth_redirect", methods=["GET"])
    def slack_oauth_redirect():
        return handler.handle(request)

    return app, flask_app


def _run_digest_and_post(
    bot_token: str,
    cfg: dict,
    destination: str,
    segment_id: str,
    is_first_run: bool,
) -> None:
    """Background: run the agent, post result to ``destination``.

    ``destination`` is a channel ID for scheduled/manual runs or a user ID
    for first-run DMs (Slack treats both the same for ``chat.postMessage``).
    """
    client = WebClient(token=bot_token)
    header = (
        ":sparkles: Here's what your daily digest will look like. "
        "Scheduled runs will start at your configured time.\n\n"
        if is_first_run
        else ""
    )
    try:
        answer = run_digest_agent(segment_id=segment_id, today=date.today().isoformat())
        client.chat_postMessage(channel=destination, text=header + answer)
    except Exception as exc:
        log.error("digest run failed:\n%s", traceback.format_exc())
        try:
            client.chat_postMessage(
                channel=destination,
                text=f":warning: Digest run failed: `{type(exc).__name__}`",
            )
        except Exception:
            log.exception("also failed to post error to Slack")
