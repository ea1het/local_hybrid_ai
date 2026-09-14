# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

# Purpose: define how stack-owned component semantics are discovered and how
# structural source changes are surfaced without mutating runtime services.
Feature: Manifest-owned component inventory
  Stack manifests are the semantic source of component topology. The management
  CLI derives its current component view from those manifests and validates the
  binding to stack-owned containers and Compose services.

  @CLI-INVENTORY-001
  Scenario: Every owned container has explicit component semantics
    Given a stack manifest owns one or more container resources
    When the component inventory is compiled
    Then every owned container is represented by exactly one component
    And every component declares a supported management type
    And every declared Compose service exists in the owning stack Compose file
    And a missing, duplicate or stale binding fails closed

  @CLI-INVENTORY-002
  Scenario: Upgrade inventory is derived from current manifests
    Given stack manifests declare component upgrade metadata
    When the operator runs "./local-ai upgrade"
    Then the CLI compiles the current manifests rather than reading a separate static component catalog
    And versioned and explicitly upgrade-visible local components are represented
    And helper components without upgrade metadata remain outside normal version maintenance
    And a source topology change is visible without requiring a prior rescan

  @CLI-INVENTORY-003
  Scenario: Rescan reports structural source changes without deploying them
    Given a previous component inventory snapshot may exist
    When the operator runs "./local-ai inventory rescan"
    Then current manifests and Compose bindings are validated
    And a source fingerprint is calculated
    And added, removed and changed component identities are reported
    And the derived snapshot may be refreshed
    But no stack is prepared, deployed, recreated, removed or upgraded
    And operational .env is not changed
    And registry discovery is not required
    And a removed component is not interpreted as consent to delete its old runtime resource
