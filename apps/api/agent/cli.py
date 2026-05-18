"""Interactive terminal CLI for the hospital-price agent.

Usage:
    uv run agent-cli
    HEALTH_API_URL=https://api.example.com uv run agent-cli

History is kept in-memory for the duration of the session — no persistence.
For the persisted server-side conversation use the chat UI; this CLI is for
local development and remote debugging against a deployed API.
"""
from __future__ import annotations

import asyncio
import os
import sys
from typing import Optional

from dotenv import load_dotenv

from .agent import LlmCallRecord, MODEL, run_agent
from .tools import API_BASE_URL


PROMPT = "\033[1;36myou>\033[0m "
ASSIST = "\033[1;32magent>\033[0m"
DIM = "\033[2m"
RESET = "\033[0m"


async def _chat_loop(api_key: str) -> None:
    history: list[dict] = []
    print(f"{DIM}agent-cli — model={MODEL} api={API_BASE_URL}")
    print(f"Type 'quit' or Ctrl-D to exit. History is in-memory only.{RESET}\n")

    while True:
        try:
            line = input(PROMPT).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not line:
            continue
        if line.lower() in ("quit", "exit", ":q"):
            return

        # Stream usage as each Gemini round-trip lands.
        total_tokens = 0
        tool_count = 0

        async def on_llm_call(rec: LlmCallRecord) -> None:
            nonlocal total_tokens, tool_count
            total_tokens += rec.total_tokens
            if rec.tool_results:
                tool_count += len(rec.tool_results)

        try:
            result = await run_agent(
                user_message=line,
                history=history,
                api_key=api_key,
                on_llm_call=on_llm_call,
            )
        except Exception as e:  # noqa: BLE001 — surface anything to the user
            print(f"{DIM}[error: {e}]{RESET}\n")
            continue

        print(f"\n{ASSIST} {result.answer}\n")
        print(f"{DIM}({tool_count} tool calls · {total_tokens} tokens){RESET}\n")

        history.append({"role": "user", "content": line})
        history.append({"role": "model", "content": result.answer})


def main() -> None:
    load_dotenv()
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        sys.stderr.write(
            "error: GOOGLE_API_KEY not set. Add it to your env or a .env file.\n"
        )
        sys.exit(1)
    asyncio.run(_chat_loop(api_key))


if __name__ == "__main__":
    main()
