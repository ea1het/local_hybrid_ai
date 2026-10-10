#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Container-only Desktop OAuth bootstrap; runtime refresh belongs to upstream."""

import sys

sys.dont_write_bytecode = True

import argparse
import getpass
import os
import secrets
from urllib.parse import parse_qs, urlsplit

# This file is mounted separately from upstream's source tree.
sys.path.insert(0, "/app")

# These scopes cover only enabled operations. In particular, gmail:send is a
# cumulative upstream tool filter; its disabled label/filter operations do not
# require us to request gmail.modify or gmail.labels.
BASE_SCOPES = ("openid", "https://www.googleapis.com/auth/userinfo.email")
SERVICE_SCOPES = {
    "mcp-gdrive": ("https://www.googleapis.com/auth/drive",),
    "mcp-gmail": ("https://www.googleapis.com/auth/gmail.readonly",
                  "https://www.googleapis.com/auth/gmail.compose",
                  "https://www.googleapis.com/auth/gmail.send"),
    "mcp-gcalendar": ("https://www.googleapis.com/auth/calendar",),
}
REDIRECT_URI = "http://localhost:8765/"


def callback_code(response, state):
    """Validate the loopback response and state before exchanging any code."""
    actual = urlsplit(response.strip())
    expected = urlsplit(REDIRECT_URI)
    if (actual.scheme, actual.netloc, actual.path) != (
        expected.scheme, expected.netloc, expected.path,
    ) or actual.fragment:
        raise RuntimeError("Paste the complete localhost callback URL from this authorization.")
    query = parse_qs(actual.query)
    returned_state = query.get("state", [])
    if len(returned_state) != 1 or not secrets.compare_digest(returned_state[0], state):
        raise RuntimeError("OAuth state does not match; restart authorization.")
    if "error" in query:
        raise RuntimeError("Google authorization was declined; no credentials were changed.")
    codes = query.get("code", [])
    if len(codes) != 1 or not codes[0]:
        raise RuntimeError("The callback URL must contain one authorization code.")
    return codes[0]


def check_saved(store, email, scopes, client_id, client_secret):
    """Use upstream's actual credential lookup, refresh, and persistence path."""
    from auth.google_auth import get_credentials

    existing = store.get_credential(email)
    if not existing or (existing.client_id, existing.client_secret) != (client_id, client_secret):
        raise RuntimeError("Missing credentials or OAuth app changed; run authorize.py for this MCP.")
    credentials = get_credentials(email, required_scopes=list(scopes))
    if not credentials or not credentials.refresh_token:
        raise RuntimeError("Google credentials are not refreshable; run authorize.py for this MCP.")
    return credentials


def authorize(store, email, scopes, client_id, client_secret):
    """Exchange a manually returned loopback code, verify identity, then save."""
    from auth.google_auth import get_user_info
    from google_auth_oauthlib.flow import Flow

    flow = Flow.from_client_config({"installed": {
        "client_id": client_id,
        "client_secret": client_secret,
        "auth_uri": "https://accounts.google.com/o/oauth2/v2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "redirect_uris": [REDIRECT_URI],
    }}, scopes=list(scopes), redirect_uri=REDIRECT_URI, autogenerate_code_verifier=True)
    url, state = flow.authorization_url(
        access_type="offline", prompt="consent", login_hint=email,
    )
    print("Open this URL in your browser and authorize the configured agent account:")
    print(url, flush=True)
    print("After consent, localhost:8765 will not load (no listener is required).")
    print("Copy the complete URL from the address bar and paste it below; input is hidden.")
    response = getpass.getpass("Callback URL: ")
    code = callback_code(response, state)
    flow.fetch_token(code=code, timeout=60)
    credentials = flow.credentials
    if not credentials.refresh_token:
        raise RuntimeError("Google did not issue a refresh token; no credentials were changed.")
    from auth.scopes import has_required_scopes

    granted = credentials.granted_scopes or credentials.scopes
    if not has_required_scopes(granted, list(scopes)):
        raise RuntimeError("Required permissions were not granted; no credentials were changed.")
    info = get_user_info(credentials)
    if not info or not info.get("verified_email") or info.get("email", "").casefold() != email.casefold():
        raise RuntimeError("Google identity does not match MCP_GOOGLE_EMAIL; no credentials were changed.")
    if not store.store_credential(email, credentials):
        raise RuntimeError("Could not persist Google credentials in the MCP data directory.")


def main():
    options = argparse.ArgumentParser(description=__doc__)
    options.add_argument("service", choices=SERVICE_SCOPES)
    options.add_argument("--check", action="store_true")
    args = options.parse_args()
    if os.getenv("MCP_SINGLE_USER_MODE") != "1" or os.getenv("MCP_ENABLE_OAUTH21") != "false":
        raise RuntimeError("This helper requires the stack's container-managed single-user mode.")
    client_id = os.environ["GOOGLE_OAUTH_CLIENT_ID"]
    client_secret = os.environ["GOOGLE_OAUTH_CLIENT_SECRET"]
    email = os.environ["USER_GOOGLE_EMAIL"]
    if not client_secret or not client_id.endswith(".apps.googleusercontent.com") or "@" not in email:
        raise RuntimeError("Complete the Google Desktop OAuth settings in the central .env first.")
    from auth.credential_store import get_credential_store

    os.umask(0o077)
    store = get_credential_store()
    scopes = (*BASE_SCOPES, *SERVICE_SCOPES[args.service])
    if args.check:
        check_saved(store, email, scopes, client_id, client_secret)
        print(f"{args.service}: stored Google credentials are valid and refreshable.")
    else:
        authorize(store, email, scopes, client_id, client_secret)
        print(f"{args.service}: Google credentials saved; the MCP handles subsequent refresh.")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, KeyError, EOFError) as error:
        raise SystemExit(str(error))
    except KeyboardInterrupt:
        raise SystemExit("Authorization cancelled.")
    except Exception as error:
        # Provider responses can contain sensitive material; never print them.
        raise SystemExit(f"Google authorization/check failed ({type(error).__name__}); no token details printed.")
