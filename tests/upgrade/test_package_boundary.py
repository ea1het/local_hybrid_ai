#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0.
"""Package-boundary tests for the upgrade command package."""
from pathlib import Path
import unittest

class UpgradePackageBoundaryTests(unittest.TestCase):
    def test_package_does_not_import_legacy_upgrade_modules(self):
        root = Path(__file__).resolve().parents[2] / "src" / "local_ai_cli" / "upgrade"
        forbidden = (
            "local_ai_cli._upgrade_legacy",
            "local_ai_cli.upgrade_entry",
            "local_ai_cli.upgrade_registry",
            "from local_ai_cli import upgrade",
            "from local_ai_cli import component_inventory",
        )
        offenders = []
        for path in root.glob("*.py"):
            text = path.read_text(encoding="utf-8")
            for token in forbidden:
                if token in text:
                    offenders.append(f"{path.name}: {token}")
        self.assertEqual([], offenders)

    def test_public_api_is_package_owned(self):
        from local_ai_cli.upgrade import api
        self.assertEqual("local_ai_cli.upgrade.api", api.__name__)
        self.assertTrue(callable(api.build_payload))

    def test_registry_is_package_owned(self):
        from local_ai_cli.upgrade import _registry as registry
        self.assertEqual("local_ai_cli.upgrade._registry", registry.__name__)
        self.assertTrue(callable(registry.parse_reference))
        self.assertTrue(callable(registry.local_digest))
        self.assertTrue(hasattr(registry, "RegistryError"))

    def test_config_root_is_repository_root(self):
        from local_ai_cli.upgrade import config
        expected = Path(__file__).resolve().parents[2]
        self.assertEqual(expected, config.ROOT)

if __name__ == "__main__":
    unittest.main()
