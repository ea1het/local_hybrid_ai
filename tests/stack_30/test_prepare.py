# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Test LiteLLM preparation and its input validation.

Temporary service directories and mocked commands exercise configuration
rendering, secret creation, prerequisite checks, and lock placement.
Importing this module does not start LiteLLM or change database data."""

import sys

sys.dont_write_bytecode = True

from types import SimpleNamespace

import pytest

from tests.helpers import load_module


def test_prepare_creates_secret_and_lock_in_temporary_tree(tmp_path, monkeypatch):
    """Generate the database secret and lock after preparing LiteLLM."""
    module = load_module("stack-30_-_litellm", "01-prepare.py")
    stack_dir = tmp_path / module.STACK_NAME
    base = tmp_path / "runtime"
    for path in (stack_dir / "config/litellm", base / "service_-_litellm/config",
                 base / "service_-_litellm-postgres/data",
                 base / "service_-_litellm-postgres/secret",
                 tmp_path / "stack-00_-_platform"):
        path.mkdir(parents=True)
    (stack_dir / "config/litellm/config.yaml").write_text("model_list: []\n")
    (tmp_path / "stack-00_-_platform/.lock").touch()
    (stack_dir / ".env").touch()
    (stack_dir / "docker-compose.yml").touch()
    monkeypatch.setattr(module, "STACK_DIR", stack_dir)
    monkeypatch.setattr(module, "ENV_FILE", stack_dir / ".env")
    monkeypatch.setattr(module, "COMPOSE_FILE", stack_dir / "docker-compose.yml")
    monkeypatch.setattr(module, "LOCK_FILE", stack_dir / ".lock")
    monkeypatch.setattr(module.os, "geteuid", lambda: 0)
    monkeypatch.setattr(module.os, "chown", lambda *args: None)
    monkeypatch.setattr(module.shutil, "which", lambda command: command)
    env = {key: "fixture" for key in ("STACKS_ROOT BASE_PATH NETWORK_NAME LITELLM_IMAGE "
           "LITELLM_VERSION LITELLM_MASTER_KEY LITELLM_SALT_KEY UI_USERNAME UI_PASSWORD "
           "STORE_MODEL_IN_DB LITELLM_DB_NAME LITELLM_DB_USER LITELLM_DB_PASSWORD").split()}
    env.update(STACKS_ROOT=str(tmp_path), BASE_PATH=str(base), NETWORK_NAME="shared",
               LITELLM_IMAGE="litellm", LITELLM_VERSION="1.0", LITELLM_DB_NAME="litellm",
               LITELLM_DB_USER="app_user")
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(module, "load_env", lambda: env)
    commands = []

    def fake_subprocess(command, **kwargs):
        """Record subprocess calls and report success."""
        commands.append(command)
        return SimpleNamespace(returncode=0)

    def fake_run(command, **kwargs):
        """Simulate network inspection, secret generation, and other commands."""
        commands.append(command)
        if command[:2] == ["docker", "network"]:
            return SimpleNamespace(stdout="bridge\n")
        if command[:2] == ["openssl", "rand"]:
            return SimpleNamespace(stdout="generated-secret\n")
        return SimpleNamespace(stdout="")

    monkeypatch.setattr(module.subprocess, "run", fake_subprocess)
    monkeypatch.setattr(module, "run", fake_run)

    module.main()

    assert (base / "service_-_litellm-postgres/secret/postgres_admin_password").read_text() == "generated-secret\n"
    assert module.LOCK_FILE.read_text().startswith("stack=stack-30_-_litellm\n")
    assert any(command[0] == "install" and "config.yaml" in command[-1] for command in commands)
    assert any(command[:2] == ["docker", "compose"] and "config" in command for command in commands)


@pytest.mark.parametrize("key,value,message", [
    ("LITELLM_IMAGE", "image:latest", "no debe usar :latest"),
    ("LITELLM_VERSION", "latest", "no puede ser latest"),
    ("LITELLM_DB_USER", "bad-user", "no es valido"),
])
def test_prepare_rejects_unsafe_settings(tmp_path, monkeypatch, key, value, message):
    """Reject mutable image tags and invalid database user names."""
    module = load_module("stack-30_-_litellm", "01-prepare.py")
    monkeypatch.setattr(module, "STACK_DIR", tmp_path / module.STACK_NAME)
    monkeypatch.setattr(module, "LOCK_FILE", tmp_path / ".lock")
    monkeypatch.setattr(module, "ENV_FILE", tmp_path / ".env")
    monkeypatch.setattr(module, "COMPOSE_FILE", tmp_path / "compose.yml")
    module.ENV_FILE.touch()
    module.COMPOSE_FILE.touch()
    monkeypatch.setattr(module.os, "geteuid", lambda: 0)
    monkeypatch.setattr(module.shutil, "which", lambda command: command)
    monkeypatch.setattr(module.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=0))
    env = {name: "fixture" for name in ("STACKS_ROOT BASE_PATH NETWORK_NAME LITELLM_IMAGE "
           "LITELLM_VERSION LITELLM_MASTER_KEY LITELLM_SALT_KEY UI_USERNAME UI_PASSWORD "
           "STORE_MODEL_IN_DB LITELLM_DB_NAME LITELLM_DB_USER LITELLM_DB_PASSWORD").split()}
    env.update(STACKS_ROOT=str(tmp_path), BASE_PATH=str(tmp_path / "runtime"),
               LITELLM_IMAGE="litellm", LITELLM_VERSION="1.0", LITELLM_DB_USER="app_user")
    env[key] = value
    for name, item in env.items():
        monkeypatch.setenv(name, item)
    monkeypatch.setattr(module, "load_env", lambda: env)

    with pytest.raises(RuntimeError, match=message):
        module.main()
