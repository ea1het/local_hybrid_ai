#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Prepare HAProxy and the web frontend after Stack 0 is ready.

This script requires the platform lock, shared network, generated TLS pair,
and source configuration. It renders or copies files into the directories
owned by Stack 0 and marks the stack prepared only after successful checks.
Existing preparation locks prevent unintended reconciliation. Importing the
module does not touch the filesystem or Docker."""

import datetime
import os
import re
import shutil
import subprocess
import sys

sys.dont_write_bytecode = True
from pathlib import Path


STACK_NAME = "stack-10_-_haproxy_web"
STACK_DIR = Path(__file__).resolve().parent
ENV_FILE = STACK_DIR / ".env"
COMPOSE_FILE = STACK_DIR / "docker-compose.yml"
LOCK_FILE = STACK_DIR / ".lock"
REQUIRED = (
    "STACKS_ROOT BASE_PATH NETWORK_NAME HAPROXY_HTTP_PORT HAPROXY_HTTPS_PORT ROOT_HOSTNAME "
    "WEB_TARGET SEARCH_HOSTNAME SEARCH_TARGET CHAT_HOSTNAME CHAT_TARGET "
    "GIT_HOSTNAME GIT_TARGET GWIA_HOSTNAME GWIA_TARGET GWIA_ROOT_EXTERNAL_HOSTNAME "
    "HOMELAB_HOSTNAME HOMELAB_TARGET NORAI_HOSTNAME NORAI_TARGET"
).split()
HAPROXY_VARS = (
    "ROOT_HOSTNAME WEB_TARGET SEARCH_HOSTNAME SEARCH_TARGET CHAT_HOSTNAME CHAT_TARGET "
    "GIT_HOSTNAME GIT_TARGET GWIA_HOSTNAME GWIA_TARGET GWIA_ROOT_EXTERNAL_HOSTNAME "
    "HOMELAB_HOSTNAME HOMELAB_TARGET NORAI_HOSTNAME NORAI_TARGET"
).split()


def log(message):
    """Print an indented progress detail."""
    print(f"  {message}")


def step(message):
    """Muestra el encabezado de una fase."""
    print(f"\n== {message}")


def die(message):
    """Print an error and abort preparation."""
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def run(*command, env=None, quiet=False):
    """Run a command, optionally suppressing its output."""
    return subprocess.run(command, env=env, stdout=subprocess.DEVNULL if quiet else None,
                          stderr=subprocess.DEVNULL if quiet else None, check=True)


def sourced_environment():
    """Reject redacted values and return environment variables loaded by Bash."""
    content = ENV_FILE.read_text()
    if re.search(r"^[A-Za-z_][A-Za-z0-9_]*=.*(<REDACT|\.{5,})", content, re.MULTILINE):
        die(f"{ENV_FILE} contains redacted or incomplete values")
    result = subprocess.run(
        ["bash", "-c", 'set -Eeuo pipefail; set -a; source "$1"; env -0', "bash", str(ENV_FILE)],
        stdout=subprocess.PIPE, check=True,
    )
    return dict(os.fsdecode(entry).split("=", 1) for entry in result.stdout.split(b"\0") if entry)


def main():
    """Check prerequisites, install proxy and web files, and write the preparation lock."""
    if LOCK_FILE.exists():
        print(f"Stack already prepared. {LOCK_FILE} exists; nothing was changed.")
        return
    if os.geteuid() != 0:
        die("run this command as root")
    for command in ("docker", "openssl", "cmp", "ln"):
        if shutil.which(command) is None:
            die(f"missing required command: {command}")
    if subprocess.run(["docker", "compose", "version"], stdout=subprocess.DEVNULL,
                      stderr=subprocess.DEVNULL).returncode:
        die("Docker Compose v2 is unavailable")
    for path in (ENV_FILE, COMPOSE_FILE):
        if not path.is_file():
            die(f"missing {path}")
    env = sourced_environment()
    for key in REQUIRED:
        if not env.get(key):
            die(f"missing {key} in {ENV_FILE}")
    gid = env.get("PLATFORM_PKI_GID") or "1999"
    if not re.fullmatch(r"[0-9]+", gid) or int(gid) <= 0:
        die("PLATFORM_PKI_GID must be a positive integer")
    stacks_root = env["STACKS_ROOT"].rstrip("/")
    base_path = env["BASE_PATH"].rstrip("/")
    if not env["STACKS_ROOT"].startswith("/") or not env["BASE_PATH"].startswith("/"):
        die("STACKS_ROOT and BASE_PATH must be absolute paths")
    if str(STACK_DIR) != f"{stacks_root}/{STACK_NAME}":
        die(f"this stack must be at {stacks_root}/{STACK_NAME}; current path: {STACK_DIR}")
    if stacks_root == base_path:
        die("STACKS_ROOT and BASE_PATH must differ")
    stack0_lock = Path(stacks_root) / "stack-00_-_platform/.lock"
    if not stack0_lock.is_file():
        die(f"Stack 00 is not prepared: missing {stack0_lock}")

    haproxy_service = Path(base_path) / "service_-_haproxy"
    web_service = Path(base_path) / "service_-_web"
    haproxy_config = haproxy_service / "config"
    tls_cert = haproxy_config / "tls.crt"
    tls_key = haproxy_config / "tls.key"
    haproxy_source = STACK_DIR / "config/haproxy"
    web_source = STACK_DIR / "config/web"
    if not (haproxy_source / "haproxy.cfg").is_file() or not (haproxy_source / "haproxy.cfg").stat().st_size:
        die(f"missing or empty {haproxy_source}/haproxy.cfg")
    if not (web_source / "index.html").is_file():
        die(f"missing {web_source}/index.html")

    network = env["NETWORK_NAME"]
    step(f"Shared Docker network {network}")
    if subprocess.run(["docker", "network", "inspect", network], stdout=subprocess.DEVNULL,
                      stderr=subprocess.DEVNULL, env=env).returncode:
        die(f"missing {network}; install Stack 00 first")
    driver = subprocess.check_output(["docker", "network", "inspect", "-f", "{{.Driver}}", network], env=env).decode().rstrip("\n")
    if driver != "bridge":
        die(f"{network} uses driver {driver}, not bridge")
    log("Stack 00 network verified")

    step("Stack 10 service directories")
    for directory in (haproxy_service, haproxy_config, web_service):
        if not directory.is_dir() or directory.is_symlink():
            die(f"missing {directory}; run ./local-ai stack-00 install first")
    log("Stack 00 service directories verified")

    step("TLS certificate")
    for path in (tls_cert, tls_key):
        if not path.is_file() or not path.stat().st_size or path.is_symlink():
            die(f"missing {path}; run ./local-ai stack-00 install first")
    for kind, path, label in (("x509", tls_cert, "TLS certificate"), ("pkey", tls_key, "TLS private key")):
        if subprocess.run(["openssl", kind, "-in", str(path), "-noout"], stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL).returncode:
            die(f"invalid {label}: {path}")
    try:
        cert_pub = subprocess.check_output(["openssl", "x509", "-in", str(tls_cert), "-pubkey", "-noout"])
        key_pub = subprocess.check_output(["openssl", "pkey", "-in", str(tls_key), "-pubout"])
    except subprocess.CalledProcessError:
        die("TLS certificate and private key do not match")
    if cert_pub != key_pub:
        die("TLS certificate and private key do not match")
    log("tls.crt / tls.key verified")

    step("HAProxy configuration")
    for name in ("casa.lan.crt", "casa.lan.key"):
        legacy = haproxy_config / name
        if legacy.is_symlink():
            legacy.unlink()
    run("install", "-m", "0644", "-o", "0", "-g", "0", str(haproxy_source / "haproxy.cfg"), str(haproxy_config / "haproxy.cfg"))
    log("haproxy.cfg installed alongside tls.crt / tls.key")

    step("Web content")
    run("cp", "-a", str(web_source) + "/.", str(web_service) + "/")
    os.chmod(web_service / "index.html", 0o644)

    step("HAProxy validation")
    image = env.get("HAPROXY_IMAGE") or "haproxy"
    version = env.get("HAPROXY_VERSION") or "3.0.26-alpine3.24"
    ref = f"{image}:{version}"
    command = ["docker", "run", "--rm", "--group-add", gid, "-v", f"{haproxy_config}:/usr/local/etc/haproxy:ro"]
    command += [item for key in HAPROXY_VARS for item in ("-e", f"{key}={env[key]}")]
    command += [ref, "haproxy", "-c", "-f", "/usr/local/etc/haproxy/haproxy.cfg"]
    subprocess.run(command, env=env, stdout=subprocess.DEVNULL, check=True)
    log(f"haproxy.cfg validated with tls.crt / tls.key using {ref}")

    step("Docker Compose validation")
    run("docker", "compose", "--env-file", str(ENV_FILE), "-f", str(COMPOSE_FILE), "config", "--quiet", env=env)
    log("Docker Compose configuration valid")
    os.umask(0o022)
    LOCK_FILE.write_text(f"stack={STACK_NAME}\nprepared_at_utc={datetime.datetime.now(datetime.timezone.utc):%Y-%m-%dT%H:%M:%SZ}\n")
    step("Preparation complete")
    log(f"lock created: {LOCK_FILE}")
    log(f"TLS: {tls_cert} / {tls_key}")


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as exc:
        raise SystemExit(exc.returncode) from None
