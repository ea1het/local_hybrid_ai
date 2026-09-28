#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Prepara SearXNG y Firecrawl sobre los directorios y la red de Stack0."""

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
            "RABBITMQ_USER RABBITMQ_PASSWORD FIRECRAWL_DB_USER FIRECRAWL_DB_PASSWORD FIRECRAWL_DB_NAME").split()


def log(message):
    """Muestra un detalle de progreso con sangría."""
    print(f"  {message}")


def step(message):
    """Muestra el encabezado de una fase."""
    print(f"\n== {message}")


def die(message):
    """Muestra un error y termina la preparación."""
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def sourced_environment():
    """Rechaza valores saneados y devuelve las variables del .env cargadas por Bash."""
    if re.search(r"^[A-Za-z_][A-Za-z0-9_]*=.*(<REDACT|\.{5,})", ENV_FILE.read_text(), re.MULTILINE):
        die(f"{ENV_FILE} contiene valores saneados/incompletos")
    result = subprocess.run(["bash", "-c", 'set -Eeuo pipefail; set -a; source "$1"; env -0', "bash", str(ENV_FILE)],
                            stdout=subprocess.PIPE, check=True)
    return dict(os.fsdecode(item).split("=", 1) for item in result.stdout.split(b"\0") if item)


def main():
    """Valida dependencias, conserva o crea el secreto y prepara la configuración."""
    if LOCK_FILE.exists():
        print(f"Stack ya preparado. Existe {LOCK_FILE}; no se realiza ningun cambio.")
        return
    if os.geteuid() != 0:
        die("ejecuta este script como root")
    for command in ("docker", "openssl", "install", "stat"):
        if shutil.which(command) is None:
            die(f"{command} no esta instalado")
    if subprocess.run(["docker", "compose", "version"], stdout=subprocess.DEVNULL,
                      stderr=subprocess.DEVNULL).returncode:
        die("Docker Compose v2 no esta disponible")
    for path in (ENV_FILE, COMPOSE_FILE):
        if not path.is_file():
            die(f"falta {path}")
    env = sourced_environment()
    for key in REQUIRED:
        if not env.get(key):
            die(f"falta {key} en {ENV_FILE}")
    stacks_root, base_path = env["STACKS_ROOT"].rstrip("/"), env["BASE_PATH"].rstrip("/")
    if not env["STACKS_ROOT"].startswith("/") or not env["BASE_PATH"].startswith("/"):
        die("STACKS_ROOT y BASE_PATH deben ser rutas absolutas")
    if str(STACK_DIR) != f"{stacks_root}/{STACK_NAME}":
        die(f"este stack debe residir en {stacks_root}/{STACK_NAME}; ruta actual: {STACK_DIR}")
    if stacks_root == base_path:
        die("STACKS_ROOT y BASE_PATH deben ser distintos")
    if not env["SEARXNG_BASE_URL"].startswith("https://"):
        die("SEARXNG_BASE_URL debe ser HTTPS")
    db_user = env["FIRECRAWL_DB_USER"]
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", db_user):
        die("FIRECRAWL_DB_USER no es valido")
    if db_user == "postgres":
        die("FIRECRAWL_DB_USER no puede ser postgres")
    if env["FIRECRAWL_DB_NAME"] != "postgres":
        die("FIRECRAWL_DB_NAME debe ser postgres para NUQ/pg_cron")
    stack0_lock = Path(stacks_root) / "stack-00_-_platform/.lock"
    settings = STACK_DIR / "config/searxng/settings.yml"
    limiter = STACK_DIR / "config/searxng/limiter.toml"
    postgres_init = STACK_DIR / "config/postgres/020-firecrawl-app-role.sh"
    for path in (stack0_lock, settings, limiter, postgres_init):
        if not path.is_file():
            die(f"falta {path}" + ("; prepara primero Stack0" if path == stack0_lock else ""))
    searxng_service = Path(base_path) / "service_-_searxng"
    searxng_config = searxng_service / "config"
    postgres_service = Path(base_path) / "service_-_firecrawl-postgres"
    postgres_secret = postgres_service / "secret/postgres_admin_password"

    network = env["NETWORK_NAME"]
    step(f"Red Docker compartida {network}")
    if subprocess.run(["docker", "network", "inspect", network], env=env, stdout=subprocess.DEVNULL,
                      stderr=subprocess.DEVNULL).returncode:
        die(f"falta {network}; instala/prepara primero Stack0")
    driver = subprocess.check_output(["docker", "network", "inspect", "-f", "{{.Driver}}", network], env=env).decode().rstrip("\n")
    if driver != "bridge":
        die(f"{network} usa driver {driver}, no bridge")
    log("existe, es bridge y permanece propiedad de Stack0")

    step("Directorios persistentes")
    for directory in (searxng_service, searxng_config, searxng_service / "data",
                      Path(base_path) / "service_-_firecrawl-redis/data",
                      Path(base_path) / "service_-_firecrawl-rabbitmq/data", postgres_service,
                      postgres_service / "data", postgres_service / "secret"):
        if not directory.is_dir() or directory.is_symlink():
            die(f"falta {directory}; ejecuta primero stack-00_-_platform/00-bootstrap.py")
    log("carpetas y permisos gestionados por Stack0 (00-bootstrap.py)")

    step("Secreto administrativo PostgreSQL")
    if postgres_secret.exists():
        if not postgres_secret.is_file() or postgres_secret.is_symlink() or not postgres_secret.stat().st_size:
            die(f"estado invalido del secreto PostgreSQL: {postgres_secret}")
        os.chown(postgres_secret, 0, 0)
        os.chmod(postgres_secret, 0o600)
        log("secreto administrativo PostgreSQL existente: preservado")
    else:
        os.umask(0o077)
        with postgres_secret.open("wb") as output:
            subprocess.run(["openssl", "rand", "-hex", "32"], stdout=output, check=True)
        os.chown(postgres_secret, 0, 0)
        os.chmod(postgres_secret, 0o600)
        log("secreto administrativo PostgreSQL: generado una vez")

    step("Configuracion de SearXNG")
    for source in (settings, limiter):
        target = searxng_config / source.name
        if target.is_dir() and not target.is_symlink():
            die(f"ruta de configuracion no puede ser un directorio: {target}")
    owner, group = searxng_config.stat().st_uid, searxng_config.stat().st_gid
    for source in (settings, limiter):
        subprocess.run(["install", "-m", "0644", "-o", str(owner), "-g", str(group),
                        str(source), str(searxng_config / source.name)], check=True)
    log("directorio bind-mounted preservado; solo se reconcilian ficheros gestionados")

    step("Validacion de Docker Compose")
    subprocess.run(["docker", "compose", "--env-file", str(ENV_FILE), "-f", str(COMPOSE_FILE),
                    "config", "--quiet"], env=env, check=True)
    log("compose valido")
    os.umask(0o022)
    LOCK_FILE.write_text(f"stack={STACK_NAME}\nprepared_at_utc={datetime.datetime.now(datetime.timezone.utc):%Y-%m-%dT%H:%M:%SZ}\n")
    step("Preparacion terminada")
    log(f"lock creado: {LOCK_FILE}")
    log(f"postgres queda reservado como rol administrativo; Firecrawl usa {db_user}")
    log("red compartida consumida desde Stack0; no se crea ni se modifica")


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as exc:
        raise SystemExit(exc.returncode) from None
