#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""
install-tls-certs.py

Instala el certificado wildcard de servidor (tls.crt / tls.key), emitido por
la CA mkcert, en la carpeta de servicio de HAProxy:

    ${BASE_PATH}/service_-_haproxy/config/tls.crt   0644 root:local-hybrid-pki
    ${BASE_PATH}/service_-_haproxy/config/tls.key   0640 root:local-hybrid-pki

Stack1 (01-prepare.py) coloca después haproxy.cfg en la misma carpeta, que se
monta en el contenedor como /usr/local/etc/haproxy. HAProxy (uid 99) lee la
clave privada mediante el grupo suplementario PLATFORM_PKI_GID.

Suposiciones:
  - tls.crt y tls.key se han copiado desde la CA mkcert a /tmp.
  - 00-bootstrap.py ya ha creado la carpeta de servicio de HAProxy.
  - install-ca-cert.py ya ha instalado la CA en
    /usr/local/share/ca-certificates/<LOCAL_CA_NAME>.crt (se usa para validar
    la cadena; LOCAL_CA_NAME se define en el .env central).

Uso:
  sudo ./install-tls-certs.py                    # instalación inicial
  sudo ./install-tls-certs.py --renew            # sustituir en un sistema en marcha
  sudo ./install-tls-certs.py --cert /ruta/tls.crt --key /ruta/tls.key

Qué hace:
  1. Valida certificado y clave (formato, correspondencia, cadena contra la CA,
     que el SAN contenga TODOS los nombres de TLS_SAN_DOMAINS del .env,
     caducidad).
  2. Los instala de forma atómica en la carpeta de servicio de HAProxy.
  3. Si HAProxy está en ejecución, indica cómo recargarlo.

Protección de sistemas en marcha: si Stack0 ya está PREPARADO
(stack-00_-_platform/.lock) el script no modifica nada salvo que se indique
--renew de forma explícita.

No borra los ficheros de /tmp. Es idempotente.
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True  # nunca crear __pycache__ en el worktree

import argparse
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

STACK_DIR = Path(__file__).resolve().parent
ROOT_DIR = STACK_DIR.parent
ENV_FILE = ROOT_DIR / ".env"
LOCK_FILE = STACK_DIR / ".lock"

DEFAULT_CERT = Path("/tmp/tls.crt")
DEFAULT_KEY = Path("/tmp/tls.key")
# Carpeta fijada por update-ca-certificates (Debian/Ubuntu); el nombre del
# fichero viene de LOCAL_CA_NAME en el .env.
SYSTEM_CA_DIR = Path("/usr/local/share/ca-certificates")
LOCAL_CA_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
EXPIRY_WARNING_SECONDS = 30 * 24 * 3600
SAN_NAME_RE = re.compile(r"^(\*\.)?[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*$")


def die(message: str, code: int = 1) -> None:
    """Muestra un error y termina con el código indicado."""
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(code)


def log(message: str) -> None:
    """Muestra un detalle de progreso con sangría."""
    print(f"  {message}")


def step(message: str) -> None:
    """Muestra el encabezado de una fase."""
    print(f"\n== {message}")


def openssl(*args: str) -> subprocess.CompletedProcess:
    """Ejecuta OpenSSL y devuelve código de salida y salida capturada."""
    return subprocess.run(["openssl", *args], text=True, capture_output=True, check=False)


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


def parse_args() -> argparse.Namespace:
    """Lee rutas de certificado, clave, CA y la opción de renovación."""
    parser = argparse.ArgumentParser(
        description="Instala tls.crt / tls.key en la carpeta de servicio de HAProxy.",
    )
    parser.add_argument("--cert", type=Path, default=DEFAULT_CERT, help=f"certificado (por defecto: {DEFAULT_CERT})")
    parser.add_argument("--key", type=Path, default=DEFAULT_KEY, help=f"clave privada (por defecto: {DEFAULT_KEY})")
    parser.add_argument(
        "--ca",
        type=Path,
        default=None,
        help=f"CA contra la que se valida la cadena (por defecto: {SYSTEM_CA_DIR}/<LOCAL_CA_NAME>.crt)",
    )
    parser.add_argument(
        "--renew",
        action="store_true",
        help="permite sustituir el certificado aunque Stack0 ya esté PREPARADO (.lock)",
    )
    return parser.parse_args()


def local_ca_path(env: dict[str, str]) -> Path:
    """Ruta de la CA en el trust store: SYSTEM_CA_DIR/<LOCAL_CA_NAME>.crt."""
    name = env.get("LOCAL_CA_NAME", "")
    if not name:
        die(f"falta LOCAL_CA_NAME en {ENV_FILE}")
    if not LOCAL_CA_NAME_RE.match(name):
        die(f"LOCAL_CA_NAME no válido (solo letras, dígitos, '.', '_', '-'; sin extensión): {name!r}")
    return SYSTEM_CA_DIR / f"{name}.crt"


def parse_san_domains(raw: str) -> list[str]:
    """Separa y valida los nombres DNS requeridos en TLS_SAN_DOMAINS."""
    names = raw.replace(",", " ").split()
    if not names:
        die(f"TLS_SAN_DOMAINS está vacío en {ENV_FILE}")
    for name in names:
        if not SAN_NAME_RE.match(name):
            die(f"nombre no válido en TLS_SAN_DOMAINS: {name!r}")
    return names


def require_regular_file(path: Path, label: str) -> None:
    """Exige un fichero regular no vacío que no sea un symlink."""
    if path.is_symlink() or not path.is_file() or path.stat().st_size == 0:
        die(f"falta o no es un fichero regular no vacío ({label}): {path}")


def validate_pair(cert: Path, key: Path, ca: Path, san_domains: list[str]) -> None:
    """Comprueba clave, cadena CA, SAN y vigencia del certificado TLS."""
    step("1/2 Validando certificado y clave")

    if openssl("x509", "-in", str(cert), "-noout").returncode != 0:
        die(f"certificado X.509 inválido: {cert}")
    if openssl("pkey", "-in", str(key), "-noout").returncode != 0:
        die(f"clave privada inválida: {key}")

    cert_pub = openssl("x509", "-in", str(cert), "-noout", "-pubkey").stdout
    key_pub = openssl("pkey", "-in", str(key), "-pubout").stdout
    if not cert_pub or cert_pub != key_pub:
        die("el certificado y la clave privada no se corresponden")
    log("certificado y clave se corresponden")

    verify = openssl("verify", "-CAfile", str(ca), str(cert))
    if verify.returncode != 0:
        die(f"el certificado no está firmado por la CA {ca}: {verify.stderr.strip() or verify.stdout.strip()}")
    log(f"cadena válida contra {ca}")

    san_output = openssl("x509", "-in", str(cert), "-noout", "-ext", "subjectAltName").stdout
    san = {entry.strip() for line in san_output.splitlines()[1:] for entry in line.split(",")}
    missing = [name for name in san_domains if f"DNS:{name}" not in san]
    if missing:
        die("el certificado no incluye en subjectAltName: " + ", ".join(f"DNS:{name}" for name in missing))
    log("SAN incluye " + ", ".join(san_domains))

    if openssl("x509", "-in", str(cert), "-noout", "-checkend", "0").returncode != 0:
        die("el certificado ha caducado")
    if openssl("x509", "-in", str(cert), "-noout", "-checkend", str(EXPIRY_WARNING_SECONDS)).returncode != 0:
        print("WARNING: el certificado caduca en menos de 30 días; renuévalo con mkcert", file=sys.stderr)

    summary = openssl("x509", "-in", str(cert), "-noout", "-subject", "-issuer", "-dates", "-fingerprint", "-sha256")
    print(summary.stdout, end="")


def install_atomic(source: Path, target: Path, mode: int, gid: int) -> bool:
    """Copia source a target (root:gid, mode) de forma atómica. Devuelve True si cambió."""
    if target.is_symlink() or (target.exists() and not target.is_file()):
        die(f"el destino no es un fichero regular: {target}")

    data = source.read_bytes()
    unchanged = target.is_file() and target.read_bytes() == data

    if not unchanged:
        fd, tmp_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.chown(tmp_name, 0, gid)
            os.chmod(tmp_name, mode)
            os.replace(tmp_name, target)
        except BaseException:
            Path(tmp_name).unlink(missing_ok=True)
            raise

    os.chown(target, 0, gid)
    os.chmod(target, mode)
    return not unchanged


def haproxy_running() -> bool:
    """Indica si existe un contenedor HAProxy en ejecución."""
    if shutil.which("docker") is None:
        return False
    result = subprocess.run(
        ["docker", "inspect", "-f", "{{.State.Running}}", "haproxy"],
        text=True,
        capture_output=True,
        check=False,
    )
    return result.returncode == 0 and result.stdout.strip() == "true"


def main() -> None:
    """Valida e instala el par TLS y avisa si HAProxy necesita recarga."""
    args = parse_args()

    if os.geteuid() != 0:
        die("ejecuta el script con sudo/root")
    if shutil.which("openssl") is None:
        die("falta el comando requerido: openssl")

    if LOCK_FILE.exists() and not args.renew:
        print(f"Stack0 ya está PREPARADO ({LOCK_FILE}); no se modifica nada.")
        print("Para sustituir el certificado en un sistema en marcha usa --renew.")
        return

    env = load_env(ENV_FILE)
    for key in ("BASE_PATH", "TLS_SAN_DOMAINS"):
        if not env.get(key):
            die(f"falta {key} en {ENV_FILE}")
    base_path = env["BASE_PATH"].rstrip("/")
    if not base_path.startswith("/"):
        die("BASE_PATH debe ser una ruta absoluta")
    san_domains = parse_san_domains(env["TLS_SAN_DOMAINS"])
    ca = args.ca if args.ca is not None else local_ca_path(env)

    pki_gid_raw = env.get("PLATFORM_PKI_GID") or "1999"
    if not pki_gid_raw.isdigit() or int(pki_gid_raw) <= 0:
        die("PLATFORM_PKI_GID debe ser un entero positivo")
    pki_gid = int(pki_gid_raw)

    target_dir = Path(base_path) / "service_-_haproxy" / "config"
    if target_dir.is_symlink() or not target_dir.is_dir():
        die(f"falta la carpeta de servicio {target_dir}; ejecuta primero 00-bootstrap.py")

    require_regular_file(args.cert, "certificado")
    require_regular_file(args.key, "clave privada")
    require_regular_file(ca, "CA (instálala con install-ca-cert.py)")

    validate_pair(args.cert, args.key, ca, san_domains)

    step("2/2 Instalando en la carpeta de servicio de HAProxy")
    cert_target = target_dir / "tls.crt"
    key_target = target_dir / "tls.key"
    changed_cert = install_atomic(args.cert, cert_target, 0o644, pki_gid)
    changed_key = install_atomic(args.key, key_target, 0o640, pki_gid)
    log(f"{cert_target}: {'actualizado' if changed_cert else 'sin cambios'} (0644 root:{pki_gid})")
    log(f"{key_target}: {'actualizado' if changed_key else 'sin cambios'} (0640 root:{pki_gid})")

    print("\nSUCCESS")
    if (changed_cert or changed_key) and haproxy_running():
        print("HAProxy está en ejecución; recárgalo para usar el nuevo certificado:")
        print(f"  cd {ROOT_DIR}/stack-10_-_haproxy_web && docker compose restart haproxy")


if __name__ == "__main__":
    main()
