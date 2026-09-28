#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Reconcile optional Hermes providers without changing PREPARED state."""

import argparse
import hashlib
import os
import re
import shutil
import subprocess
import sys

sys.dont_write_bytecode = True
import tempfile
from pathlib import Path

from stack_env import load_env


STACK_DIR = Path(__file__).resolve().parent
ENV_FILE = STACK_DIR / ".env"
LOCK_FILE = STACK_DIR / ".lock"
SOURCE_CONFIG = STACK_DIR / "config/hermes/config.yaml"


def log(message: str) -> None:
    """Print a capability reconciliation message."""
    print(f"[capabilities] {message}")


def die(message: str) -> None:
    """Report an error and exit unsuccessfully."""
    print(f"[capabilities] ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def run(*command: str, capture: bool = False, check: bool = True) -> subprocess.CompletedProcess[str]:
    """Run a stack-local command, failing with context unless check is disabled."""
    result = subprocess.run(command, cwd=STACK_DIR, text=True, capture_output=capture, check=False)
    if check and result.returncode:
        if capture and result.stderr:
            print(result.stderr, end="", file=sys.stderr)
        die(f"command failed ({result.returncode}): {' '.join(command)}")
    return result


def digest(path: Path) -> str:
    """Return the SHA-256 digest of a file."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def container_running(name: str) -> bool:
    """Check whether Docker reports a container as running."""
    if run("docker", "inspect", name, capture=True, check=False).returncode:
        return False
    return run("docker", "inspect", "-f", "{{.State.Running}}", name, capture=True).stdout.strip() == "true"


def container_ready_on_network(name: str, network: str) -> bool:
    """Check that a running container belongs to the requested network."""
    if not container_running(name):
        return False
    template = '{{if index .NetworkSettings.Networks "' + network + '"}}yes{{else}}no{{end}}'
    return run("docker", "inspect", "-f", template, name, capture=True).stdout.strip() == "yes"


def stop_memory_sync_if_running(name: str) -> None:
    """Stop only the Git memory sidecar when it is running."""
    if container_running(name):
        run("docker", "stop", name, capture=True)
        log("Git-memory sidecar stopped; no other Stack6 service was changed")


def write_git_memory_state(path: Path, state: str, uid: int, gid: int) -> None:
    """Atomically write the operator's desired Git memory state."""
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w") as output:
        output.write(state + "\n")
    os.chown(temporary, uid, gid)
    temporary.chmod(0o640)
    os.replace(temporary, path)


def read_git_memory_state(path: Path) -> str:
    """Read and validate the desired Git memory state, defaulting to disabled."""
    state = "disabled"
    if path.is_file() and not path.is_symlink():
        state = path.read_text().splitlines()[0] if path.stat().st_size else ""
    if state not in {"enabled", "disabled"}:
        die(f"invalid Git-memory desired state in {path}")
    return state


def render_config(model: str, web_enabled: bool) -> bytes:
    """Render the selected model and web tool availability into managed config."""
    rendered = SOURCE_CONFIG.read_text().replace("${HERMES_MODEL}", model)
    if web_enabled:
        rendered = re.sub(r"(?m)^([ \t]*disabled_toolsets:[ \t]*)\[web\]([ \t]*)$", r"\1[]\2", rendered)
    if not rendered:
        die("rendered config is empty")
    if "${HERMES_MODEL}" in rendered:
        die("rendered config still contains HERMES_MODEL placeholder")
    expected = "[]" if web_enabled else "[web]"
    if not re.search(rf"(?m)^[ \t]*disabled_toolsets:[ \t]*{re.escape(expected)}[ \t]*$", rendered):
        die("rendered config did not reflect web provider availability")
    return rendered.encode()


def main() -> None:
    """Reconcile optional providers and Git memory against prepared stack state."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--restart", action="store_true", help="recreate running Hermes only when config changes")
    intent = parser.add_mutually_exclusive_group()
    intent.add_argument("--enable-git-memory", action="store_true")
    intent.add_argument("--disable-git-memory", action="store_true")
    options = parser.parse_args()

    if os.geteuid() != 0:
        die("run as root")
    for command in ("docker", "git"):
        if shutil.which(command) is None:
            die(f"missing required command: {command}")
    if run("docker", "compose", "version", capture=True, check=False).returncode:
        die("Docker Compose v2 is required")
    if not ENV_FILE.is_file():
        die(f"missing {ENV_FILE}")
    if not LOCK_FILE.is_file():
        die("Stack6 is not PREPARED; run 01-prepare.py first")
    if not SOURCE_CONFIG.is_file() or SOURCE_CONFIG.stat().st_size == 0:
        die(f"missing managed source {SOURCE_CONFIG}")
    original_env, original_lock = digest(ENV_FILE), digest(LOCK_FILE)
    env = load_env(ENV_FILE)
    required = (
        "BASE_PATH", "NETWORK_NAME", "HERMES_SERVICE", "HERMES_CONTAINER",
        "HERMES_UID", "HERMES_GID", "HERMES_MODEL", "HERMES_MEMORY_SERVICE",
        "MEMORY_SYNC_SERVICE", "MEMORY_SYNC_CONTAINER",
    )
    for key in required:
        if not env.get(key):
            die(f"missing {key} in .env")
    if not env["BASE_PATH"].startswith("/"):
        die("BASE_PATH must be absolute")
    base_path = Path(env["BASE_PATH"].rstrip("/"))
    deployed_config = base_path / env["HERMES_SERVICE"] / "config/config.yaml"
    memory_dir = base_path / env["HERMES_MEMORY_SERVICE"] / "data"
    memory_sync_dir = base_path / env["MEMORY_SYNC_SERVICE"]
    ssh_dir = memory_sync_dir / "ssh"
    state_file = memory_sync_dir / "desired-state"
    if not deployed_config.is_file() or deployed_config.is_symlink():
        die(f"invalid deployed config: {deployed_config}")

    web_enabled = all(container_ready_on_network(name, env["NETWORK_NAME"]) for name in ("searxng", "firecrawl-api"))
    if web_enabled:
        for key in ("SEARXNG_URL", "FIRECRAWL_API_URL"):
            if not env.get(key):
                die(f"web provider is present but {key} is empty")
        log("web.search + web.extract: available")
    else:
        log("web.search + web.extract: unavailable; Hermes web remains disabled")
    rendered = render_config(env["HERMES_MODEL"], web_enabled)
    changed = deployed_config.read_bytes() != rendered
    if changed:
        with tempfile.NamedTemporaryFile(dir=deployed_config.parent, delete=False) as output:
            output.write(rendered)
            temporary = Path(output.name)
        try:
            os.chown(temporary, int(env["HERMES_UID"]), int(env["HERMES_GID"]))
            temporary.chmod(0o640)
            os.replace(temporary, deployed_config)
        finally:
            temporary.unlink(missing_ok=True)
        log("managed Hermes configuration updated")
    else:
        log("managed Hermes configuration already converged")
    if changed and options.restart and container_running(env["HERMES_CONTAINER"]):
        run("docker", "compose", "up", "-d", "--no-deps", "--force-recreate", "hermes")
        log("Hermes recreated; no other service was restarted")

    memory_sync_dir.mkdir(mode=0o750, parents=True, exist_ok=True)
    os.chown(memory_sync_dir, int(env["HERMES_UID"]), int(env["HERMES_GID"]))
    memory_sync_dir.chmod(0o750)
    if options.enable_git_memory:
        write_git_memory_state(state_file, "enabled", int(env["HERMES_UID"]), int(env["HERMES_GID"]))
    elif options.disable_git_memory:
        write_git_memory_state(state_file, "disabled", int(env["HERMES_UID"]), int(env["HERMES_GID"]))
    desired = read_git_memory_state(state_file)
    provider = env.get("GITEA_CONTAINER_NAME", "gitea")
    remote_available = container_ready_on_network(provider, env["NETWORK_NAME"])
    log(f"git.remote: {'available' if remote_available else 'unavailable'}")
    if desired == "disabled":
        stop_memory_sync_if_running(env["MEMORY_SYNC_CONTAINER"])
        log("Git-memory: disabled by operator intent")
    elif not remote_available:
        stop_memory_sync_if_running(env["MEMORY_SYNC_CONTAINER"])
        log("Git-memory: requested but provider unavailable; local memory/Git state preserved")
    else:
        repository = env.get("GITMEM_REPOSITORY", "")
        branch = env.get("GITMEM_BRANCH", "")
        if not repository or repository.startswith("PUT_YOUR_"):
            die("Git-memory is enabled but GITMEM_REPOSITORY is not configured")
        if not branch:
            die("Git-memory is enabled but GITMEM_BRANCH is empty")
        if not (memory_dir / ".git").is_dir():
            die("Git-memory is enabled but working tree is not adopted; run prepare-git-memory.py safely first")
        for name in ("MEMORY.md", "USER.md"):
            path = memory_dir / name
            if not path.is_file() or path.is_symlink():
                die(f"invalid {name} in adopted Git-memory working tree")
        for name in ("ssh_config", "id_ed25519", "known_hosts"):
            path = ssh_dir / name
            if not path.is_file() or path.is_symlink() or path.stat().st_size == 0:
                die("Git-memory is enabled but dedicated SSH material is incomplete; run prepare-maintenance-sidecars.py first")
        if container_running(env["MEMORY_SYNC_CONTAINER"]):
            log("Git-memory: enabled and sidecar already running")
        else:
            git = ("git", "-c", f"safe.directory={memory_dir}", "-C", str(memory_dir))
            # A dirty tree or divergent heads require operator reconciliation before sync starts.
            local_head = run(*git, "rev-parse", "HEAD", capture=True).stdout.strip()
            if run(*git, "status", "--porcelain", capture=True).stdout.strip():
                die("Git-memory working tree is dirty; refusing to start sidecar automatically")
            if run(*git, "branch", "--show-current", capture=True).stdout.strip() != branch:
                die("Git-memory local branch does not match GITMEM_BRANCH")
            run("docker", "compose", "--profile", "git-memory", "build", "hermes-memory-sync", capture=True)
            script = ('export GIT_SSH_COMMAND="ssh -F /run/hermes-memory-ssh/ssh_config"; '
                      'git -c safe.directory=/work/hermes-memory -C /work/hermes-memory '
                      'ls-remote origin "refs/heads/${MEMORY_SYNC_BRANCH}"')
            remote_raw = run("docker", "compose", "--profile", "git-memory", "run", "--rm", "--no-deps",
                             "--entrypoint", "bash", "hermes-memory-sync", "-lc", script, capture=True).stdout
            remote_head = next((line.split()[0] for line in remote_raw.splitlines()
                                if len(line.split()) >= 2 and line.split()[1] == f"refs/heads/{branch}"), "")
            if not remote_head:
                die(f"Git-memory remote branch {branch} is unavailable")
            if local_head != remote_head:
                die("Git-memory local/remote HEAD differ; refusing automatic sidecar start")
            run("docker", "compose", "--profile", "git-memory", "up", "-d", "--no-deps", "hermes-memory-sync")
            log("Git-memory: enabled; sidecar started after clean local/remote equality preflight")
    if digest(ENV_FILE) != original_env:
        die(".env changed during reconciliation")
    if digest(LOCK_FILE) != original_lock:
        die(".lock changed during reconciliation")
    if web_enabled:
        log("result: web enabled exclusively through configured local SearXNG + Firecrawl")
    else:
        log("result: web disabled; no external fallback is permitted by managed config")
    log(f"result: Git-memory desired={desired}, git.remote={'available' if remote_available else 'unavailable'}")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError) as error:
        die(str(error))
