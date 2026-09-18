# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Keep repository file-license coverage explicit and fail closed."""

import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class LicenseHeaderContractTests(unittest.TestCase):
    """Verify every safely commentable tracked file carries the MPL notice."""

    def test_tracked_files_have_mpl_header_or_documented_exception(self):
        """Delegate classification to the same conservative repository policy."""
        result = subprocess.run(
            [sys.executable, "tools/apply_mpl_headers.py", "--check"],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout)


if __name__ == "__main__":
    unittest.main()
