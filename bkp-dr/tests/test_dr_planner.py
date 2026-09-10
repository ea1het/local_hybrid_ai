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
        self.assertEqual(dr_planner.resolve_plan(["all"]), [0, 1, 2, 3, 4, 5, 6])

    def test_stack3_includes_stack0_dependency(self):
        self.assertEqual(dr_planner.resolve_plan(["3"]), [0, 3])

    def test_stack6_includes_only_required_dependency_closure(self):
        self.assertEqual(dr_planner.resolve_plan(["6"]), [0, 3, 6])

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
        }
        self.assertEqual(actual, expected)
        self.assertEqual(len(prerequisites), 2)

    def test_backup_plan_classifies_required_and_external_prerequisites(self):
        entries = dr_planner.build_plan_entries(dr_planner.resolve_plan(["all"]), self.manifests)
        _, prerequisites = dr_planner.build_backup_plan(entries)
        actual = {(item.stack_id, item.resource_id): item.kind for item in prerequisites}
        self.assertEqual(
            actual,
            {
                (3, "litellm-salt"): "REQUIRE",
                (6, "hermes-knowledge"): "EXTERNAL",
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
            parent = Path(tmp)
            root = parent / "backups" / "nested"
            self.assertFalse(root.exists())
            result = dr_planner.preflight_backup_destination(root, "cli")
            self.assertFalse(root.exists())
            self.assertFalse(result.root_exists)
            self.assertTrue(result.writable_parent)
            self.assertEqual(result.nearest_existing_parent, parent)

    def test_destination_preflight_rejects_existing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "backup-file"
            target.write_text("not a directory", encoding="utf-8")
            with self.assertRaises(dr_planner.RecoveryError):
                dr_planner.preflight_backup_destination(target, "cli")

    def test_dotenv_parser_handles_export_and_quotes_without_evaluation(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            env_path.write_text(
                "# comment\nexport BASE_PATH='/srv/runtime'\nSECRET=do-not-print\nEMPTY=\n",
                encoding="utf-8",
            )
            values = dr_planner.read_dotenv_presence(env_path)
            self.assertEqual(values["BASE_PATH"], "/srv/runtime")
            self.assertEqual(values["SECRET"], "do-not-print")
            self.assertEqual(values["EMPTY"], "")

    def test_runtime_path_expansion_is_limited_to_base_path(self):
        self.assertEqual(
            dr_planner.expand_runtime_path("${BASE_PATH}/service/pki", Path("/srv/runtime")),
            Path("/srv/runtime/service/pki"),
        )
        with self.assertRaises(dr_planner.RecoveryError):
            dr_planner.expand_runtime_path("${HOME}/pki", Path("/srv/runtime"))

    def test_gitea_help_flags_are_parsed_without_help_text_storage(self):
        flags = dr_planner.gitea_help_flags("Usage: gitea dump --file value --tempdir value --skip-repository")
        self.assertEqual(flags, ["--file", "--skip-repository", "--tempdir"])

    def test_runtime_preflight_validates_sources_without_exposing_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "runtime"
            pki = base / "service_-_platform" / "pki"
            pki.mkdir(parents=True)
            (pki / "tls.key").write_text("identity", encoding="utf-8")
            env_path = Path(tmp) / ".env"
            env_path.write_text(
                f"BASE_PATH={base}\nDB_NAME=litellm\nDB_USER=litellm\nSALT=super-secret-value\n",
                encoding="utf-8",
            )
            manifests = {
                0: {
                    "owns": [],
                    "recovery": {"resources": [{
                        "id": "platform-pki", "strategy": "archive",
                        "config": {"source": {"type": "runtime-path", "path": "${BASE_PATH}/service_-_platform/pki"}},
                    }]},
                },
                3: {
                    "owns": ["container:litellm-postgres"],
                    "recovery": {"resources": [
                        {"id": "db", "strategy": "postgres-custom-dump", "config": {"source": {
                            "type": "postgres", "service": "litellm-postgres", "database_env": "DB_NAME", "user_env": "DB_USER"
                        }}},
                        {"id": "salt", "strategy": "external-config", "config": {"source": {"type": "environment", "key": "SALT"}}},
                    ]},
                },
                4: {
                    "owns": ["container:gitea"],
                    "recovery": {"resources": [{
                        "id": "gitea-state", "strategy": "gitea-native-dump",
                        "config": {"source": {"type": "application", "service": "gitea"}},
                    }]},
                },
                6: {
                    "owns": [],
                    "recovery": {"resources": [{
                        "id": "knowledge", "strategy": "git",
                        "config": {"source": {"type": "git"}},
                    }]},
                },
            }

            def fake_runner(cmd):
                if cmd[:2] == ["docker", "inspect"]:
                    return subprocess.CompletedProcess(cmd, 0, "running|healthy\n", "")
                if "pg_isready" in cmd:
                    return subprocess.CompletedProcess(cmd, 0, "accepting connections\n", "")
                if cmd[-1] == "--version":
                    return subprocess.CompletedProcess(cmd, 0, "Gitea version 1.24.6 built with GNU Make\n", "")
                if cmd[-2:] == ["dump", "--help"]:
                    return subprocess.CompletedProcess(cmd, 0, "Options: --file --tempdir --skip-repository\n", "")
                return subprocess.CompletedProcess(cmd, 1, "", "unexpected")

            checks = dr_planner.preflight_runtime_sources(
                manifests,
                [0, 3, 4, 6],
                env_path=env_path,
                runner=fake_runner,
                docker_available=True,
            )
            serialized = repr([check.as_dict() for check in checks])
            self.assertNotIn("super-secret-value", serialized)
            self.assertIn("Gitea version 1.24.6", serialized)
            self.assertIn("--file", serialized)
            self.assertTrue(any(check.check == "postgres-source" for check in checks))
            self.assertTrue(any(check.status == "DECLARED" for check in checks))

    def test_runtime_preflight_rejects_unowned_service(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "runtime"
            base.mkdir()
            env_path = Path(tmp) / ".env"
            env_path.write_text(f"BASE_PATH={base}\nDB_NAME=litellm\n", encoding="utf-8")
            manifests = {
                3: {
                    "owns": [],
                    "recovery": {"resources": [{
                        "id": "db", "strategy": "postgres-custom-dump", "config": {"source": {
                            "type": "postgres", "service": "litellm-postgres", "database_env": "DB_NAME"
                        }}},
                    ]},
                }
            }
            with self.assertRaises(dr_planner.RecoveryError):
                dr_planner.preflight_runtime_sources(
                    manifests, [3], env_path=env_path, docker_available=True
                )

    def test_backup_plan_payload_is_metadata_only(self):
        entries = dr_planner.build_plan_entries([0, 3, 4, 6], self.manifests)
        artifacts, prerequisites = dr_planner.build_backup_plan(entries)
        destination = dr_planner.DestinationPreflight(
            root=Path("/opt/local-hybrid-ai-backups"),
            source="default",
            root_exists=False,
            nearest_existing_parent=Path("/opt"),
            writable_parent=True,
        )
        runtime_checks = [
            dr_planner.RuntimeCheck(None, None, "operational-env", "OK", True, "present and readable")
        ]
        payload = dr_planner.backup_plan_payload(
            ["all"],
            [0, 3, 4, 6],
            artifacts,
            prerequisites,
            source_commit="a" * 40,
            destination=destination,
            runtime_checks=runtime_checks,
        )
        serialized = repr(payload)
        self.assertEqual(payload["kind"], "local-hybrid-ai-backup-plan")
        self.assertFalse(payload["changes_made"])
        self.assertNotIn("LITELLM_SALT_KEY", serialized)
        self.assertEqual(payload["layout"]["checksums"], "checksums.sha256")
        self.assertEqual(payload["destination"]["root"], "/opt/local-hybrid-ai-backups")
        self.assertEqual(payload["destination"]["source"], "default")
        self.assertEqual(payload["destination"]["backup_set_name_pattern"], "backup-YYYYMMDDTHHMMSSZ")
        self.assertEqual(payload["runtime_preflight"][0]["status"], "OK")
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
