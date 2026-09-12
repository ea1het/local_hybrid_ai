Feature: Stack0 platform foundation

  @STACK0-FOUNDATION-001
  Scenario: Shared platform identity and network exist before applications
    When Stack0 is prepared and deployed
    Then the shared redlocal bridge exists
    And platform PKI is owned by Stack0
    And downstream stacks can use the managed root environment link
