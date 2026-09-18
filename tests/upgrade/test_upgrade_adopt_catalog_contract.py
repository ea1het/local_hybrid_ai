# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0.
"""Regression contracts for the runtime version-authority catalog."""
from __future__ import annotations

import unittest

from local_ai_cli import upgrade_adopt
from local_ai_cli.common import component_inventory


class UpgradeAdoptCatalogContractTests(unittest.TestCase):
    def test_every_versioned_catalog_component_has_adoption_authority(self):
        components = component_inventory.compile_components()
        versioned = {
            f"{component['stack']}/{component['id']}"
            for component in components
            if component["management"]["type"] == "versioned"
        }
        self.assertEqual(set(upgrade_adopt.AUTHORITIES), versioned)

    def test_non_versioned_components_do_not_get_image_authority(self):
        components = component_inventory.compile_components()
        non_versioned = {
            f"{component['stack']}/{component['id']}"
            for component in components
            if component["management"]["type"] != "versioned"
        }
        self.assertTrue({"stack0/platform-foundation", "stack4/runner", "stack6/sandbox"} <= non_versioned)
        self.assertTrue(set(upgrade_adopt.AUTHORITIES).isdisjoint(non_versioned))

    def test_conflict_validation_is_pure(self):
        current = {"HAPROXY_VERSION": "3.0.25"}
        expected = {"HAPROXY_VERSION": "3.0.26"}
        with self.assertRaises(upgrade_adopt.AdoptionError) as raised:
            upgrade_adopt._validate_conflicts(current, expected)
        self.assertEqual(raised.exception.code, "UPGRADE_ADOPTION_CONFLICT")
        self.assertEqual(current, {"HAPROXY_VERSION": "3.0.25"})
        self.assertEqual(expected, {"HAPROXY_VERSION": "3.0.26"})


if __name__ == "__main__":
    unittest.main()
