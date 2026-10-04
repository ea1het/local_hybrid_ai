"""Stage managed HAProxy and web files without changing container state.

Repository copies are authoritative for these two files; previous runtime
copies are backed up before replacement. Compose variables and certificates
remain separate inputs, and the operator decides when to stop and start.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from wrapper.lib.reconfig_runtime import (ReconfigError, compose_config, environment,
                                          lifecycle_hint, sync_managed, validate_managed)

STACK_DIR = Path(__file__).resolve().parent


def main() -> int:
    try:
        values = environment(STACK_DIR)
        base_path = values.get("BASE_PATH", "")
        if not base_path.startswith("/"):
            raise ReconfigError("BASE_PATH must be absolute")
        config_dir = Path(base_path) / "service_-_haproxy/config"
        web_dir = Path(base_path) / "service_-_web"
        for path in (config_dir / "tls.crt", config_dir / "tls.key"):
            if path.is_symlink() or not path.is_file():
                raise ReconfigError(f"missing TLS material: {path}")
        compose_config(STACK_DIR)
        files = (
            (STACK_DIR / "config/haproxy/haproxy.cfg", config_dir / "haproxy.cfg"),
            (STACK_DIR / "config/web/index.html", web_dir / "index.html"),
        )
        for source, target in files:
            validate_managed(source, target)
        changed = []
        for source, target in files:
            if sync_managed(source, target):
                changed.append(target.name)
        print(f"Stack 10: {'updated ' + ', '.join(changed) if changed else 'managed files unchanged'}.")
        if changed:
            lifecycle_hint("10")
        else:
            print("If Compose variables changed in .env, run ./local-ai stack-10 stop and ./local-ai stack-10 start.")
        return 0
    except (ReconfigError, OSError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
