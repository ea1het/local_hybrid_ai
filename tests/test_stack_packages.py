# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Verify that every operational stack is importable as a Python package.

These tests exercise package discovery and a representative entrypoint for
each stack without running any main function. They protect relative helper
imports while keeping the legacy directory and CLI filenames stable.
"""

import importlib
import sys
from pathlib import Path

sys.dont_write_bytecode = True

import pytest


STACKS = (
    "stack-00_-_platform",
    "stack-10_-_haproxy_web",
    "stack-20_-_searxng_firecrawl",
    "stack-30_-_litellm",
    "stack-40_-_gitea",
    "stack-50_-_dockhand",
    "stack-60_-_hermes",
    "stack-70_-_open-webui",
)
ROOT = Path(__file__).resolve().parents[1]
STACK_MODULES = tuple(
    path
    for stack in STACKS
    for path in sorted((ROOT / stack).rglob("*.py"))
    if path.name != "__init__.py"
)


@pytest.mark.parametrize("stack", STACKS)
def test_stack_package_and_preparation_module_import(stack):
    """Resolve each package and its preparation script without running setup."""
    package = importlib.import_module(stack)
    prepare = importlib.import_module(f"{stack}.01-prepare")

    assert package.__path__
    assert prepare.__package__ == stack
    assert "Import" in prepare.__doc__ or "import" in prepare.__doc__


def test_shared_helpers_resolve_within_their_stack_packages():
    """Keep platform and Hermes helper imports package-relative."""
    platform = importlib.import_module("stack-00_-_platform.01-prepare")
    platform_helper = importlib.import_module("stack-00_-_platform.ops_common")
    hermes = importlib.import_module("stack-60_-_hermes.01-prepare")
    hermes_helper = importlib.import_module("stack-60_-_hermes.stack_env")

    assert platform.load_env is platform_helper.load_env
    assert hermes.load_env is hermes_helper.load_env


@pytest.mark.parametrize("path", STACK_MODULES, ids=lambda path: str(path.relative_to(ROOT)))
def test_every_stack_module_imports_with_package_context(path):
    """Import each stack module and expose its substantive module docstring."""
    name = ".".join(path.relative_to(ROOT).with_suffix("").parts)
    module = importlib.import_module(name)

    assert module.__package__
    assert len(module.__doc__.split()) >= 20
