"""Stack-owned structured data boundary for ``local-ai``."""
STACK_ID="stack6"
def json_payload(**state):
    """Return stack6 state as JSON-compatible data; never serialize or print."""
    return {"stack":STACK_ID,**state}
