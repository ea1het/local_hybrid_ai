# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Stage the three managed SearXNG files without changing container state.

Without --apply this command reports differences only. With --apply it backs
up changed runtime copies and installs repository-owned settings, limiter,
and favicon files. Database state and container lifecycle remain untouched.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from wrapper.lib.reconfig_runtime import (ReconfigError, compose_config, environment,
                                          lifecycle_hint, managed_needs_update, sync_managed)

STACK_DIR = Path(__file__).resolve().parent
NAMES = ("settings.yml", "limiter.toml", "favicons.toml")


def main(apply: bool = False) -> int:
    try:
        values = environment(STACK_DIR)
        base_path = values.get("BASE_PATH", "")
        if not base_path.startswith("/"):
            raise ReconfigError("BASE_PATH must be absolute")
        runtime = Path(base_path) / "service_-_searxng/config"
        compose_config(STACK_DIR)
        files = tuple((STACK_DIR / "config/searxng" / name, runtime / name) for name in NAMES)
        changes = [(source, target) for source, target in files if managed_needs_update(source, target)]
        print(f"Stack 20 plan: {'update ' + ', '.join(target.name for _, target in changes) if changes else 'no managed file changes'}.")
        if not apply:
            print("Preview only; run ./local-ai stack-20 reconfig --apply to apply this plan.")
        elif changes:
            for source, target in changes:
                sync_managed(source, target)
            print("Stack 20 managed files updated.")
            lifecycle_hint("20")
        else:
            print("Nothing to apply.")
        print("Compose-only .env changes are not tracked; if changed, run ./local-ai stack-20 stop and ./local-ai stack-20 start.")
        return 0
    except (ReconfigError, OSError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="Apply the displayed reconfiguration plan")
    raise SystemExit(main(parser.parse_args().apply))
