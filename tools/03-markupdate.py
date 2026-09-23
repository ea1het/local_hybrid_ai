#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Interactively inject template versions marked UPDATE into the main .env.

Takes the result of 02-checkenv.py, asks y/n for every component whose action
is UPDATE, shows the selection and asks once more. Only if that last answer is
yes are all selected variables written to .env, in a single atomic write.
Answering no, pressing Ctrl-C or closing the input leaves .env untouched.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import sys
import tempfile
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
REPO_ROOT = TOOLS.parent
YES = {"y", "yes", "s", "si", "sí"}
NO = {"n", "no"}


def load(filename: str, name: str):
    spec = importlib.util.spec_from_file_location(name, TOOLS / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def ask(question: str) -> bool:
    while True:
        answer = input(f"{question} [y/n]: ").strip().lower()
        if answer in YES:
            return True
        if answer in NO:
            return False
        print("Please answer y or n.")


def write_atomic(path: Path, lines: list[str]) -> None:
    info = path.stat()
    handle = tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False)
    try:
        with handle:
            handle.write("\n".join(lines))
        os.chmod(handle.name, info.st_mode & 0o7777)
        if os.geteuid() == 0:
            os.chown(handle.name, info.st_uid, info.st_gid)
        os.replace(handle.name, path)
    except BaseException:
        Path(handle.name).unlink(missing_ok=True)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--env", type=Path, default=REPO_ROOT / ".env",
                        help="environment to update (default: repository .env)")
    parser.add_argument("--template", type=Path, default=REPO_ROOT / ".env.template",
                        help="reference template (default: repository .env.template)")
    args = parser.parse_args(argv)

    for path in (args.env, args.template):
        if not path.is_file():
            print(f"ERROR: not found: {path}", file=sys.stderr)
            return 1

    repo = load("01-checkrepo.py", "checkrepo")
    checkenv = load("02-checkenv.py", "checkenv")
    entries = checkenv.compare(repo, args.env, args.template)
    updates = [entry for entry in entries if entry["action"] == "UPDATE"]

    if not updates:
        print("Nothing to update: no component is marked UPDATE.")
        return 0

    print(f"{len(updates)} component(s) marked UPDATE in {args.env}\n")
    selected = []
    try:
        for entry in updates:
            component = entry["component"]
            question = f"{component.name} ({component.var}): {entry['old']} -> {entry['new']}. Inject?"
            if ask(question):
                selected.append(entry)

        if not selected:
            print("\nNothing selected. .env unchanged.")
            return 0

        print("\nChanges to inject into", args.env)
        for entry in selected:
            component = entry["component"]
            print(f"  {component.var}: {entry['old']} -> {entry['new']}")
        if not ask("\nAre you happy with these changes?"):
            print("Cancelled. .env unchanged.")
            return 0
    except (KeyboardInterrupt, EOFError):
        print("\nAborted. .env unchanged.")
        return 1

    wanted = {entry["component"].var: entry for entry in selected}
    lines = args.env.read_text().split("\n")
    out = []
    applied = 0
    for raw in lines:
        match = repo.LINE_RE.match(raw)
        if match and match["key"] in wanted:
            entry = wanted[match["key"]]
            new_value = repo.rewrite_value(entry["component"], match["val"], entry["new"])
            raw = f"{match['key']}={new_value}{match['tail'] or ''}"
            applied += 1
        out.append(raw)

    if applied != len(wanted):
        print("ERROR: could not locate every selected variable in .env; nothing written.",
              file=sys.stderr)
        return 1

    write_atomic(args.env, out)
    print(f"\nDone: {applied} variable(s) updated in {args.env}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
