# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Reconfigure managed Gitea files and the initial administrator password.

Without --apply this command only reports configuration and password drift.
With --apply it stages managed files and, if needed, updates the initial
administrator password through the already running Gitea admin CLI. A private
SQLite backup precedes rotation. No container lifecycle action is performed.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import time
from contextlib import closing
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from wrapper.lib.reconfig_runtime import (ReconfigError, compose_config, container_running,
                                          environment, lifecycle_hint, sync_content, validate_managed)
from wrapper.stubs.bootstrap_env import missing

STACK_DIR = Path(__file__).resolve().parent
APP_KEYS = ("GITEA_DOMAIN", "GITEA_ROOT_URL", "GITEA_SSH_DOMAIN", "GITEA_SSH_PORT",
            "GITEA_INTERNAL_TOKEN", "GITEA_JWT_SECRET")


def render(source: Path, values: dict[str, str]) -> bytes:
    """Render only the installation-owned placeholders."""
    content = source.read_text()
    for name, value in values.items():
        content = content.replace(f"@@{name}@@", value)
    if re.search(r"@@[A-Za-z0-9_]+@@", content):
        raise ReconfigError(f"unresolved placeholders in {source}")
    return content.encode()


def fingerprint(values: dict[str, str]) -> str:
    """Fingerprint the configured password without storing it in runtime."""
    payload = f"{values['GITEA_ADMIN_USERNAME']}\0{values['GITEA_ADMIN_PASSWORD']}".encode()
    return hmac.new(values["GITEA_INTERNAL_TOKEN"].encode(), payload, hashlib.sha256).hexdigest()


def saved_fingerprint(path: Path) -> str | None:
    """Read only a root-owned private fingerprint file."""
    if path.is_symlink():
        raise ReconfigError(f"unsafe administrator state: {path}")
    if not path.exists():
        return None
    metadata = path.stat()
    if not path.is_file() or metadata.st_uid != 0 or metadata.st_mode & 0o077:
        raise ReconfigError(f"administrator state is not root-owned and private: {path}")
    value = path.read_text().strip()
    if not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ReconfigError(f"invalid administrator state: {path}")
    return value


def save_fingerprint(path: Path, value: str) -> None:
    """Record a successful password change without exposing the password."""
    descriptor, name = tempfile.mkstemp(prefix=".gitea-admin-", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w") as output:
            os.fchown(output.fileno(), 0, 0)
            os.fchmod(output.fileno(), 0o600)
            output.write(value + "\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def backup_database(database: Path) -> Path:
    """Take a consistent private SQLite backup before changing credentials."""
    if database.is_symlink() or not database.is_file():
        raise ReconfigError(f"missing or unsafe Gitea database: {database}")
    backup = database.with_name(f"{database.name}-backup-{time.time_ns()}")
    descriptor = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    os.close(descriptor)
    try:
        with closing(sqlite3.connect(f"file:{database}?mode=ro", uri=True)) as source:
            with closing(sqlite3.connect(backup)) as destination:
                source.backup(destination)
        print(f"Database backup: {backup}")
        return backup
    except (OSError, sqlite3.Error):
        backup.unlink(missing_ok=True)
        raise


def rotate_password(container: str, username: str, password: str) -> None:
    """Pass the password over stdin, never as a host process argument."""
    command = ["docker", "exec", "-i", container, "sh", "-ceu",
               'IFS= read -r username; IFS= read -r password; '
               'gitea admin user change-password --config /etc/gitea/app.ini '
               '--username "$username" --password "$password" --must-change-password=false >/dev/null']
    result = subprocess.run(command, input=f"{username}\n{password}\n", text=True,
                            capture_output=True, check=False)
    if result.returncode:
        raise ReconfigError(f"Gitea administrator password update failed (exit {result.returncode}); "
                            "the command output was withheld to protect secrets")


def main(apply: bool = False) -> int:
    try:
        values = environment(STACK_DIR)
        required = (*APP_KEYS, "BASE_PATH", "GITEA_DOCKER_NETWORK", "NETWORK_NAME",
                    "GITEA_ADMIN_USERNAME", "GITEA_ADMIN_PASSWORD", "GITEA_CONTAINER_NAME")
        for name in required:
            if missing(values.get(name)):
                raise ReconfigError(f"{name} is missing or incomplete in .env")
        base_path = values["BASE_PATH"]
        if not base_path.startswith("/"):
            raise ReconfigError("BASE_PATH must be absolute")
        if values["GITEA_DOCKER_NETWORK"] != values["NETWORK_NAME"]:
            raise ReconfigError("GITEA_DOCKER_NETWORK must match NETWORK_NAME")
        service = Path(base_path) / "service_-_gitea"
        runner = Path(base_path) / "service_-_gitea-runner"
        app_source = STACK_DIR / "config/gitea/app.ini"
        runner_source = STACK_DIR / "config/gitea-runner/config.yaml"
        app_target = service / "config/app.ini"
        runner_target = runner / "data/config.yaml"
        for source, target in ((app_source, app_target), (runner_source, runner_target)):
            validate_managed(source, target)
            if not target.is_file():
                raise ReconfigError(f"missing prepared Gitea configuration: {target}")
        alias = service / "config/conf/app.ini"
        if not alias.is_symlink() or os.readlink(alias) != "../app.ini":
            raise ReconfigError(f"unexpected Gitea configuration alias: {alias}")
        app_content = render(app_source, {name: values[name] for name in APP_KEYS})
        runner_content = render(runner_source, {"GITEA_DOCKER_NETWORK": values["GITEA_DOCKER_NETWORK"]})
        compose_config(STACK_DIR)
        state = service / "config/.admin-password-reconfig"
        expected = fingerprint(values)
        password_changed = saved_fingerprint(state) != expected
        changed_app = app_content != app_target.read_bytes()
        changed_runner = runner_content != runner_target.read_bytes()
        print(f"Stack 40 plan: app.ini {'update' if changed_app else 'unchanged'}; "
              f"runner config {'update' if changed_runner else 'unchanged'}; "
              f"administrator password {'rotate' if password_changed else 'unchanged'}.")
        if not apply:
            if password_changed:
                print("Password rotation requires an already running Gitea; the first application rotates once.")
            print("Preview only; run ./local-ai stack-40 reconfig --apply to apply this plan.")
            return 0
        if password_changed:
            container = values["GITEA_CONTAINER_NAME"]
            if not container_running(container):
                raise ReconfigError("Gitea must already be running to update its administrator password; "
                                    "run ./local-ai stack-40 start, then ./local-ai stack-40 reconfig --apply")
            backup_database(service / "data/gitea.db")
            rotate_password(container, values["GITEA_ADMIN_USERNAME"], values["GITEA_ADMIN_PASSWORD"])
            save_fingerprint(state, expected)
            print("Gitea administrator password updated; the new value is active without a restart.")
        if changed_app:
            sync_content(app_content, app_target)
        if changed_runner:
            sync_content(runner_content, runner_target)
        print(f"Stack 40: app.ini {'updated' if changed_app else 'unchanged'}; "
              f"runner config {'updated' if changed_runner else 'unchanged'}.")
        if changed_app or changed_runner:
            lifecycle_hint("40")
        elif not password_changed:
            print("No managed configuration changed; no container action is needed.")
        return 0
    except (ReconfigError, OSError, ValueError, sqlite3.Error) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="Apply the displayed reconfiguration plan")
    raise SystemExit(main(parser.parse_args().apply))
