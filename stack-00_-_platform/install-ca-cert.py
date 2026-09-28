#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""
install-ca-cert.py

Instala la CA local (mkcert) en el trust store del host y termina.

Suposiciones:
  - La CA pública se ha copiado desde el Mac mini (CA mkcert) a /tmp/rootCA.pem.
  - El host es Debian/Ubuntu (update-ca-certificates).

Uso:
  sudo ./install-ca-cert.py                      # instalación inicial
  sudo ./install-ca-cert.py --force              # sustituir en un sistema en marcha
  sudo ./install-ca-cert.py --ca /ruta/rootCA.pem

Qué hace:
  1. Valida que el fichero es un certificado de CA (CA:TRUE).
  2. Lo instala en /usr/local/share/ca-certificates/<LOCAL_CA_NAME>.crt
     (LOCAL_CA_NAME se define en el .env central).
  3. Ejecuta update-ca-certificates.
  4. Verifica con openssl que la CA forma parte del bundle del host
     (/etc/ssl/certs/ca-certificates.crt).

No modifica ningún stack. Los contenedores que necesitan confiar en la CA
(p. ej. LiteLLM en Stack3) montan el bundle del host desde su propio Compose.
No borra /tmp/rootCA.pem.

Protección de sistemas en marcha: si Stack0 ya está PREPARADO
(stack-00_-_platform/.lock) el script no modifica nada salvo que se indique
--force de forma explícita (p. ej. rotación de la CA).

Es idempotente: puede ejecutarse varias veces.
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True  # nunca crear __pycache__ en el worktree

import argparse
import os
import re
import shutil
import subprocess
from pathlib import Path

STACK_DIR = Path(__file__).resolve().parent
ENV_FILE = STACK_DIR.parent / ".env"
LOCK_FILE = STACK_DIR / ".lock"
DEFAULT_CA = Path("/tmp/rootCA.pem")
# Rutas fijadas por update-ca-certificates (Debian/Ubuntu), no por el despliegue:
# solo lee ficheros *.crt de SYSTEM_CA_DIR y genera HOST_CA_BUNDLE.
SYSTEM_CA_DIR = Path("/usr/local/share/ca-certificates")
HOST_CA_BUNDLE = Path("/etc/ssl/certs/ca-certificates.crt")
LOCAL_CA_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def die(message: str, code: int = 1) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(code)


def run(cmd: list[str], *, capture: bool = False) -> subprocess.CompletedProcess:
    print("+", " ".join(cmd))
    try:
        return subprocess.run(cmd, text=True, check=True, capture_output=capture)
    except subprocess.CalledProcessError as exc:
        if capture:
            if exc.stdout:
                print(exc.stdout, file=sys.stderr, end="")
            if exc.stderr:
                print(exc.stderr, file=sys.stderr, end="")
        die(f"falló el comando: {' '.join(cmd)}")
        raise


def load_env(env_file: Path) -> dict[str, str]:
    """Carga el .env central con las mismas reglas que los scripts bash (source)."""
    if not env_file.is_file() or env_file.is_symlink():
        die(f"falta el entorno operativo raíz: {env_file}")
    result = subprocess.run(
        ["bash", "-c", 'set -a; source "$1"; set +a; env -0', "_", str(env_file)],
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        die(f"no se pudo cargar {env_file}: {result.stderr.decode(errors='replace').strip()}")
    env: dict[str, str] = {}
    for item in result.stdout.split(b"\0"):
        if b"=" in item:
            key, _, value = item.partition(b"=")
            env[key.decode()] = value.decode(errors="replace")
    return env


def local_ca_path(env: dict[str, str]) -> Path:
    """Ruta de la CA en el trust store: SYSTEM_CA_DIR/<LOCAL_CA_NAME>.crt."""
    name = env.get("LOCAL_CA_NAME", "")
    if not name:
        die(f"falta LOCAL_CA_NAME en {ENV_FILE}")
    if not LOCAL_CA_NAME_RE.match(name):
        die(f"LOCAL_CA_NAME no válido (solo letras, dígitos, '.', '_', '-'; sin extensión): {name!r}")
    return SYSTEM_CA_DIR / f"{name}.crt"


def require_root() -> None:
    if os.geteuid() != 0:
        die("Ejecuta el script con sudo/root.")


def require_commands() -> None:
    required = ("openssl", "install", "update-ca-certificates")
    missing = [cmd for cmd in required if shutil.which(cmd) is None]
    if missing:
        die("Faltan comandos requeridos: " + ", ".join(missing))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Instala la CA local (rootCA.pem) en el trust store del host.",
    )
    parser.add_argument(
        "--ca",
        type=Path,
        default=DEFAULT_CA,
        help=f"Ruta al certificado de la CA (por defecto: {DEFAULT_CA})",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="permite sustituir la CA aunque Stack0 ya esté PREPARADO (.lock)",
    )
    return parser.parse_args()


def find_ca(path: Path) -> Path:
    source = path.resolve()
    if not source.is_file() or path.is_symlink():
        die(f"No existe el certificado CA (o es un symlink): {path}. Cópialo desde la CA mkcert.")
    return source


def validate_ca(source: Path) -> None:
    print("\n== 1/3 Validando CA ==")
    result = run(["openssl", "x509", "-in", str(source), "-noout", "-text"], capture=True)
    if "CA:TRUE" not in result.stdout:
        die(f"El certificado no parece ser una CA (no contiene CA:TRUE): {source}")

    summary = run(
        [
            "openssl", "x509", "-in", str(source), "-noout",
            "-subject", "-issuer", "-dates", "-fingerprint", "-sha256",
        ],
        capture=True,
    )
    print(summary.stdout, end="")


def install_ca_on_host(source: Path, dest: Path) -> None:
    print("\n== 2/3 Instalando CA en el host ==")
    dest.parent.mkdir(parents=True, exist_ok=True)
    run(["install", "-m", "0644", "-o", "0", "-g", "0", str(source), str(dest)])
    run(["update-ca-certificates"])


def verify_bundle(dest: Path) -> None:
    print("\n== 3/3 Verificando bundle del host ==")
    if not HOST_CA_BUNDLE.is_file():
        die(f"No existe el bundle del sistema esperado: {HOST_CA_BUNDLE}")
    verify = run(["openssl", "verify", "-CAfile", str(HOST_CA_BUNDLE), str(dest)], capture=True)
    print(verify.stdout, end="")


def main() -> None:
    args = parse_args()

    if LOCK_FILE.exists() and not args.force:
        print(f"Stack0 ya está PREPARADO ({LOCK_FILE}); no se modifica nada.")
        print("Para sustituir la CA en un sistema en marcha usa --force.")
        return

    require_root()
    require_commands()

    dest = local_ca_path(load_env(ENV_FILE))
    source = find_ca(args.ca)
    print(f"CA origen: {source}")

    validate_ca(source)
    install_ca_on_host(source, dest)
    verify_bundle(dest)

    print("\nSUCCESS")
    print(f"CA local instalada:  {dest}")
    print(f"Bundle del host:     {HOST_CA_BUNDLE}")


if __name__ == "__main__":
    main()
