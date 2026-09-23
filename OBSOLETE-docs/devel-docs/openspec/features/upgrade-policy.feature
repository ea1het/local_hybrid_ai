# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

Feature: Installation-owned upgrade compatibility policy
  Registry availability, compatibility policy, executor capability, selection and
  execution are separate gates. Project defaults provide safe initial behavior;
  an installation may override policy without editing Git or the protected `.env`.

  Rule: Effective policy is the composition of project default and local override

    @CLI-POLICY-001
    Scenario: Effective policy combines project default and installation override
      Given the component catalog declares a default upgrade policy
      And policy overrides are stored in installation-local runtime state
      When no installation override exists
      Then the effective policy is the catalog default
      When the operator sets an installation override through local-ai
      Then the effective policy is the local override
      And the catalog default remains unchanged in Git

  Rule: Series policies define monotonic compatibility boundaries

    @CLI-POLICY-002
    Scenario: Minor-series only permits newer releases in the same major and minor series
      Given a component uses minor-series policy
      When the operator selects a target version
      Then the target must be strictly newer than the installed version
      And its major and minor version numbers must match the installed version
      And a patch downgrade or cross-minor target is rejected

    @CLI-POLICY-003
    Scenario: Major-series only permits newer releases in the same major series
      Given a component uses major-series policy
      When the operator selects a target version
      Then the target must be strictly newer than the installed version
      And its major version number must match the installed version
      And crossing to another major series is rejected without an explicit manual-policy choice

    @CLI-POLICY-004
    Scenario: Manual policy uses an explicitly named target without series inference
      Given a component uses manual policy
      When the operator explicitly selects an existing target
      Then local-ai does not infer a minor-series or major-series boundary
      And the target must still exist in the configured registry/package
      And a comparable semantic version may not be a downgrade
      And manual does not make a non-selectable component executable

  Rule: Policy mutation preserves traceability and does not manufacture selection intent

    @CLI-POLICY-005
    Scenario: Clear removes only the installation override
      Given a component has an installation policy override
      When the operator runs "./local-ai upgrade policy <stack> <component> clear"
      Then the local override is removed
      And the effective policy returns to the catalog default
      And no upgrade selection is cleared
      And no container or desired version is changed

    @CLI-POLICY-006
    Scenario: Restricting policy preserves but invalidates an incompatible selection
      Given an upgrade target was selected under the effective policy
      When the operator changes the policy so the selected target is no longer permitted
      Then the selected target remains in the local upgrade plan
      And policy status reports the selection as invalid
      And "./local-ai upgrade --yes" rejects it with UPGRADE_TARGET_UNSUPPORTED
      And rejection occurs before recovery or desired-state mutation

  Rule: Compatibility authorization and executor capability remain independent

    @CLI-POLICY-007
    Scenario: Compatibility policy and executor capability are independent controls
      Given a registry target satisfies the effective compatibility policy
      But the component is not selectable
      When the operator attempts to select it
      Then selection fails with UPGRADE_COMPONENT_NOT_SELECTABLE
      And changing policy alone cannot enable the component executor

    @CLI-POLICY-008
    Scenario: The executor revalidates effective policy before mutation
      Given a target was selected previously
      And installation policy may have changed since selection
      When the operator runs "./local-ai upgrade --yes"
      Then the executor revalidates the current effective policy
      And it does not trust policy captured at selection time as permanent authorization
      And an unsupported target fails before target-image preflight, recovery or desired-state mutation
