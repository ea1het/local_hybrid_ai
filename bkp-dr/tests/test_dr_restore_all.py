import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import dr_restore_all


class RestoreAllPlannerTests(unittest.TestCase):
    def metadata(self):
        return {
            "schema_version": 1,
            "kind": "local-hybrid-ai-backup-set",
            "created_at": "2026-09-11T00:49:27Z",
            "source_commit": "a" * 40,
            "requested": ["all"],
            "resolved_stacks": [0, 1, 3, 4, 6],
            "global_artifacts": [
                {
                    "resource_id": "operational-env",
                    "strategy": "file-copy",
                    "sensitive": True,
                    "restore_phase": "pre-prepare",
                    "relative_path": "artifacts/global/operational.env",
                    "sha256": "b" * 64,
                    "size_bytes": 10,
                }
            ],
            "artifacts": [
                {
                    "stack_id": 0,
                    "resource_id": "platform-pki",
                    "strategy": "archive",
                    "sensitive": True,
                    "restore_phase": "pre-prepare",
                    "relative_path": "artifacts/stack0/platform-pki.tar",
                    "sha256": "c" * 64,
                    "size_bytes": 20,
                },
                {
                    "stack_id": 3,
                    "resource_id": "litellm-database",
                    "strategy": "postgres-custom-dump",
                    "sensitive": True,
                    "restore_phase": "post-prepare-pre-deploy",
                    "relative_path": "artifacts/stack3/litellm-database.dump",
                    "sha256": "d" * 64,
                    "size_bytes": 30,
                },
                {
                    "stack_id": 4,
                    "resource_id": "gitea-state",
                    "strategy": "gitea-native-dump",
                    "sensitive": True,
                    "restore_phase": "post-prepare-pre-deploy",
                    "relative_path": "artifacts/stack4/gitea-state.zip",
                    "sha256": "e" * 64,
                    "size_bytes": 40,
                },
            ],
            "prerequisites": [
                {
                    "stack_id": 3,
                    "resource_id": "litellm-salt",
                    "kind": "REQUIRE",
                    "strategy": "external-config",
                    "sensitive": True,
                },
                {
                    "stack_id": 6,
                    "resource_id": "hermes-knowledge",
                    "kind": "EXTERNAL",
                    "strategy": "git",
                    "sensitive": False,
                },
            ],
        }

    def manifests(self):
        def manifest(sid, directory, resources=None):
            return {
                "id": sid,
                "directory": directory,
                "recovery": {"contract": {"schema_version": 1, "mode": "mixed"}, "resources": resources or []},
            }

        return {
            0: manifest(0, "stack0_-_platform", [{
                "id": "platform-pki", "class": "persistent-identity", "strategy": "archive", "sensitive": True,
                "config": {"source": {"type": "runtime-path", "path": "${BASE_PATH}/service_-_platform/pki"}, "restore": {"phase": "pre-prepare"}},
            }]),
            1: manifest(1, "stack1_-_haproxy_web"),
            3: manifest(3, "stack3_-_litellm", [
                {"id": "litellm-database", "class": "persistent-data", "strategy": "postgres-custom-dump", "sensitive": True,
                 "config": {"source": {"type": "postgres"}, "restore": {"phase": "post-prepare-pre-deploy"}}},
                {"id": "litellm-salt", "class": "persistent-identity", "strategy": "external-config", "sensitive": True,
                 "config": {"source": {"type": "environment", "key": "LITELLM_SALT_KEY"}}},
            ]),
            4: manifest(4, "stack4_-_gitea", [{
                "id": "gitea-state", "class": "persistent-data", "strategy": "gitea-native-dump", "sensitive": True,
                "config": {"source": {"type": "application"}, "restore": {"phase": "post-prepare-pre-deploy"}},
            }]),
            6: manifest(6, "stack6_-_hermes", [{
                "id": "hermes-knowledge", "class": "externalized", "strategy": "git", "sensitive": False,
                "config": {"source": {"type": "git", "repository_env": "GITMEM_REPOSITORY"}},
            }]),
        }

    def lifecycle(self):
        manifests = self.manifests()
        return {"schema_version": 1, "stacks": {
            str(sid): {"directory": manifest["directory"]}
            for sid, manifest in manifests.items()
        }}

    def test_order_places_state_between_prepare_and_deploy(self):
        metadata = self.metadata()
        actions = dr_restore_all.build_restore_actions(metadata, self.manifests(), self.lifecycle())
        phases = [action.phase for action in actions]
        order = {name: index for index, name in enumerate(dr_restore_all.PHASE_ORDER)}
        self.assertEqual(phases, sorted(phases, key=order.__getitem__))
        pg = next(a for a in actions if a.resource_id == "litellm-database")
        gitea = next(a for a in actions if a.resource_id == "gitea-state")
        pki = next(a for a in actions if a.resource_id == "platform-pki")
        memory = next(a for a in actions if a.resource_id == "hermes-knowledge")
        self.assertEqual(pki.phase, "pre-prepare")
        self.assertEqual(pg.phase, "post-prepare-pre-deploy")
        self.assertEqual(gitea.phase, "post-prepare-pre-deploy")
        self.assertEqual(memory.phase, "external")

    def test_manifest_strategy_drift_is_rejected(self):
        manifests = self.manifests()
        manifests[3]["recovery"]["resources"][0]["strategy"] = "archive"
        with self.assertRaises(dr_restore_all.RestoreAllError):
            dr_restore_all.validate_manifest_correspondence(self.metadata(), manifests)

    def test_missing_operational_env_global_artifact_is_rejected(self):
        metadata = self.metadata()
        metadata["global_artifacts"] = []
        with self.assertRaises(dr_restore_all.RestoreAllError):
            dr_restore_all.validate_manifest_correspondence(metadata, self.manifests())

    def test_checksum_index_requires_exact_declared_coverage(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            metadata = self.metadata()
            # Replace synthetic hashes/sizes with real files.
            declared = metadata["global_artifacts"] + metadata["artifacts"]
            lines = []
            for index, artifact in enumerate(declared):
                path = root / artifact["relative_path"]
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(f"payload-{index}".encode())
                digest = dr_restore_all._sha256(path)
                artifact["sha256"] = digest
                artifact["size_bytes"] = path.stat().st_size
                lines.append(f"{digest}  {artifact['relative_path']}\n")
            metadata_path = root / "backup.json"
            metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
            metadata_hash = dr_restore_all._sha256(metadata_path)
            lines.append(f"{metadata_hash}  backup.json\n")
            (root / "checksums.sha256").write_text("".join(lines), encoding="utf-8")
            self.assertEqual(dr_restore_all.verify_checksum_index(root, metadata), len(lines))
            with (root / "checksums.sha256").open("a", encoding="utf-8") as handle:
                handle.write(f"{'f' * 64}  undeclared.bin\n")
            with self.assertRaises(dr_restore_all.RestoreAllError):
                dr_restore_all.verify_checksum_index(root, metadata)

    @mock.patch("dr_restore_all.git_commit_available", return_value=True)
    @mock.patch("dr_restore_all.load_lifecycle")
    @mock.patch("dr_restore_all.dr.load_manifests")
    @mock.patch("dr_restore_all.verify_checksum_index", return_value=5)
    @mock.patch("dr_restore_all.read_completed_backup_set")
    def test_plan_is_read_only_payload(self, read_meta, verify_checksums, load_manifests, load_lifecycle, git_available):
        read_meta.return_value = self.metadata()
        load_manifests.return_value = self.manifests()
        load_lifecycle.return_value = self.lifecycle()
        plan = dr_restore_all.plan_restore_all(Path("/backup/test"))
        self.assertEqual(plan.checksums_verified, 5)
        self.assertFalse(plan.as_dict()["changes_made"])
        self.assertEqual(plan.source_commit, "a" * 40)


if __name__ == "__main__":
    unittest.main()
