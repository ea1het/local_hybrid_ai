Feature: Stack7 Open WebUI
  Stack7 provides the user-facing chat UI on top of Stack3 while preserving explicit
  model authorization and persistent application state. The reconciler owns the
  curated model/access policy; ordinary users do not inherit every upstream model.

  Rule: Model exposure is explicit and idempotently reconciled

    @STACK7-POLICY-001
    Scenario: A regular user receives the curated default model
      Given the first administrator exists
      And Open WebUI persistent state is available
      When Stack7 model policy is reconciled
      Then basic_autorouter is active
      And basic_autorouter has exactly the intended public read access
      And Arena is disabled
      And model-access bypass remains disabled
      And a regular user sees only the curated public model
      And running reconciliation again does not duplicate grants or create another model record

  Rule: Web search is an explicit optional capability attached to the curated model

    @STACK7-WEB-001
    Scenario: New chats start with web search enabled
      Given Stack7 persistent configuration is initialized
      And Stack2 web capabilities are available to the installation
      Then basic_autorouter is the default model
      And the model advertises the web_search capability
      And web search is active by default for new chats
      And the user can disable it per chat
      And Stack7 reaches SearXNG and Firecrawl through internal service networking rather than direct host ports
      And Stack7 remains dependent on Stack3 even when Stack2 is absent because web capability is optional rather than its inference backend
