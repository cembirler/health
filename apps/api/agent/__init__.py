"""agent_cli — the hospital-price-transparency agent.

Public surface:
    run_agent            — the function-calling loop (one user turn → final answer)
    AgentResult          — what run_agent returns (just the terminal `answer`)
    LlmCallRecord        — captured per Gemini round-trip (for chat_requests rows)
    UpstreamModelError   — raised when the model endpoint fails after retries
    MaxIterationsReached — raised when the loop hits its iteration cap
    MODEL                — current model id (env-configurable)
    TOOLS                — the tool registry (mutable; populated by tools.py)

The agent talks to the world over HTTP — see `tools.py`. Set `HEALTH_API_URL`
(default `http://127.0.0.1:8000`) to point at a different API instance, e.g.
when running the CLI against a remote deployment.
"""

from .agent import (
    AgentResult,
    LlmCallRecord,
    MaxIterationsReached,
    MODEL,
    UpstreamModelError,
    run_agent,
)
from .tools import TOOLS, Tool

__all__ = [
    "run_agent",
    "AgentResult",
    "LlmCallRecord",
    "MaxIterationsReached",
    "UpstreamModelError",
    "MODEL",
    "TOOLS",
    "Tool",
]
