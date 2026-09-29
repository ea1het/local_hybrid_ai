#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Validate Open WebUI prerequisites and mark Stack 70 prepared.

The script checks the platform dependency, required configuration, and
service files before writing its preparation lock. It does not mint
credentials; the separate bootstrap script handles missing values.
Importing the module does not inspect Docker or change runtime state."""


import os
import shutil
import subprocess
import sys

sys.dont_write_bytecode = True
from datetime import datetime, timezone
from pathlib import Path


STACK_NAME = "stack-70_-_open-webui"
STACK_DIR = Path(__file__).resolve().parent
ENV_FILE = STACK_DIR / ".env"
COMPOSE_FILE = STACK_DIR / "docker-compose.yml"
LOCK_FILE = STACK_DIR / ".lock"
REQUIRED_KEYS = (
    "STACKS_ROOT", "BASE_PATH", "NETWORK_NAME", "OPENWEBUI_IMAGE",
    "OPENWEBUI_VERSION", "OPENWEBUI_LITELLM_BASE_URL",
    "OPENWEBUI_LITELLM_API_KEY", "OPENWEBUI_SECRET_KEY",
)


class PrepareError(Exception):
    """Report a failed Stack7 preparation prerequisite."""
    pass


def require(condition, message):
    """Raise ``PrepareError`` when a prerequisite is false."""
    if not condition:
        raise PrepareError(message)


def run(*command, env=None, quiet=False):
    """Run a command and return captured stdout when ``quiet`` is true."""
    try:
        result = subprocess.run(
            command, env=env, text=True, capture_output=quiet, check=False
        )
    except OSError as exc:
        raise PrepareError(f"no se pudo ejecutar {command[0]}: {exc}") from exc
    require(result.returncode == 0, f"fallo: {' '.join(command)}")
    return result.stdout.strip() if quiet else ""


def load_env():
    """Source the central environment with Bash and return exported values."""
    result = subprocess.run(
        ("bash", "-c", 'set -a; source "$1" || exit; env -0', "bash", str(ENV_FILE)),
        stdout=subprocess.PIPE, check=False,
    )
    require(result.returncode == 0, f"no se pudo cargar {ENV_FILE}")
    return dict(entry.decode().split("=", 1) for entry in result.stdout.split(b"\0") if entry)


def main():
    """Check Stack0, LiteLLM, and runtime paths before writing the lock."""
    if LOCK_FILE.exists() or LOCK_FILE.is_symlink():
        print(f"Stack ya preparado. Existe {LOCK_FILE}; no se realiza ningun cambio.")
        return

    require(os.geteuid() == 0, "ejecuta este script como root")
    require(shutil.which("docker") is not None, "docker no esta instalado")
    require(subprocess.run(("docker", "compose", "version"), stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, check=False).returncode == 0,
            "Docker Compose v2 no esta disponible")
    require(ENV_FILE.is_symlink(), f"falta el symlink gestionado {ENV_FILE}")
    require(os.readlink(ENV_FILE) == "../.env", f"{ENV_FILE} debe apuntar exactamente a ../.env")
    require(ENV_FILE.is_file(), "falta el .env central")
    require(COMPOSE_FILE.is_file(), f"falta {COMPOSE_FILE}")

    env = load_env()
    for key in REQUIRED_KEYS:
        require(bool(env.get(key)), f"falta {key} en {ENV_FILE}")
    for key in ("OPENWEBUI_LITELLM_API_KEY", "OPENWEBUI_SECRET_KEY"):
        require(not env[key].startswith("PUT_YOUR_"), f"{key} conserva un placeholder")
    version = env["OPENWEBUI_VERSION"]
    require(version not in ("latest", "main", "dev"),
            f"OPENWEBUI_VERSION debe ser una version estable fijada, no {version}")
    stacks_root = env["STACKS_ROOT"]
    base_path = env["BASE_PATH"]
    require(stacks_root.startswith("/") and base_path.startswith("/"),
            "STACKS_ROOT y BASE_PATH deben ser rutas absolutas")
    require(str(STACK_DIR) == f"{stacks_root.rstrip('/')}/{STACK_NAME}",
            f"este stack debe residir en {stacks_root.rstrip('/')}/{STACK_NAME}; ruta actual: {STACK_DIR}")
    require(stacks_root.rstrip("/") != base_path.rstrip("/"),
            "STACKS_ROOT y BASE_PATH deben ser distintos")

    for stack, label in (("stack-00_-_platform", "Stack0"), ("stack-30_-_litellm", "Stack3")):
        lock = Path(stacks_root.rstrip("/")) / stack / ".lock"
        require(lock.is_file(), f"{label} no esta preparado: falta {lock}")

    network = env["NETWORK_NAME"]
    print(f"\n== Red Docker compartida {network}")
    require(subprocess.run(("docker", "network", "inspect", network),
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           check=False).returncode == 0,
            f"falta {network}; instala/prepara primero Stack0")
    driver = run("docker", "network", "inspect", "-f", "{{.Driver}}", network, quiet=True)
    require(driver == "bridge", f"{network} usa driver {driver}, no bridge")
    print("  red de Stack0 verificada")

    print("\n== Gateway LiteLLM")
    require(subprocess.run(("docker", "inspect", "litellm"), stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, check=False).returncode == 0,
            "falta el contenedor litellm; despliega primero Stack3")
    running = run("docker", "inspect", "-f", "{{.State.Running}}", "litellm", quiet=True)
    require(running == "true", "litellm no esta en ejecucion")
    print("  LiteLLM disponible")

    print("\n== Runtime persistente Open WebUI")
    data_dir = Path(base_path.rstrip("/")) / "service_-_open-webui" / "data"
    for directory in (data_dir.parent, data_dir):
        require(directory.is_dir() and not directory.is_symlink(),
                f"falta {directory}; ejecuta primero stack-00_-_platform/00-bootstrap.py")
    print(f"  datos persistentes: {data_dir}")

    print("\n== Validacion de Docker Compose")
    run("docker", "compose", "--env-file", str(ENV_FILE), "-f", str(COMPOSE_FILE),
        "config", "--quiet", env=env)
    print("  compose valido")

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    LOCK_FILE.write_text(f"stack={STACK_NAME}\nprepared_at_utc={timestamp}\n")
    LOCK_FILE.chmod(0o644)
    print(f"\n== Preparacion terminada\n  lock creado: {LOCK_FILE}")
    print("  Open WebUI usara exclusivamente el gateway OpenAI-compatible de Stack3")


if __name__ == "__main__":
    try:
        main()
    except PrepareError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
