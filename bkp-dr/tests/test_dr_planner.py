import importlib.util
import subprocess
import sys
import tempfile
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
        self.assertEqual(dr_planner.resolve_plan(["all"]), [0, 1, 2, 3, 4, 5, 6, 7])

    def test_stack3_includes_stack0_dependency(self):
        self.assertEqual(dr_planner.resolve_plan(["3"]), [0, 3])

    def test_stack6_includes_only_required_dependency_closure(self):
        self.assertEqual(dr_planner.resolve_plan(["6"]), [0, 3, 6])

    def test_stack7_includes_stack0_and_stack3_dependency_closure(self):
        self.assertEqual(dr_planner.resolve_plan(["7"]), [0, 3, 7])

    def test_full_plan_has_expected_dispositions(self):
        entries = dr_planner.build_plan_entries(dr_planner.resolve_plan(["all"]), self.manifests)
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
            (7, "open-webui-data"): "BACKUP",
            (7, "open-webui-secret-key"): "REQUIRE",
        }
        self.assertEqual(actual, expected)

    def test_restore_phases_are_exposed_without_workflow_invention(self):
        entries = dr_planner.build_plan_entries([0, 3, 4, 7], self.manifests)
        phases = {entry.resource_id: entry.restore_phase for entry in entries}
        self.assertEqual(phases["platform-pki"], "pre-prepare")
        self.assertEqual(phases["litellm-database"], "post-prepare-pre-deploy")
        self.assertEqual(phases["litellm-salt"], None)
        self.assertEqual(phases["gitea-state"], "post-prepare-pre-deploy")
        self.assertEqual(phases["open-webui-data"], "post-prepare-pre-deploy")
        self.assertEqual(phases["open-webui-secret-key"], None)

    def test_planner_does_not_expose_strategy_config_or_secret_keys(self):
        entries = dr_planner.build_plan_entries([3], self.manifests)
        serialized = repr([entry.as_dict() for entry in entries])
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
        entries = dr_planner.build_plan_entries(dr_planner.resolve_plan(["all"]), self.manifests)
        artifacts, prerequisites = dr_planner.build_backup_plan(entries)
        actual = {(item.stack_id, item.resource_id, item.relative_path) for item in artifacts}
        expected = {
            (0, "platform-pki", "artifacts/stack0/platform-pki.tar"),
            (3, "litellm-database", "artifacts/stack3/litellm-database.dump"),
            (4, "gitea-state", "artifacts/stack4/gitea-state.zip"),
            (7, "open-webui-data", "artifacts/stack7/open-webui-data.tar"),
        }
        self.assertEqual(actual, expected)
        self.assertEqual(len(prerequisites), 3)

    def test_backup_plan_classifies_required_and_external_prerequisites(self):
        entries = dr_planner.build_plan_entries(dr_planner.resolve_plan(["all"]), self.manifests)
        _, prerequisites = dr_planner.build_backup_plan(entries)
        actual = {(item.stack_id, item.resource_id): item.kind for item in prerequisites}
        self.assertEqual(
            actual,
            {
                (3, "litellm-salt"): "REQUIRE",
                (6, "hermes-knowledge"): "EXTERNAL",
                (7, "open-webui-secret-key"): "REQUIRE",
            },
        )

    def test_backup_destination_defaults_to_opt(self):
        path, source = dr_planner.resolve_backup_root(None, environ={})
        self.assertEqual(path, Path("/opt/local-hybrid-ai-backups"))
        self.assertEqual(source, "default")

    def test_backup_destination_environment_overrides_default(self):
        path, source = dr_planner.resolve_backup_root(None, environ={"DR_BACKUP_ROOT": "/srv/dr"})
        self.assertEqual(path, Path("/srv/dr"))
        self.assertEqual(source, "environment")

    def test_backup_destination_cli_overrides_environment(self):
        path, source = dr_planner.resolve_backup_root(
            "/mnt/backup/local-ai", environ={"DR_BACKUP_ROOT": "/srv/dr"}
        )
        self.assertEqual(path, Path("/mnt/backup/local-ai"))
        self.assertEqual(source, "cli")

    def test_backup_destination_rejects_relative_path(self):
        with self.assertRaises(dr_planner.RecoveryError):
            dr_planner.resolve_backup_root("relative/path", environ={})

    def test_backup_destination_rejects_filesystem_root(self):
        with self.assertRaises(dr_planner.RecoveryError):
            dr_planner.resolve_backup_root("/", environ={})

    def test_destination_preflight_is_read_only_for_missing_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "not-created"
            result = dr_planner.preflight_backup_destination(root)
            self.assertFalse(root.exists())
            self.assertEqual(result["status"], "MISSING")

    def test_destination_preflight_accepts_existing_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = dr_planner.preflight_backup_destination(root)
            self.assertEqual(result["status"], "READY")

    def test_destination_preflight_rejects_existing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "backup"
            path.write_text("not-a-directory", encoding="utf-8")
            with self.assertRaises(dr_planner.RecoveryError):
                dr_planner.preflight_backup_destination(path)

    def test_cli_plan_all_json(self):
        cp = subprocess.run(
            [sys.executable, str(DR_PATH), "plan", "all", "--json"],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        self.assertEqual(cp.returncode, 0, cp.stderr)
        payload = __import__("json").loads(cp.stdout)
        self.assertEqual(payload["requested"], ["all"])
        self.assertEqual(payload["resolved_stacks"], [0, 1, 2, 3, 4, 5, 6, 7])


if __name__ == "__main__":
    unittest.main()
