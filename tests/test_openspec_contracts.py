"""Executable evidence for cross-cutting OpenSpec behavioural contracts.

This module ties stable Gherkin tags to concrete repository invariants: required
dependencies, readiness after restart reconciliation, declared DR artifacts,
Stack6 Docker isolation, Stack7 explicit access/default web behaviour, and global
traceability completeness. It intentionally tests durable behaviour rather than
mirroring every implementation detail.
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OPENSPEC = ROOT / "docs" / "devel-docs" / "openspec"


def load_manifests() -> dict[int, dict]:
    manifests: dict[int, dict] = {}
    for path in sorted(ROOT.glob("stack*_*/manifest.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        manifests[data["id"]] = data
    return manifests


class OpenSpecContractTests(unittest.TestCase):
    """Near-direct executable evidence for selected Gherkin contracts."""

    def test_PLATFORM_DEP_001_required_dependencies_are_declared(self):
        manifests = load_manifests()
        self.assertEqual(manifests[6]["requires"], [0, 3])
        self.assertEqual(manifests[7]["requires"], [0, 3])
        for sid, manifest in manifests.items():
            for dependency in manifest.get("requires", []):
                self.assertIn(dependency, manifests, f"stack{sid} requires unknown stack{dependency}")

    def test_INSTALL_LIFECYCLE_001_restart_reconcile_waits_ready(self):
        lifecycle = json.loads((ROOT / "commands" / "install-lifecycle.json").read_text(encoding="utf-8"))
        reconcile = lifecycle["stacks"]["6"]["reconcile"]
        self.assertEqual(reconcile[0], ["bash", "./06-reconcile-capabilities.sh", "--restart"])
        self.assertEqual(reconcile[1], ["bash", "./07-wait-ready.sh"])

    def test_DR_BACKUP_001_stack7_artifact_is_declared(self):
        manifest = load_manifests()[7]
        resource = next(r for r in manifest["recovery"]["resources"] if r["id"] == "open-webui-data")
        self.assertEqual(resource["strategy"], "archive")
        self.assertTrue(resource["sensitive"])
        self.assertEqual(resource["config"]["quiesce_container"], "open-webui")

    def test_DR_STACK7_001_restore_contract_preserves_data_and_identity(self):
        manifest = load_manifests()[7]
        resources = {r["id"]: r for r in manifest["recovery"]["resources"]}
        self.assertEqual(resources["open-webui-data"]["config"]["restore"]["phase"], "post-prepare-pre-deploy")
        self.assertEqual(resources["open-webui-secret-key"]["strategy"], "external-config")

    def test_STACK6_ISOLATION_001_hermes_has_no_docker_socket(self):
        compose = (ROOT / "stack6_-_hermes" / "docker-compose.yml").read_text(encoding="utf-8")
        self.assertNotIn("/var/run/docker.sock", compose)
        self.assertIn("hermes-sandbox", compose)

    def test_STACK7_POLICY_001_access_is_explicit_not_bypassed(self):
        compose = (ROOT / "stack7_-_open-webui" / "docker-compose.yml").read_text(encoding="utf-8")
        reconciler = (ROOT / "stack7_-_open-webui" / "03-reconcile-model-policy.py").read_text(encoding="utf-8")
        self.assertNotIn("BYPASS_MODEL_ACCESS_CONTROL", compose)
        self.assertIn('principal_id="*"', reconciler)
        self.assertIn('permission="read"', reconciler)
        self.assertIn("basic_autorouter", reconciler)

    def test_STACK7_WEB_001_web_search_is_default_interface_behaviour(self):
        compose = (ROOT / "stack7_-_open-webui" / "docker-compose.yml").read_text(encoding="utf-8")
        self.assertIn('DEFAULT_MODELS: "basic_autorouter"', compose)
        self.assertIn('ENABLE_EVALUATION_ARENA_MODELS: "false"', compose)
        self.assertIn('DEFAULT_INTERFACE_SETTINGS: \'{"webSearch":"always"}\'', compose)

    def test_all_gherkin_tags_have_traceability_entries(self):
        trace = (OPENSPEC / "traceability.md").read_text(encoding="utf-8")
        tags = set()
        for feature in OPENSPEC.rglob("*.feature"):
            tags.update(re.findall(r"@([A-Z0-9-]+)", feature.read_text(encoding="utf-8")))
        missing = sorted(tag for tag in tags if f"`{tag}`" not in trace)
        self.assertEqual(missing, [], f"OpenSpec tags without traceability: {missing}")

    def test_openspec_is_centralized_under_docs(self):
        self.assertTrue(OPENSPEC.is_dir())
        self.assertFalse((ROOT / "openspec").exists())


if __name__ == "__main__":
    unittest.main()
