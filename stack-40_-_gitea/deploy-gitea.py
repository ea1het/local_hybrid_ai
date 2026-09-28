#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Deploy the prepared Gitea stack and verify runner registration."""

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.dont_write_bytecode = True

STACK_NAME = "stack-40_-_gitea"
STACK_DIR = Path(__file__).resolve().parent
ENV_FILE = STACK_DIR / ".env"
COMPOSE_FILE = STACK_DIR / "docker-compose.yml"
LOCK_FILE = STACK_DIR / ".lock"


def die(message):
    """Abort deployment with a runtime error containing ``message``."""
    raise RuntimeError(message)


def step(message):
    """Print a deployment step heading."""
    print(f"\n== {message}")


def log(message):
    """Print an indented progress message."""
    print(f"  {message}")


def run(command, env=None, capture=False):
    """Run a command, optionally capturing stdout, and raise on failure."""
    return subprocess.run(command, env=env, check=True, text=True,
                          stdout=subprocess.PIPE if capture else None)


def main():
    """Migrate Gitea, ensure an administrator, and start the stack."""
    if not shutil.which("docker"):
        die("docker no esta instalado")
    if subprocess.run(["docker", "compose", "version"], stdout=subprocess.DEVNULL,
                      stderr=subprocess.DEVNULL).returncode:
        die("Docker Compose v2 no esta disponible")
    if not ENV_FILE.is_file():
        die(f"falta {ENV_FILE}")
    if not LOCK_FILE.is_file():
        die(f"Stack4 no esta preparado: falta {LOCK_FILE}; ejecuta primero ./01-prepare.py")
    loaded = subprocess.run(["bash", "-Eeuo", "pipefail", "-c", 'set -a; source "$1"; env -0', "bash", str(ENV_FILE)],
                            check=True, stdout=subprocess.PIPE).stdout
    env = dict(item.decode().split("=", 1) for item in loaded.split(b"\0") if item)
    os.environ.update(env)
    required = ("STACKS_ROOT BASE_PATH GITEA_DOMAIN GITEA_ROOT_URL GITEA_SSH_DOMAIN GITEA_SSH_PORT "
                "GITEA_ADMIN_USERNAME GITEA_ADMIN_EMAIL GITEA_ADMIN_PASSWORD "
                "GITEA_RUNNER_INSTANCE_URL GITEA_RUNNER_NAME")
    for key in required.split():
        if not env.get(key):
            die(f"falta {key} en {ENV_FILE}")
    expected = f"{env['STACKS_ROOT'].rstrip('/')}/{STACK_NAME}"
    if str(STACK_DIR) != expected:
        die(f"este stack debe residir en {expected}; ruta actual: {STACK_DIR}")
    app_ini = Path(env["BASE_PATH"].rstrip("/")) / "service_-_gitea/config/app.ini"
    runner_service = Path(env["BASE_PATH"].rstrip("/")) / "service_-_gitea-runner"
    runner_config = runner_service / "data/config.yaml"
    token_file = runner_service / "secret/registration-token"
    state_file = runner_service / "data/.runner"
    for path in (app_ini, runner_config):
        if not path.is_file():
            die(f"falta {path}; ejecuta primero ./01-prepare.py")
    if not token_file.is_file() or not token_file.stat().st_size:
        die("falta el token runtime del runner; ejecuta primero ./01-prepare.py")
    compose = ["docker", "compose", "--env-file", str(ENV_FILE), "-f", str(COMPOSE_FILE)]
    step("Validacion y descarga")
    run(compose + ["config", "--quiet"], env=env)
    run(compose + ["pull"], env=env)
    step("Migraciones de Gitea")
    run(compose + ["run", "--rm", "gitea", "gitea", "migrate", "--config", "/etc/gitea/app.ini"], env=env)
    step("Usuario administrador")
    admins = subprocess.run(compose + ["run", "--rm", "gitea", "gitea", "admin", "user", "list",
                                    "--config", "/etc/gitea/app.ini", "--admin"],
                            env=env, stdout=subprocess.PIPE, text=True)
    if admins.returncode or env["GITEA_ADMIN_USERNAME"] not in admins.stdout:
        run(compose + ["run", "--rm", "-e", "GITEA_ADMIN_USERNAME", "-e", "GITEA_ADMIN_EMAIL",
                       "-e", "GITEA_ADMIN_PASSWORD", "gitea", "sh", "-ceu",
                       'gitea admin user create --config /etc/gitea/app.ini '
                       '--username "$GITEA_ADMIN_USERNAME" --email "$GITEA_ADMIN_EMAIL" '
                       '--password "$GITEA_ADMIN_PASSWORD" --admin --must-change-password=false'], env=env)
    step("Arranque")
    run(compose + ["up", "-d"], env=env)
    step("Validacion del runner")
    for attempt in range(30):
        inspected = subprocess.run(["docker", "inspect", "-f", "{{.State.Running}}", "gitea-runner"],
                                   stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        if inspected.stdout.strip() == "true" and state_file.is_file() and state_file.stat().st_size:
            log("runner registrado con identidad persistente")
            break
        if attempt == 29:
            die("el runner no creo/recupero su identidad persistente")
        time.sleep(2)
    run(compose + ["ps"], env=env)
    step("Instalacion terminada")
    log(f"Gitea publico: {env['GITEA_ROOT_URL']}")
    log(f"runner: {env['GITEA_RUNNER_NAME']}")


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        message = (f"fallo {error.cmd[0]} (exit {error.returncode})"
                   if isinstance(error, subprocess.CalledProcessError) else str(error))
        print(f"ERROR: {message}", file=sys.stderr)
        sys.exit(1)
