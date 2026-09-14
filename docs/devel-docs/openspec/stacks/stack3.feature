# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

Feature: Stack3 AI gateway
  Stack3 provides one OpenAI-compatible inference boundary for application stacks and
  owns LiteLLM's durable PostgreSQL state. Application credentials are separate from
  the administrative master credential, and operational upgrades remain independent
  from the MCP/inference routing design.

  @STACK3-GATEWAY-001
  Scenario: Applications consume one OpenAI-compatible gateway
    Given Stack0 networking is available
    And Stack3 PostgreSQL and LiteLLM reach READY
    When an authorized application sends an inference request
    Then LiteLLM provides ai.gateway over the internal network
    And the application uses a dedicated least-privilege virtual key rather than the administrative master key
    And gateway durable state is persisted in PostgreSQL
    And that durable database is recoverable through a logical PostgreSQL dump
    And application stacks do not need direct credentials for every underlying model provider
