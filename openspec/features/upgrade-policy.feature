Feature: Installation-owned upgrade compatibility policy

  @CLI-POLICY-001
  Scenario: Effective policy combines project default and installation override
    Given the component catalog declares a default upgrade policy
    When no installation override exists
    Then the effective policy is the catalog default
    When the operator sets an installation override
    Then the effective policy is the local override

  @CLI-POLICY-002
  Scenario: Minor-series only permits newer releases in the same major and minor series
    Given a component uses minor-series policy
    When the operator selects a target version
    Then the target must be strictly newer than the installed version
    And its major and minor version numbers must match the installed version

  @CLI-POLICY-003
  Scenario: Major-series only permits newer releases in the same major series
    Given a component uses major-series policy
    When the operator selects a target version
    Then the target must be strictly newer than the installed version
    And its major version number must match the installed version

  @CLI-POLICY-004
  Scenario: Manual policy uses an explicitly named target without series inference
    Given a component uses manual policy
    When the operator explicitly selects an existing target
    Then local-ai does not infer a minor-series or major-series boundary
    And a comparable semantic version may not be a downgrade

  @CLI-POLICY-005
  Scenario: Clear removes only the installation override
    Given a component has an installation policy override
    When the operator runs "./local-ai upgrade policy <stack> <component> clear"
    Then the local override is removed
    And the effective policy returns to the catalog default
    And no upgrade selection is cleared

  @CLI-POLICY-006
  Scenario: Restricting policy preserves but invalidates an incompatible selection
    Given an upgrade target was selected under the effective policy
    When the operator changes the policy so the selected target is no longer permitted
    Then the selected target remains in the local upgrade plan
    And policy status reports the selection as invalid
    And "./local-ai upgrade --yes" rejects it with UPGRADE_TARGET_UNSUPPORTED

  @CLI-POLICY-007
  Scenario: Compatibility policy and executor capability are independent controls
    Given a registry target satisfies the effective compatibility policy
    But the component is not selectable
    When the operator attempts to select it
    Then selection fails with UPGRADE_COMPONENT_NOT_SELECTABLE

  @CLI-POLICY-008
  Scenario: The executor revalidates effective policy before mutation
    Given a target was selected previously
    And installation policy may have changed since selection
    When the operator runs "./local-ai upgrade --yes"
    Then the executor revalidates the current effective policy
    And an unsupported target fails before target preflight, recovery or desired-state mutation
