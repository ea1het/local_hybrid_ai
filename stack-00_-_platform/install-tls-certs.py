#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Install the local TLS certificate and key for HAProxy.

The script validates the certificate/key pair, trust chain, expiration, and
all hostnames configured by TLS_SAN_DOMAINS before atomically installing
tls.crt and tls.key in HAProxy's service directory. It relies on bootstrap
having created that directory and on the local CA being installed first.
Ownership and modes allow HAProxy to read the private key through the
local-hybrid-pki group. A valid installed pair is kept without requiring
the source files; missing or invalid material is repaired from them.
--renew explicitly requests replacement, and importing is inert."""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True  # never create __pycache__ in the worktree

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

DEFAULT_CERT = Path("/tmp/tls.crt")
DEFAULT_KEY = Path("/tmp/tls.key")
# Directory used by update-ca-certificates (Debian/Ubuntu); the filename
# comes from LOCAL_CA_NAME in the central .env file.
SYSTEM_CA_DIR = Path("/usr/local/share/ca-certificates")
LOCAL_CA_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
EXPIRY_WARNING_SECONDS = 30 * 24 * 3600
SAN_NAME_RE = re.compile(r"^(\*\.)?[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*$")


def die(message: str, code: int = 1) -> None:
    """Print an error and exit with the requested status code."""
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(code)


def log(message: str) -> None:
    """Print an indented progress detail."""
    print(f"  {message}")


def step(message: str) -> None:
    """Muestra el encabezado de una fase."""
    print(f"\n== {message}")


def openssl(*args: str) -> subprocess.CompletedProcess:
    """Run OpenSSL and return its exit status and captured output."""
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
    """Parse certificate, key, and CA paths and the renewal option."""
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
        help="sustituye el par TLS aunque el instalado sea válido (rotación explícita)",
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
    """Require a nonempty regular file rather than a symbolic link."""
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


def pair_healthy(cert: Path, key: Path, ca: Path, san_domains: list[str]) -> bool:
    """Check the installed pair without printing or changing private material."""
    if any(path.is_symlink() or not path.is_file() or path.stat().st_size == 0 for path in (cert, key)):
        return False
    if openssl("x509", "-in", str(cert), "-noout").returncode != 0:
        return False
    if openssl("pkey", "-in", str(key), "-noout").returncode != 0:
        return False
    cert_pub = openssl("x509", "-in", str(cert), "-noout", "-pubkey")
    key_pub = openssl("pkey", "-in", str(key), "-pubout")
    if cert_pub.returncode or key_pub.returncode or not cert_pub.stdout or cert_pub.stdout != key_pub.stdout:
        return False
    if openssl("verify", "-CAfile", str(ca), str(cert)).returncode != 0:
        return False
    if openssl("x509", "-in", str(cert), "-noout", "-checkend", "0").returncode != 0:
        return False
    result = openssl("x509", "-in", str(cert), "-noout", "-ext", "subjectAltName")
    if result.returncode != 0:
        return False
    san = {entry.strip() for line in result.stdout.splitlines()[1:] for entry in line.split(",")}
    return all(f"DNS:{name}" in san for name in san_domains)


def ensure_metadata(path: Path, mode: int, gid: int) -> bool:
    """Repair ownership and mode without replacing an otherwise valid file."""
    st = path.stat()
    changed = (st.st_uid, st.st_gid, st.st_mode & 0o7777) != (0, gid, mode)
    if changed:
        os.chown(path, 0, gid)
        os.chmod(path, mode)
    return changed


def install_atomic(source: Path, target: Path, mode: int, gid: int) -> bool:
    """Atomically copy source to target with root:gid ownership and mode; report whether it changed."""
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

    return not unchanged or ensure_metadata(target, mode, gid)


def haproxy_running() -> bool:
    """Report whether an HAProxy container is running."""
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

    require_regular_file(ca, "CA (instálala con install-ca-cert.py)")
    cert_target = target_dir / "tls.crt"
    key_target = target_dir / "tls.key"
    for target in (cert_target, key_target):
        if target.is_symlink() or (target.exists() and not target.is_file()):
            die(f"destino TLS no seguro: {target}")

    if not args.renew and pair_healthy(cert_target, key_target, ca, san_domains):
        changed_cert = ensure_metadata(cert_target, 0o644, pki_gid)
        changed_key = ensure_metadata(key_target, 0o640, pki_gid)
        print("Par TLS instalado y válido; certificados conservados.")
        if (changed_cert or changed_key) and haproxy_running():
            print("Permisos TLS reparados; comprueba HAProxy y reinícialo si es necesario.")
        return

    require_regular_file(args.cert, "certificado")
    require_regular_file(args.key, "clave privada")
    validate_pair(args.cert, args.key, ca, san_domains)

    step("2/2 Instalando en la carpeta de servicio de HAProxy")
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
