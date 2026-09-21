#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0.
"""Private upgrade-component discovery owned by completion."""

from __future__ import annotations
from local_ai_cli.common import manifests


def upgrade_components(stack):
    if not stack.isdigit():
        return []
    manifest = manifests.all_manifests().get(int(stack), {})
    out = []
    for item in manifest.get("components", []):
        if isinstance(item, dict) and isinstance(item.get("id"), str) and isinstance(item.get("upgrade"), dict):
            out.append(item["id"])
    return sorted(out)
