#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Prepare MCP settings or adopt an existing deployment without changing data.

Importing this module does not prepare directories, change containers, or
perform Google authorization. Operations run only through explicit entrypoints.
"""

import sys
sys.dont_write_bytecode = True
import os
from pathlib import Path

if __package__:
    from .stack_env import (SERVICES, configuration, parser, prepare_settings, selected,
                           settings_changes, runtime_directories, validate_configuration, validate_network)
else:
    from stack_env import (SERVICES, configuration, parser, prepare_settings, selected,
                           settings_changes, runtime_directories, validate_configuration, validate_network)


def write_lock():
    """Mark full preparation only after all checks succeed."""
    path = Path(__file__).resolve().parent / ".lock"
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise RuntimeError("Invalid Stack 80 preparation lock.")
    if not path.exists():
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as output:
            output.write("Stack 80 prepared; Google authorization remains manual.\n")


def main():
    options = parser(__doc__)
    options.add_argument("--validate-only", action="store_true",
                         help="Validate configuration without runtime checks or writes.")
    options.add_argument("--adopt", action="store_true",
                         help="Validate existing runtime and write only the full-stack preparation lock.")
    args = options.parse_args()
    if args.adopt and (args.validate_only or args.mcp):
        options.error("--adopt requires the full stack and cannot use --validate-only")
    services = selected(args)
    if not args.validate_only and not args.adopt:
        prepare_settings(services)
    config = configuration()
    validate_configuration(config, services)
    if args.validate_only:
        print("Selected MCP settings and Compose validated; runtime not checked.")
        return
    validate_network(config)
    if args.adopt and settings_changes(services):
        raise RuntimeError("Settings need maintenance; stop Stack 80 and run preparation before adoption.")
    runtime_directories(config, services, create=not args.adopt)
    if set(services) == set(SERVICES):
        write_lock()
    for name in services:
        print(f"{name}: {'adopted' if args.adopt else 'prepared'}; credentials preserved.")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError) as error:
        raise SystemExit(str(error))
