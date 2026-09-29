# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Require a rendered healthcheck for every Compose service.

When Docker Compose is installed, configuration rendering checks each stack
using the public template environment only. It does not contact the daemon,
start containers, read operational secrets, or execute any healthcheck.
"""

import json
import shutil
import subprocess
import sys

sys.dont_write_bytecode = True

import pytest

from tests.helpers import ROOT
from wrapper.lib.stack_status import OPTIONAL_SERVICES, REQUIRED_SERVICES


STACK_DIRS = {
    "10": "stack-10_-_haproxy_web",
    "20": "stack-20_-_searxng_firecrawl",
    "30": "stack-30_-_litellm",
    "40": "stack-40_-_gitea",
    "50": "stack-50_-_dockhand",
    "60": "stack-60_-_hermes",
    "70": "stack-70_-_open-webui",
}


@pytest.mark.parametrize("number", tuple(STACK_DIRS))
def test_every_compose_service_has_healthcheck(number):
    """Match status inventory to Compose and require every service probe."""
    if shutil.which("docker") is None:
        pytest.skip("Docker Compose CLI unavailable")
    version = subprocess.run(["docker", "compose", "version"], capture_output=True, check=False)
    if version.returncode:
        pytest.skip("Docker Compose CLI unavailable")

    command = ["docker", "compose", "--env-file", str(ROOT / ".env.template"),
               "-f", str(ROOT / STACK_DIRS[number] / "docker-compose.yml")]
    if number == "60":
        command += ["--profile", "git-memory"]
    result = subprocess.run(command + ["config", "--format", "json"], cwd=ROOT,
                            capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    services = json.loads(result.stdout)["services"]
    expected = set(REQUIRED_SERVICES[number]) | set(OPTIONAL_SERVICES.get(number, ()))
    assert set(services) == expected
    assert all(service.get("healthcheck", {}).get("test") for service in services.values())
