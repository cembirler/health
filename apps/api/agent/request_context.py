"""Per-request user context for the agent loop.

The agent runs as a fire-and-forget background task — by the time it executes,
the original FastAPI Request is gone. Routes that kick off the agent capture
the user-visible bits (client IP, browser timezone) into a dict and stash it
in this contextvar before invoking `run_agent`. Tools that need it read via
`get_request_context()`.

Kept tiny and stringly-typed so tools tolerate missing keys.
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any, Optional


_ctx: ContextVar[Optional[dict]] = ContextVar("_request_ctx", default=None)


def set_request_context(ctx: dict):
    """Set the per-task context. Returns a token for `reset_request_context`."""
    return _ctx.set(ctx)


def reset_request_context(token) -> None:
    _ctx.reset(token)


def get_request_context() -> dict:
    """Return the current context dict (or {} if none was set).

    Tools should read keys defensively — any field may be absent in tests
    or when the calling route didn't supply it.
    """
    v = _ctx.get()
    return v if v is not None else {}


def get_ctx_value(key: str, default: Any = None) -> Any:
    return get_request_context().get(key, default)
