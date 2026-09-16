"""Stack-owned structured data boundary for ``local-ai``."""
STACK_ID="stack1"
def json_payload(**state):
    """Return stack1 state as JSON-compatible data; never serialize or print."""
    return {"stack":STACK_ID,**state}
