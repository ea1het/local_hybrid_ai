# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Guard against Python bytecode artifacts in operational entrypoints.

The suite statically checks that each repository Python module disables
bytecode before local imports and runs representative scripts in isolated
temporary trees. It asserts that neither __pycache__ directories nor .pyc
files appear. Importing this module only defines tests and parameters."""

import ast
import os
import shutil
import subprocess
import sys

sys.dont_write_bytecode = True
from pathlib import Path

import pytest

from tests.helpers import ROOT


def python_modules():
    """List repository Python modules covered by the bytecode policy."""
    return sorted(
        [
            *ROOT.glob("stack-*/**/*.py"),
            *ROOT.glob("wrapper/**/*.py"),
            *ROOT.glob(".github/workflows/*.py"),
            *ROOT.glob("tests/**/*.py"),
        ]
    )


@pytest.mark.parametrize("path", python_modules(), ids=lambda path: str(path.relative_to(ROOT)))
def test_module_disables_bytecode_before_local_import(path):
    """Require bytecode suppression before imports of local helpers."""
    tree = ast.parse(path.read_text(), filename=str(path))
    disable_line = next(
        (
            node.lineno
            for node in tree.body
            if isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Attribute)
                and isinstance(target.value, ast.Name)
                and target.value.id == "sys"
                and target.attr == "dont_write_bytecode"
                for target in node.targets
            )
            and isinstance(node.value, ast.Constant)
            and node.value.value is True
        ),
        None,
    )
    assert disable_line is not None
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module in {"ops_common", "stack_env"}:
            assert disable_line < node.lineno
        if isinstance(node, ast.Import) and any(alias.name == "sync_envs" for alias in node.names):
            assert disable_line < node.lineno


@pytest.mark.parametrize(
    "script,helper",
    [
        ("stack-00_-_platform/verify.py", "stack-00_-_platform/ops_common.py"),
        ("stack-60_-_hermes/wait-ready.py", "stack-60_-_hermes/stack_env.py"),
        ("wrapper/bin/upgrade.py", "wrapper/stubs/sync_envs.py"),
    ],
)
def test_local_import_does_not_create_pycache(tmp_path, script, helper):
    """Run entrypoints in isolation and assert they create no bytecode."""
    for name in (script, helper):
        destination = tmp_path / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, destination)
    entrypoint = tmp_path / script
    environment = dict(os.environ)
    environment.pop("PYTHONDONTWRITEBYTECODE", None)
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import runpy, sys; from pathlib import Path; "
            "sys.dont_write_bytecode = False; "
            "sys.path.insert(0, str(Path(sys.argv[1]).parent)); "
            "runpy.run_path(sys.argv[1], run_name='bytecode_probe')",
            str(entrypoint),
        ],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert not list(tmp_path.rglob("__pycache__"))
    assert not list(tmp_path.rglob("*.pyc"))
