# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0.
"""Regression contracts for the complete runtime version-authority catalog."""
from __future__ import annotations

import unittest

from commands import upgrade, upgrade_adopt


class UpgradeAdoptCatalogContractTests(unittest.TestCase):
    def test_every_catalog_component_has_adoption_authority(self):
        catalog = {upgrade.key(component) for component in upgrade.load_catalog()}
        self.assertEqual(set(upgrade_adopt.AUTHORITIES), catalog)

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
