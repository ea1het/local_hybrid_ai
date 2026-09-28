#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Provisiona el rol y la base de datos PostgreSQL dedicados a LiteLLM."""

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.dont_write_bytecode = True

STACK_DIR = Path(__file__).resolve().parent
ENV_FILE = STACK_DIR / ".env"
COMPOSE_FILE = STACK_DIR / "docker-compose.yml"
LOCK_FILE = STACK_DIR / ".lock"


def die(message):
    """Interrumpe el provisionado con un error de ejecución."""
    raise RuntimeError(message)


def step(message):
    """Muestra el encabezado de una fase."""
    print(f"\n== {message}")


def log(message):
    """Muestra un detalle de progreso con sangría."""
    print(f"  {message}")


def run(command, *, env=None, input_text=None, capture=False):
    """Ejecuta un comando con entrada opcional y posible captura de salida."""
    return subprocess.run(command, env=env, input=input_text, text=True, check=True,
                          stdout=subprocess.PIPE if capture else None)


def main():
    """Arranca PostgreSQL, crea o actualiza rol y base, y verifica acceso."""
    if os.geteuid() != 0:
        die("ejecuta este script como root")
    if not shutil.which("docker"):
        die("docker no esta instalado")
    if subprocess.run(["docker", "compose", "version"], stdout=subprocess.DEVNULL,
                      stderr=subprocess.DEVNULL).returncode:
        die("Docker Compose v2 no esta disponible")
    if not ENV_FILE.is_file():
        die(f"falta {ENV_FILE}")
    if not LOCK_FILE.is_file():
        die(f"Stack3 no esta preparado: falta {LOCK_FILE}; ejecuta primero ./01-prepare.py")
    loaded = subprocess.run(["bash", "-Eeuo", "pipefail", "-c", 'set -a; source "$1"; env -0', "bash", str(ENV_FILE)],
                            check=True, stdout=subprocess.PIPE).stdout
    env = dict(item.decode().split("=", 1) for item in loaded.split(b"\0") if item)
    os.environ.update(env)
    for key in ("BASE_PATH", "LITELLM_DB_NAME", "LITELLM_DB_USER", "LITELLM_DB_PASSWORD"):
        if not env.get(key):
            die(f"falta {key} en {ENV_FILE}")
    secret_file = Path(env["BASE_PATH"].rstrip("/")) / "service_-_litellm-postgres/secret/postgres_admin_password"
    if not secret_file.is_file() or secret_file.is_symlink() or not secret_file.stat().st_size:
        die("falta el secreto administrativo PostgreSQL; ejecuta primero ./01-prepare.py")
    admin_password = secret_file.read_text().rstrip("\n")
    if not admin_password:
        die("el secreto administrativo PostgreSQL esta vacio")
    compose = ["docker", "compose", "--env-file", str(ENV_FILE), "-f", str(COMPOSE_FILE)]
    step("Arranque de PostgreSQL dedicado")
    run(compose + ["up", "-d", "litellm-postgres"], env=env)
    for attempt in range(40):
        if subprocess.run(["docker", "exec", "litellm-postgres", "pg_isready", "-U", "postgres", "-d", "postgres"],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
            break
        if attempt == 39:
            die("litellm-postgres no esta disponible")
        time.sleep(2)
    log("litellm-postgres disponible")
    admin = ["docker", "exec", "-i", "-e", f"PGPASSWORD={admin_password}", "litellm-postgres",
             "psql", "-v", "ON_ERROR_STOP=1", "-h", "127.0.0.1", "-U", "postgres", "-d", "postgres"]
    step("Usuario PostgreSQL de LiteLLM")
    run(admin + ["-v", f"db_user={env['LITELLM_DB_USER']}", "-v", f"db_password={env['LITELLM_DB_PASSWORD']}"],
        input_text="""SELECT format('CREATE ROLE %I WITH LOGIN PASSWORD %L', :'db_user', :'db_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'db_user')
\\gexec
SELECT format('ALTER ROLE %I WITH LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION', :'db_user', :'db_password')
\\gexec
""")
    step("Base de datos PostgreSQL de LiteLLM")
    exists = run(admin + ["-v", f"db_name={env['LITELLM_DB_NAME']}", "-tA"],
                 input_text="SELECT 1 FROM pg_database WHERE datname = :'db_name';\n", capture=True).stdout.strip()
    if exists != "1":
        run(["docker", "exec", "-e", f"PGPASSWORD={admin_password}", "litellm-postgres", "createdb",
             "-h", "127.0.0.1", "-U", "postgres", "-O", env["LITELLM_DB_USER"], env["LITELLM_DB_NAME"]])
    run(admin + ["-v", f"db_name={env['LITELLM_DB_NAME']}", "-v", f"db_user={env['LITELLM_DB_USER']}"],
        input_text="SELECT format('ALTER DATABASE %I OWNER TO %I', :'db_name', :'db_user')\n\\gexec\n")
    step("Validacion de credenciales LiteLLM")
    run(["docker", "exec", "-e", f"PGPASSWORD={env['LITELLM_DB_PASSWORD']}", "litellm-postgres", "psql",
         "-v", "ON_ERROR_STOP=1", "-h", "127.0.0.1", "-U", env["LITELLM_DB_USER"],
         "-d", env["LITELLM_DB_NAME"], "-tAc", "SELECT 1;"], capture=True)
    log("conexion PostgreSQL: OK")
    step("Validacion de Docker Compose")
    run(compose + ["config", "--quiet"], env=env)
    log("compose valido")
    step("Provisionado terminado")
    log("PostgreSQL dedicado de Stack3 provisionado y validado")


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        message = (f"fallo {error.cmd[0]} (exit {error.returncode})"
                   if isinstance(error, subprocess.CalledProcessError) else str(error))
        print(f"ERROR: {message}", file=sys.stderr)
        sys.exit(1)
