# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Render the customizable banner shown by the root local-ai command."""

import sys

sys.dont_write_bytecode = True

HEADER_TEMPLATE = r"""
# ##           ##
# #          #  #
# ##    ##    ###   #          #  #
# #  #  #     #  #   #    ####  ###
# #  #  #     # ##   #          #  #
#### ##    ##    # #  ###         #  #

Version: {version}

"""


def render_header(version: str) -> str:
    """Insert the current version into the operator-editable banner."""
    return HEADER_TEMPLATE.replace("{version}", version)
