"""
yflow.agents — step type executors (CLI/HTTP wrappers).

Each module exposes a `run(step, session) -> str` function that:
- takes a step dict + WorkflowSession
- executes the agent via CLI / HTTP / subprocess
- returns the output string
- is provider-agnostic (e.g., uses stdlib only, not provider SDKs)
"""

from yflow.agents.minimax import run as run_minimax

__all__ = ["run_minimax"]
