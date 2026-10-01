#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Prepare LiteLLM configuration and its dedicated PostgreSQL storage.

The entrypoint verifies Stack 0 prerequisites, the service source files,
and pre-created runtime directories. It installs configuration while
preserving the PostgreSQL data directory. The install wrapper provisions
the database, issues consumer keys, and writes .lock after all phases.
Importing this module has no side effects."""

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.dont_write_bytecode = True

STACK_NAME = "stack-30_-_litellm"
STACK_DIR = Path(__file__).resolve().parent
ENV_FILE = STACK_DIR / ".env"
COMPOSE_FILE = STACK_DIR / "docker-compose.yml"
LOCK_FILE = STACK_DIR / ".lock"


def die(message):
    """Abort preparation with an execution error."""
    raise RuntimeError(message)


def log(message):
    """Print an indented progress detail."""
    print(f"  {message}")


def step(message):
    """Muestra el encabezado de una fase."""
    print(f"\n== {message}")


def run(command, env=None, capture=False):
    """Ejecuta un comando y, opcionalmente, captura su salida de texto."""
    return subprocess.run(command, env=env, check=True, text=True,
                          stdout=subprocess.PIPE if capture else None)


def load_env():
    """Carga con Bash el .env del stack y devuelve las variables exportadas."""
    result = subprocess.run(
        ["bash", "-Eeuo", "pipefail", "-c", 'set -a; source "$1"; env -0', "bash", str(ENV_FILE)],
        check=True, stdout=subprocess.PIPE,
    )
    return dict(item.decode().split("=", 1) for item in result.stdout.split(b"\0") if item)


def require(env, keys):
    """Exige cada variable nombrada en la cadena separada por espacios."""
    for key in keys.split():
        if not env.get(key):
            die(f"missing {key} in {ENV_FILE}")


def main():
    """Check dependencies and prepare configuration without writing the lock."""
    if LOCK_FILE.exists() or LOCK_FILE.is_symlink():
        print(f"Stack already prepared. {LOCK_FILE} exists; no changes made.")
        return
    if os.geteuid() != 0:
        die("run this command as root")
    for command in ("docker", "openssl", "install"):
        if not shutil.which(command):
            die(f"{command} is not installed")
    if subprocess.run(["docker", "compose", "version"], stdout=subprocess.DEVNULL,
                      stderr=subprocess.DEVNULL).returncode:
        die("Docker Compose v2 is not available")
    for path in (ENV_FILE, COMPOSE_FILE):
        if not path.is_file():
            die(f"missing {path}")
    if re.search(r"^[A-Za-z_][A-Za-z0-9_]*=.*(<REDACT|\.{5,})",
                 ENV_FILE.read_text(), re.MULTILINE):
        die(f"{ENV_FILE} contains redacted or incomplete values")
    env = load_env()
    os.environ.update(env)
    require(env, "STACKS_ROOT BASE_PATH NETWORK_NAME LITELLM_IMAGE LITELLM_VERSION "
            "LITELLM_MASTER_KEY LITELLM_SALT_KEY UI_USERNAME UI_PASSWORD "
            "STORE_MODEL_IN_DB LITELLM_DB_NAME LITELLM_DB_USER LITELLM_DB_PASSWORD "
            "LITELLM_POSTGRES_ADMIN_PASSWORD OMLX_BASE_URL OMLX_API_KEY")
    if env["LITELLM_POSTGRES_ADMIN_PASSWORD"].startswith("PUT_YOUR_"):
        die("PostgreSQL administrator password is a placeholder; run ./local-ai env bootstrap")
    if env["OMLX_API_KEY"].startswith("PUT_YOUR_"):
        die("OMLX_API_KEY is required before Stack 30 install; copy the key from the oMLX server into .env")
    if not env["OMLX_BASE_URL"].startswith("https://"):
        die("OMLX_BASE_URL must use HTTPS")
    stacks_root = env["STACKS_ROOT"].rstrip("/")
    base_path = env["BASE_PATH"].rstrip("/")
    if not env["STACKS_ROOT"].startswith("/") or not env["BASE_PATH"].startswith("/"):
        die("STACKS_ROOT and BASE_PATH must be absolute paths")
    if str(STACK_DIR) != f"{stacks_root}/{STACK_NAME}":
        die(f"this stack must reside in {stacks_root}/{STACK_NAME}; current path: {STACK_DIR}")
    if stacks_root == base_path:
        die("STACKS_ROOT and BASE_PATH must differ")
    if env["LITELLM_IMAGE"].endswith(":latest"):
        die("LITELLM_IMAGE must not use :latest")
    if env["LITELLM_VERSION"] == "latest":
        die("LITELLM_VERSION cannot be latest")
    for key in ("LITELLM_DB_NAME", "LITELLM_DB_USER"):
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", env[key]):
            die(f"{key} is invalid")
    stack0_lock = Path(stacks_root) / "stack-00_-_platform/.lock"
    if not stack0_lock.is_file():
        die(f"Stack 00 is not prepared: missing {stack0_lock}")
    network = env["NETWORK_NAME"]
    if subprocess.run(["docker", "network", "inspect", network], stdout=subprocess.DEVNULL,
                      stderr=subprocess.DEVNULL).returncode:
        die(f"missing network {network}; prepare Stack 00 first")
    driver = run(["docker", "network", "inspect", "-f", "{{.Driver}}", network], capture=True).stdout.strip()
    if driver != "bridge":
        die(f"{network} uses driver {driver}, not bridge")
    service_dir = Path(base_path) / "service_-_litellm"
    postgres_dir = Path(base_path) / "service_-_litellm-postgres"
    data_dir = postgres_dir / "data"
    config_source = STACK_DIR / "config/litellm/config.yaml"
    config_dir = service_dir / "config"
    if not config_source.is_file():
        die(f"missing {config_source}")
    step("Stack 30 runtime")
    for directory in (service_dir, config_dir, postgres_dir, data_dir):
        if not directory.is_dir() or directory.is_symlink():
            die(f"missing {directory}; run Stack 00 bootstrap first")
    log("service directories verified")
    log(f"dedicated PostgreSQL: {data_dir}")
    step("LiteLLM configuration")
    run(["install", "-m", "0644", "-o", "0", "-g", "0", str(config_source), str(config_dir / "config.yaml")])
    log(f"config.yaml synchronized from {config_source} without replacing the bind-mounted directory")
    log(f"pinned image: {env['LITELLM_IMAGE']}:{env['LITELLM_VERSION']}")
    step("Docker Compose validation")
    run(["docker", "compose", "--env-file", str(ENV_FILE), "-f", str(COMPOSE_FILE), "config", "--quiet"], env=env)
    log("Docker Compose configuration valid")
    step("Preparation complete")
    log("PostgreSQL provisioning and consumer credentials are the next install steps")
    log("PostgreSQL is managed by Stack 30")


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        message = (f"{error.cmd[0]} failed (exit {error.returncode})"
                   if isinstance(error, subprocess.CalledProcessError) else str(error))
        print(f"ERROR: {message}", file=sys.stderr)
        sys.exit(1)
