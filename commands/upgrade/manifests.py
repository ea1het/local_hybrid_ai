# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0.
"""Package-private manifest discovery for Upgrade."""
from __future__ import annotations
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MANIFEST_TOOL = ROOT / "stack0_-_platform" / "manifests.py"

class ManifestError(RuntimeError):
    pass

def _manifest_json(*args: str):
    try:
        cp = subprocess.run([sys.executable, str(MANIFEST_TOOL), *args], cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or str(exc)).strip()
        raise ManifestError(f"manifest resolver failed: {detail}") from exc
    try:
        return json.loads(cp.stdout)
    except json.JSONDecodeError as exc:
        raise ManifestError("manifest resolver returned invalid JSON") from exc

def all_manifests() -> dict[int, dict]:
    raw = _manifest_json("list", "--json")
    if not isinstance(raw, list):
        raise ManifestError("manifest list is not an array")
    return {int(item["id"]): item for item in raw}
