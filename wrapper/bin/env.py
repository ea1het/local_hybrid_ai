#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Expose protected environment bootstrap through the root local-ai CLI."""

import argparse
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from wrapper.stubs.bootstrap_env import bootstrap, BootstrapError


def main(argv: list[str] | None = None) -> int:
    """Dispatch env bootstrap with an explicit verb and no secret output."""
    parser = argparse.ArgumentParser(prog="./local-ai env", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("bootstrap", help="Create or complete locally controlled secrets")
    options = parser.parse_args(argv)
    if options.command == "bootstrap":
        try:
            generated, pending, backup, changed = bootstrap(Path(__file__).resolve().parents[2])
        except (BootstrapError, OSError, UnicodeError, ValueError) as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 1
        print(f"Environment: {'updated' if changed else 'unchanged'}; generated/adopted {len(generated)} local value(s).")
        if backup:
            print(f"Protected backup: {backup}")
        if pending:
            print("External or service-issued credentials still pending: " + ", ".join(pending))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
