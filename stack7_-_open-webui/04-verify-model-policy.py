#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Verify Stack7-owned Open WebUI policy for basic_autorouter without mutation.

Before the first administrator exists the policy is not yet applicable and the
check reports DEFER successfully. Once an administrator exists, every required
policy property must be present or verification fails closed.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap

CONTAINER = "open-webui"
MODEL_ID = "basic_autorouter"

INNER = r'''
import asyncio
from sqlalchemy import select

from open_webui.internal.db import get_async_db_context
from open_webui.models.access_grants import AccessGrants
from open_webui.models.models import Model
from open_webui.models.users import User

MODEL_ID = "basic_autorouter"
REQUIRED_CAPABILITIES = {
    "builtin_tools",
    "citations",
    "code_interpreter",
    "file_context",
    "file_upload",
    "image_generation",
    "memory",
    "status_updates",
    "terminal",
    "vision",
    "web_search",
}


async def main():
    async with get_async_db_context() as db:
        admin_result = await db.execute(
            select(User).where(User.role == "admin").order_by(User.created_at.asc())
        )
        if admin_result.scalars().first() is None:
            print("DEFER basic_autorouter policy verification: no Open WebUI admin exists yet")
            return

        model_result = await db.execute(select(Model).where(Model.id == MODEL_ID))
        model = model_result.scalars().first()
        if model is None:
            raise RuntimeError("basic_autorouter model policy is missing")
        if not model.is_active:
            raise RuntimeError("basic_autorouter is not active")

        meta = dict(model.meta or {})
        capabilities = dict(meta.get("capabilities") or {})
        missing = sorted(name for name in REQUIRED_CAPABILITIES if capabilities.get(name) is not True)
        if missing:
            raise RuntimeError("basic_autorouter missing required capabilities: " + ", ".join(missing))

        feature_ids = list(meta.get("defaultFeatureIds") or [])
        if "web_search" not in feature_ids:
            raise RuntimeError("basic_autorouter does not enable web_search by default")

        grants = await AccessGrants.get_grants_by_resource("model", MODEL_ID, db=db)
        public_read = any(
            grant.principal_type == "user"
            and grant.principal_id == "*"
            and grant.permission == "read"
            for grant in grants
        )
        if not public_read:
            raise RuntimeError("basic_autorouter public read grant is missing")

    print("PASS basic_autorouter policy verified: active, web_search default, public read")


asyncio.run(main())
'''


def main() -> int:
    probe = subprocess.run(
        ["docker", "inspect", "-f", "{{.State.Running}}", CONTAINER],
        text=True,
        capture_output=True,
    )
    if probe.returncode != 0 or probe.stdout.strip() != "true":
        print("FAIL open-webui container is not running", file=sys.stderr)
        return 1

    run = subprocess.run(
        ["docker", "exec", "-i", CONTAINER, "python", "-"],
        input=textwrap.dedent(INNER),
        text=True,
    )
    return run.returncode


if __name__ == "__main__":
    raise SystemExit(main())
