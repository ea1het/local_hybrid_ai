#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Prepare Gitea server and runner configuration without deploying them.

The script checks Stack 0 prerequisites, required source files, environment
values, and runtime directories. It renders service configuration and
preserves an existing runner token before writing a preparation lock.
deploy-gitea.py performs the later service migration and startup; importing
this module does not run either phase."""

import datetime
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.dont_write_bytecode = True

STACK_NAME = "stack-40_-_gitea"
STACK_DIR = Path(__file__).resolve().parent
ENV_FILE = STACK_DIR / ".env"
COMPOSE_FILE = STACK_DIR / "docker-compose.yml"
LOCK_FILE = STACK_DIR / ".lock"


def die(message):
    """Abort preparation with a runtime error containing ``message``."""
    raise RuntimeError(message)


def log(message):
    """Print an indented progress message."""
    print(f"  {message}")


def step(message):
    """Print a preparation step heading."""
    print(f"\n== {message}")


def run(command, env=None, capture=False):
    """Run a command, optionally capturing stdout, and raise on failure."""
    return subprocess.run(command, env=env, check=True, text=True,
                          stdout=subprocess.PIPE if capture else None)


def render(source, target, values):
    """Replace template markers and atomically install the rendered file."""
    content = source.read_text()
    for key, value in values.items():
        content = content.replace(f"@@{key}@@", value)
    if re.search(r"@@[A-Za-z0-9_]+@@", content):
        die(f"unresolved placeholders in {source}")
    temporary = target.with_name(f"{target.name}.tmp.{os.getpid()}")
    temporary.write_text(content)
    temporary.replace(target)


def main():
    """Check Stack0 and prepare persistent Gitea and runner files once."""
    if LOCK_FILE.exists() or LOCK_FILE.is_symlink():
        print(f"Stack already prepared. {LOCK_FILE} exists; no changes made.")
        return
    if os.geteuid() != 0:
        die("run this command as root")
    for command in ("docker", "openssl"):
        if not shutil.which(command):
            die(f"missing required command: {command}")
    if subprocess.run(["docker", "compose", "version"], stdout=subprocess.DEVNULL,
                      stderr=subprocess.DEVNULL).returncode:
        die("Docker Compose v2 is not available")
    for path in (ENV_FILE, COMPOSE_FILE):
        if not path.is_file():
            die(f"missing {path}")
    if re.search(r"^[A-Za-z_][A-Za-z0-9_]*=.*(<REDACT|\.{5,})",
                 ENV_FILE.read_text(), re.MULTILINE):
        die(f"{ENV_FILE} contains redacted or incomplete values")
    loaded = subprocess.run(["bash", "-Eeuo", "pipefail", "-c", 'set -a; source "$1"; env -0', "bash", str(ENV_FILE)],
                            check=True, stdout=subprocess.PIPE).stdout
    env = dict(item.decode().split("=", 1) for item in loaded.split(b"\0") if item)
    os.environ.update(env)
    required = ("STACKS_ROOT BASE_PATH NETWORK_NAME GITEA_IMAGE GITEA_CONTAINER_NAME GITEA_UID GITEA_GID "
                "GITEA_SSH_BIND GITEA_SSH_PORT GITEA_DOCKER_NETWORK GITEA_DOMAIN GITEA_ROOT_URL "
                "GITEA_SSH_DOMAIN GITEA_TIMEZONE GITEA_INTERNAL_TOKEN GITEA_JWT_SECRET "
                "GITEA_ADMIN_USERNAME GITEA_ADMIN_EMAIL GITEA_ADMIN_PASSWORD "
                "GITEA_RUNNER_NAME GITEA_RUNNER_INSTANCE_URL")
    for key in required.split():
        if not env.get(key):
            die(f"missing {key} in {ENV_FILE}")
    stacks_root = env["STACKS_ROOT"].rstrip("/")
    base_path = env["BASE_PATH"].rstrip("/")
    if not env["STACKS_ROOT"].startswith("/") or not env["BASE_PATH"].startswith("/"):
        die("STACKS_ROOT and BASE_PATH must be absolute paths")
    if str(STACK_DIR) != f"{stacks_root}/{STACK_NAME}":
        die(f"this stack must reside in {stacks_root}/{STACK_NAME}; current path: {STACK_DIR}")
    if stacks_root == base_path:
        die("STACKS_ROOT and BASE_PATH must differ")
    if env["GITEA_ROOT_URL"] != f"https://{env['GITEA_DOMAIN']}/":
        die(f"GITEA_ROOT_URL must be https://{env['GITEA_DOMAIN']}/")
    if env["GITEA_RUNNER_INSTANCE_URL"] != "http://gitea:3000/":
        die("GITEA_RUNNER_INSTANCE_URL must be http://gitea:3000/")
    if env["GITEA_DOCKER_NETWORK"] != env["NETWORK_NAME"]:
        die(f"GITEA_DOCKER_NETWORK must match NETWORK_NAME ({env['NETWORK_NAME']})")
    stack0_lock = Path(stacks_root) / "stack-00_-_platform/.lock"
    if not stack0_lock.is_file():
        die(f"Stack 00 is not prepared: missing {stack0_lock}")
    gitea_service = Path(base_path) / "service_-_gitea"
    runner_service = Path(base_path) / "service_-_gitea-runner"
    token_file = runner_service / "secret/registration-token"
    app_source = STACK_DIR / "config/gitea/app.ini"
    runner_source = STACK_DIR / "config/gitea-runner/config.yaml"
    app_target = gitea_service / "config/app.ini"
    default_target = gitea_service / "config/conf/app.ini"
    runner_target = runner_service / "data/config.yaml"
    for source in (app_source, runner_source):
        if not source.is_file():
            die(f"missing {source}")
    for directory in (gitea_service / "config", gitea_service / "config/conf",
                      gitea_service / "data", runner_service / "data", runner_service / "secret"):
        if not directory.is_dir() or directory.is_symlink():
            die(f"missing {directory}; run Stack 00 bootstrap first")
    network = env["GITEA_DOCKER_NETWORK"]
    step(f"Shared Docker network {network}")
    if subprocess.run(["docker", "network", "inspect", network], stdout=subprocess.DEVNULL,
                      stderr=subprocess.DEVNULL).returncode:
        die(f"missing {network}; install or prepare Stack 00 first")
    driver = run(["docker", "network", "inspect", "-f", "{{.Driver}}", network], capture=True).stdout.strip()
    if driver != "bridge":
        die(f"{network} uses driver {driver}, not bridge")
    log("Stack 00 network verified")
    step("Persistent runner token")
    if token_file.is_file() and token_file.stat().st_size:
        log("existing token preserved")
    else:
        token = env.get("GITEA_RUNNER_REGISTRATION_TOKEN", "")
        if token and not token.startswith("PUT_YOUR_"):
            token += "\n"
            log("legacy .env token adopted in runtime")
        else:
            token = run(["openssl", "rand", "-hex", "24"], capture=True).stdout
            log("token generated once in runtime")
        descriptor = os.open(token_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "w") as secret:
            secret.write(token)
    if not token_file.stat().st_size:
        die(f"could not prepare {token_file}")
    os.chown(token_file, 0, int(env["GITEA_GID"]))
    os.chmod(token_file, 0o440)
    step("Gitea configuration")
    app_keys = ("GITEA_DOMAIN", "GITEA_ROOT_URL", "GITEA_SSH_DOMAIN", "GITEA_SSH_PORT",
                "GITEA_INTERNAL_TOKEN", "GITEA_JWT_SECRET")
    render(app_source, app_target, {key: env[key] for key in app_keys})
    os.chown(app_target, int(env["GITEA_UID"]), int(env["GITEA_GID"]))
    os.chmod(app_target, 0o640)
    if default_target.is_symlink():
        if os.readlink(default_target) != "../app.ini":
            die(f"{default_target} is an unexpected symlink")
    elif default_target.exists():
        die(f"{default_target} exists but is not the expected managed alias")
    else:
        # Gitea reads custom/conf/app.ini; keep it linked to the rendered bind file.
        default_target.symlink_to("../app.ini")
    os.chown(default_target, int(env["GITEA_UID"]), int(env["GITEA_GID"]), follow_symlinks=False)
    log("bind-mounted configuration preserved; app.ini also available at custom/conf/app.ini")
    step("Runner configuration")
    for obsolete in ("ca-certificates.crt", "certificates.txt"):
        (runner_service / "data" / obsolete).unlink(missing_ok=True)
    render(runner_source, runner_target, {"GITEA_DOCKER_NETWORK": network})
    os.chown(runner_target, int(env["GITEA_UID"]), int(env["GITEA_GID"]))
    os.chmod(runner_target, 0o640)
    step("Docker Compose validation")
    run(["docker", "compose", "--env-file", str(ENV_FILE), "-f", str(COMPOSE_FILE), "config", "--quiet"], env=env)
    log("Docker Compose configuration valid")
    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    LOCK_FILE.write_text(f"stack={STACK_NAME}\nprepared_at_utc={timestamp}\n")
    step("Preparation complete")
    log(f"lock created: {LOCK_FILE}")
    log("runner token: persistent runtime state, not required in .env")
    log("for a new deployment only, run the Gitea deployment step to migrate and start the stack")


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, ValueError, subprocess.CalledProcessError) as error:
        message = (f"{error.cmd[0]} failed (exit {error.returncode})"
                   if isinstance(error, subprocess.CalledProcessError) else str(error))
        print(f"ERROR: {message}", file=sys.stderr)
        sys.exit(1)
