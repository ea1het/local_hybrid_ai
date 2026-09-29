#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Prepare LiteLLM configuration and its dedicated PostgreSQL storage.

The entrypoint verifies Stack 0 prerequisites, the service source files,
and pre-created runtime directories. It provisions required secrets and
configuration while preserving an existing PostgreSQL data directory;
database role creation is handled separately by provision-postgres.py.
The .lock marks successful preparation, not service health. Import is inert."""

import datetime
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
            die(f"falta {key} en {ENV_FILE}")


def main():
    """Check dependencies, prepare the secret and configuration, and write the lock."""
    if LOCK_FILE.exists() or LOCK_FILE.is_symlink():
        print(f"Stack ya preparado. Existe {LOCK_FILE}; no se realiza ningun cambio.")
        return
    if os.geteuid() != 0:
        die("ejecuta este script como root")
    for command in ("docker", "openssl", "install"):
        if not shutil.which(command):
            die(f"{command} no esta instalado")
    if subprocess.run(["docker", "compose", "version"], stdout=subprocess.DEVNULL,
                      stderr=subprocess.DEVNULL).returncode:
        die("Docker Compose v2 no esta disponible")
    for path in (ENV_FILE, COMPOSE_FILE):
        if not path.is_file():
            die(f"falta {path}")
    if re.search(r"^[A-Za-z_][A-Za-z0-9_]*=.*(<REDACT|\.{5,})",
                 ENV_FILE.read_text(), re.MULTILINE):
        die(f"{ENV_FILE} contiene valores saneados/incompletos")
    env = load_env()
    os.environ.update(env)
    require(env, "STACKS_ROOT BASE_PATH NETWORK_NAME LITELLM_IMAGE LITELLM_VERSION "
            "LITELLM_MASTER_KEY LITELLM_SALT_KEY UI_USERNAME UI_PASSWORD "
            "STORE_MODEL_IN_DB LITELLM_DB_NAME LITELLM_DB_USER LITELLM_DB_PASSWORD")
    stacks_root = env["STACKS_ROOT"].rstrip("/")
    base_path = env["BASE_PATH"].rstrip("/")
    if not env["STACKS_ROOT"].startswith("/") or not env["BASE_PATH"].startswith("/"):
        die("STACKS_ROOT y BASE_PATH deben ser rutas absolutas")
    if str(STACK_DIR) != f"{stacks_root}/{STACK_NAME}":
        die(f"este stack debe residir en {stacks_root}/{STACK_NAME}; ruta actual: {STACK_DIR}")
    if stacks_root == base_path:
        die("STACKS_ROOT y BASE_PATH deben ser distintos")
    if env["LITELLM_IMAGE"].endswith(":latest"):
        die("LITELLM_IMAGE no debe usar :latest")
    if env["LITELLM_VERSION"] == "latest":
        die("LITELLM_VERSION no puede ser latest")
    for key in ("LITELLM_DB_NAME", "LITELLM_DB_USER"):
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", env[key]):
            die(f"{key} no es valido")
    stack0_lock = Path(stacks_root) / "stack-00_-_platform/.lock"
    if not stack0_lock.is_file():
        die(f"Stack0 no esta preparado: falta {stack0_lock}")
    network = env["NETWORK_NAME"]
    if subprocess.run(["docker", "network", "inspect", network], stdout=subprocess.DEVNULL,
                      stderr=subprocess.DEVNULL).returncode:
        die(f"falta la red {network}; ejecuta primero Stack0")
    driver = run(["docker", "network", "inspect", "-f", "{{.Driver}}", network], capture=True).stdout.strip()
    if driver != "bridge":
        die(f"{network} usa driver {driver}, no bridge")
    service_dir = Path(base_path) / "service_-_litellm"
    postgres_dir = Path(base_path) / "service_-_litellm-postgres"
    data_dir = postgres_dir / "data"
    secret_dir = postgres_dir / "secret"
    password_file = secret_dir / "postgres_admin_password"
    config_source = STACK_DIR / "config/litellm/config.yaml"
    config_dir = service_dir / "config"
    if not config_source.is_file():
        die(f"falta {config_source}")
    step("Runtime de Stack3")
    for directory in (service_dir, config_dir, postgres_dir, data_dir, secret_dir):
        if not directory.is_dir() or directory.is_symlink():
            die(f"falta {directory}; ejecuta primero stack-00_-_platform/00-bootstrap.py")
    log("carpetas de servicio verificadas")
    if password_file.exists() or password_file.is_symlink():
        if not password_file.is_file() or password_file.is_symlink() or not password_file.stat().st_size:
            die(f"estado invalido del secreto PostgreSQL: {password_file}")
        log("secreto administrativo PostgreSQL existente: preservado")
    else:
        password = run(["openssl", "rand", "-hex", "32"], capture=True).stdout
        descriptor = os.open(password_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as secret:
            secret.write(password)
        log("secreto administrativo PostgreSQL: generado una vez")
    os.chown(password_file, 0, 0)
    os.chmod(password_file, 0o600)
    log(f"PostgreSQL dedicado: {data_dir}")
    step("Configuracion de LiteLLM")
    run(["install", "-m", "0644", "-o", "0", "-g", "0", str(config_source), str(config_dir / "config.yaml")])
    log(f"config.yaml sincronizado desde {config_source} sin reemplazar el directorio bind")
    log(f"imagen fijada: {env['LITELLM_IMAGE']}:{env['LITELLM_VERSION']}")
    step("Validacion de Docker Compose")
    run(["docker", "compose", "--env-file", str(ENV_FILE), "-f", str(COMPOSE_FILE), "config", "--quiet"], env=env)
    log("compose valido")
    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    LOCK_FILE.write_text(f"stack={STACK_NAME}\nprepared_at_utc={timestamp}\n")
    step("Preparacion terminada")
    log(f"lock creado: {LOCK_FILE}")
    log("PostgreSQL pertenece ahora a Stack3")


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        message = (f"fallo {error.cmd[0]} (exit {error.returncode})"
                   if isinstance(error, subprocess.CalledProcessError) else str(error))
        print(f"ERROR: {message}", file=sys.stderr)
        sys.exit(1)
