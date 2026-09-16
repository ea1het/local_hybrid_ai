"""Stack-owned structured data boundary for ``local-ai``."""
STACK_ID="stack0"
def json_payload(**state):
    """Return stack0 state as JSON-compatible data; never serialize or print."""
    return {"stack":STACK_ID,**state}
