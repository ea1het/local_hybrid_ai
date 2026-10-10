# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Reject callback substitution before any credential exchange can occur."""

import sys

sys.dont_write_bytecode = True

import importlib.util

import pytest

from .verify import ROOT


spec = importlib.util.spec_from_file_location("stack80_callback", ROOT / "google-oauth.py")
oauth = importlib.util.module_from_spec(spec)
spec.loader.exec_module(oauth)


def test_valid_callback():
    assert oauth.callback_code("http://localhost:8765/?state=expected&code=fixture%2Bcode", "expected") == "fixture+code"


@pytest.mark.parametrize("callback", [
    "https://attacker.example/?state=expected&code=fixture",
    "http://localhost:8765/other?state=expected&code=fixture",
    "http://localhost:8765/?state=unexpected&code=fixture",
    "http://localhost:8765/?code=fixture",
    "http://localhost:8765/?state=expected&state=unexpected&code=fixture",
    "http://localhost:8765/?state=expected&code=one&code=two",
    "http://localhost:8765/?state=expected&error=access_denied",
    "http://localhost:8765/?state=expected&code=fixture#fragment",
])
def test_invalid_callback(callback):
    with pytest.raises(RuntimeError):
        oauth.callback_code(callback, "expected")
