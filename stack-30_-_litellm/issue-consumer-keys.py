#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Issue the three minimal LiteLLM consumer keys during Stack 30 install.

A disposable LiteLLM Compose container connects to the already provisioned
PostgreSQL database. Hermes and Open WebUI receive separate inference keys
limited to the three fixed oMLX models; Hermes also receives a separate MCP
key with no initial server grants. The operator configures MCP servers and
their key permissions later. Each issued key is stored immediately in the
protected root .env, after creating one private backup. No key is printed or
rotated, and the temporary LiteLLM container is removed before return.
Importing this module does not access Docker or modify credentials.
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True

import fcntl
import json
import os
import stat
import subprocess
import time
from pathlib import Path

from wrapper.stubs.bootstrap_env import (BootstrapError, assignments, backup_path, missing,
                                         protected_text, render, root_owned, save, write_private)

ROOT = Path(__file__).resolve().parent.parent
STACK_DIR = Path(__file__).resolve().parent
ENV_FILE = ROOT / ".env"
CONTAINER = "local-ai-litellm-install"
MODELS = ("mlx/local-general", "mlx/local-agent", "mlx/local-coding")
KEYS = {"hermes-model": "LITELLM_API_KEY", "hermes-mcp": "LITELLM_MCP_API_KEY",
        "webui-model": "OPENWEBUI_LITELLM_API_KEY"}

KEY_SCRIPT = r"""
import json, os, sys, urllib.request
base = "http://127.0.0.1:4000"
master = os.environ["LITELLM_MASTER_KEY"]
role = sys.argv[1]
models = ["mlx/local-general", "mlx/local-agent", "mlx/local-coding"]
headers = {"Authorization": f"Bearer {master}", "Content-Type": "application/json"}
body = {"metadata": {"consumer": role, "managed_by": "local_hybrid_ai"},
        "object_permission": {"mcp_servers": ["no-mcp-servers"]}}
if role == "hermes-mcp":
    body["allowed_routes"] = ["mcp_routes"]
else:
    body["models"] = models
    body["allowed_routes"] = ["llm_api_routes", "info_routes"]
request = urllib.request.Request(base + "/key/generate", data=json.dumps(body).encode(),
                                 headers=headers, method="POST")
with urllib.request.urlopen(request, timeout=20) as response:
    result = json.load(response)
key = result.get("key") or result.get("token")
if not isinstance(key, str) or not key.startswith("sk-"):
    raise SystemExit("LiteLLM did not return a virtual key")
if role != "hermes-mcp":
    check = urllib.request.Request(base + "/v1/models",
                                   headers={"Authorization": f"Bearer {key}"})
    with urllib.request.urlopen(check, timeout=20) as response:
        visible = json.load(response)
    if not set(models).issubset({item.get("id") for item in visible.get("data", [])
                                 if isinstance(item, dict)}):
        raise SystemExit("issued key cannot see all three configured models")
print(json.dumps({"key": key}))
"""


def compose(*arguments: str) -> list[str]:
    """Build a Compose command with the managed environment and stack file."""
    return ["docker", "compose", "--env-file", str(STACK_DIR / ".env"),
            "-f", str(STACK_DIR / "docker-compose.yml"), *arguments]


def issue_keys() -> list[str]:
    """Issue only missing credentials and remove the disposable proxy."""
    if os.geteuid() != 0:
        raise BootstrapError("run Stack 30 install as root")
    lock = ROOT / ".env-bootstrap.lock"
    descriptor = os.open(lock, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or not root_owned(metadata) or stat.S_IMODE(metadata.st_mode) != 0o600:
            raise BootstrapError(f"unsafe bootstrap lock: {lock}")
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        old = protected_text(ENV_FILE)
        values = assignments(old)
        if missing(values.get("OMLX_API_KEY")) or missing(values.get("LITELLM_MASTER_KEY")):
            raise BootstrapError("OMLX_API_KEY and LITELLM_MASTER_KEY must be set in .env")
        roles = [role for role, key in KEYS.items() if missing(values.get(key))]
        if not roles:
            return []
        existing = subprocess.run(["docker", "inspect", "--type", "container", CONTAINER],
                                  stdin=subprocess.DEVNULL, capture_output=True, text=True, check=False)
        if existing.returncode == 0:
            raise BootstrapError(f"temporary LiteLLM container already exists: {CONTAINER}")
        launched = False
        backup = None
        issued = []
        try:
            result = subprocess.run(compose("run", "-d", "--rm", "--no-deps", "--name", CONTAINER,
                                            "litellm"), cwd=STACK_DIR, stdin=subprocess.DEVNULL,
                                    capture_output=True, text=True, check=False)
            if result.returncode:
                present = subprocess.run(["docker", "inspect", "--type", "container", CONTAINER],
                                         stdin=subprocess.DEVNULL, capture_output=True, text=True, check=False)
                launched = present.returncode == 0
                raise BootstrapError("could not start disposable LiteLLM installer container")
            launched = True
            for attempt in range(45):
                probe = subprocess.run(["docker", "exec", CONTAINER, "python3", "-c",
                                        "import urllib.request; urllib.request.urlopen('http://127.0.0.1:4000/health/liveliness', timeout=3)"],
                                       stdin=subprocess.DEVNULL, capture_output=True, text=True, check=False)
                if probe.returncode == 0:
                    break
                if attempt == 44:
                    raise BootstrapError("temporary LiteLLM did not become live")
                time.sleep(2)
            backup = backup_path(ENV_FILE)
            write_private(backup, old)
            for role in roles:
                result = subprocess.run(["docker", "exec", CONTAINER, "python3", "-c", KEY_SCRIPT, role],
                                        stdin=subprocess.DEVNULL, capture_output=True, text=True, check=False)
                if result.returncode:
                    raise BootstrapError(f"LiteLLM could not issue {role}; inspect possible orphaned keys")
                try:
                    key = json.loads(result.stdout)["key"]
                except (ValueError, KeyError, TypeError) as error:
                    raise BootstrapError(f"invalid LiteLLM response for {role}; inspect possible orphaned keys") from error
                if not isinstance(key, str) or not key.startswith("sk-"):
                    raise BootstrapError(f"invalid LiteLLM key for {role}; inspect possible orphaned keys")
                updated = render(old, {KEYS[role]: key})
                save(ENV_FILE, old, updated, backup)
                old = updated
                issued.append(KEYS[role])
        finally:
            if launched:
                removed = subprocess.run(["docker", "rm", "-f", CONTAINER], stdin=subprocess.DEVNULL,
                                         capture_output=True, text=True, check=False)
                if removed.returncode:
                    raise BootstrapError(f"could not remove temporary LiteLLM container {CONTAINER}")
        return issued
    finally:
        os.close(descriptor)


if __name__ == "__main__":
    try:
        issued = issue_keys()
        print(f"LiteLLM consumer keys: {len(issued)} issued; values stored in protected .env")
    except (BootstrapError, OSError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1) from None
