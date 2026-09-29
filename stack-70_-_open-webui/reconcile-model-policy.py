#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Reconcile the Stack 70 basic_autorouter policy inside Open WebUI.

The host wrapper executes an embedded script in the pinned container and
uses Open WebUI's ORM rather than modifying SQLite directly. If no admin
exists yet, it reports DEFER successfully; otherwise it idempotently
updates the model policy and public access grants. It never changes
LiteLLM configuration. Importing the wrapper does not contact Docker."""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True  # never write __pycache__ into the worktree

import subprocess
import textwrap

CONTAINER = "open-webui"
MODEL_ID = "basic_autorouter"

INNER = r"""
import asyncio
import time
from sqlalchemy import select

from open_webui.internal.db import get_async_db_context
from open_webui.models.access_grants import AccessGrants
from open_webui.models.models import Model
from open_webui.models.users import User

MODEL_ID = "basic_autorouter"

REQUIRED_CAPABILITIES = {
    "builtin_tools": True,
    "citations": True,
    "code_interpreter": True,
    "file_context": True,
    "file_upload": True,
    "image_generation": True,
    "memory": True,
    "status_updates": True,
    "terminal": True,
    "vision": True,
    "web_search": True,
}


async def main():
    '''Create or update the model policy and grant public read access.'''
    async with get_async_db_context() as db:
        admin_result = await db.execute(
            select(User).where(User.role == "admin").order_by(User.created_at.asc())
        )
        admin = admin_result.scalars().first()
        if admin is None:
            print("DEFER basic_autorouter policy reconciliation: no Open WebUI admin exists yet")
            return

        model_result = await db.execute(select(Model).where(Model.id == MODEL_ID))
        model = model_result.scalars().first()

        now = int(time.time())
        if model is None:
            model = Model(
                id=MODEL_ID,
                user_id=admin.id,
                base_model_id=None,
                name=MODEL_ID,
                params={},
                meta={
                    "capabilities": REQUIRED_CAPABILITIES,
                    "defaultFeatureIds": ["web_search"],
                },
                is_active=True,
                created_at=now,
                updated_at=now,
            )
            db.add(model)
        else:
            meta = dict(model.meta or {})
            capabilities = dict(meta.get("capabilities") or {})
            capabilities.update(REQUIRED_CAPABILITIES)
            meta["capabilities"] = capabilities
            feature_ids = list(meta.get("defaultFeatureIds") or [])
            if "web_search" not in feature_ids:
                feature_ids.append("web_search")
            meta["defaultFeatureIds"] = feature_ids
            model.meta = meta
            model.is_active = True
            model.updated_at = now
            if not model.user_id:
                model.user_id = admin.id

        await db.commit()

        await AccessGrants.grant_access(
            resource_type="model",
            resource_id=MODEL_ID,
            principal_type="user",
            principal_id="*",
            permission="read",
            db=db,
        )

    print("PASS basic_autorouter policy reconciled: active, web_search default, public read")


asyncio.run(main())
"""


def main() -> int:
    """Run policy reconciliation inside the running Open WebUI container."""
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
