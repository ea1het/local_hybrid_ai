# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Stack-owned structured data boundary for ``local-ai``."""
STACK_ID="stack7"
def json_payload(**state):
    """Return stack7 state as JSON-compatible data; never serialize or print."""
    return {"stack":STACK_ID,**state}
