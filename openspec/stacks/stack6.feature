Feature: Stack6 Hermes agent

  @STACK6-ISOLATION-001
  Scenario: Hermes cannot control Docker directly
    When Hermes is deployed
    Then the Hermes container has no Docker socket
    And command execution uses the isolated sandbox

  @STACK6-MEMORY-001
  Scenario: Portable user memory is externalized through Git
    Given MEMORY.md and USER.md are tracked in the configured repository
    Then DR verifies the repository and branch alignment
    And Hermes runtime databases and sandbox contents remain reconstructable
