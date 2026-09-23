#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Compare the container versions of the installed .env with .env.template.

Prints one table: installed version (.env), new version (.env.template) and
the action needed. Components pinned by digest are shown as manual-only.
The component list is shared with 01-checkrepo.py.
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
REPO_ROOT = TOOLS.parent


def load_checkrepo():
    spec = importlib.util.spec_from_file_location("checkrepo", TOOLS / "01-checkrepo.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def shown(tag: str | None, digest: str | None) -> str:
    if digest:
        return digest[:19] + "…" if len(digest) > 19 else digest
    return tag or "-"


def compare(repo, env_path: Path, template_path: Path) -> list[dict]:
    """Return one entry per component: component, old, new, action."""
    installed = repo.read_env(env_path)
    template = repo.read_env(template_path)
    entries = []
    for component in repo.COMPONENTS:
        old_tag, old_digest = repo.current_tag(component, installed)
        new_tag, new_digest = repo.current_tag(component, template)
        old, new = shown(old_tag, old_digest), shown(new_tag, new_digest)
        if component.var not in installed:
            action, old = "MISSING in .env", "-"
        elif component.manual or old_digest or new_digest:
            action = "Manual update only"
        elif old == new:
            action = "OK"
        else:
            action = "UPDATE"
        entries.append({"component": component, "old": old, "new": new, "action": action})
    return entries


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--env", type=Path, default=REPO_ROOT / ".env",
                        help="installed environment (default: repository .env)")
    parser.add_argument("--template", type=Path, default=REPO_ROOT / ".env.template",
                        help="reference template (default: repository .env.template)")
    args = parser.parse_args(argv)

    for path in (args.env, args.template):
        if not path.is_file():
            print(f"ERROR: not found: {path}", file=sys.stderr)
            return 1

    repo = load_checkrepo()
    entries = compare(repo, args.env, args.template)
    rows = [("COMPONENT", "VARIABLE", "INSTALLED", "NEW", "ACTION")]
    rows += [(e["component"].name, e["component"].var, e["old"], e["new"], e["action"])
             for e in entries]
    pending = sum(e["action"] in ("UPDATE", "MISSING in .env") for e in entries)

    widths = [max(len(row[col]) for row in rows) for col in range(5)]
    for index, row in enumerate(rows):
        print("  ".join(cell.ljust(widths[col]) for col, cell in enumerate(row)).rstrip())
        if index == 0:
            print("  ".join("-" * width for width in widths))
    print(f"\n{pending} pending")
    return 0


if __name__ == "__main__":
    sys.exit(main())
