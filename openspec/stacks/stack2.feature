Feature: Stack2 web capabilities

  @STACK2-WEB-001
  Scenario: Local web search and extraction are available to consumers
    When Stack2 is running
    Then SearXNG provides web.search over redlocal
    And Firecrawl provides web.extract over redlocal
