#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Apply and verify the project shebang across tracked Python modules.

Every tracked ``.py`` file starts with ``#!/usr/bin/env python3`` as its
literal first line, ahead of the MPL notice ``tools/apply_mpl_headers.py``
inserts next. The tool is conservative: it only ever prepends the shebang
when a file has none, and never touches a file that already starts with
some other shebang.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SHEBANG = "#!/usr/bin/env python3\n"


def git_python_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=ROOT,
        check=True,
        stdout=subprocess.PIPE,
    )
    return [
        ROOT / part.decode("utf-8")
        for part in result.stdout.split(b"\0")
        if part and part.decode("utf-8").endswith(".py")
    ]


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

    for path in git_python_files():
        if path.is_symlink():
            continue
        relative = rel(path)
        data = path.read_bytes()
        if is_binary_bytes(data):
            continue
        text = data.decode("utf-8")
        if text.startswith("#!"):
            continue

        if check_only:
            missing.append(relative)
            continue

        path.write_text(SHEBANG + text, encoding="utf-8", newline="")
        changed.append(relative)

    if check_only:
        if missing:
            print("Files missing the project shebang:")
            for item in sorted(missing):
                print(f"  - {item}")
            return 1
        print("Python shebang check passed.")
        return 0

    print(f"Added a shebang to {len(changed)} tracked Python module(s).")
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
