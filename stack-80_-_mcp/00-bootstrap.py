#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Link the central environment and create per-MCP settings/signing keys."""

from stack_env import parser, prepare_settings, selected


def main():
    args = parser(__doc__).parse_args()
    prepare_settings(selected(args))
    print("Central .env preserved. Client ID is read once from the global environment.")


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError) as error:
        raise SystemExit(str(error))
