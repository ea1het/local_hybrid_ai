# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Exercise clean protected environment creation and idempotence."""

import base64
import hashlib
import os
import stat
import subprocess
import sys

sys.dont_write_bytecode = True

import pytest

from tests.helpers import ROOT
from wrapper.stubs import bootstrap_env


def fixture_root(tmp_path, monkeypatch):
    """Create a complete template with an isolated runtime path."""
    monkeypatch.setattr(bootstrap_env.os, "geteuid", lambda: 0)
    monkeypatch.setattr(bootstrap_env, "root_owned", lambda metadata: True)
    monkeypatch.setattr(bootstrap_env, "private_owner", lambda descriptor: os.fchmod(descriptor, 0o600))
    template = (ROOT / ".env.template").read_text()
    template = template.replace("BASE_PATH=/opt/docker/runtime", f"BASE_PATH={tmp_path / 'runtime'}")
    (tmp_path / ".env.template").write_text(template)
    return tmp_path


def test_fresh_bootstrap_and_idempotence(tmp_path, monkeypatch):
    """Generate local secrets only once and leave external tokens untouched."""
    root = fixture_root(tmp_path, monkeypatch)
    generated, pending, backup, changed = bootstrap_env.bootstrap(root)
    assert changed and backup is None
    assert "TELEGRAM_BOT_TOKEN" in pending
    assert "LITELLM_API_KEY" in pending
    assert "LITELLM_POSTGRES_ADMIN_PASSWORD" in generated
    env = root / ".env"
    values = bootstrap_env.assignments(env.read_text())
    assert values["TELEGRAM_BOT_TOKEN"] == ""
    assert values["LITELLM_MASTER_KEY"].startswith("sk-")
    assert values["LITELLM_API_KEY"].startswith("PUT_YOUR_")
    assert values["LITELLM_MCP_API_KEY"].startswith("PUT_YOUR_")
    assert values["OPENWEBUI_LITELLM_API_KEY"].startswith("PUT_YOUR_")
    assert not (root / "runtime/service_-_litellm-postgres/secret").exists()
    assert not (root / "runtime/service_-_firecrawl-postgres/secret").exists()
    assert stat.S_IMODE(env.stat().st_mode) == 0o600
    assert len(values["HERMES_DASHBOARD_BASIC_AUTH_PASSWORD"]) == 64
    scheme, count, block, parallel, salt, digest = values["HERMES_DASHBOARD_BASIC_AUTH_PASSWORD_HASH"].split("$")
    assert scheme == "scrypt"
    assert hashlib.scrypt(values["HERMES_DASHBOARD_BASIC_AUTH_PASSWORD"].encode(),
                          salt=base64.b64decode(salt), n=int(count), r=int(block), p=int(parallel),
                          dklen=32) == base64.b64decode(digest)
    loaded_hash = subprocess.run(["bash", "-c", 'source "$1"; printf "%s" "$HERMES_DASHBOARD_BASIC_AUTH_PASSWORD_HASH"',
                                  "bash", str(env)], capture_output=True, text=True, check=True).stdout
    assert loaded_hash == values["HERMES_DASHBOARD_BASIC_AUTH_PASSWORD_HASH"]
    unchanged = env.read_bytes()
    again = bootstrap_env.bootstrap(root)
    assert again[0] == [] and again[2] is None and again[3] is False
    assert env.read_bytes() == unchanged


def test_existing_template_env_is_backed_up(tmp_path, monkeypatch):
    """Back up an existing template before filling its local secrets."""
    root = fixture_root(tmp_path, monkeypatch)
    original = (root / ".env.template").read_text()
    env = root / ".env"
    env.write_text(original)
    env.chmod(0o600)
    _, _, backup, changed = bootstrap_env.bootstrap(root)
    assert changed and backup is not None and backup.read_text() == original
    assert stat.S_IMODE(backup.stat().st_mode) == 0o600
    values = bootstrap_env.assignments(env.read_text())
    assert values["FIRECRAWL_POSTGRES_ADMIN_PASSWORD"] != "PUT_YOUR_PASSWORD_HERE"
    assert values["LITELLM_POSTGRES_ADMIN_PASSWORD"] != "PUT_YOUR_PASSWORD_HERE"


def test_rejects_unsafe_env_file(tmp_path, monkeypatch):
    """Reject a symlink instead of following it during bootstrap."""
    root = fixture_root(tmp_path, monkeypatch)
    outside = tmp_path / "outside"
    outside.write_text("private")
    (root / ".env").symlink_to(outside)
    with pytest.raises(OSError):
        bootstrap_env.bootstrap(root)
    assert outside.read_text() == "private"


@pytest.mark.parametrize("stack,variable", [
    ("stack-20_-_searxng_firecrawl", "FIRECRAWL_POSTGRES_ADMIN_PASSWORD"),
    ("stack-30_-_litellm", "LITELLM_POSTGRES_ADMIN_PASSWORD"),
])
def test_postgres_compose_uses_env_without_password_file(stack, variable):
    """PostgreSQL must not mount or create a duplicate password file."""
    compose = (ROOT / stack / "docker-compose.yml").read_text()
    assert f"POSTGRES_PASSWORD: ${{{variable}:?" in compose
    assert "POSTGRES_PASSWORD_FILE" not in compose
    assert "/run/secrets/postgres_admin_password" not in compose


def test_existing_dashboard_hash_must_match_stored_password(tmp_path, monkeypatch):
    """Do not claim a generated login password that cannot authenticate."""
    root = fixture_root(tmp_path, monkeypatch)
    bootstrap_env.bootstrap(root)
    env = root / ".env"
    original = env.read_text()
    password = bootstrap_env.assignments(original)["HERMES_DASHBOARD_BASIC_AUTH_PASSWORD"]
    changed = original.replace(f"HERMES_DASHBOARD_BASIC_AUTH_PASSWORD={password}",
                               "HERMES_DASHBOARD_BASIC_AUTH_PASSWORD=wrong")
    env.write_text(changed)
    with pytest.raises(bootstrap_env.BootstrapError, match="does not match"):
        bootstrap_env.bootstrap(root)
    assert env.read_text() == changed
