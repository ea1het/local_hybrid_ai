Feature: Stack5 Dockhand

  @STACK5-RECONSTRUCT-001
  Scenario: Dockhand is reconstructable
    Given source and protected configuration are available
    When Stack5 is rebuilt
    Then no Dockhand runtime volume is required as a DR artifact
