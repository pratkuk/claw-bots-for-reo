"""Local dev runner for the multi-tenant Claw host.

Loads ``.env``, builds the Bolt+Flask app via ``claw.slack_app.build_app``,
and serves on ``127.0.0.1:3000``. Put your ngrok URL as the Slack app's
request URL + OAuth redirect URL.

Required env vars (add ``CLAW_CONFIG_ENCRYPTION_KEY`` to your .env — the
others should already be there from the earlier spike):

    SLACK_CLIENT_ID
    SLACK_CLIENT_SECRET
    SLACK_SIGNING_SECRET
    CLAW_CONFIG_ENCRYPTION_KEY   # generate: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

Optional:

    CLAW_VOLUME_DIR   # defaults to ./workspace
"""

from __future__ import annotations

import sys
from pathlib import Path

from dotenv import load_dotenv

REPO = Path(__file__).resolve().parent.parent
load_dotenv(REPO / ".env")

# Make ``claw`` importable when running this as a script.
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from claw.slack_app import build_app  # noqa: E402

if __name__ == "__main__":
    app, flask_app = build_app()
    print("Claw host running on http://127.0.0.1:3000")
    print("Install path:   <ngrok-url>/slack/install")
    print("Events path:    <ngrok-url>/slack/events")
    print("Redirect path:  <ngrok-url>/slack/oauth_redirect")
    flask_app.run(host="127.0.0.1", port=3000, debug=False, use_reloader=False)
