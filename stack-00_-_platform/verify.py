#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

import grp
import os
import re
import stat
import sys
from pathlib import Path

sys.dont_write_bytecode = True

from ops_common import die, load_env, log, require, require_commands, require_root, run


def real_directory(path: Path) -> bool:
    return path.is_dir() and not path.is_symlink()


def real_nonempty_file(path: Path) -> bool:
    return path.is_file() and not path.is_symlink() and path.stat().st_size > 0


def main() -> None:
    stack_dir = Path(__file__).resolve().parent
    root_dir = stack_dir.parent
    env_file = root_dir / ".env"
    require_root()
    require_commands("docker", "openssl")
    if not env_file.is_file() or env_file.is_symlink():
        die(f"missing root operational environment: {env_file}")
    env_stat = env_file.stat()
    if (env_stat.st_uid, env_stat.st_gid, stat.S_IMODE(env_stat.st_mode)) != (0, 0, 0o600):
        die(f"{env_file} must be root:root 0600")

    env = load_env(env_file)
    require(env, env_file, "STACKS_ROOT", "BASE_PATH", "NETWORK_NAME", "ROOT_HOSTNAME", "TLS_SAN_DOMAINS", "LOCAL_CA_NAME")
    if str(root_dir) != env["STACKS_ROOT"].rstrip("/"):
        die("worktree path does not match STACKS_ROOT")

    for directory in sorted(root_dir.glob("stack-[0-9][0-9]_-_*")):
        if directory == stack_dir or not real_directory(directory):
            continue
        env_link = directory / ".env"
        if not env_link.is_symlink():
            die(f"missing managed symlink: {env_link}")
        if os.readlink(env_link) != "../.env":
            die(f"unexpected target for {env_link}")
    log("central .env symlinks: OK")

    base_path = Path(env["BASE_PATH"].rstrip("/"))
    platform_root = base_path / "service_-_platform"
    haproxy_config = base_path / "service_-_haproxy" / "config"
    for directory in (platform_root, platform_root / "state", platform_root / "logs", haproxy_config):
        if not real_directory(directory):
            die(f"missing service directory: {directory} (run 00-bootstrap.py)")
    log("base service tree: OK")

    pki_gid = env.get("PLATFORM_PKI_GID") or "1999"
    try:
        group = grp.getgrnam("local-hybrid-pki")
    except KeyError:
        die("missing group local-hybrid-pki (run 00-bootstrap.py)")
    if str(group.gr_gid) != pki_gid:
        die(f"local-hybrid-pki does not have GID {pki_gid}")
    log("PKI consumer group: OK")

    network_name = env["NETWORK_NAME"]
    run("docker", "network", "inspect", network_name, capture=True)
    driver = run("docker", "network", "inspect", "-f", "{{.Driver}}", network_name, capture=True).stdout.strip()
    if driver != "bridge":
        die(f"{network_name} is not a bridge network")
    log("shared Docker network: OK")

    ca_name = env["LOCAL_CA_NAME"]
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", ca_name):
        die(f"invalid LOCAL_CA_NAME: {ca_name}")
    local_ca = Path("/usr/local/share/ca-certificates") / f"{ca_name}.crt"
    host_bundle = Path("/etc/ssl/certs/ca-certificates.crt")
    if not local_ca.is_file() or local_ca.stat().st_size == 0:
        die(f"local CA not installed: {local_ca} (run install-ca-cert.py)")
    run("openssl", "verify", "-CAfile", str(host_bundle), str(local_ca), capture=True)
    log("local CA trusted by host: OK")

    certificate = haproxy_config / "tls.crt"
    private_key = haproxy_config / "tls.key"
    if not real_nonempty_file(certificate):
        die(f"missing {certificate} (run install-tls-certs.py)")
    if not real_nonempty_file(private_key):
        die(f"missing {private_key} (run install-tls-certs.py)")
    key_stat = private_key.stat()
    if (key_stat.st_uid, str(key_stat.st_gid), stat.S_IMODE(key_stat.st_mode)) != (0, pki_gid, 0o640):
        die(f"{private_key} must be root:{pki_gid} 0640")
    certificate_public_key = run("openssl", "x509", "-in", str(certificate), "-noout", "-pubkey", capture=True).stdout
    private_public_key = run("openssl", "pkey", "-in", str(private_key), "-pubout", capture=True).stdout
    if certificate_public_key != private_public_key:
        die("TLS certificate and key do not match")
    run("openssl", "verify", "-CAfile", str(local_ca), str(certificate), capture=True)
    run("openssl", "x509", "-in", str(certificate), "-noout", "-checkend", "0", capture=True)
    san_output = run("openssl", "x509", "-in", str(certificate), "-noout", "-ext", "subjectAltName", capture=True).stdout
    san_names = set(re.findall(r"DNS:([^,\s]+)", san_output))
    for name in re.split(r"[,\s]+", env["TLS_SAN_DOMAINS"].strip()):
        if name and name not in san_names:
            die(f"TLS certificate SAN does not include DNS:{name} (TLS_SAN_DOMAINS)")
    log("HAProxy TLS material: OK")
    print("\nStack0 READY")


if __name__ == "__main__":
    main()
