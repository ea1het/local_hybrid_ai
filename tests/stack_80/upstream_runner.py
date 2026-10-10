# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.


"""Isolated upstream server with fake Google token responses."""

import sys

sys.dont_write_bytecode = True

import importlib.util
import json
import os
import contextlib
import io
from unittest.mock import patch
from urllib.parse import parse_qs, urlencode, urlsplit
from pathlib import Path
from datetime import datetime, timedelta
sys.path.insert(0, os.environ["STACK80_TEST_UPSTREAM"])
from auth import google_auth
from auth.credential_store import get_credential_store
from google.oauth2.credentials import Credentials

spec = importlib.util.spec_from_file_location("stack80_oauth", os.environ["STACK80_TEST_HELPER"])
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)
service = os.environ["STACK80_TEST_SERVICE"]
scopes = (*helper.BASE_SCOPES, *helper.SERVICE_SCOPES[service])
email = os.environ["USER_GOOGLE_EMAIL"]
client_id = os.environ["GOOGLE_OAUTH_CLIENT_ID"]
client_secret = os.environ["GOOGLE_OAUTH_CLIENT_SECRET"]
store = get_credential_store()
userinfo = {"email": email, "verified_email": True}
token_payload = {"access_token": "initial-fixture", "expires_in": 3600,
                 "refresh_token": "fixture-refresh", "token_type": "Bearer",
                 "scope": " ".join(scopes)}

# Exercise the real Google OAuth library's authorization URL, PKCE, and code
# exchange. Mock only its HTTPS transport and Google's userinfo response.
import requests
from google_auth_oauthlib.flow import Flow
original_authorization_url = Flow.authorization_url
authorization_state = {}


def authorization_url(flow, **kwargs):
    url, state = original_authorization_url(flow, **kwargs)
    query = parse_qs(urlsplit(url).query)
    assert query["code_challenge_method"] == ["S256"]
    assert query["redirect_uri"] == [helper.REDIRECT_URI]
    assert query["access_type"] == ["offline"]
    assert query["prompt"] == ["consent"]
    assert set(query["scope"][0].split()) == set(scopes)
    authorization_state["state"] = state
    return url, state


def exchange(session, request, **kwargs):
    assert request.url == "https://oauth2.googleapis.com/token"
    body = parse_qs(request.body.decode() if isinstance(request.body, bytes) else request.body)
    assert body["grant_type"] == ["authorization_code"]
    assert body["code"] == ["fixture-code"] and body["code_verifier"][0]
    response = requests.Response()
    response.status_code = 200
    response._content = json.dumps(token_payload).encode()
    response.request = request
    return response


def callback(prompt):
    return helper.REDIRECT_URI + "?" + urlencode({"code": "fixture-code", "state": authorization_state["state"]})


with patch.object(Flow, "authorization_url", authorization_url), \
     patch.object(requests.Session, "send", exchange), \
     patch.object(helper.getpass, "getpass", callback), \
     patch.object(google_auth, "get_user_info", return_value=userinfo), \
     contextlib.redirect_stdout(io.StringIO()):
    helper.authorize(store, email, scopes, client_id, client_secret)
    saved = {path: path.read_bytes() for path in Path(store.base_dir).glob("*.json")}
    userinfo["email"] = "other@example.com"
    try:
        helper.authorize(store, email, scopes, client_id, client_secret)
    except RuntimeError as error:
        assert "identity does not match" in str(error)
    else:
        raise AssertionError("Wrong-account consent must be rejected")
    userinfo["email"] = email
    token_payload.pop("refresh_token")
    try:
        helper.authorize(store, email, scopes, client_id, client_secret)
    except RuntimeError as error:
        assert "did not issue a refresh token" in str(error)
    else:
        raise AssertionError("Consent without offline access must be rejected")
    assert all(path.read_bytes() == value for path, value in saved.items())
assert store.get_credential(email).refresh_token == "fixture-refresh"
assert all(path.stat().st_mode & 0o777 == 0o600 for path in Path(store.base_dir).glob("*.json"))
print("PASS: real OAuth code exchange, PKCE, identity/refresh rejection, private persistence", flush=True)

credentials = Credentials(
    token="expired-fixture", refresh_token="fixture-refresh", client_id=client_id,
    client_secret=client_secret, token_uri="https://oauth2.googleapis.com/token",
    scopes=list(scopes), expiry=datetime.utcnow() - timedelta(hours=2),
)
assert store.store_credential(email, credentials)

# Only the Google HTTP token endpoint is mocked. Use the real google-auth
# refresh implementation and upstream lookup/persistence, including rotation.
class Response:
    status = 200
    data = json.dumps({"access_token": "ya29.stack80-test-only", "expires_in": 3600,
                       "refresh_token": "fixture-rotated-refresh", "token_type": "Bearer"}).encode()
    headers = {}
class Request:
    def __call__(self, url, method="GET", body=None, headers=None, **kwargs):
        assert url == "https://oauth2.googleapis.com/token"
        assert method == "POST" and b"grant_type=refresh_token" in body
        return Response()
google_auth.Request = Request
current = helper.check_saved(store, email, scopes, client_id, client_secret)
assert current.valid and current.token == "ya29.stack80-test-only"
assert current.refresh_token == "fixture-rotated-refresh"
reloaded = store.get_credential(email)
assert reloaded.token == current.token and reloaded.refresh_token == current.refresh_token
assert reloaded.client_secret == client_secret
assert not google_auth.get_credentials("other@example.com", required_scopes=list(scopes))
print("PASS: real upstream refresh, rotated token persistence, and account isolation", flush=True)

import main
main.main()
