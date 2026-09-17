# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0.
from __future__ import annotations

import inspect
import unittest
from pathlib import Path

import commands.restore.api as api


class RestorePackageBoundaryTests(unittest.TestCase):
    def test_public_api_is_package_owned(self):
        self.assertTrue(Path(inspect.getfile(api)).resolve().parent.name == "restore")

    def test_public_api_does_not_import_recovery(self):
        source = Path(inspect.getfile(api)).read_text(encoding="utf-8")
        self.assertNotIn("commands.recovery", source)

    def test_restore_implementation_is_package_owned(self):
        root = Path(inspect.getfile(api)).resolve().parent
        for name in ("dr.py", "dr_restore_all.py", "dr_restore_drill.py", "dr_restore_live_service.py", "dr_restore_resume.py"):
            self.assertTrue((root / name).is_file(), name)

    def test_public_surface_is_complete(self):
        for name in ("plan_payload", "drill_payload", "check_clean_target_payload", "apply_payload", "resume_payload", "cli_text"):
            self.assertTrue(callable(getattr(api, name, None)), name)


if __name__ == "__main__":
    unittest.main()
