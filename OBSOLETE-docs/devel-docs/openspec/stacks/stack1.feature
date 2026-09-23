# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

Feature: Stack1 ingress
  Stack1 is the user-facing HTTP ingress boundary. Applications join the shared
  internal network and are published only when Stack1 is explicitly configured to
  route them; backend services do not gain host ports merely because they are reachable.

  @STACK1-INGRESS-001
  Scenario: User-facing HTTP enters through HAProxy
    Given an application is configured for ingress
    And the application is reachable on redlocal by its internal service identity
    When a user accesses the configured public route
    Then HAProxy reaches the application over redlocal
    And the application does not require a direct host port
    And internal databases or auxiliary services remain unpublished unless their own contract explicitly requires exposure
    And removing an optional application route does not transfer ingress ownership to the application stack
