#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0.
"""Canonical stack manifest discovery, shared by every command package."""
from __future__ import annotations
import json,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
MANIFEST_TOOL=ROOT/"stack0_-_platform"/"manifests.py"
class ManifestError(RuntimeError):pass
def manifest_json(*args):
 try:cp=subprocess.run([sys.executable,str(MANIFEST_TOOL),*args],cwd=ROOT,text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=True)
 except subprocess.CalledProcessError as exc:raise ManifestError(f"manifest resolver failed: {(exc.stderr or exc.stdout or str(exc)).strip()}") from exc
 try:return json.loads(cp.stdout)
 except json.JSONDecodeError as exc:raise ManifestError("manifest resolver returned invalid JSON") from exc
def all_manifests():
 raw=manifest_json("list","--json")
 if not isinstance(raw,list):raise ManifestError("manifest list is not an array")
 return {int(item["id"]):item for item in raw}
