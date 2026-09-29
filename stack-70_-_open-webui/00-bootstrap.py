#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Bootstrap missing Open WebUI environment values explicitly.

This utility fills missing or placeholder Stack 70 values in the protected
root .env, keeping existing custom values. Before a change it saves the exact
original bytes to a root-owned, mode-0600, timestamped backup. When a key is
needed, LiteLLM issues one scoped to every model currently visible through
its API; the returned key is stored only in .env, never printed. Importing
the module does not issue a key or write .env."""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True  # never write __pycache__ into the worktree

import json
import os
import re
import secrets
import stat
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path

STACK_DIR = Path(__file__).resolve().parent
ROOT = STACK_DIR.parent
ENV_FILE = ROOT / ".env"

DEFAULTS = {
    "OPENWEBUI_IMAGE": "ghcr.io/open-webui/open-webui",
    "OPENWEBUI_VERSION": "v0.11.3",
    "OPENWEBUI_LITELLM_BASE_URL": "http://litellm:4000/v1",
}
SECRET_KEYS = {"OPENWEBUI_LITELLM_API_KEY", "OPENWEBUI_SECRET_KEY"}
ALL_KEYS = (*DEFAULTS.keys(), "OPENWEBUI_LITELLM_API_KEY", "OPENWEBUI_SECRET_KEY")
PLACEHOLDER_RE = re.compile(r"^PUT_YOUR_[A-Z0-9_]+_HERE$")
ASSIGNMENT_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$")


class BootstrapError(RuntimeError):
    """Report an invalid bootstrap prerequisite or failed key issuance."""
    pass


def run(cmd: list[str], *, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    """Run a command and capture its output without raising for its exit code."""
    return subprocess.run(
        cmd,
        input=input_text,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def require_env_file() -> str:
    """Read the root-owned operational environment after checking its mode."""
    if os.geteuid() != 0:
        raise BootstrapError("run as root so the protected operational .env remains root-owned")
    if not ENV_FILE.is_file() or ENV_FILE.is_symlink():
        raise BootstrapError(f"operational environment must be a regular file: {ENV_FILE}")
    st = ENV_FILE.stat()
    if stat.S_IMODE(st.st_mode) != 0o600:
        raise BootstrapError(f"operational environment must have mode 0600: {ENV_FILE}")
    if st.st_uid != 0 or st.st_gid != 0:
        raise BootstrapError(f"operational environment must be owned by root:root: {ENV_FILE}")
    return ENV_FILE.read_bytes().decode("utf-8")


def parse_values(text: str) -> tuple[dict[str, str], dict[str, int]]:
    """Extract Stack7 assignments and reject duplicate managed keys."""
    values: dict[str, str] = {}
    counts: dict[str, int] = {}
    for raw in text.splitlines():
        match = ASSIGNMENT_RE.match(raw)
        if not match:
            continue
        key, value = match.groups()
        if key in ALL_KEYS:
            counts[key] = counts.get(key, 0) + 1
            values[key] = value
    duplicates = [key for key, count in counts.items() if count != 1]
    if duplicates:
        raise BootstrapError("duplicate Stack7 variables in .env: " + ", ".join(sorted(duplicates)))
    return values, counts


def missing_or_placeholder(value: str | None) -> bool:
    """Return whether a value is absent, empty, or a standard placeholder."""
    return value is None or value == "" or bool(PLACEHOLDER_RE.fullmatch(value))


def litellm_running() -> None:
    """Require the LiteLLM container to be running before key issuance."""
    cp = run(["docker", "inspect", "-f", "{{.State.Running}}", "litellm"])
    if cp.returncode != 0 or cp.stdout.strip() != "true":
        raise BootstrapError("LiteLLM must be running before issuing the Stack7 virtual key")


def issue_litellm_key() -> tuple[str, list[str]]:
    """Issue a model-scoped key using the master key inside LiteLLM."""
    script = r"""
import json, os, sys, urllib.request
master = os.environ.get("LITELLM_MASTER_KEY", "")
if not master:
    raise SystemExit("missing LITELLM_MASTER_KEY in LiteLLM runtime")
headers = {"Authorization": f"Bearer {master}", "Content-Type": "application/json"}
req = urllib.request.Request("http://127.0.0.1:4000/v1/models", headers=headers)
with urllib.request.urlopen(req, timeout=15) as response:
    payload = json.load(response)
models = sorted({item.get("id") for item in payload.get("data", []) if isinstance(item, dict) and item.get("id")})
if not models:
    raise SystemExit("LiteLLM returned no model ids; refusing to issue an unscoped key")
body = json.dumps({
    "models": models,
    "metadata": {"consumer": "stack7-open-webui", "managed_by": "local_hybrid_ai"},
}).encode()
req = urllib.request.Request("http://127.0.0.1:4000/key/generate", data=body, headers=headers, method="POST")
with urllib.request.urlopen(req, timeout=20) as response:
    generated = json.load(response)
key = generated.get("key") or generated.get("token")
if not isinstance(key, str) or not key.startswith("sk-"):
    raise SystemExit("LiteLLM key generation did not return a valid virtual key")
check_headers = {"Authorization": f"Bearer {key}"}
req = urllib.request.Request("http://127.0.0.1:4000/v1/models", headers=check_headers)
with urllib.request.urlopen(req, timeout=15) as response:
    verified = json.load(response)
visible = sorted({item.get("id") for item in verified.get("data", []) if isinstance(item, dict) and item.get("id")})
if not visible:
    raise SystemExit("generated Stack7 key cannot see any models")
print(json.dumps({"key": key, "models": models}, separators=(",", ":")))
"""
    cp = run(["docker", "exec", "-i", "litellm", "python3", "-c", script])
    if cp.returncode != 0:
        detail = (cp.stderr or cp.stdout or "").strip()
        if len(detail) > 1000:
            detail = "..." + detail[-1000:]
        raise BootstrapError(f"LiteLLM virtual-key issuance failed: {detail or 'no diagnostic output'}")
    try:
        result = json.loads(cp.stdout)
    except json.JSONDecodeError as exc:
        raise BootstrapError("LiteLLM virtual-key helper returned invalid JSON") from exc
    key = result.get("key")
    models = result.get("models")
    if not isinstance(key, str) or not key.startswith("sk-"):
        raise BootstrapError("LiteLLM virtual-key helper returned an invalid key")
    if not isinstance(models, list) or not models or not all(isinstance(v, str) and v for v in models):
        raise BootstrapError("LiteLLM virtual-key helper returned an invalid model scope")
    return key, models


def render_updated(text: str, replacements: dict[str, str]) -> str:
    """Replace managed assignments and append missing ones in key order."""
    seen: set[str] = set()
    output: list[str] = []
    for raw in text.splitlines():
        match = ASSIGNMENT_RE.match(raw)
        if match and match.group(1) in replacements:
            key = match.group(1)
            output.append(f"{key}={replacements[key]}")
            seen.add(key)
        else:
            output.append(raw)
    missing = [key for key in ALL_KEYS if key in replacements and key not in seen]
    if missing:
        if output and output[-1] != "":
            output.append("")
        output.append("# Stack7 / Open WebUI — bootstrapped explicitly; secrets never print to stdout")
        for key in missing:
            output.append(f"{key}={replacements[key]}")
    return "\n".join(output) + "\n"


def backup_env(expected_text: str) -> Path:
    """Save the unchanged operational .env exclusively before modifying it."""
    timestamp = datetime.now().strftime("%y%m%d-%H%M%S")
    backup = ROOT / f".env-backup-{timestamp}"
    source_fd = os.open(ENV_FILE, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        source_stat = os.fstat(source_fd)
        if (not stat.S_ISREG(source_stat.st_mode)
                or stat.S_IMODE(source_stat.st_mode) != 0o600
                or source_stat.st_uid != 0 or source_stat.st_gid != 0):
            raise BootstrapError("operational .env changed type, mode, or owner before backup")
        with os.fdopen(source_fd, "rb", closefd=False) as source:
            original = source.read()
    finally:
        os.close(source_fd)
    if original != expected_text.encode("utf-8"):
        raise BootstrapError("operational .env changed during bootstrap; refusing to overwrite it")

    descriptor = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        os.fchown(descriptor, 0, 0)
        with os.fdopen(descriptor, "wb", closefd=False) as output:
            output.write(original)
            output.flush()
            os.fsync(output.fileno())
    except BaseException:
        backup.unlink(missing_ok=True)
        raise
    finally:
        os.close(descriptor)
    directory_fd = os.open(ROOT, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
    return backup


def atomic_write(payload: str, expected_text: str) -> None:
    """Replace .env atomically only if it still matches the backed-up version."""
    fd, tmp_name = tempfile.mkstemp(prefix=".env.stack7.", dir=ROOT)
    tmp = Path(tmp_name)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8", closefd=True) as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.chown(tmp, 0, 0)
        if require_env_file() != expected_text:
            raise BootstrapError("operational .env changed during bootstrap; refusing to overwrite it")
        os.replace(tmp, ENV_FILE)
        # Sync the directory so the replacement survives a sudden power loss.
        directory_fd = os.open(ROOT, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        tmp.unlink(missing_ok=True)


def main() -> int:
    """Fill missing Stack7 values and return an operator-facing exit code."""
    try:
        text = require_env_file()
        values, _ = parse_values(text)
        replacements: dict[str, str] = {}

        for key, default in DEFAULTS.items():
            if missing_or_placeholder(values.get(key)):
                replacements[key] = default

        if missing_or_placeholder(values.get("OPENWEBUI_SECRET_KEY")):
            replacements["OPENWEBUI_SECRET_KEY"] = secrets.token_hex(32)

        needs_key = missing_or_placeholder(values.get("OPENWEBUI_LITELLM_API_KEY"))
        if needs_key:
            litellm_running()

        if not replacements and not needs_key:
            print("Stack7 environment already bootstrapped; no changes made.")
            return 0

        backup = backup_env(text)
        issued_models: list[str] = []
        if needs_key:
            key, issued_models = issue_litellm_key()
            replacements["OPENWEBUI_LITELLM_API_KEY"] = key

        updated = render_updated(text, replacements)
        atomic_write(updated, text)
        print("Stack7 environment bootstrap: PASS")
        print(f"- protected backup: {backup}")
        print(f"- updated variables: {len(replacements)}")
        if issued_models:
            print(f"- dedicated LiteLLM virtual key issued for {len(issued_models)} model id(s)")
        print("- secret values were not printed")
        return 0
    except (BootstrapError, OSError, ValueError) as exc:
        print(f"STACK7 BOOTSTRAP ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
