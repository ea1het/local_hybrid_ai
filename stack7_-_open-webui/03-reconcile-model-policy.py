#!/usr/bin/env python3
"""Reconcile Stack7-owned Open WebUI policy for basic_autorouter.

Run after the first Open WebUI administrator exists. The script is idempotent,
uses Open WebUI's own ORM/data layer inside the pinned container, never touches
LiteLLM, and never writes SQLite directly.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap

CONTAINER = "open-webui"
MODEL_ID = "basic_autorouter"

INNER = r'''
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
    async with get_async_db_context() as db:
        admin_result = await db.execute(
            select(User).where(User.role == "admin").order_by(User.created_at.asc())
        )
        admin = admin_result.scalars().first()
        if admin is None:
            raise RuntimeError(
                "No Open WebUI admin exists yet. Create the first admin account, then rerun this reconciler."
            )

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
