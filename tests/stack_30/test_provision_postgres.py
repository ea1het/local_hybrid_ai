# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import sys

sys.dont_write_bytecode = True

from types import SimpleNamespace

import pytest

from tests.helpers import load_module


@pytest.mark.parametrize("database_exists", [False, True])
def test_provision_creates_database_only_when_missing(tmp_path, monkeypatch, database_exists):
    module = load_module("stack-30_-_litellm", "provision-postgres.py")
    env_file = tmp_path / ".env"
    lock_file = tmp_path / ".lock"
    env_file.touch()
    lock_file.touch()
    monkeypatch.setattr(module, "ENV_FILE", env_file)
    monkeypatch.setattr(module, "LOCK_FILE", lock_file)
    monkeypatch.setattr(module, "COMPOSE_FILE", tmp_path / "compose.yml")
    monkeypatch.setattr(module.os, "geteuid", lambda: 0)
    monkeypatch.setattr(module.shutil, "which", lambda command: command)
    env = {"BASE_PATH": str(tmp_path), "LITELLM_DB_NAME": "litellm",
           "LITELLM_DB_USER": "app_user", "LITELLM_DB_PASSWORD": "app_password"}
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    secret = tmp_path / "service_-_litellm-postgres/secret/postgres_admin_password"
    secret.parent.mkdir(parents=True)
    secret.write_text("admin_password\n")
    commands = []

    def fake_subprocess(command, **kwargs):
        commands.append((command, kwargs))
        if command[0] == "bash":
            return SimpleNamespace(stdout=b"\0".join(f"{key}={value}".encode() for key, value in env.items()) + b"\0")
        return SimpleNamespace(returncode=0)

    def fake_run(command, **kwargs):
        commands.append((command, kwargs))
        if kwargs.get("capture"):
            return SimpleNamespace(stdout="1\n" if database_exists else "")
        return SimpleNamespace(stdout="")

    monkeypatch.setattr(module.subprocess, "run", fake_subprocess)
    monkeypatch.setattr(module, "run", fake_run)

    module.main()

    assert any(command[-3:] == ["up", "-d", "litellm-postgres"] for command, _ in commands)
    assert any("ALTER ROLE" in kwargs.get("input_text", "") for _, kwargs in commands)
    assert any(command[-2:] == ["-tAc", "SELECT 1;"] for command, _ in commands)
    assert any(command[0] == "createdb" or "createdb" in command for command, _ in commands) is not database_exists
    assert all("admin_password" not in str(kwargs) for _, kwargs in commands)


def test_provision_rejects_symlinked_admin_secret(tmp_path, monkeypatch):
    module = load_module("stack-30_-_litellm", "provision-postgres.py")
    env_file = tmp_path / ".env"
    lock_file = tmp_path / ".lock"
    env_file.touch()
    lock_file.touch()
    monkeypatch.setattr(module, "ENV_FILE", env_file)
    monkeypatch.setattr(module, "LOCK_FILE", lock_file)
    monkeypatch.setattr(module.os, "geteuid", lambda: 0)
    monkeypatch.setattr(module.shutil, "which", lambda command: command)
    secret = tmp_path / "service_-_litellm-postgres/secret/postgres_admin_password"
    secret.parent.mkdir(parents=True)
    target = tmp_path / "target-secret"
    target.write_text("password")
    secret.symlink_to(target)
    env = {"BASE_PATH": str(tmp_path), "LITELLM_DB_NAME": "litellm",
           "LITELLM_DB_USER": "app_user", "LITELLM_DB_PASSWORD": "app_password"}

    def fake_subprocess(command, **kwargs):
        if command[0] == "bash":
            return SimpleNamespace(stdout=b"\0".join(f"{key}={value}".encode() for key, value in env.items()) + b"\0")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(module.subprocess, "run", fake_subprocess)
    monkeypatch.setattr(module, "run", lambda *args, **kwargs: pytest.fail("provisioning must not start"))

    with pytest.raises(RuntimeError, match="secreto administrativo"):
        module.main()
