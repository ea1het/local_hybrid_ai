Feature: Disaster recovery

  @DR-BACKUP-001
  Scenario: A global backup publishes one atomic recovery point
    Given deployed stacks declare recovery resources and prerequisites
    And required external prerequisites are valid
    When the operator runs backup all
    Then one immutable backup set is published atomically
    And every declared artifact is covered by the checksum index
    And sensitive metadata contains no secret values

  @DR-RESTORE-001
  Scenario: Recovery uses declared strategies instead of raw runtime copying
    Given a completed recovery point
    When restore planning resolves the platform
    Then reconstructable stacks are rebuilt from source
    And managed data uses its declared recovery adapter
    And externalized data is verified through its declared prerequisite

  @DR-STACK7-001
  Scenario: Open WebUI persistent state can be restored in isolation
    Given a Stack7-aware global recovery point
    When open-webui-data is restored using the DR archive contract
    Then users chats configuration model policy and access grants are present
    And the live Open WebUI runtime is not modified
