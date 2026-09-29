# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Exercise read-only stack status classification without contacting Docker.

Temporary Compose inputs and mocked JSON rows cover prepared, stopped,
degraded, optional-profile, and authenticated database-probe reporting.
"""

import json
import sys
from types import SimpleNamespace

sys.dont_write_bytecode = True

import pytest

from wrapper.lib import stack_status


def stack_paths(tmp_path):
    """Create safe mock Compose inputs and a preparation lock."""
    stack_dir = tmp_path / "stack"
    stack_dir.mkdir()
    (tmp_path / ".env").write_text("NETWORK_NAME=redlocal\n")
    (stack_dir / ".env").symlink_to("../.env")
    (stack_dir / "docker-compose.yml").write_text("services: {}\n")
    lock_file = stack_dir / ".lock"
    lock_file.write_text("prepared")
    return stack_dir, lock_file


def test_ready_status_parses_compose_json_lines(tmp_path, monkeypatch, capsys):
    """Report every required healthy container and preserve optional absence."""
    stack_dir, lock_file = stack_paths(tmp_path)
    records = [dict(Service=service, State="running", Health="healthy")
               for service in stack_status.REQUIRED_SERVICES["60"]]
    commands = []

    def fake_run(command, **kwargs):
        """Return Compose JSON Lines without a runtime mutation."""
        commands.append(command)
        return SimpleNamespace(returncode=0, stdout="\n".join(json.dumps(item) for item in records), stderr="")

    monkeypatch.setattr(stack_status.subprocess, "run", fake_run)
    assert stack_status.report_status("60", stack_dir, lock_file) == 0
    assert commands[0][-4:] == ["ps", "--all", "--format", "json"]
    output = capsys.readouterr().out
    assert "hermes-memory-sync: inactive optional profile" in output
    assert "runtime=READY" in output


@pytest.mark.parametrize("rows,expected", [
    ({}, "STOPPED"),
    ({"haproxy": ("running", "healthy")}, "PARTIAL"),
    ({"haproxy": ("running", "unhealthy"), "web": ("running", "healthy")}, "DEGRADED"),
    ({"haproxy": ("running", "healthy"), "web": ("running", "none")}, "RUNNING"),
])
def test_runtime_classification(tmp_path, monkeypatch, capsys, rows, expected):
    """Do not mistake missing, unhealthy, or unprobed services for READY."""
    stack_dir, lock_file = stack_paths(tmp_path)
    monkeypatch.setattr(stack_status, "compose_rows", lambda path: {
        service: {"Service": service, "State": state, "Health": health}
        for service, (state, health) in rows.items()
    })
    assert stack_status.report_status("10", stack_dir, lock_file) == 1
    assert f"runtime={expected}" in capsys.readouterr().out


@pytest.mark.parametrize("number", ("20", "30"))
def test_deep_status_runs_authenticated_read_only_database_query(tmp_path, monkeypatch, capsys, number):
    """Check database connectivity once without exposing password values."""
    stack_dir, lock_file = stack_paths(tmp_path)
    monkeypatch.setattr(stack_status, "compose_rows", lambda path: {
        service: {"Service": service, "State": "running", "Health": "healthy"}
        for service in stack_status.REQUIRED_SERVICES[number]
    })
    calls = []

    def fake_run(command, **kwargs):
        """Capture the Docker exec invocation and return SELECT 1."""
        calls.append(command)
        return SimpleNamespace(returncode=0, stdout="1\n", stderr="")

    monkeypatch.setattr(stack_status.subprocess, "run", fake_run)
    assert stack_status.report_status(number, stack_dir, lock_file, deep=True) == 0
    assert calls[0][:3] == ["docker", "exec", stack_status.DATABASE_PROBES[number][0]]
    assert "SELECT 1" in calls[0][-1]
    assert "PostgreSQL SELECT 1: OK" in capsys.readouterr().out


def test_deep_query_failure_does_not_report_ready(tmp_path, monkeypatch, capsys):
    """Keep a database authentication error separate from container health."""
    stack_dir, lock_file = stack_paths(tmp_path)
    monkeypatch.setattr(stack_status, "compose_rows", lambda path: {
        service: {"Service": service, "State": "running", "Health": "healthy"}
        for service in stack_status.REQUIRED_SERVICES["30"]
    })
    monkeypatch.setattr(stack_status, "database_probe", lambda number: False)
    assert stack_status.report_status("30", stack_dir, lock_file, deep=True) == 1
    output = capsys.readouterr().out
    assert "PostgreSQL SELECT 1: FAILED" in output
    assert "overall=NOT READY" in output


def test_platform_status_never_claims_verified_without_deep_check(tmp_path, capsys):
    """Stack 00 has no containers and its shallow status is only preparation."""
    stack_dir, lock_file = stack_paths(tmp_path)
    assert stack_status.report_platform_status(stack_dir, lock_file) == 0
    assert "NOT VERIFIED" in capsys.readouterr().out
