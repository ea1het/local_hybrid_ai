import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DR_PATH = ROOT / "dr.py"
SPEC = importlib.util.spec_from_file_location("dr_planner", DR_PATH)
dr_planner = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = dr_planner
SPEC.loader.exec_module(dr_planner)


class DisasterRecoveryPlannerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifests = dr_planner.load_manifests()

    def test_all_resolves_every_stack_in_dependency_order(self):
        self.assertEqual(dr_planner.resolve_plan(["all"]), [0, 1, 2, 3, 4, 5, 6])

    def test_stack3_includes_stack0_dependency(self):
        self.assertEqual(dr_planner.resolve_plan(["3"]), [0, 3])

    def test_stack6_includes_only_required_dependency_closure(self):
        self.assertEqual(dr_planner.resolve_plan(["6"]), [0, 3, 6])

    def test_full_plan_has_expected_dispositions(self):
        entries = dr_planner.build_plan_entries(
            dr_planner.resolve_plan(["all"]),
            self.manifests,
        )
        actual = {(entry.stack_id, entry.resource_id): entry.disposition for entry in entries}
        expected = {
            (0, "platform-pki"): "BACKUP",
            (1, None): "RECONSTRUCT",
            (2, None): "RECONSTRUCT",
            (3, "litellm-database"): "BACKUP",
            (3, "litellm-salt"): "REQUIRE",
            (4, "gitea-state"): "BACKUP",
            (5, None): "RECONSTRUCT",
            (6, "hermes-knowledge"): "EXTERNAL",
        }
        self.assertEqual(actual, expected)

    def test_restore_phases_are_exposed_without_workflow_invention(self):
        entries = dr_planner.build_plan_entries([0, 3, 4], self.manifests)
        phases = {entry.resource_id: entry.restore_phase for entry in entries}
        self.assertEqual(phases["platform-pki"], "pre-prepare")
        self.assertEqual(phases["litellm-database"], "post-prepare-pre-deploy")
        self.assertEqual(phases["litellm-salt"], None)
        self.assertEqual(phases["gitea-state"], "post-prepare-pre-deploy")

    def test_planner_does_not_expose_strategy_config_or_secret_keys(self):
        entries = dr_planner.build_plan_entries([3], self.manifests)
        payloads = [entry.as_dict() for entry in entries]
        serialized = repr(payloads)
        self.assertNotIn("LITELLM_SALT_KEY", serialized)
        self.assertNotIn("database_env", serialized)
        self.assertNotIn("user_env", serialized)

    def test_target_graph_is_supported(self):
        self.assertEqual(dr_planner.resolve_plan(["6"], target=True), [0, 3, 6])

    def test_externalized_resource_is_not_classified_as_backup(self):
        entries = dr_planner.build_plan_entries([6], self.manifests)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].disposition, "EXTERNAL")
        self.assertEqual(entries[0].strategy, "git")

    def test_backup_plan_contains_only_real_artifacts(self):
        entries = dr_planner.build_plan_entries(
            dr_planner.resolve_plan(["all"]),
            self.manifests,
        )
        artifacts, prerequisites = dr_planner.build_backup_plan(entries)
        actual = {(item.stack_id, item.resource_id, item.relative_path) for item in artifacts}
        expected = {
            (0, "platform-pki", "artifacts/stack0/platform-pki.tar"),
            (3, "litellm-database", "artifacts/stack3/litellm-database.dump"),
            (4, "gitea-state", "artifacts/stack4/gitea-state.zip"),
        }
        self.assertEqual(actual, expected)
        self.assertEqual(len(prerequisites), 2)

    def test_backup_plan_classifies_required_and_external_prerequisites(self):
        entries = dr_planner.build_plan_entries(
            dr_planner.resolve_plan(["all"]),
            self.manifests,
        )
        _, prerequisites = dr_planner.build_backup_plan(entries)
        actual = {(item.stack_id, item.resource_id): item.kind for item in prerequisites}
        self.assertEqual(
            actual,
            {
                (3, "litellm-salt"): "REQUIRE",
                (6, "hermes-knowledge"): "EXTERNAL",
            },
        )

    def test_backup_plan_payload_is_metadata_only(self):
        entries = dr_planner.build_plan_entries([0, 3, 4, 6], self.manifests)
        artifacts, prerequisites = dr_planner.build_backup_plan(entries)
        payload = dr_planner.backup_plan_payload(
            ["all"],
            [0, 3, 4, 6],
            artifacts,
            prerequisites,
            source_commit="a" * 40,
        )
        serialized = repr(payload)
        self.assertEqual(payload["kind"], "local-hybrid-ai-backup-plan")
        self.assertFalse(payload["changes_made"])
        self.assertNotIn("LITELLM_SALT_KEY", serialized)
        self.assertEqual(payload["layout"]["checksums"], "checksums.sha256")
        for artifact in payload["artifacts"]:
            self.assertNotIn("sha256", artifact)
            self.assertNotIn("size_bytes", artifact)

    def test_completed_backup_schema_is_distinct_from_dry_run_plan(self):
        schema_path = ROOT / "backup-set.schema.json"
        self.assertTrue(schema_path.is_file())
        schema_text = schema_path.read_text(encoding="utf-8")
        self.assertIn('"local-hybrid-ai-backup-set"', schema_text)
        self.assertIn('"sha256"', schema_text)
        self.assertIn('"size_bytes"', schema_text)
        self.assertNotIn('"local-hybrid-ai-backup-plan"', schema_text)

    def test_artifact_path_rejects_non_backup_entry(self):
        entries = dr_planner.build_plan_entries([6], self.manifests)
        with self.assertRaises(dr_planner.RecoveryError):
            dr_planner.artifact_relative_path(entries[0])


if __name__ == "__main__":
    unittest.main()
