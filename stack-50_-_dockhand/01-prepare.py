#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Validate Stack0 and prepare Dockhand's persistent Docker volume."""

import datetime
import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.dont_write_bytecode = True

STACK_NAME = "stack-50_-_dockhand"
STACK_DIR = Path(__file__).resolve().parent
ENV_FILE = STACK_DIR / ".env"
COMPOSE_FILE = STACK_DIR / "docker-compose.yml"
LOCK_FILE = STACK_DIR / ".lock"
VOLUME = "dockhand_data"


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


def main():
    """Check prerequisites, preserve or create the volume, and write the lock."""
    if LOCK_FILE.exists() or LOCK_FILE.is_symlink():
        print(f"Stack ya preparado. Existe {LOCK_FILE}; no se realiza ningun cambio.")
        return
    if os.geteuid() != 0:
        die("ejecuta este script como root")
    if not shutil.which("docker"):
        die("docker no esta instalado")
    if subprocess.run(["docker", "compose", "version"], stdout=subprocess.DEVNULL,
                      stderr=subprocess.DEVNULL).returncode:
        die("Docker Compose v2 no esta disponible")
    for path in (ENV_FILE, COMPOSE_FILE):
        if not path.is_file():
            die(f"falta {path}")
    loaded = subprocess.run(["bash", "-Eeuo", "pipefail", "-c", 'set -a; source "$1"; env -0', "bash", str(ENV_FILE)],
                            check=True, stdout=subprocess.PIPE).stdout
    env = dict(item.decode().split("=", 1) for item in loaded.split(b"\0") if item)
    os.environ.update(env)
    for key in ("STACKS_ROOT", "BASE_PATH", "NETWORK_NAME"):
        if not env.get(key):
            die(f"falta {key} en {ENV_FILE}")
    stacks_root = env["STACKS_ROOT"].rstrip("/")
    base_path = env["BASE_PATH"].rstrip("/")
    if not env["STACKS_ROOT"].startswith("/") or not env["BASE_PATH"].startswith("/"):
        die("STACKS_ROOT y BASE_PATH deben ser rutas absolutas")
    if str(STACK_DIR) != f"{stacks_root}/{STACK_NAME}":
        die(f"este stack debe residir en {stacks_root}/{STACK_NAME}; ruta actual: {STACK_DIR}")
    if stacks_root == base_path:
        die("STACKS_ROOT y BASE_PATH deben ser distintos")
    stack0_lock = Path(stacks_root) / "stack-00_-_platform/.lock"
    if not stack0_lock.is_file():
        die(f"Stack0 no esta preparado: falta {stack0_lock}")
    network = env["NETWORK_NAME"]
    step(f"Red Docker compartida {network}")
    if subprocess.run(["docker", "network", "inspect", network], stdout=subprocess.DEVNULL,
                      stderr=subprocess.DEVNULL).returncode:
        die(f"falta {network}; instala/prepara primero Stack0")
    driver = run(["docker", "network", "inspect", "-f", "{{.Driver}}", network], capture=True).stdout.strip()
    if driver != "bridge":
        die(f"{network} usa driver {driver}, no bridge")
    log("red de Stack0 verificada")
    step(f"Volumen persistente {VOLUME}")
    if subprocess.run(["docker", "volume", "inspect", VOLUME], stdout=subprocess.DEVNULL,
                      stderr=subprocess.DEVNULL).returncode:
        run(["docker", "volume", "create", VOLUME], capture=True)
        log("volumen creado")
    else:
        log("volumen existente preservado")
    if subprocess.run(["docker", "volume", "inspect", VOLUME], stdout=subprocess.DEVNULL,
                      stderr=subprocess.DEVNULL).returncode:
        die(f"no se pudo preparar el volumen {VOLUME}")
    volume_name = run(["docker", "volume", "inspect", "-f", "{{.Name}}", VOLUME], capture=True).stdout.strip()
    if volume_name != VOLUME:
        die(f"volumen inesperado: {volume_name}")
    step("Validacion de Docker Compose")
    run(["docker", "compose", "--env-file", str(ENV_FILE), "-f", str(COMPOSE_FILE), "config", "--quiet"], env=env)
    log("compose valido")
    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    LOCK_FILE.write_text(f"stack={STACK_NAME}\nprepared_at_utc={timestamp}\n")
    LOCK_FILE.chmod(0o644)
    step("Preparacion terminada")
    log(f"lock creado: {LOCK_FILE}")
    log(f"volumen {VOLUME}: propiedad de Stack5 y preservado entre despliegues")


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        message = (f"fallo {error.cmd[0]} (exit {error.returncode})"
                   if isinstance(error, subprocess.CalledProcessError) else str(error))
        print(f"ERROR: {message}", file=sys.stderr)
        sys.exit(1)
