"""CLI entrypoint (Phase 0 hello-agent).

    uv run python -m src.entrypoints.cli "your message"

Builds the minimal graph with a SQLite checkpointer, invokes it once, and prints
the model reply plus the call cost. This is the Phase 0 exit proof: the graph
lifecycle runs against a real OpenRouter call.
"""

from __future__ import annotations

import logging
import sys

from src.agent.checkpoint import get_checkpointer
from src.agent.graph import build_graph
from src.config.settings import get_settings


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print('usage: python -m src.entrypoints.cli "your message"', file=sys.stderr)
        return 2

    message = " ".join(args)

    settings = get_settings()
    if not settings.openrouter_api_key:
        print(
            "OPENROUTER_API_KEY is not set. Copy config.example.env to .env and "
            "fill it in.",
            file=sys.stderr,
        )
        return 1

    checkpointer = get_checkpointer()
    graph = build_graph(checkpointer)
    result = graph.invoke(
        {"user_input": message, "llm_response": "", "cost_usd": None},
        config={"configurable": {"thread_id": "cli"}},
    )

    print(result["llm_response"])
    cost = result.get("cost_usd")
    cost_str = f"${cost:.6f}" if cost is not None else "unknown"
    print(f"\n[cost: {cost_str}]", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
