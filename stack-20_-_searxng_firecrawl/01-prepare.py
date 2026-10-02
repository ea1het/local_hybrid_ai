#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Prepare SearXNG and Firecrawl without owning platform directories.

The entrypoint validates Stack 0's lock and network, reads required settings,
and installs service configuration into directories created by bootstrap.
It preserves existing persistent secrets and writes the stack lock only when
preparation completes. Importing it neither starts containers nor changes
host state."""

import datetime
import os
import re
import shutil
import subprocess
import sys

sys.dont_write_bytecode = True
from pathlib import Path

STACK_NAME = "stack-20_-_searxng_firecrawl"
STACK_DIR = Path(__file__).resolve().parent
ENV_FILE = STACK_DIR / ".env"
COMPOSE_FILE = STACK_DIR / "docker-compose.yml"
LOCK_FILE = STACK_DIR / ".lock"
REQUIRED = ("STACKS_ROOT BASE_PATH NETWORK_NAME SEARXNG_SECRET SEARXNG_BASE_URL REDIS_PASSWORD "
            "RABBITMQ_USER RABBITMQ_PASSWORD FIRECRAWL_DB_USER FIRECRAWL_DB_PASSWORD FIRECRAWL_DB_NAME "
            "FIRECRAWL_POSTGRES_ADMIN_PASSWORD").split()


def log(message):
    """Print an indented progress detail."""
    print(f"  {message}")


def step(message):
    """Muestra el encabezado de una fase."""
    print(f"\n== {message}")


def die(message):
    """Print an error and abort preparation."""
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def sourced_environment():
    """Rechaza valores saneados y devuelve las variables del .env cargadas por Bash."""
    if re.search(r"^[A-Za-z_][A-Za-z0-9_]*=.*(<REDACT|\.{5,})", ENV_FILE.read_text(), re.MULTILINE):
        die(f"{ENV_FILE} contains redacted or incomplete values")
    result = subprocess.run(["bash", "-c", 'set -Eeuo pipefail; set -a; source "$1"; env -0', "bash", str(ENV_FILE)],
                            stdout=subprocess.PIPE, check=True)
    return dict(os.fsdecode(item).split("=", 1) for item in result.stdout.split(b"\0") if item)


def main():
    """Validate dependencies and prepare configuration without copying secrets."""
    if LOCK_FILE.exists():
        print(f"Stack already prepared. {LOCK_FILE} exists; no changes made.")
        return
    if os.geteuid() != 0:
        die("run this command as root")
    for command in ("docker", "openssl", "install", "stat"):
        if shutil.which(command) is None:
            die(f"{command} is not installed")
    if subprocess.run(["docker", "compose", "version"], stdout=subprocess.DEVNULL,
                      stderr=subprocess.DEVNULL).returncode:
        die("Docker Compose v2 is not available")
    for path in (ENV_FILE, COMPOSE_FILE):
        if not path.is_file():
            die(f"missing {path}")
    env = sourced_environment()
    for key in REQUIRED:
        if not env.get(key):
            die(f"missing {key} in {ENV_FILE}")
        if env[key].startswith("PUT_YOUR_"):
            die(f"{key} still contains a template placeholder; run ./local-ai env bootstrap")
    stacks_root, base_path = env["STACKS_ROOT"].rstrip("/"), env["BASE_PATH"].rstrip("/")
    if not env["STACKS_ROOT"].startswith("/") or not env["BASE_PATH"].startswith("/"):
        die("STACKS_ROOT and BASE_PATH must be absolute paths")
    if str(STACK_DIR) != f"{stacks_root}/{STACK_NAME}":
        die(f"this stack must reside in {stacks_root}/{STACK_NAME}; current path: {STACK_DIR}")
    if stacks_root == base_path:
        die("STACKS_ROOT and BASE_PATH must differ")
    if not env["SEARXNG_BASE_URL"].startswith("https://"):
        die("SEARXNG_BASE_URL must use HTTPS")
    db_user = env["FIRECRAWL_DB_USER"]
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", db_user):
        die("FIRECRAWL_DB_USER is invalid")
    if db_user == "postgres":
        die("FIRECRAWL_DB_USER cannot be postgres")
    if env["FIRECRAWL_DB_NAME"] != "postgres":
        die("FIRECRAWL_DB_NAME must be postgres for NUQ/pg_cron")
    stack0_lock = Path(stacks_root) / "stack-00_-_platform/.lock"
    settings = STACK_DIR / "config/searxng/settings.yml"
    limiter = STACK_DIR / "config/searxng/limiter.toml"
    favicons = STACK_DIR / "config/searxng/favicons.toml"
    postgres_init = STACK_DIR / "config/postgres/020-firecrawl-app-role.sh"
    for path in (stack0_lock, settings, limiter, favicons, postgres_init):
        if not path.is_file():
            die(f"missing {path}" + ("; prepare Stack 00 first" if path == stack0_lock else ""))
    searxng_service = Path(base_path) / "service_-_searxng"
    searxng_config = searxng_service / "config"
    postgres_service = Path(base_path) / "service_-_firecrawl-postgres"

    network = env["NETWORK_NAME"]
    step(f"Shared Docker network {network}")
    if subprocess.run(["docker", "network", "inspect", network], env=env, stdout=subprocess.DEVNULL,
                      stderr=subprocess.DEVNULL).returncode:
        die(f"missing {network}; install or prepare Stack 00 first")
    driver = subprocess.check_output(["docker", "network", "inspect", "-f", "{{.Driver}}", network], env=env).decode().rstrip("\n")
    if driver != "bridge":
        die(f"{network} uses driver {driver}, not bridge")
    log("exists, uses the bridge driver, and remains owned by Stack 00")

    step("Persistent directories")
    for directory in (searxng_service, searxng_config, searxng_service / "data",
                      Path(base_path) / "service_-_firecrawl-redis/data",
                      Path(base_path) / "service_-_firecrawl-rabbitmq/data", postgres_service,
                      postgres_service / "data"):
        if not directory.is_dir() or directory.is_symlink():
            die(f"missing {directory}; run Stack 00 bootstrap first")
    log("directories and permissions managed by Stack 00")

    step("SearXNG configuration")
    for source in (settings, limiter, favicons):
        target = searxng_config / source.name
        if target.is_dir() and not target.is_symlink():
            die(f"configuration path cannot be a directory: {target}")
    owner, group = searxng_config.stat().st_uid, searxng_config.stat().st_gid
    for source in (settings, limiter, favicons):
        subprocess.run(["install", "-m", "0644", "-o", str(owner), "-g", str(group),
                        str(source), str(searxng_config / source.name)], check=True)
    log("bind-mounted directory preserved; only managed files reconciled")

    step("Docker Compose validation")
    subprocess.run(["docker", "compose", "--env-file", str(ENV_FILE), "-f", str(COMPOSE_FILE),
                    "config", "--quiet"], env=env, check=True)
    log("Docker Compose configuration valid")
    os.umask(0o022)
    LOCK_FILE.write_text(f"stack={STACK_NAME}\nprepared_at_utc={datetime.datetime.now(datetime.timezone.utc):%Y-%m-%dT%H:%M:%SZ}\n")
    step("Preparation complete")
    log(f"lock created: {LOCK_FILE}")
    log(f"postgres remains the administrator role; Firecrawl uses {db_user}")
    log("shared network provided by Stack 00; not created or modified")


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as exc:
        raise SystemExit(exc.returncode) from None
