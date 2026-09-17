# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0.
from pathlib import Path
import unittest

class UpgradePackageBoundaryTests(unittest.TestCase):
    def test_package_does_not_import_legacy_upgrade_modules(self):
        root = Path(__file__).resolve().parents[1]
        forbidden = (
            "commands._upgrade_legacy",
            "commands.upgrade_entry",
            "from commands import upgrade",
            "from commands import component_inventory",
        )
        offenders = []
        for path in root.glob("*.py"):
            text = path.read_text(encoding="utf-8")
            for token in forbidden:
                if token in text:
                    offenders.append(f"{path.name}: {token}")
        self.assertEqual([], offenders)

    def test_public_api_is_package_owned(self):
        from commands.upgrade import api
        self.assertEqual("commands.upgrade.api", api.__name__)
        self.assertTrue(callable(api.build_payload))

    def test_core_root_is_repository_root(self):
        from commands.upgrade import core
        expected = Path(__file__).resolve().parents[3]
        self.assertEqual(expected, core.ROOT)

if __name__ == "__main__":
    unittest.main()
