# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Reconcile Open WebUI's LiteLLM connection and model policy when safe.

Without --apply this command reports connection and model-policy drift.
With --apply it updates a stale key only while stopped, or reconciles policy
through the running application's ORM. It never manages container lifecycle.
"""

from __future__ import annotations

import subprocess
import argparse
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


def policy_status() -> str:
    """Probe model policy through the application's read-only verifier."""
    result = subprocess.run(
        [sys.executable, "-B", str(STACK_DIR / "verify-model-policy.py")],
        cwd=STACK_DIR, stdin=subprocess.DEVNULL, capture_output=True, text=True, check=False,
    )
    if result.returncode == 0 and "PASS" in result.stdout:
        return "current"
    if result.returncode == 0 and "DEFER" in result.stdout:
        return "deferred until the first administrator exists"
    return "would reconcile or requires review"


def main(apply: bool = False) -> int:
    try:
        values = environment(STACK_DIR)
        endpoint = values.get("OPENWEBUI_LITELLM_BASE_URL", "")
        key = values.get("OPENWEBUI_LITELLM_API_KEY", "")
        base_path = values.get("BASE_PATH", "")
        if not endpoint or missing(key) or not base_path.startswith("/"):
            raise ReconfigError("LiteLLM URL, key, or BASE_PATH is missing from .env")
        database = Path(base_path) / "service_-_open-webui/data/webui.db"
        running = container_running("open-webui")
        stale_key = needs_update(database, endpoint, key)
        print(f"Stack 70 plan: LiteLLM connection {'update' if stale_key else 'unchanged'}.")
        if stale_key and running:
            print("DEFER: Open WebUI is running; SQLite must not be changed now.")
            print("Run ./local-ai stack-70 stop, then ./local-ai stack-70 reconfig --apply, then ./local-ai stack-70 start.")
            return 1 if apply else 0
        if not apply:
            if running:
                print(f"Stack 70 plan: model policy {policy_status()}.")
            else:
                print("Stack 70 plan: model policy deferred until Open WebUI is running.")
            print("Preview only; run ./local-ai stack-70 reconfig --apply to apply this plan.")
            return 0
        if stale_key:
            reconcile(database, endpoint, key)
            print("Stack 70 LiteLLM connection updated.")
            lifecycle_hint("70")
        if running:
            result = subprocess.run(
                [sys.executable, "-B", str(STACK_DIR / "reconcile-model-policy.py")],
                cwd=STACK_DIR, stdin=subprocess.DEVNULL, check=False,
            )
            return result.returncode
        print("DEFER: model policy needs a running Open WebUI and its first administrator.")
        print("After ./local-ai stack-70 start, run ./local-ai stack-70 reconfig and then --apply if needed.")
        return 0
    except (ReconfigError, ConnectionError, OSError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="Apply the displayed reconfiguration plan")
    raise SystemExit(main(parser.parse_args().apply))
