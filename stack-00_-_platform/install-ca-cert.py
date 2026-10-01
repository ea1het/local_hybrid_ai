#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Install the local mkcert CA into the Linux host trust store.

The script validates that the supplied PEM is a CA certificate, installs it
under /usr/local/share/ca-certificates using LOCAL_CA_NAME from .env, refreshes
the host certificate bundle, and verifies that the new CA is trusted. The
default input is LOCAL_CA_SOURCE_PATH from .env; the host needs
update-ca-certificates.
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
# Only reads *.crt files from SYSTEM_CA_DIR and generates HOST_CA_BUNDLE.
SYSTEM_CA_DIR = Path("/usr/local/share/ca-certificates")
HOST_CA_BUNDLE = Path("/etc/ssl/certs/ca-certificates.crt")
LOCAL_CA_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def die(message: str, code: int = 1) -> None:
    """Print an error and exit with the requested status code."""
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(code)


def run(cmd: list[str], *, capture: bool = False) -> subprocess.CompletedProcess:
    """Run a command and fail on error, optionally capturing its output."""
    print("+", " ".join(cmd))
    try:
        return subprocess.run(cmd, text=True, check=True, capture_output=capture)
    except subprocess.CalledProcessError as exc:
        if capture:
            if exc.stdout:
                print(exc.stdout, file=sys.stderr, end="")
            if exc.stderr:
                print(exc.stderr, file=sys.stderr, end="")
        die(f"command failed: {' '.join(cmd)}")
        raise


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


def local_ca_path(env: dict[str, str]) -> Path:
    """Return the installed CA path under SYSTEM_CA_DIR."""
    name = env.get("LOCAL_CA_NAME", "")
    if not name:
        die(f"missing LOCAL_CA_NAME in {ENV_FILE}")
    if not LOCAL_CA_NAME_RE.match(name):
        die(f"invalid LOCAL_CA_NAME (letters, digits, '.', '_', '-' only; no extension): {name!r}")
    return SYSTEM_CA_DIR / f"{name}.crt"


def require_root() -> None:
    """Require root privileges before changing the CA trust store."""
    if os.geteuid() != 0:
        die("run this script as root")


def require_commands() -> None:
    """Check that installation and validation commands are available."""
    required = ("openssl", "install", "update-ca-certificates")
    missing = [cmd for cmd in required if shutil.which(cmd) is None]
    if missing:
        die("missing required commands: " + ", ".join(missing))


def parse_args() -> argparse.Namespace:
    """Parse the optional CA path and explicit replacement permission."""
    parser = argparse.ArgumentParser(
        description="Install the local CA (rootCA.pem) in the host trust store.",
    )
    parser.add_argument(
        "--ca",
        type=Path,
        default=None,
        help="CA source path (default: LOCAL_CA_SOURCE_PATH in .env)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="replace an installed CA even if it is valid (explicit rotation)",
    )
    return parser.parse_args()


def find_ca(path: Path) -> Path:
    """Return a regular CA source file, rejecting symlinks."""
    source = path.resolve()
    if not source.is_file() or path.is_symlink():
        die(f"CA source is missing or is a symlink: {path}. Copy it from the mkcert CA.")
    return source


def source_path(env: dict[str, str]) -> Path:
    """Require an absolute CA source path from the central environment."""
    value = env.get("LOCAL_CA_SOURCE_PATH", "")
    if not value or not Path(value).is_absolute():
        die("LOCAL_CA_SOURCE_PATH must be an absolute path in .env")
    return Path(value)


def validate_ca(source: Path) -> None:
    """Check CA:TRUE and display the source certificate details."""
    print("\n== 1/3 Validating CA ==")
    result = run(["openssl", "x509", "-in", str(source), "-noout", "-text"], capture=True)
    if "CA:TRUE" not in result.stdout:
        die(f"certificate is not a CA (CA:TRUE missing): {source}")

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
    print("\n== 2/3 Installing CA on host ==")
    dest.parent.mkdir(parents=True, exist_ok=True)
    run(["install", "-m", "0644", "-o", "0", "-g", "0", str(source), str(dest)])
    run(["update-ca-certificates"])


def verify_bundle(dest: Path) -> None:
    """Verify the installed CA against the host certificate bundle."""
    print("\n== 3/3 Verifying host CA bundle ==")
    if not HOST_CA_BUNDLE.is_file():
        die(f"missing expected system certificate bundle: {HOST_CA_BUNDLE}")
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

    env = load_env(ENV_FILE)
    dest = local_ca_path(env)
    if dest.is_symlink() or (dest.exists() and not dest.is_file()):
        die(f"unsafe CA destination: {dest}")

    if not args.force and certificate_valid(dest):
        dest_stat = dest.stat()
        if (dest_stat.st_uid, dest_stat.st_gid, dest_stat.st_mode & 0o7777) != (0, 0, 0o644):
            os.chown(dest, 0, 0)
            os.chmod(dest, 0o644)
            print(f"CA permissions repaired: {dest}")
        if not bundle_trusts(dest):
            print(f"CA installed but not trusted by the bundle; refreshing: {dest}")
            run(["update-ca-certificates"])
        verify_bundle(dest)
        print(f"CA already installed and trusted; unchanged: {dest}")
        return

    source = find_ca(args.ca if args.ca is not None else source_path(env))
    print(f"CA source: {source}")

    validate_ca(source)
    install_ca_on_host(source, dest)
    verify_bundle(dest)

    print("\nSUCCESS")
    print(f"Local CA installed: {dest}")
    print(f"Host bundle:        {HOST_CA_BUNDLE}")


if __name__ == "__main__":
    main()
