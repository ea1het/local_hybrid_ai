#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Manually authorize Google or check stored credentials inside selected MCPs."""

import sys

sys.dont_write_bytecode = True

import subprocess

from stack_env import compose_command, parser, selected


def main():
    options = parser(__doc__)
    options.add_argument("--check", action="store_true",
                         help="Check saved credentials; refresh expired tokens without a browser.")
    args = options.parse_args()
    if not args.check and not sys.stdin.isatty():
        options.error("Authorization requires an interactive terminal; use --check for automation.")
    for service in selected(args):
        arguments = ["exec"]
        if args.check:
            arguments.append("-T")
        arguments.extend([service, "/app/.venv/bin/python", "-B",
                          "/opt/stack80/google-oauth.py", service])
        if args.check:
            arguments.append("--check")
        # Inherit the terminal for the browser URL and hidden callback input.
        # No credentials or authorization codes enter host command arguments.
        result = subprocess.run(compose_command(*arguments), check=False)
        if result.returncode:
            raise SystemExit(result.returncode)


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError) as error:
        raise SystemExit(str(error))
