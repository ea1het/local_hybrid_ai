Feature: Stack5 Dockhand
  Dockhand is treated as reconstructable platform tooling. Its runtime existence does
  not automatically make its local volume a durable recovery artifact; source,
  protected configuration and the selected image version are sufficient to rebuild it.

  @STACK5-RECONSTRUCT-001
  Scenario: Dockhand is reconstructable
    Given the recorded project source and protected operational configuration are available
    And the installation can obtain the configured Dockhand container artifact
    When Stack5 is rebuilt through the common lifecycle
    Then no Dockhand runtime volume is required as a DR artifact
    And Stack5 can be prepared and deployed from declared configuration
    And disposable runtime state is not promoted to backup truth merely because a Docker volume exists
    And the project default upgrade compatibility policy remains independent from whether an executor is currently selectable
