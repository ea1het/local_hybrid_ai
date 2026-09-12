import copy
import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFESTS_PATH = ROOT / "stack0_-_platform" / "manifests.py"
SPEC = importlib.util.spec_from_file_location("manifest_registry", MANIFESTS_PATH)
manifest_registry = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(manifest_registry)


class RecoveryContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = manifest_registry.load_recovery_schema(ROOT)
        cls.manifests = manifest_registry.load_manifests(ROOT)

    def test_all_current_manifests_declare_expected_recovery_mode(self):
        expected = {
            0: "mixed",
            1: "reconstructable",
            2: "reconstructable",
            3: "mixed",
            4: "managed",
            5: "reconstructable",
            6: "reconstructable",
            7: "mixed",
        }
        actual = {
            stack_id: data["recovery"]["contract"]["mode"]
            for stack_id, data in self.manifests.items()
        }
        self.assertEqual(actual, expected)

    def test_current_and_target_graphs_still_validate(self):
        manifest_registry.validate_graph(self.manifests, False)
        manifest_registry.validate_contracts(self.manifests, False)
        manifest_registry.validate_graph(self.manifests, True)
        manifest_registry.validate_contracts(self.manifests, True)

    def test_recovery_schema_enums_are_loaded_from_schema_file(self):
        self.assertEqual(self.schema["version"], 1)
        self.assertEqual(
            self.schema["modes"],
            {"reconstructable", "managed", "mixed"},
        )
        self.assertIn("postgres-custom-dump", self.schema["strategies"])
        self.assertIn("persistent-identity", self.schema["classes"])
        self.assertIn("pre-prepare", self.schema["restore_phases"])

    def test_managed_mode_requires_resources(self):
        data = copy.deepcopy(self.manifests[4])
        data["recovery"].pop("resources")
        with self.assertRaises(SystemExit):
            manifest_registry.validate_recovery(data, self.schema, Path("manifest.json"))

    def test_reconstructable_stack_rejects_local_persistent_resource(self):
        data = copy.deepcopy(self.manifests[6])
        data["recovery"]["resources"][0]["class"] = "persistent-data"
        with self.assertRaises(SystemExit):
            manifest_registry.validate_recovery(data, self.schema, Path("manifest.json"))

    def test_strategy_rejects_wrong_source_type(self):
        data = copy.deepcopy(self.manifests[3])
        data["recovery"]["resources"][0]["config"]["source"]["type"] = "runtime-path"
        with self.assertRaises(SystemExit):
            manifest_registry.validate_recovery(data, self.schema, Path("manifest.json"))

    def test_duplicate_recovery_resource_ids_are_rejected(self):
        data = copy.deepcopy(self.manifests[3])
        duplicate = copy.deepcopy(data["recovery"]["resources"][0])
        data["recovery"]["resources"].append(duplicate)
        with self.assertRaises(SystemExit):
            manifest_registry.validate_recovery(data, self.schema, Path("manifest.json"))

    def test_recovery_contract_rejects_unknown_fields(self):
        data = copy.deepcopy(self.manifests[1])
        data["recovery"]["contract"]["future_magic"] = True
        with self.assertRaises(SystemExit):
            manifest_registry.validate_recovery(data, self.schema, Path("manifest.json"))

    def test_stack7_quiesced_archive_is_valid(self):
        data = copy.deepcopy(self.manifests[7])
        resource = next(r for r in data["recovery"]["resources"] if r["id"] == "open-webui-data")
        self.assertEqual(resource["strategy"], "archive")
        self.assertEqual(resource["config"]["quiesce_container"], "open-webui")
        manifest_registry.validate_recovery(data, self.schema, Path("manifest.json"))

    def test_archive_rejects_empty_quiesce_container(self):
        data = copy.deepcopy(self.manifests[7])
        resource = next(r for r in data["recovery"]["resources"] if r["id"] == "open-webui-data")
        resource["config"]["quiesce_container"] = ""
        with self.assertRaises(SystemExit):
            manifest_registry.validate_recovery(data, self.schema, Path("manifest.json"))


if __name__ == "__main__":
    unittest.main()
