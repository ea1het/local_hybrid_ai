Feature: Stack4 Git service

  @STACK4-GIT-001
  Scenario: Gitea durable state is recoverable without raw filesystem database backup
    Given Gitea is deployed
    When a DR backup is created
    Then Stack4 uses a controlled native Gitea dump
    And repository integrity can be verified with git fsck
