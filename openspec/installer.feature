Feature: Common installer lifecycle

  @INSTALL-PLAN-001
  Scenario: Planning is read only
    Given valid manifests and lifecycle definitions
    When an operator requests an install plan
    Then dependencies and actions are displayed
    And no runtime state is changed

  @INSTALL-LIFECYCLE-001
  Scenario: A stack converges through the declared lifecycle
    Given a requested stack and its required dependencies
    When the operator installs the stack
    Then PREPARE completes before DEPLOY
    And READY converges before VERIFY
    And a restart-causing reconcile is followed by READY before final verification

  @INSTALL-LOCK-001
  Scenario: Prepared state is not confused with healthy state
    Given a stack has a .lock file
    Then the stack is considered prepared only
    And deployment readiness is determined independently
