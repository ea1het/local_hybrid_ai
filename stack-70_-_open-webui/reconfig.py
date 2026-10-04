"""Reconcile Open WebUI's LiteLLM connection and model policy when safe.

The saved key can change only while the application is stopped. The model
policy can be reconciled only through the running application's ORM. This
module reports the deferred phase without managing the container lifecycle.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from wrapper.lib.open_webui_connection import ConnectionError, needs_update, reconcile
from wrapper.lib.reconfig_runtime import (ReconfigError, container_running, environment,
                                          lifecycle_hint)
from wrapper.stubs.bootstrap_env import missing

STACK_DIR = Path(__file__).resolve().parent


def main() -> int:
    try:
        values = environment(STACK_DIR)
        endpoint = values.get("OPENWEBUI_LITELLM_BASE_URL", "")
        key = values.get("OPENWEBUI_LITELLM_API_KEY", "")
        base_path = values.get("BASE_PATH", "")
        if not endpoint or missing(key) or not base_path.startswith("/"):
            raise ReconfigError("LiteLLM URL, key, or BASE_PATH is missing from .env")
        database = Path(base_path) / "service_-_open-webui/data/webui.db"
        running = container_running("open-webui")
        if needs_update(database, endpoint, key) and running:
            print("DEFER: Open WebUI is running; its SQLite connection cannot be changed safely.")
            print("Run ./local-ai stack-70 stop, then ./local-ai stack-70 reconfig, then ./local-ai stack-70 start.")
            return 1
        changed = reconcile(database, endpoint, key) if database.exists() else False
        print(f"Stack 70 LiteLLM connection: {'updated' if changed else 'unchanged'}.")
        if changed:
            lifecycle_hint("70")
        if running:
            result = subprocess.run(
                [sys.executable, "-B", str(STACK_DIR / "reconcile-model-policy.py")],
                cwd=STACK_DIR, stdin=subprocess.DEVNULL, check=False,
            )
            return result.returncode
        print("DEFER: model policy needs a running Open WebUI and its first administrator.")
        print("After ./local-ai stack-70 start, run ./local-ai stack-70 reconfig again.")
        return 0
    except (ReconfigError, ConnectionError, OSError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
