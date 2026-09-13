Feature: Stack2 web capabilities
  Stack2 owns local web-search and extraction capabilities and the internal services
  required to provide them. Consumers discover these capabilities through manifests;
  Stack2 remains optional for stacks that can operate without web access.

  @STACK2-WEB-001
  Scenario: Local web search and extraction are available to consumers
    Given Stack0 networking is available
    And Stack2 is prepared and its required containers reach READY
    When a prepared consumer requests the declared web capabilities
    Then SearXNG provides web.search over redlocal
    And Firecrawl provides web.extract over redlocal
    And supporting Redis, RabbitMQ, Playwright and database services remain internal implementation dependencies
    And no consumer needs a direct host port to use the capabilities
    And a consumer that can operate without Stack2 does not silently fall back to an unrelated cloud web provider when Stack2 is absent
