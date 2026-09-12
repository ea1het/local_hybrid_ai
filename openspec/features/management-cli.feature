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
