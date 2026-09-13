from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "local-ai"


class ManagementCliContractTests(unittest.TestCase):
    def run_cli(self, *args: str, runtime_root: str | None = None):
        env = os.environ.copy()
        if runtime_root is not None:
            env["LOCAL_AI_RUNTIME_ROOT"] = runtime_root
        return subprocess.run(
            [str(CLI), *args], cwd=ROOT, env=env, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
        )

    def test_cli_boundary_exposes_versioned_json_upgrade_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            cp = self.run_cli("--json", "upgrade", "check", "--offline", runtime_root=tmp)
        self.assertEqual(cp.returncode, 0, cp.stderr)
        payload = json.loads(cp.stdout)
        self.assertEqual(payload["schema_version"], "1")
        self.assertEqual(payload["command"], "upgrade.check")
        self.assertTrue(payload["success"])

    def test_upgrade_check_contains_all_declared_components_and_selected_column(self):
        catalog = json.loads((ROOT / "internal" / "upgrade-components.json").read_text())
        expected = sum(len(stack["components"]) for stack in catalog["stacks"])
        with tempfile.TemporaryDirectory() as tmp:
            cp = self.run_cli("--json", "upgrade", "check", "--offline", runtime_root=tmp)
        payload = json.loads(cp.stdout)
        self.assertEqual(len(payload["components"]), expected)
        self.assertTrue(all("selected" in row for row in payload["components"]))

    def test_human_upgrade_table_uses_numeric_stack_column_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            cp = self.run_cli("upgrade", "check", "--offline", runtime_root=tmp)
        self.assertEqual(cp.returncode, 0, cp.stderr)
        data_lines = [line for line in cp.stdout.splitlines() if line and not line.startswith("STACK") and not line.startswith("-")]
        self.assertTrue(any(line.startswith("7 ") and "open-webui" in line for line in data_lines))
        self.assertFalse(any(line.startswith("stack") for line in data_lines))

    def test_json_upgrade_contract_keeps_stable_stack_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            cp = self.run_cli("--json", "upgrade", "check", "--offline", runtime_root=tmp)
        self.assertEqual(cp.returncode, 0, cp.stderr)
        payload = json.loads(cp.stdout)
        open_webui = next(row for row in payload["components"] if row["component"] == "open-webui")
        self.assertEqual(open_webui["stack"], "stack7")

    def test_stack7_shorthand_select_persists_plan_without_runtime_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            cp = self.run_cli("upgrade", "stack7", "select", "v0.12.0", runtime_root=tmp)
            self.assertEqual(cp.returncode, 0, cp.stderr)
            plan = json.loads((Path(tmp) / "platform" / "upgrade-plan.json").read_text())
        selected = plan["selected"]["stack7/open-webui"]
        self.assertEqual(selected["version"], "v0.12.0")

    def test_multicomponent_stack_requires_component_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            cp = self.run_cli("upgrade", "stack3", "select", "1.100.0", runtime_root=tmp)
        self.assertNotEqual(cp.returncode, 0)
        self.assertIn("multiple components", cp.stderr)

    def test_nonselectable_component_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            cp = self.run_cli("upgrade", "stack1", "select", "3.1-alpine", runtime_root=tmp)
        self.assertNotEqual(cp.returncode, 0)
        self.assertIn("UPGRADE_COMPONENT_NOT_SELECTABLE", cp.stderr)

    def test_upgrade_yes_never_auto_selects_available_versions(self):
        with tempfile.TemporaryDirectory() as tmp:
            cp = self.run_cli("upgrade", "--yes", runtime_root=tmp)
        self.assertNotEqual(cp.returncode, 0)
        self.assertIn("no upgrades are selected", cp.stderr)
        self.assertIn("UPGRADE_NOTHING_SELECTED", cp.stderr)

    def test_stale_plan_fails_before_execution(self):
        with tempfile.TemporaryDirectory() as tmp:
            cp = self.run_cli("upgrade", "stack7", "select", "v0.12.0", runtime_root=tmp)
            self.assertEqual(cp.returncode, 0, cp.stderr)
            plan_path = Path(tmp) / "platform" / "upgrade-plan.json"
            plan = json.loads(plan_path.read_text())
            plan["selected"]["stack7/open-webui"]["current_at_selection"] = "definitely-not-current"
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            cp = self.run_cli("upgrade", "--yes", runtime_root=tmp)
        self.assertNotEqual(cp.returncode, 0)
        self.assertIn("UPGRADE_PLAN_STALE", cp.stderr)

    def test_json_errors_have_stable_error_codes(self):
        with tempfile.TemporaryDirectory() as tmp:
            cp = self.run_cli("--json", "upgrade", "--yes", runtime_root=tmp)
        self.assertNotEqual(cp.returncode, 0)
        payload = json.loads(cp.stdout)
        self.assertEqual(payload["error"]["code"], "UPGRADE_NOTHING_SELECTED")


if __name__ == "__main__":
    unittest.main()
