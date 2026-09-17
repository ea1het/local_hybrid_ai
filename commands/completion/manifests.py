# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0.
"""Private manifest discovery owned by completion."""
from __future__ import annotations
import json,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];MANIFEST_TOOL=ROOT/"stack0_-_platform"/"manifests.py"
class CompletionManifestError(RuntimeError):pass
def all_manifests():
 try:cp=subprocess.run([sys.executable,str(MANIFEST_TOOL),"list","--json"],cwd=ROOT,text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=True)
 except subprocess.CalledProcessError as exc:raise CompletionManifestError((exc.stderr or exc.stdout or str(exc)).strip()) from exc
 try:raw=json.loads(cp.stdout)
 except json.JSONDecodeError as exc:raise CompletionManifestError("manifest resolver returned invalid JSON") from exc
 if not isinstance(raw,list):raise CompletionManifestError("manifest list is not an array")
 return {int(item["id"]):item for item in raw}
