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
from slack_sdk.errors import SlackApiError
from slack_sdk.oauth.installation_store.file import FileInstallationStore
from slack_sdk.oauth.state_store.file import FileOAuthStateStore

from . import slack_handlers as handlers
from .agent import run_digest_agent

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s.%(msecs)03d %(levelname)s [%(threadName)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
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
        scopes=[
            "chat:write",
            "commands",
            "channels:read",
            "channels:history",
            "channels:join",
        ],
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
    def submit_setup_step1(ack, view, client):
        import time as _t

        t0 = _t.monotonic()
        log.info("step1 submit received")
        # Read inputs synchronously — fast. Reject before showing loader if empty.
        try:
            api_key, tenant_id = handlers.read_step1(view)
        except (KeyError, AttributeError, ValueError):
            ack(
                response_action="update",
                view=handlers.build_setup_step1_view(error="Please fill in both fields."),
            )
            return
        if not api_key or not tenant_id:
            ack(
                response_action="update",
                view=handlers.build_setup_step1_view(error="Please fill in both fields."),
            )
            return

        log.info("step1 acking with loader (t=%.3fs)", _t.monotonic() - t0)
        ack(response_action="update", view=handlers.build_setup_loading_view())
        log.info("step1 acked (t=%.3fs)", _t.monotonic() - t0)

        view_id = view["id"]
        threading.Thread(
            target=_advance_to_step2,
            args=(client.token, view_id, api_key, tenant_id),
            daemon=True,
        ).start()

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


def _advance_to_step2(
    bot_token: str, view_id: str, api_key: str, tenant_id: str
) -> None:
    """Background: call Reo, then swap the loading modal for step 2 or an error."""
    import time as _t

    from .errors import list_segments_safe, map_reo_error

    client = WebClient(token=bot_token)
    t0 = _t.monotonic()
    log.info("bg reo list_segments start")
    try:
        segments = list_segments_safe(api_key)
    except Exception as exc:
        log.exception("bg reo list_segments FAILED after %.2fs", _t.monotonic() - t0)
        client.views_update(
            view_id=view_id,
            view=handlers.build_setup_step1_view(error=map_reo_error(exc)),
        )
        return
    log.info(
        "bg reo list_segments ok in %.2fs: %d segments",
        _t.monotonic() - t0,
        len(segments),
    )
    resp = client.views_update(
        view_id=view_id,
        view=handlers.build_setup_step2_view(
            api_key=api_key, tenant_id=tenant_id, segments=segments
        ),
    )
    log.info("bg views_update ok=%s", resp.get("ok"))


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
        answer = run_digest_agent(
            segment_id=segment_id,
            today=date.today().isoformat(),
            reo_api_key=cfg["reo_api_key"],
        )
        _post_with_autojoin(client, destination, header + answer, cfg.get("installer_user_id"))
    except Exception as exc:
        log.error("digest run failed:\n%s", traceback.format_exc())
        try:
            fallback = cfg.get("installer_user_id") or destination
            client.chat_postMessage(
                channel=fallback,
                text=f":warning: Digest run failed: `{type(exc).__name__}`",
            )
        except Exception:
            log.exception("also failed to post error to Slack")


def _post_with_autojoin(
    client: WebClient, channel: str, text: str, installer_user_id: str | None
) -> None:
    """Post to ``channel``; if bot isn't a member, try to join (public channels
    only) and retry. If join fails (private/DM), DM the installer with a
    nudge to ``/invite`` the bot.
    """
    try:
        client.chat_postMessage(channel=channel, text=text)
        return
    except SlackApiError as exc:
        if exc.response.get("error") != "not_in_channel":
            raise
    try:
        client.conversations_join(channel=channel)
        client.chat_postMessage(channel=channel, text=text)
        return
    except SlackApiError:
        log.warning("conversations.join failed for %s — DMing installer", channel)
    if installer_user_id:
        client.chat_postMessage(
            channel=installer_user_id,
            text=(
                f":warning: I couldn't post your digest to <#{channel}> because "
                f"I'm not a member. Invite me with `/invite @claw` in that "
                f"channel, or run `/setup` again to pick a different one.\n\n"
                + text
            ),
        )
