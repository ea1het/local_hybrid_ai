#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Apply and verify the project shebang on executable Python scripts.

Only tracked ``.py`` files marked executable in Git need a shebang. Import-only
modules and tests need none. The tool never replaces a different shebang or
follows a symlink in the worktree.
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True  # never write __pycache__ into the worktree

import argparse
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SHEBANG = "#!/usr/bin/env python3\n"


def git_executable_python_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "--stage", "-z"],
        cwd=ROOT,
        check=True,
        stdout=subprocess.PIPE,
    )
    paths = []
    for entry in result.stdout.split(b"\0"):
        if not entry:
            continue
        metadata, filename = entry.split(b"\t", 1)
        mode, _object_id, stage = metadata.split()
        if stage == b"0" and mode == b"100755" and filename.endswith(b".py"):
            paths.append(ROOT / filename.decode("utf-8"))
    return paths


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def is_binary_bytes(data: bytes) -> bool:
    if b"\0" in data[:8192]:
        return True
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return True
    return False


def scan(check_only: bool) -> int:
    missing: list[str] = []
    changed: list[str] = []
    invalid: list[str] = []

    for path in git_executable_python_files():
        relative = rel(path)
        if path.is_symlink():
            invalid.append(f"{relative}: symlinked worktree path")
            continue
        try:
            data = path.read_bytes()
        except OSError as error:
            invalid.append(f"{relative}: cannot read ({error})")
            continue
        if is_binary_bytes(data):
            invalid.append(f"{relative}: binary or non-UTF-8 content")
            continue
        text = data.decode("utf-8")
        if text.splitlines() and text.splitlines()[0] == SHEBANG.rstrip("\n"):
            continue
        if text.startswith("\ufeff"):
            invalid.append(f"{relative}: UTF-8 BOM before shebang; review manually")
            continue
        if text.startswith("#!"):
            invalid.append(f"{relative}: different shebang; review manually")
            continue

        if check_only:
            missing.append(relative)
            continue

        path.write_text(SHEBANG + text, encoding="utf-8", newline="")
        changed.append(relative)

    if missing or invalid:
        print("Executable Python files needing shebang attention:")
        for item in sorted(missing + invalid):
            print(f"  - {item}")
        return 1

    if check_only:
        print("Executable Python shebang check passed.")
        return 0

    print(f"Added a shebang to {len(changed)} executable Python script(s).")
    for item in sorted(changed):
        print(f"  - {item}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="verify instead of modifying files")
    args = parser.parse_args()
    return scan(args.check)


if __name__ == "__main__":
    sys.exit(main())
