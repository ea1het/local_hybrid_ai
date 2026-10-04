"""Stage the three managed SearXNG files without changing container state.

The repository owns settings, limiter, and favicon configuration. Changed
runtime copies are backed up before replacement, while database state and
container lifecycle remain untouched for explicit operator action later.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from wrapper.lib.reconfig_runtime import (ReconfigError, compose_config, environment,
                                          lifecycle_hint, sync_managed, validate_managed)

STACK_DIR = Path(__file__).resolve().parent
NAMES = ("settings.yml", "limiter.toml", "favicons.toml")


def main() -> int:
    try:
        values = environment(STACK_DIR)
        base_path = values.get("BASE_PATH", "")
        if not base_path.startswith("/"):
            raise ReconfigError("BASE_PATH must be absolute")
        runtime = Path(base_path) / "service_-_searxng/config"
        compose_config(STACK_DIR)
        files = tuple((STACK_DIR / "config/searxng" / name, runtime / name) for name in NAMES)
        for source, target in files:
            validate_managed(source, target)
        changed = []
        for source, target in files:
            if sync_managed(source, target):
                changed.append(target.name)
        print(f"Stack 20: {'updated ' + ', '.join(changed) if changed else 'managed files unchanged'}.")
        if changed:
            lifecycle_hint("20")
        else:
            print("If Compose variables changed in .env, run ./local-ai stack-20 stop and ./local-ai stack-20 start.")
        return 0
    except (ReconfigError, OSError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter).parse_args()
    raise SystemExit(main())
