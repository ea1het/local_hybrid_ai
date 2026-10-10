# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Offline contracts; optional upstream HTTP and refresh tests with mocked Google.

Run with Python from the upstream venv for --upstream checks. No real Google
credentials, Docker containers, LiteLLM registrations or Google API writes.
"""

import sys

sys.dont_write_bytecode = True

import argparse
import asyncio
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2] / "stack-80_-_mcp"
SERVICES = ("mcp-gdrive", "mcp-gmail", "mcp-gcalendar")
CLIENT_ID = "stack80-fixture.apps.googleusercontent.com"


def compose_checks(directory):
    stack = directory / "stack"
    shutil.copytree(ROOT, stack, ignore=shutil.ignore_patterns(".env", "__pycache__"))
    central = directory / ".env"
    central.write_text(f"BASE_PATH={directory / 'data'}\nNETWORK_NAME=redlocal\n"
                       f"GOOGLE_WORKSPACE_MCP_VERSION=2.1.0\n"
                       f"MCP_GOOGLE_OAUTH_CLIENT_ID={CLIENT_ID}\n"
                       "MCP_GOOGLE_OAUTH_CLIENT_SECRET=fixture-secret\n"
                       "MCP_GOOGLE_EMAIL=agent@example.com\n"
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
    assert not list(stack.rglob("__pycache__"))
    env = stack / ".env"
    for name in SERVICES:
        settings = stack / "config" / name / ".env"
        assert "GOOGLE_OAUTH_CLIENT_ID=" not in settings.read_text()
    command = ["docker", "compose", "--env-file", str(env), "-f", str(stack / "docker-compose.yml")]
    result = subprocess.run([*command, "config", "--format", "json"], check=True, capture_output=True, text=True)
    config = json.loads(result.stdout)
    assert set(config["services"]) == set(SERVICES)
    assert config["networks"]["redlocal"]["external"]
    paths = set()
    for name, service in config["services"].items():
        assert not service.get("ports")
        assert set(service["networks"]) == {"redlocal"}
        assert service["container_name"] == name
        assert service["environment"]["EXTERNAL_OAUTH21_PROVIDER"] == "false"
        assert service["environment"]["MCP_ENABLE_OAUTH21"] == "false"
        assert service["environment"]["GOOGLE_OAUTH_CLIENT_SECRET"] == "fixture-secret"
        assert service["environment"]["GOOGLE_OAUTH_CLIENT_ID"] == CLIENT_ID
        assert service["environment"]["USER_GOOGLE_EMAIL"] == "agent@example.com"
        assert service["environment"]["MCP_SINGLE_USER_MODE"] == "1"
        assert service["environment"]["WORKSPACE_MCP_STATELESS_MODE"] == "false"
        assert service["build"]["context"].endswith("#v2.1.0")
        assert service["image"].endswith(":2.1.0")
        assert "FASTMCP_SERVER_AUTH_GOOGLE_JWT_SIGNING_KEY" not in service["environment"]
        helper = service["volumes"][1]
        assert helper["read_only"] and helper["target"] == "/opt/stack80/google-oauth.py"
        assert "start_google_auth" in service["command"]
        paths.add(service["volumes"][0]["source"])
    assert len(paths) == 3
    subprocess.run([sys.executable, str(stack / "01-prepare.py"), "--validate-only"], check=True)
    assert central.read_bytes() == central_before
    assert "calendar:full" in config["services"]["mcp-gcalendar"]["command"]
    assert "complete" in config["services"]["mcp-gcalendar"]["command"]
    assert config["services"]["mcp-gcalendar"]["command"][-2:] == ["--disabled-tools", "start_google_auth"]
    print("PASS: bootstrap selection/idempotence, central Google settings, versioned Compose, network and data separation")
    return config




async def upstream_checks(upstream, config, directory):
    import httpx2
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    version = subprocess.run(["git", "-C", str(upstream), "describe", "--tags", "--exact-match"],
                            check=True, capture_output=True, text=True).stdout.strip()
    assert version == "v2.1.0"
    runner = Path(__file__).with_name("upstream_runner.py")
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
               "STACK80_TEST_UPSTREAM": str(upstream),
               "STACK80_TEST_HELPER": str(ROOT / "google-oauth.py"),
               "STACK80_TEST_SERVICE": name}
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
            # No upstream OAuth header or LiteLLM user identity is needed for discovery.
            async with httpx2.AsyncClient() as client:
                async with streamable_http_client(url + "/mcp", http_client=client) as (read, write):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        listing = (await session.list_tools()).tools
                        tools = {tool.name for tool in listing}
                        assert all("user_google_email" not in tool.input_schema.get("required", []) for tool in listing)
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
            assert "PASS: real OAuth code exchange" in log_path.read_text()
            assert "PASS: real upstream refresh" in log_path.read_text()
            print(f"PASS: {name}, readiness, header-free discovery, persistent refresh, {len(tools)} scoped tools")
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
