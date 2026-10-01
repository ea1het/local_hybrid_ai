#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Provision LiteLLM's PostgreSQL role and database after preparation.

This install phase requires the administrative password from .env, then
executes database commands in the dedicated PostgreSQL service.
It avoids recreating an existing database and does not reset persistent
PostgreSQL data. Importing the module does not connect to the database."""

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
    """Abort provisioning with an execution error."""
    raise RuntimeError(message)


def step(message):
    """Muestra el encabezado de una fase."""
    print(f"\n== {message}")


def log(message):
    """Print an indented progress detail."""
    print(f"  {message}")


def run(command, *, env=None, input_text=None, capture=False):
    """Ejecuta un comando con entrada opcional y posible captura de salida."""
    return subprocess.run(command, env=env, input=input_text, text=True, check=True,
                          stdout=subprocess.PIPE if capture else None)


def main():
    """Arranca PostgreSQL, crea o actualiza rol y base, y verifica acceso."""
    if os.geteuid() != 0:
        die("run this command as root")
    if not shutil.which("docker"):
        die("docker is not installed")
    if subprocess.run(["docker", "compose", "version"], stdout=subprocess.DEVNULL,
                      stderr=subprocess.DEVNULL).returncode:
        die("Docker Compose v2 is not available")
    if not ENV_FILE.is_file():
        die(f"missing {ENV_FILE}")
    loaded = subprocess.run(["bash", "-Eeuo", "pipefail", "-c", 'set -a; source "$1"; env -0', "bash", str(ENV_FILE)],
                            check=True, stdout=subprocess.PIPE).stdout
    env = dict(item.decode().split("=", 1) for item in loaded.split(b"\0") if item)
    os.environ.update(env)
    for key in ("BASE_PATH", "LITELLM_DB_NAME", "LITELLM_DB_USER", "LITELLM_DB_PASSWORD",
                "LITELLM_POSTGRES_ADMIN_PASSWORD"):
        if not env.get(key):
            die(f"missing {key} in {ENV_FILE}")
    admin_password = env["LITELLM_POSTGRES_ADMIN_PASSWORD"]
    if admin_password.startswith("PUT_YOUR_"):
        die("PostgreSQL administrator password is a template placeholder")
    compose = ["docker", "compose", "--env-file", str(ENV_FILE), "-f", str(COMPOSE_FILE)]
    step("Starting dedicated PostgreSQL")
    run(compose + ["up", "-d", "litellm-postgres"], env=env)
    for attempt in range(40):
        if subprocess.run(["docker", "exec", "litellm-postgres", "pg_isready", "-U", "postgres", "-d", "postgres"],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
            break
        if attempt == 39:
            die("litellm-postgres is not available")
        time.sleep(2)
    log("litellm-postgres is available")
    admin = ["docker", "exec", "-i", "-e", f"PGPASSWORD={admin_password}", "litellm-postgres",
             "psql", "-v", "ON_ERROR_STOP=1", "-h", "127.0.0.1", "-U", "postgres", "-d", "postgres"]
    step("LiteLLM PostgreSQL user")
    run(admin + ["-v", f"db_user={env['LITELLM_DB_USER']}", "-v", f"db_password={env['LITELLM_DB_PASSWORD']}"],
        input_text="""SELECT format('CREATE ROLE %I WITH LOGIN PASSWORD %L', :'db_user', :'db_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'db_user')
\\gexec
SELECT format('ALTER ROLE %I WITH LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION', :'db_user', :'db_password')
\\gexec
""")
    step("LiteLLM PostgreSQL database")
    exists = run(admin + ["-v", f"db_name={env['LITELLM_DB_NAME']}", "-tA"],
                 input_text="SELECT 1 FROM pg_database WHERE datname = :'db_name';\n", capture=True).stdout.strip()
    if exists != "1":
        run(["docker", "exec", "-e", f"PGPASSWORD={admin_password}", "litellm-postgres", "createdb",
             "-h", "127.0.0.1", "-U", "postgres", "-O", env["LITELLM_DB_USER"], env["LITELLM_DB_NAME"]])
    run(admin + ["-v", f"db_name={env['LITELLM_DB_NAME']}", "-v", f"db_user={env['LITELLM_DB_USER']}"],
        input_text="SELECT format('ALTER DATABASE %I OWNER TO %I', :'db_name', :'db_user')\n\\gexec\n")
    step("LiteLLM credential validation")
    run(["docker", "exec", "-e", f"PGPASSWORD={env['LITELLM_DB_PASSWORD']}", "litellm-postgres", "psql",
         "-v", "ON_ERROR_STOP=1", "-h", "127.0.0.1", "-U", env["LITELLM_DB_USER"],
         "-d", env["LITELLM_DB_NAME"], "-tAc", "SELECT 1;"], capture=True)
    log("PostgreSQL connection: OK")
    step("Docker Compose validation")
    run(compose + ["config", "--quiet"], env=env)
    log("Docker Compose configuration valid")
    step("Provisioning complete")
    log("Stack 30 dedicated PostgreSQL provisioned and validated")


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        message = (f"{error.cmd[0]} failed (exit {error.returncode})"
                   if isinstance(error, subprocess.CalledProcessError) else str(error))
        print(f"ERROR: {message}", file=sys.stderr)
        sys.exit(1)
