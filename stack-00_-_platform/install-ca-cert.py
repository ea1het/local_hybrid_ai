#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Install the local mkcert CA into the Linux host trust store.

The script validates that the supplied PEM is a CA certificate, installs it
under /usr/local/share/ca-certificates using LOCAL_CA_NAME from .env, refreshes
the host certificate bundle, and verifies that the new CA is trusted. The
default input is /tmp/rootCA.pem; the host needs update-ca-certificates.
An installed, trusted CA is preserved without requiring the source PEM, even
when Stack 0 has a lock. Missing or invalid CA state is repaired from the
source; --force explicitly authorizes rotation. Importing is safe."""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True  # never create __pycache__ in the worktree

import argparse
import os
import re
import shutil
import subprocess
from pathlib import Path

STACK_DIR = Path(__file__).resolve().parent
ENV_FILE = STACK_DIR.parent / ".env"
DEFAULT_CA = Path("/tmp/rootCA.pem")
# Rutas fijadas por update-ca-certificates (Debian/Ubuntu), no por el despliegue:
# Only reads *.crt files from SYSTEM_CA_DIR and generates HOST_CA_BUNDLE.
SYSTEM_CA_DIR = Path("/usr/local/share/ca-certificates")
HOST_CA_BUNDLE = Path("/etc/ssl/certs/ca-certificates.crt")
LOCAL_CA_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def die(message: str, code: int = 1) -> None:
    """Print an error and exit with the requested status code."""
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(code)


def run(cmd: list[str], *, capture: bool = False) -> subprocess.CompletedProcess:
    """Ejecuta un comando y termina si falla; puede capturar su salida."""
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
    """Require root privileges before changing the CA trust store."""
    if os.geteuid() != 0:
        die("Ejecuta el script con sudo/root.")


def require_commands() -> None:
    """Check that installation and validation commands are available."""
    required = ("openssl", "install", "update-ca-certificates")
    missing = [cmd for cmd in required if shutil.which(cmd) is None]
    if missing:
        die("Faltan comandos requeridos: " + ", ".join(missing))


def parse_args() -> argparse.Namespace:
    """Parse the optional CA path and explicit replacement permission."""
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
        help="sustituye la CA instalada aunque ya sea válida (rotación explícita)",
    )
    return parser.parse_args()


def find_ca(path: Path) -> Path:
    """Devuelve la ruta resuelta de un certificado CA regular, sin symlink."""
    source = path.resolve()
    if not source.is_file() or path.is_symlink():
        die(f"No existe el certificado CA (o es un symlink): {path}. Cópialo desde la CA mkcert.")
    return source


def validate_ca(source: Path) -> None:
    """Comprueba CA:TRUE y muestra los datos del certificado origen."""
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
    """Install the public CA certificate and refresh the host trust bundle."""
    print("\n== 2/3 Instalando CA en el host ==")
    dest.parent.mkdir(parents=True, exist_ok=True)
    run(["install", "-m", "0644", "-o", "0", "-g", "0", str(source), str(dest)])
    run(["update-ca-certificates"])


def verify_bundle(dest: Path) -> None:
    """Verifica la CA instalada frente al bundle de certificados del host."""
    print("\n== 3/3 Verificando bundle del host ==")
    if not HOST_CA_BUNDLE.is_file():
        die(f"No existe el bundle del sistema esperado: {HOST_CA_BUNDLE}")
    verify = run(["openssl", "verify", "-CAfile", str(HOST_CA_BUNDLE), str(dest)], capture=True)
    print(verify.stdout, end="")


def certificate_valid(path: Path) -> bool:
    """Check whether an existing regular file contains a CA certificate."""
    if path.is_symlink() or not path.is_file():
        return False
    result = subprocess.run(
        ["openssl", "x509", "-in", str(path), "-noout", "-text"],
        text=True, capture_output=True, check=False,
    )
    return result.returncode == 0 and "CA:TRUE" in result.stdout


def bundle_trusts(path: Path) -> bool:
    """Check that the host bundle verifies the installed CA."""
    if not HOST_CA_BUNDLE.is_file():
        return False
    result = subprocess.run(
        ["openssl", "verify", "-CAfile", str(HOST_CA_BUNDLE), str(path)],
        text=True, capture_output=True, check=False,
    )
    return result.returncode == 0


def main() -> None:
    """Preserve a trusted CA or repair missing and invalid host CA state."""
    args = parse_args()
    require_root()
    require_commands()

    dest = local_ca_path(load_env(ENV_FILE))
    if dest.is_symlink() or (dest.exists() and not dest.is_file()):
        die(f"destino de CA no seguro: {dest}")

    if not args.force and certificate_valid(dest):
        dest_stat = dest.stat()
        if (dest_stat.st_uid, dest_stat.st_gid, dest_stat.st_mode & 0o7777) != (0, 0, 0o644):
            os.chown(dest, 0, 0)
            os.chmod(dest, 0o644)
            print(f"Permisos de CA reparados: {dest}")
        if not bundle_trusts(dest):
            print(f"CA instalada pero sin confianza en el bundle; actualizando: {dest}")
            run(["update-ca-certificates"])
        verify_bundle(dest)
        print(f"CA ya instalada y confiable; sin cambios: {dest}")
        return

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
