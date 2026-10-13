#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Preview or stage MCP settings without deployment or Google authorization.

Importing this module does not prepare directories, change containers, or
perform Google authorization. Operations run only through explicit entrypoints.
"""

import sys
sys.dont_write_bytecode = True
import argparse
import importlib
from pathlib import Path

STACK_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(STACK_DIR.parent))
from wrapper.lib.reconfig_runtime import ReconfigError, environment, lifecycle_hint
from wrapper.lib.stack_status import container_rows


def main(apply=False):
    """Preserve service overrides and tokens; validate before any changes."""
    try:
        environment(STACK_DIR)
        api = importlib.import_module("stack-80_-_mcp.stack_env")
        changes = api.settings_changes(api.SERVICES)
        # Compose can read existing settings containing obsolete keys. Missing
        # settings require initial installation rather than a mutating preview.
        config = api.configuration()
        api.validate_configuration(config)
        api.runtime_directories(config)
        print(f"Stack 80 plan: {len(changes)} private settings file(s) need updating.")
        for path, _ in changes:
            print(f"  {path.relative_to(STACK_DIR)}")
        if not apply:
            print("Preview only; run ./local-ai stack-80 reconfig --apply to apply this plan.")
        elif changes:
            rows = container_rows(STACK_DIR)
            if any(row["State"] in {"running", "restarting", "paused"} for row in rows.values()):
                raise RuntimeError("Stop Stack 80 before changing managed settings; no files were changed.")
            api.apply_settings(changes)
            print("Stack 80 managed settings applied with private backups; credentials preserved.")
        else:
            print("No managed settings changes.")
        print("Compose and central .env changes are not tracked as runtime file differences.")
        print("Changing the Google OAuth app, account, or scopes may require manual authorize.py.")
        print("Changing BASE_PATH or MCP_UID/MCP_GID requires explicit data/ownership migration.")
        print("Google tokens were not read, refreshed, or removed. LiteLLM was not modified.")
        lifecycle_hint("80")
        return 0
    except (ReconfigError, OSError, ValueError, RuntimeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Apply the previewed settings changes")
    raise SystemExit(main(parser.parse_args().apply))
