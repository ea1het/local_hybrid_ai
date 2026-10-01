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
    """Print a phase heading."""
    print(f"\n== {message}")


def openssl(*args: str) -> subprocess.CompletedProcess:
    """Run OpenSSL and return its exit status and captured output."""
    return subprocess.run(["openssl", *args], text=True, capture_output=True, check=False)


def load_env(env_file: Path) -> dict[str, str]:
    """Load the central .env using the shell's source rules."""
    if not env_file.is_file() or env_file.is_symlink():
        die(f"missing root environment: {env_file}")
    result = subprocess.run(
        ["bash", "-c", 'set -a; source "$1"; set +a; env -0', "_", str(env_file)],
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        die(f"could not load {env_file}: {result.stderr.decode(errors='replace').strip()}")
    env: dict[str, str] = {}
    for item in result.stdout.split(b"\0"):
        if b"=" in item:
            key, _, value = item.partition(b"=")
            env[key.decode()] = value.decode(errors="replace")
    return env


def parse_args() -> argparse.Namespace:
    """Parse certificate, key, and CA paths and the renewal option."""
    parser = argparse.ArgumentParser(
        description="Install tls.crt and tls.key in the HAProxy service directory.",
    )
    parser.add_argument("--cert", type=Path, default=None,
                        help="certificate source (default: TLS_CERT_SOURCE_PATH in .env)")
    parser.add_argument("--key", type=Path, default=None,
                        help="private-key source (default: TLS_KEY_SOURCE_PATH in .env)")
    parser.add_argument(
        "--ca",
        type=Path,
        default=None,
        help=f"CA used to validate the chain (default: {SYSTEM_CA_DIR}/<LOCAL_CA_NAME>.crt)",
    )
    parser.add_argument(
        "--renew",
        action="store_true",
        help="replace the TLS pair even if it is valid (explicit rotation)",
    )
    return parser.parse_args()


def local_ca_path(env: dict[str, str]) -> Path:
    """Return the installed CA path under SYSTEM_CA_DIR."""
    name = env.get("LOCAL_CA_NAME", "")
    if not name:
        die(f"missing LOCAL_CA_NAME in {ENV_FILE}")
    if not LOCAL_CA_NAME_RE.match(name):
        die(f"invalid LOCAL_CA_NAME (letters, digits, '.', '_', '-' only; no extension): {name!r}")
    return SYSTEM_CA_DIR / f"{name}.crt"


def source_path(env: dict[str, str], key: str) -> Path:
    """Require an absolute TLS source path from the central environment."""
    value = env.get(key, "")
    if not value or not Path(value).is_absolute():
        die(f"{key} must be an absolute path in .env")
    return Path(value)


def parse_san_domains(raw: str) -> list[str]:
    """Split and validate the required DNS names in TLS_SAN_DOMAINS."""
    names = raw.replace(",", " ").split()
    if not names:
        die(f"TLS_SAN_DOMAINS is empty in {ENV_FILE}")
    for name in names:
        if not SAN_NAME_RE.match(name):
            die(f"invalid name in TLS_SAN_DOMAINS: {name!r}")
    return names


def require_regular_file(path: Path, label: str) -> None:
    """Require a nonempty regular file rather than a symbolic link."""
    if path.is_symlink() or not path.is_file() or path.stat().st_size == 0:
        die(f"missing or invalid nonempty regular file ({label}): {path}")


def validate_pair(cert: Path, key: Path, ca: Path, san_domains: list[str]) -> None:
    """Check TLS key, CA chain, SAN names, and certificate validity."""
    step("1/2 Validating certificate and key")

    if openssl("x509", "-in", str(cert), "-noout").returncode != 0:
        die(f"invalid X.509 certificate: {cert}")
    if openssl("pkey", "-in", str(key), "-noout").returncode != 0:
        die(f"invalid private key: {key}")

    cert_pub = openssl("x509", "-in", str(cert), "-noout", "-pubkey").stdout
    key_pub = openssl("pkey", "-in", str(key), "-pubout").stdout
    if not cert_pub or cert_pub != key_pub:
        die("certificate and private key do not match")
    log("certificate and private key match")

    verify = openssl("verify", "-CAfile", str(ca), str(cert))
    if verify.returncode != 0:
        die(f"certificate is not signed by CA {ca}: {verify.stderr.strip() or verify.stdout.strip()}")
    log(f"chain validates against {ca}")

    san_output = openssl("x509", "-in", str(cert), "-noout", "-ext", "subjectAltName").stdout
    san = {entry.strip() for line in san_output.splitlines()[1:] for entry in line.split(",")}
    missing = [name for name in san_domains if f"DNS:{name}" not in san]
    if missing:
        die("certificate subjectAltName is missing: " + ", ".join(f"DNS:{name}" for name in missing))
    log("SAN includes " + ", ".join(san_domains))

    if openssl("x509", "-in", str(cert), "-noout", "-checkend", "0").returncode != 0:
        die("certificate has expired")
    if openssl("x509", "-in", str(cert), "-noout", "-checkend", str(EXPIRY_WARNING_SECONDS)).returncode != 0:
        print("WARNING: certificate expires within 30 days; renew it with mkcert", file=sys.stderr)

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
        die(f"destination is not a regular file: {target}")

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
    """Validate and install TLS material, noting when HAProxy needs a reload."""
    args = parse_args()

    if os.geteuid() != 0:
        die("run this script as root")
    if shutil.which("openssl") is None:
        die("missing required command: openssl")

    env = load_env(ENV_FILE)
    for key in ("BASE_PATH", "TLS_SAN_DOMAINS"):
        if not env.get(key):
            die(f"missing {key} in {ENV_FILE}")
    base_path = env["BASE_PATH"].rstrip("/")
    if not base_path.startswith("/"):
        die("BASE_PATH must be an absolute path")
    san_domains = parse_san_domains(env["TLS_SAN_DOMAINS"])
    ca = args.ca if args.ca is not None else local_ca_path(env)

    pki_gid_raw = env.get("PLATFORM_PKI_GID") or "1999"
    if not pki_gid_raw.isdigit() or int(pki_gid_raw) <= 0:
        die("PLATFORM_PKI_GID must be a positive integer")
    pki_gid = int(pki_gid_raw)

    target_dir = Path(base_path) / "service_-_haproxy" / "config"
    if target_dir.is_symlink() or not target_dir.is_dir():
        die(f"missing service directory {target_dir}; run Stack 00 bootstrap first")

    require_regular_file(ca, "CA (install it with install-ca-cert.py)")
    cert_target = target_dir / "tls.crt"
    key_target = target_dir / "tls.key"
    for target in (cert_target, key_target):
        if target.is_symlink() or (target.exists() and not target.is_file()):
            die(f"unsafe TLS destination: {target}")

    if not args.renew and pair_healthy(cert_target, key_target, ca, san_domains):
        changed_cert = ensure_metadata(cert_target, 0o644, pki_gid)
        changed_key = ensure_metadata(key_target, 0o640, pki_gid)
        print("Installed TLS pair is valid; certificates preserved.")
        if (changed_cert or changed_key) and haproxy_running():
            print("TLS permissions repaired; check HAProxy and restart it if necessary.")
        return

    cert_source = args.cert if args.cert is not None else source_path(env, "TLS_CERT_SOURCE_PATH")
    key_source = args.key if args.key is not None else source_path(env, "TLS_KEY_SOURCE_PATH")
    require_regular_file(cert_source, "certificate")
    require_regular_file(key_source, "private key")
    validate_pair(cert_source, key_source, ca, san_domains)

    step("2/2 Installing in HAProxy service directory")
    changed_cert = install_atomic(cert_source, cert_target, 0o644, pki_gid)
    changed_key = install_atomic(key_source, key_target, 0o640, pki_gid)
    log(f"{cert_target}: {'updated' if changed_cert else 'unchanged'} (0644 root:{pki_gid})")
    log(f"{key_target}: {'updated' if changed_key else 'unchanged'} (0640 root:{pki_gid})")

    print("\nSUCCESS")
    if (changed_cert or changed_key) and haproxy_running():
        print("HAProxy is running; restart it to use the new certificate:")
        print(f"  cd {ROOT_DIR}/stack-10_-_haproxy_web && docker compose restart haproxy")


if __name__ == "__main__":
    main()
