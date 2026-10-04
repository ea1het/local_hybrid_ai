"""Stage Hermes' central environment and managed model configuration.

The root environment determines the selected model and gateway connection.
The current web-tool choice is preserved; optional Git-memory setup remains
separate. This module changes files only and never stops or starts Hermes.
"""

from __future__ import annotations

import importlib
import re
import argparse
import sys
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from wrapper.lib.hermes_runtime_env import RuntimeEnvironmentError, reconcile
from wrapper.lib.reconfig_runtime import (ReconfigError, compose_config, environment,
                                          lifecycle_hint, sync_content)

STACK_DIR = Path(__file__).resolve().parent


def main() -> int:
    try:
        values = environment(STACK_DIR)
        model = values.get("HERMES_MODEL", "")
        service = values.get("HERMES_SERVICE", "")
        base_path = values.get("BASE_PATH", "")
        if not model or model.startswith("PUT_YOUR_"):
            raise ReconfigError("HERMES_MODEL is missing or incomplete")
        if not base_path.startswith("/") or not service.startswith("service_-_") or Path(service).name != service:
            raise ReconfigError("invalid Hermes runtime location in .env")
        if values.get("TELEGRAM_BOT_TOKEN"):
            if not re.fullmatch(r"[0-9]+:[A-Za-z0-9_-]{30,}", values["TELEGRAM_BOT_TOKEN"]):
                raise ReconfigError("TELEGRAM_BOT_TOKEN has an invalid format")
            if not re.fullmatch(r"[1-9][0-9]*(?:,[1-9][0-9]*)*", values.get("TELEGRAM_ALLOWED_USERS", "")):
                raise ReconfigError("TELEGRAM_ALLOWED_USERS must list numeric user IDs")
        runtime = Path(base_path) / service
        config = runtime / "config/config.yaml"
        runtime_env = runtime / "data/.env"
        if config.is_symlink() or not config.is_file():
            raise ReconfigError(f"missing managed Hermes configuration: {config}")
        current = config.read_text()
        disabled = re.findall(r"(?m)^\s*disabled_toolsets:\s*(\[web\]|\[\])\s*$", current)
        if len(disabled) != 1:
            raise ReconfigError("unknown Hermes web-tool state; review config.yaml manually")
        capabilities = importlib.import_module("stack-60_-_hermes.reconcile-capabilities")
        compose_config(STACK_DIR)
        rendered = capabilities.render_config(model, disabled[0] == "[]")
        changed_config = sync_content(rendered, config)
        changed_env = reconcile(runtime_env, frozenset(values))
        print(f"Stack 60: managed configuration {'updated' if changed_config else 'unchanged'}; "
              f"runtime overrides {'removed' if changed_env else 'absent'}.")
        if changed_config or changed_env:
            lifecycle_hint("60")
        else:
            print("If Compose-only values changed in .env, run ./local-ai stack-60 stop and ./local-ai stack-60 start.")
        print("Optional Git memory and provider reconciliation remain separate operations.")
        return 0
    except (ReconfigError, RuntimeEnvironmentError, OSError, ValueError, UnicodeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter).parse_args()
    raise SystemExit(main())
