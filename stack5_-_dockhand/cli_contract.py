"""Stack-owned structured data boundary for ``local-ai``."""
STACK_ID="stack5"
def json_payload(**state):
    """Return stack5 state as JSON-compatible data; never serialize or print."""
    return {"stack":STACK_ID,**state}
