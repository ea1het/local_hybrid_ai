# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

Feature: Stack0 platform foundation
  Stack0 owns platform-wide primitives that must exist before application stacks:
  the shared Docker network, platform runtime directories and PKI/bootstrap identity.
  It must remain application-agnostic so downstream stacks can depend on it without
  importing application policy into the foundation.

  @STACK0-FOUNDATION-001
  Scenario: Shared platform identity and network exist before applications
    Given a clean installation with no application stack prepared
    When Stack0 is prepared and deployed
    Then the shared redlocal bridge exists under Stack0 ownership
    And platform PKI is owned by Stack0
    And platform runtime directories have the expected restrictive ownership and modes
    And downstream stacks can use the managed root environment link
    And Stack0 does not claim application containers or application persistent data
    And later stack installation may depend on these primitives without recreating them independently
