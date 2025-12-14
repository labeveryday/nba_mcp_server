"""
Strands Agent example that uses this NBA MCP server via stdio transport.

Prereqs:
  pip install strands-agents

Run:
  # Interactive mode (REPL)
  python examples/strands_nba_agent.py

  # Demo mode (runs a few curated prompts)
  python examples/strands_nba_agent.py --demo

  # One-shot mode
  python examples/strands_nba_agent.py --once "Find LeBron's player_id and show his season stats for 2024-25"
"""

import argparse
import sys

from mcp import stdio_client, StdioServerParameters
from strands import Agent
from strands.tools.mcp import MCPClient


def main() -> int:
    parser = argparse.ArgumentParser(description="Strands + NBA MCP server demo")
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Run a short scripted demo (no interactive loop).",
    )
    parser.add_argument(
        "--once",
        type=str,
        default=None,
        help="Run a single prompt and exit.",
    )
    args, unknown = parser.parse_known_args()

    # Back-compat: if user passes a bare prompt without --once, treat it as one-shot.
    fallback_prompt = " ".join(unknown).strip()
    once_prompt = args.once or (fallback_prompt if fallback_prompt else None)

    # Launch this repo's MCP server as a subprocess using the current Python interpreter.
    mcp_client = MCPClient(
        lambda: stdio_client(
            StdioServerParameters(
                command=sys.executable,
                args=["-u", "-m", "nba_mcp_server"],
            )
        )
    )

    # Python Strands requires explicit lifecycle management for MCP connections.
    with mcp_client:
        tools_resp = mcp_client.list_tools_sync()
        tools = getattr(tools_resp, "tools", tools_resp)
        agent = Agent(
            tools=tools,
            system_prompt=(
                "You are an NBA analyst agent. Use MCP tools to look up IDs first when needed "
                "(resolve_player_id, resolve_team_id, find_game_id). "
                "Prefer calling tools over guessing."
            ),
        )

        if args.demo:
            demo_prompts = [
                "Show me today's NBA games.",
                "Resolve the team_id for the Lakers.",
                "Resolve the player_id for LeBron James.",
                "Find a recent game_id and show the box score.",
                "Get LeBron James' 2024-25 season stats.",
            ]
            for i, prompt in enumerate(demo_prompts, 1):
                print(f"\n=== Demo {i}/{len(demo_prompts)} ===")
                print(f"User: {prompt}\n")
                try:
                    result = agent(prompt)
                    print(result)
                except Exception as e:
                    print(f"[error] {type(e).__name__}: {e}")
            return 0

        if once_prompt:
            result = agent(once_prompt)
            print(result)
            return 0

        # Interactive REPL mode (default)
        print("NBA Strands Agent (interactive). Type 'quit'/'exit' or Ctrl-D to end.")
        try:
            while True:
                try:
                    prompt = input("\nYou> ").strip()
                except EOFError:
                    print("\nGoodbye.")
                    break
                if not prompt:
                    continue
                if prompt.lower() in {"quit", "exit"}:
                    print("Goodbye.")
                    break
                try:
                    result = agent(prompt)
                    print(f"\nAgent> {result}")
                except Exception as e:
                    print(f"\nAgent> [error] {type(e).__name__}: {e}")
        except KeyboardInterrupt:
            print("\nInterrupted. Goodbye.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())


