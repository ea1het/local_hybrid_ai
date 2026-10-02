# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Exercise read-only stack status classification without contacting Docker.

Temporary stack paths and mocked Docker inspection cover prepared, stopped,
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


def test_ready_status_inspects_docker_containers(tmp_path, monkeypatch, capsys):
    """Report required container health without reading local Compose inputs."""
    stack_dir, lock_file = stack_paths(tmp_path)
    (stack_dir / ".env").unlink()
    (stack_dir / "docker-compose.yml").unlink()
    records = [dict(Config={"Labels": {"com.docker.compose.service": service,
                                       "com.docker.compose.project.working_dir": str(stack_dir)}},
                    State={"Status": "running", "Health": {"Status": "healthy"}})
               for service in stack_status.REQUIRED_SERVICES["60"]]
    commands = []

    def fake_run(command, **kwargs):
        """Return Docker IDs and inspect records without a runtime mutation."""
        commands.append(command)
        output = "one two three" if command[1] == "ps" else json.dumps(records)
        return SimpleNamespace(returncode=0, stdout=output, stderr="")

    monkeypatch.setattr(stack_status.subprocess, "run", fake_run)
    assert stack_status.report_status("60", stack_dir, lock_file) == 0
    assert commands[0] == ["docker", "ps", "--all", "--quiet", "--no-trunc", "--filter",
                           "label=com.docker.compose.service"]
    assert commands[1][:4] == ["docker", "inspect", "--type", "container"]
    output = capsys.readouterr().out
    assert "preparation=PREPARED\n\n  hermes:" in output
    assert "inactive optional profile\n\nruntime=READY" in output
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
    monkeypatch.setattr(stack_status, "container_rows", lambda path: {
        service: {"Service": service, "State": state, "Health": health}
        for service, (state, health) in rows.items()
    })
    assert stack_status.report_status("10", stack_dir, lock_file) == 1
    assert f"runtime={expected}" in capsys.readouterr().out


@pytest.mark.parametrize("number", ("20", "30"))
def test_deep_status_runs_authenticated_read_only_database_query(tmp_path, monkeypatch, capsys, number):
    """Check database connectivity once without exposing password values."""
    stack_dir, lock_file = stack_paths(tmp_path)
    monkeypatch.setattr(stack_status, "container_rows", lambda path: {
        service: {"Service": service, "State": "running", "Health": "healthy"}
        for service in stack_status.REQUIRED_SERVICES[number]
    })
    calls = []

    def fake_run(command, **kwargs):
        """Capture the Docker exec invocation and return SELECT 1."""
        calls.append(command)
        return SimpleNamespace(returncode=0, stdout="1\n", stderr="")

    monkeypatch.setattr(stack_status.subprocess, "run", fake_run)
    monkeypatch.setattr(stack_status, "searxng_search_probe", lambda: True)
    assert stack_status.report_status(number, stack_dir, lock_file, deep=True) == 0
    assert calls[0][:3] == ["docker", "exec", stack_status.DATABASE_PROBES[number][0]]
    assert "SELECT 1" in calls[0][-1]
    assert "PostgreSQL SELECT 1: OK" in capsys.readouterr().out


def test_stack_20_deep_status_detects_search_failure(tmp_path, monkeypatch, capsys):
    """A healthy HTTP process is insufficient when JSON search returns 403."""
    stack_dir, lock_file = stack_paths(tmp_path)
    monkeypatch.setattr(stack_status, "container_rows", lambda path: {
        service: {"State": "running", "Health": "healthy"}
        for service in stack_status.REQUIRED_SERVICES["20"]
    })
    monkeypatch.setattr(stack_status, "database_probe", lambda number: True)
    monkeypatch.setattr(stack_status, "searxng_search_probe", lambda: False)

    assert stack_status.report_status("20", stack_dir, lock_file, deep=True) == 1
    output = capsys.readouterr().out
    assert "SearXNG JSON search: FAILED" in output
    assert "runtime=READY" in output
    assert "overall=NOT READY" in output


@pytest.mark.parametrize("exit_code,expected", [(0, True), (1, False)])
def test_searxng_search_probe_reports_http_result(monkeypatch, exit_code, expected):
    """Run a local JSON search without emitting response data or credentials."""
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=exit_code)

    monkeypatch.setattr(stack_status.subprocess, "run", fake_run)
    assert stack_status.searxng_search_probe() is expected
    assert calls[0][:4] == ["docker", "exec", "searxng", "python3"]
    assert "format=json" in calls[0][-1]


def test_deep_query_failure_does_not_report_ready(tmp_path, monkeypatch, capsys):
    """Keep a database authentication error separate from container health."""
    stack_dir, lock_file = stack_paths(tmp_path)
    monkeypatch.setattr(stack_status, "container_rows", lambda path: {
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


def test_missing_lock_does_not_hide_healthy_runtime(tmp_path, monkeypatch, capsys):
    """Show live health even when the installation lock was lost."""
    stack_dir, lock_file = stack_paths(tmp_path)
    lock_file.unlink()
    (stack_dir / ".env").unlink()
    (stack_dir / "docker-compose.yml").unlink()
    monkeypatch.setattr(stack_status, "container_rows", lambda path: {
        service: {"State": "running", "Health": "healthy"}
        for service in stack_status.REQUIRED_SERVICES["10"]
    })
    assert stack_status.report_status("10", stack_dir, lock_file) == 1
    output = capsys.readouterr().out
    assert "preparation=UNPREPARED" in output
    assert "runtime=READY" in output
    assert "overall=NOT READY" in output


def test_docker_failure_is_unknown_not_stopped(tmp_path, monkeypatch, capsys):
    """Do not interpret an unavailable Docker daemon as absent containers."""
    stack_dir, lock_file = stack_paths(tmp_path)
    monkeypatch.setattr(stack_status.subprocess, "run", lambda *args, **kwargs:
                        SimpleNamespace(returncode=1, stdout="", stderr="unavailable"))
    assert stack_status.report_status("10", stack_dir, lock_file) == 2
    assert "runtime=UNKNOWN (Docker ps failed" in capsys.readouterr().out


def test_legacy_compose_working_directory_is_recognized(tmp_path, monkeypatch):
    """Find containers created before the stack source directories were renamed."""
    stack_dir = tmp_path / "stack-10_-_haproxy_web"
    records = [dict(Config={"Labels": {
        "com.docker.compose.project.working_dir": str(tmp_path / "stack1_-_haproxy_web"),
        "com.docker.compose.service": service,
    }}, State={"Status": "running", "Health": {"Status": "healthy"}})
        for service in stack_status.REQUIRED_SERVICES["10"]]

    def fake_run(command, **kwargs):
        """Return two legacy containers and one unrelated container."""
        output = "one two three" if command[1] == "ps" else json.dumps([
            *records,
            dict(Config={"Labels": {
                "com.docker.compose.project.working_dir": str(tmp_path / "other"),
                "com.docker.compose.service": "web",
            }}, State={"Status": "running"}),
        ])
        return SimpleNamespace(returncode=0, stdout=output, stderr="")

    monkeypatch.setattr(stack_status.subprocess, "run", fake_run)
    rows = stack_status.container_rows(stack_dir)
    assert set(rows) == set(stack_status.REQUIRED_SERVICES["10"])
    assert all(row["Health"] == "healthy" for row in rows.values())


def test_moved_checkout_falls_back_to_named_container_project(tmp_path, monkeypatch):
    """Locate an existing Compose project when its recorded path has moved."""
    stack_dir = tmp_path / "stack-10_-_haproxy_web"
    old_path = tmp_path / "prior_checkout" / "stack1_-_haproxy_web"
    records = [dict(Name=f"/{service}", Config={"Labels": {
        "com.docker.compose.project.working_dir": str(old_path),
        "com.docker.compose.project": "old-stack1",
        "com.docker.compose.service": service,
    }}, State={"Status": "running", "Health": {"Status": "healthy"}})
        for service in stack_status.REQUIRED_SERVICES["10"]]
    records.append(dict(Name="/unrelated", Config={"Labels": {
        "com.docker.compose.project.working_dir": str(old_path),
        "com.docker.compose.project": "unrelated",
        "com.docker.compose.service": "web",
    }}, State={"Status": "running"}))

    def fake_run(command, **kwargs):
        """Return inspect records for two projects."""
        output = "one two three" if command[1] == "ps" else json.dumps(records)
        return SimpleNamespace(returncode=0, stdout=output, stderr="")

    monkeypatch.setattr(stack_status.subprocess, "run", fake_run)
    assert set(stack_status.container_rows(stack_dir)) == {"haproxy", "web"}
