Feature: Single management CLI anticorruption boundary

  @CLI-BOUNDARY-001
  Scenario: External automation inspects upgrades without internal coupling
    When the consumer runs "./local-ai --json upgrade check"
    Then it receives a versioned machine-readable response
    And it does not need the path of any Python or shell implementation

  @CLI-UPGRADE-001
  Scenario: Upgrade check shows the complete component inventory
    When the operator runs "./local-ai upgrade check"
    Then every declared component of every stack is represented
    And the table contains Current, Available and Selected columns

  @CLI-UPGRADE-002
  Scenario: Selecting a version changes only the local upgrade plan
    When the operator selects a version for a component
    Then the selection is persisted in the installation runtime area
    And no container is changed

  @CLI-UPGRADE-003
  Scenario: Yes never means upgrade everything
    Given one or more component versions are selected
    When the operator runs "./local-ai upgrade --yes"
    Then only selected components may be considered by the executor
    And unselected available versions are never implicitly selected

  @CLI-UPGRADE-004
  Scenario: A stale selection is rejected before mutation
    Given a component was selected from a recorded current version
    And the actual runtime version changed afterwards
    When the operator runs "./local-ai upgrade --yes"
    Then execution fails with UPGRADE_PLAN_STALE
    And no recovery point or deployment is started

  @CLI-UPGRADE-005
  Scenario: A selected stateful component upgrades through the guarded lifecycle
    Given a selected component declares a safe targeted deploy method
    When the operator confirms with "./local-ai upgrade --yes"
    Then a recovery point is created first when the component requires one
    And only explicitly selected version keys are changed
    And the selected component reaches READY and its stack VERIFY passes
    And prepared dependent consumers are reverified
    And the selection is cleared only after success
