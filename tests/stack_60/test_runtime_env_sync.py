# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Verify Hermes runtime credentials cannot override central Compose secrets."""

import sys

sys.dont_write_bytecode = True

import stat

import pytest

from wrapper.lib.hermes_runtime_env import (RuntimeEnvironmentError, config_needs_update,
                                            needs_update, reconcile, reconcile_config)


def test_removes_gateway_overrides_without_losing_other_runtime_values(tmp_path):
    """Keep unrelated Hermes settings and back up the original privately."""
    runtime = tmp_path / ".env"
    runtime.write_text("OTHER=keep\nLITELLM_API_KEY=old\nLITELLM_MCP_API_KEY=old-mcp\n"
                       "TELEGRAM_BOT_TOKEN=old-telegram\n")
    runtime.chmod(0o600)
    managed_keys = frozenset({"TELEGRAM_BOT_TOKEN"})
    assert needs_update(runtime, managed_keys)
    assert reconcile(runtime, managed_keys)
    assert runtime.read_text() == "OTHER=keep\n"
    backup = next(tmp_path.glob(".env-backup-*"))
    assert "LITELLM_API_KEY=old" in backup.read_text()
    assert stat.S_IMODE(backup.stat().st_mode) == 0o600
    assert not reconcile(runtime)


def test_rejects_symlink_and_tightens_runtime_permissions(tmp_path):
    """Refuse a symlink but privatize an existing file while removing overrides."""
    runtime = tmp_path / ".env"
    target = tmp_path / "target"
    target.write_text("LITELLM_API_KEY=old\n")
    runtime.symlink_to(target)
    with pytest.raises(RuntimeEnvironmentError, match="unsafe"):
        reconcile(runtime)
    runtime.unlink()
    runtime.write_text("LITELLM_API_KEY=old\n")
    runtime.chmod(0o644)
    assert reconcile(runtime)
    assert stat.S_IMODE(runtime.stat().st_mode) == 0o600


def test_restores_only_managed_gateway_references(tmp_path):
    """Undo a runtime-written key without resetting Hermes' other settings."""
    config = tmp_path / "config.yaml"
    config.write_text("model:\n  base_url: http://old/v1\n  api_key: sk-old\n"
                      "mcp_servers:\n  litellm_gateway:\n    url: http://old/mcp\n"
                      "      Authorization: \"Bearer sk-old-mcp\"\nother: keep\n")
    config.chmod(0o640)
    assert config_needs_update(config)
    assert reconcile_config(config)
    assert config.read_text() == (
        "model:\n  base_url: ${LITELLM_BASE_URL}\n  api_key: ${LITELLM_API_KEY}\n"
        "mcp_servers:\n  litellm_gateway:\n    url: ${LITELLM_MCP_URL}\n"
        "      Authorization: \"Bearer ${LITELLM_MCP_API_KEY}\"\nother: keep\n"
    )
    assert not reconcile_config(config)
    assert next(tmp_path.glob("config.yaml-backup-*"))
