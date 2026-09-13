Feature: Stack6 Hermes agent
  Stack6 runs the Hermes agent while preserving a strict privilege boundary. Model
  access goes through LiteLLM, arbitrary commands go through an isolated sandbox and
  only Git-backed MEMORY.md/USER.md are treated as durable user memory for recovery.

  Rule: Agent execution does not inherit host container control

    @STACK6-ISOLATION-001
    Scenario: Hermes cannot control Docker directly
      Given Stack6 is prepared with Hermes and its isolated sandbox
      When Hermes is deployed
      Then the Hermes container has no Docker socket
      And arbitrary command execution uses the isolated SSH sandbox
      And sandbox ownership is distinct from Hermes application state
      And an unavailable optional local execution capability fails closed
      And the agent cannot gain host Docker authority merely through a platform-management integration

  Rule: Durable user memory is portable and externalized

    @STACK6-MEMORY-001
    Scenario: Portable user memory is externalized through Git
      Given MEMORY.md and USER.md are tracked in the configured repository and branch
      And Git synchronization credentials are supplied as an external operator prerequisite
      When Stack6 adopts the memory working tree
      Then Hermes mounts that working tree as its durable memory path
      And DR verifies repository integrity and branch/remote alignment
      And the Git provider is not assumed to be Stack4 unless the installation configured it that way
      And Hermes sessions, local databases, caches, packages, logs, SOUL.md and sandbox contents remain reconstructable
      And a clean recovery requires re-provisioning the external memory-sync SSH material rather than recovering disposable runtime directories
