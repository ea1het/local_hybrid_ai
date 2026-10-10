# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Offline contract checks; optional upstream HTTP smoke tests with mocked identity.

Run with Python from the upstream venv for --upstream checks. No real Google
credentials, Docker containers, LiteLLM registrations or Google API writes.
"""

import argparse
import asyncio
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2] / "stack-80_-_mcp"
SERVICES = ("mcp-gdrive", "mcp-gmail", "mcp-gcalendar")
CLIENT_ID = "stack80-fixture.apps.googleusercontent.com"
TOKEN = "ya29.stack80-test-only"


def compose_checks(directory):
    stack = directory / "stack"
    shutil.copytree(ROOT, stack, ignore=shutil.ignore_patterns(".env", "__pycache__"))
    central = directory / ".env"
    central.write_text(f"BASE_PATH={directory / 'data'}\nNETWORK_NAME=redlocal\n"
                       f"GOOGLE_WORKSPACE_MCP_VERSION=2.1.0\n"
                       f"MCP_GOOGLE_OAUTH_CLIENT_ID={CLIENT_ID}\n"
                       f"MCP_UID={os.getuid()}\nMCP_GID={os.getgid()}\n")
    central.chmod(0o600)
    central_before = central.read_bytes()
    bootstrap = [sys.executable, str(stack / "00-bootstrap.py")]
    subprocess.run([*bootstrap, "--mcp", "mcp-gdrive"], check=True, capture_output=True)
    assert not (stack / "config/mcp-gmail/.env").exists()
    assert not (stack / "config/mcp-gcalendar/.env").exists()
    subprocess.run(bootstrap, check=True, capture_output=True)
    assert (stack / ".env").is_symlink()
    assert os.readlink(stack / ".env") == "../.env"
    assert central.read_bytes() == central_before
    before = {path: path.read_bytes() for path in stack.rglob(".env")}
    subprocess.run(bootstrap, check=True, capture_output=True)
    assert all(path.read_bytes() == value for path, value in before.items())
    assert all(path.stat().st_mode & 0o777 == 0o600 for path in before)
    env = stack / ".env"
    for name in SERVICES:
        settings = stack / "config" / name / ".env"
        assert "GOOGLE_OAUTH_CLIENT_ID=" not in settings.read_text()
    command = ["docker", "compose", "--env-file", str(env), "-f", str(stack / "docker-compose.yml")]
    result = subprocess.run([*command, "config", "--format", "json"], check=True, capture_output=True, text=True)
    config = json.loads(result.stdout)
    assert set(config["services"]) == set(SERVICES)
    assert config["networks"]["redlocal"]["external"]
    keys, paths = set(), set()
    for name, service in config["services"].items():
        assert not service.get("ports")
        assert set(service["networks"]) == {"redlocal"}
        assert service["container_name"] == name
        assert service["environment"]["EXTERNAL_OAUTH21_PROVIDER"] == "true"
        assert service["environment"]["GOOGLE_OAUTH_CLIENT_SECRET"] == ""
        assert service["environment"]["GOOGLE_OAUTH_CLIENT_ID"] == CLIENT_ID
        assert service["environment"]["MCP_SINGLE_USER_MODE"] == "false"
        assert service["build"]["context"].endswith("#v2.1.0")
        assert service["image"].endswith(":2.1.0")
        keys.add(service["environment"]["FASTMCP_SERVER_AUTH_GOOGLE_JWT_SIGNING_KEY"])
        paths.add(service["volumes"][0]["source"])
    assert len(keys) == len(paths) == 3
    subprocess.run([sys.executable, str(stack / "01-prepare.py"), "--validate-only"], check=True)
    assert central.read_bytes() == central_before
    assert "calendar:full" in config["services"]["mcp-gcalendar"]["command"]
    assert "complete" in config["services"]["mcp-gcalendar"]["command"]
    assert "--disabled-tools" not in config["services"]["mcp-gcalendar"]["command"]
    print("PASS: bootstrap selection/idempotence, private settings, versioned Compose, network and data separation")
    return config


RUNNER = '''
import asyncio
import os
import sys
sys.path.insert(0, os.environ["STACK80_TEST_UPSTREAM"])
from auth import google_auth
from auth.external_oauth_provider import ExternalOAuthProvider

# Only Google userinfo is mocked. The real external provider validates the
# bearer header and constructs the credentials used by service decorators.
def fixture_userinfo(credentials, **kwargs):
    if credentials.token == "ya29.stack80-test-only":
        return {"email": "agent@example.com", "id": "stack80-test"}
    return None
google_auth.get_user_info = fixture_userinfo

async def check_credentials():
    provider = ExternalOAuthProvider(
        client_id=os.environ["GOOGLE_OAUTH_CLIENT_ID"], client_secret=None,
        base_url="http://localhost:8000",
        jwt_signing_key=os.environ["FASTMCP_SERVER_AUTH_GOOGLE_JWT_SIGNING_KEY"],
    )
    try:
        token = await provider.verify_token("ya29.stack80-test-only")
        assert token.email == "agent@example.com"
        from auth.oauth21_session_store import ensure_session_from_access_token
        credentials = await ensure_session_from_access_token(token, token.email)
        assert credentials.token == "ya29.stack80-test-only"
        assert credentials.refresh_token is None and not credentials.client_secret
    finally:
        provider.close()
asyncio.run(check_credentials())
import main
main.main()
'''


async def upstream_checks(upstream, config, directory):
    import httpx2
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    version = subprocess.run(["git", "-C", str(upstream), "describe", "--tags", "--exact-match"],
                            check=True, capture_output=True, text=True).stdout.strip()
    assert version == "v2.1.0"
    runner = directory / "runner.py"
    runner.write_text(RUNNER)
    for name, service in config["services"].items():
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        home = directory / name
        home.mkdir()
        env = {**os.environ, **service["environment"], "HOME": str(home),
               "GOOGLE_MCP_CREDENTIALS_DIR": str(home / "credentials"),
               "WORKSPACE_ATTACHMENT_DIR": str(home / "attachments"),
               "ALLOWED_FILE_DIRS": str(home / "attachments"),
               "WORKSPACE_MCP_BASE_URI": "http://127.0.0.1",
               "WORKSPACE_MCP_HOST": "127.0.0.1", "WORKSPACE_MCP_PORT": str(port),
               "STACK80_TEST_UPSTREAM": str(upstream)}
        log_path = directory / f"{name}.log"
        with log_path.open("w") as log:
            process = subprocess.Popen([sys.executable, str(runner), *service["command"]],
                                       cwd=upstream, env=env, stdout=log, stderr=log)
        url = f"http://127.0.0.1:{port}"
        try:
            async with httpx2.AsyncClient(timeout=5) as client:
                for attempt in range(60):
                    if process.poll() is not None:
                        raise RuntimeError(log_path.read_text()[-6000:])
                    try:
                        response = await client.get(url + "/health/ready")
                        if response.status_code == 200:
                            break
                    except httpx2.RequestError:
                        pass
                    await asyncio.sleep(0.25)
                else:
                    raise RuntimeError("Upstream startup timed out")
                assert (await client.post(url + "/mcp", json={})).status_code == 401
                assert (await client.post(url + "/mcp", json={}, headers={"Authorization": "Bearer ya29.invalid-fixture"})).status_code == 401
            async with httpx2.AsyncClient(headers={"Authorization": f"Bearer {TOKEN}"}) as client:
                async with streamable_http_client(url + "/mcp", http_client=client) as (read, write):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        tools = {tool.name for tool in (await session.list_tools()).tools}
            if name == "mcp-gdrive":
                assert {"search_drive_files", "create_drive_file", "list_drive_items", "update_drive_file"} <= tools
                assert not any("gmail" in tool or tool.startswith("import_to_google") for tool in tools)
            elif name == "mcp-gmail":
                assert {"search_gmail_messages", "send_gmail_message", "draft_gmail_message"} <= tools
                assert not any("drive" in tool or "label" in tool or "filter" in tool for tool in tools)
            else:
                assert {"list_calendars", "get_events", "manage_event", "create_calendar",
                        "query_freebusy", "manage_out_of_office", "manage_focus_time"} == tools
            assert "start_google_auth" not in tools
            print(f"PASS: {name}, readiness, missing/invalid token rejection, bearer-to-credentials forwarding, {len(tools)} scoped tools")
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


def main():
    options = argparse.ArgumentParser(description=__doc__)
    options.add_argument("--upstream", type=Path)
    args = options.parse_args()
    with tempfile.TemporaryDirectory(prefix="stack80-check-") as temporary:
        directory = Path(temporary)
        config = compose_checks(directory)
        if args.upstream:
            asyncio.run(upstream_checks(args.upstream.resolve(), config, directory))


if __name__ == "__main__":
    main()
