"""
Live MCP smoke test: starts the NBA MCP server via stdio and calls every tool once.

This is NOT a unit test; it hits real NBA endpoints and may be affected by:
- Network availability
- NBA API outages / rate limits
- No games on a given date

Run:
  python scripts/live_mcp_tool_smoke_test.py

Note:
  This script spawns the server with `python -u -m nba_mcp_server` to avoid stdout buffering issues over pipes.

Optional env tuning (recommended for live testing):
  NBA_MCP_MAX_CONCURRENCY=2
  NBA_MCP_RETRIES=1
  NBA_MCP_HTTP_TIMEOUT_SECONDS=20
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from mcp import stdio_client, StdioServerParameters


@dataclass
class ToolRunResult:
    name: str
    status: str  # "ok" | "skipped" | "error"
    detail: str


def _today_yyyymmdd() -> str:
    return datetime.now().strftime("%Y%m%d")


def _yesterday_yyyymmdd() -> str:
    return (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")


def _extract_text(result: Any) -> str:
    # MCP tool results may be returned as:
    # - dict: {"content":[{"type":"text","text":"..."}]}
    # - pydantic model with `.content` (e.g., CallToolResult) where content items are TextContent models
    # - other shapes; fall back to str(...)
    try:
        # Object-style (CallToolResult)
        content_obj = getattr(result, "content", None)
        if isinstance(content_obj, list) and content_obj:
            first = content_obj[0]
            text = getattr(first, "text", None)
            if isinstance(text, str):
                return text
            if isinstance(first, dict) and "text" in first:
                return str(first.get("text", ""))

        # Dict-style
        content = result.get("content") if isinstance(result, dict) else None
        if isinstance(content, list) and content and isinstance(content[0], dict):
            return str(content[0].get("text", ""))
    except Exception:
        pass
    return str(result)


def _parse_first_id_line(text: str, prefix: str) -> Optional[str]:
    for line in text.splitlines():
        if line.strip().startswith(prefix):
            return line.split(":", 1)[1].strip()
    return None


def _now_ts() -> str:
    return datetime.now().strftime("%H:%M:%S")


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


async def main() -> int:
    # Launch server using the current interpreter.
    # Use unbuffered mode (-u) so JSON-RPC responses flush immediately over pipes.
    params = StdioServerParameters(command=sys.executable, args=["-u", "-m", "nba_mcp_server"])

    # A small helper to limit spam in output.
    verbose = os.getenv("NBA_MCP_SMOKE_VERBOSE", "0") == "1"
    tool_timeout_s = max(1.0, _env_float("NBA_MCP_SMOKE_TOOL_TIMEOUT_SECONDS", 45.0))
    init_timeout_s = max(1.0, _env_float("NBA_MCP_SMOKE_INIT_TIMEOUT_SECONDS", 20.0))
    debug = os.getenv("NBA_MCP_SMOKE_DEBUG", "0") == "1"

    results: List[ToolRunResult] = []

    print(f"[{_now_ts()}] NBA MCP live smoke test starting...", flush=True)
    print(f"[{_now_ts()}] Python: {sys.executable}", flush=True)
    print(f"[{_now_ts()}] Server command: {params.command} {' '.join(params.args)}", flush=True)
    print(f"[{_now_ts()}] Init timeout: {init_timeout_s:.0f}s | Per-tool timeout: {tool_timeout_s:.0f}s", flush=True)
    if debug:
        print(f"[{_now_ts()}] CWD: {os.getcwd()}", flush=True)
        print(f"[{_now_ts()}] PYTHONPATH: {os.getenv('PYTHONPATH', '')}", flush=True)

    async with stdio_client(params) as (read, write):
        from mcp.client.session import ClientSession

        async with ClientSession(read, write) as session:
            print(f"[{_now_ts()}] MCP subprocess started; initializing session...", flush=True)
            await asyncio.wait_for(session.initialize(), timeout=init_timeout_s)

            print(f"[{_now_ts()}] Session initialized; listing tools...", flush=True)
            tools_resp = await asyncio.wait_for(session.list_tools(), timeout=init_timeout_s)
            tools = tools_resp.tools
            tool_names = [t.name for t in tools]

            print(f"[{_now_ts()}] Discovered {len(tool_names)} tools.", flush=True)
            print(
                f"[{_now_ts()}] Per-tool timeout: {tool_timeout_s:.0f}s (set NBA_MCP_SMOKE_TOOL_TIMEOUT_SECONDS to change)",
                flush=True,
            )

            async def call(name: str, arguments: Dict[str, Any]) -> Tuple[bool, str]:
                try:
                    res = await asyncio.wait_for(session.call_tool(name, arguments), timeout=tool_timeout_s)
                    text = _extract_text(res)
                    if verbose:
                        print(f"\n--- {name} ---\n{text}\n")
                    return True, text
                except asyncio.TimeoutError:
                    return False, f"TimeoutError: tool call exceeded {tool_timeout_s:.0f}s"
                except Exception as e:
                    return False, f"{type(e).__name__}: {e}"

            # Resolve helper IDs we’ll reuse across tools.
            print(f"[{_now_ts()}] Resolving prerequisite IDs (player_id/team_id/game_id)...", flush=True)
            ok, lebron_text = await call("resolve_player_id", {"query": "LeBron James", "limit": 1})
            if not ok:
                print(f"[{_now_ts()}] resolve_player_id prereq failed: {lebron_text}", flush=True)
            lebron_id = _parse_first_id_line(lebron_text, "ID:")
            if lebron_id and "|" in lebron_id:
                lebron_id = lebron_id.split("|", 1)[0].strip()
            if not lebron_id:
                print(f"[{_now_ts()}] resolve_player_id returned unexpected output (first 200 chars): {lebron_text[:200]!r}", flush=True)

            ok, lakers_text = await call("resolve_team_id", {"query": "Lakers", "limit": 1})
            if not ok:
                print(f"[{_now_ts()}] resolve_team_id prereq failed: {lakers_text}", flush=True)
            lakers_id = _parse_first_id_line(lakers_text, "ID:")
            if lakers_id and "|" in lakers_id:
                lakers_id = lakers_id.split("|", 1)[0].strip()
            if not lakers_id:
                print(f"[{_now_ts()}] resolve_team_id returned unexpected output (first 200 chars): {lakers_text[:200]!r}", flush=True)

            # Find a game_id so we can exercise game tools.
            # Some live endpoints may 403; this uses get_scoreboard_by_date (which has stats fallback)
            # and walks back up to 14 days to find any game.
            game_id = None
            now = datetime.now()
            for days_back in range(0, 15):
                date_str = (now - timedelta(days=days_back)).strftime("%Y%m%d")
                ok, board_text = await call("get_scoreboard_by_date", {"date": date_str})
                if not ok:
                    continue
                gid = _parse_first_id_line(board_text, "Game ID:")
                if gid and gid != "N/A":
                    game_id = gid
                    break
            if not game_id:
                print(f"[{_now_ts()}] Could not find any game_id in last 14 days via get_scoreboard_by_date.", flush=True)
            print(
                f"[{_now_ts()}] Prereqs: lebron_id={lebron_id or 'N/A'} | lakers_id={lakers_id or 'N/A'} | game_id={game_id or 'N/A'}",
                flush=True,
            )

            # Default arguments per tool (best-effort).
            # For tools that need IDs, we rely on resolved IDs above.
            tool_args: Dict[str, Optional[Dict[str, Any]]] = {
                "get_server_info": {},
                "resolve_team_id": {"query": "Warriors", "limit": 3},
                "resolve_player_id": {"query": "Stephen Curry", "limit": 3},
                "find_game_id": {"date": _today_yyyymmdd(), "limit": 3},
                "get_todays_scoreboard": {},
                "get_scoreboard_by_date": {"date": _today_yyyymmdd()},
                "get_game_details": {"game_id": game_id} if game_id else None,
                "get_box_score": {"game_id": game_id} if game_id else None,
                "get_play_by_play": {"game_id": game_id} if game_id else None,
                "get_game_rotation": {"game_id": game_id} if game_id else None,
                "search_players": {"query": "LeBron"},
                "get_player_info": {"player_id": lebron_id} if lebron_id else None,
                "get_player_season_stats": {"player_id": lebron_id, "season": "2024-25"} if lebron_id else None,
                "get_player_game_log": {"player_id": lebron_id, "season": "2024-25"} if lebron_id else None,
                "get_player_career_stats": {"player_id": lebron_id} if lebron_id else None,
                "get_player_hustle_stats": {"player_id": lebron_id, "season": "2024-25"} if lebron_id else None,
                "get_league_hustle_leaders": {"stat_category": "deflections", "season": "2024-25"},
                "get_player_defense_stats": {"player_id": lebron_id, "season": "2024-25"} if lebron_id else None,
                "get_all_time_leaders": {"stat_category": "points", "limit": 5},
                "get_all_teams": {},
                "get_team_roster": {"team_id": lakers_id, "season": "2024-25"} if lakers_id else None,
                "get_standings": {"season": "2024-25"},
                "get_league_leaders": {"stat_type": "Points", "season": "2024-25"},
                "get_schedule": {"team_id": lakers_id} if lakers_id else None,
                "get_player_awards": {"player_id": lebron_id} if lebron_id else None,
                "get_season_awards": {"season": "2002-03"},
                "get_shot_chart": {"player_id": lebron_id, "season": "2024-25"} if lebron_id else None,
                "get_shooting_splits": {"player_id": lebron_id, "season": "2024-25"} if lebron_id else None,
                "get_player_advanced_stats": {"player_id": lebron_id, "season": "2024-25"} if lebron_id else None,
                "get_team_advanced_stats": {"team_id": lakers_id, "season": "2024-25"} if lakers_id else None,
            }

            # Call each discovered tool once.
            total = len(tool_names)
            for idx, name in enumerate(tool_names, 1):
                args = tool_args.get(name, {})
                if args is None:
                    print(f"[{_now_ts()}] ({idx}/{total}) {name}: SKIP (missing prerequisite ID)", flush=True)
                    results.append(
                        ToolRunResult(
                            name=name,
                            status="skipped",
                            detail="Missing prerequisite ID (player/team/game).",
                        )
                    )
                    continue

                print(f"[{_now_ts()}] ({idx}/{total}) {name}: running...", flush=True)
                ok, text = await call(name, args)
                if ok:
                    print(f"[{_now_ts()}] ({idx}/{total}) {name}: OK", flush=True)
                    results.append(ToolRunResult(name=name, status="ok", detail=text[:200].replace("\n", " ")))
                else:
                    print(f"[{_now_ts()}] ({idx}/{total}) {name}: ERROR ({text})", flush=True)
                    results.append(ToolRunResult(name=name, status="error", detail=text))

    # Print summary
    ok_count = sum(1 for r in results if r.status == "ok")
    skip_count = sum(1 for r in results if r.status == "skipped")
    err_count = sum(1 for r in results if r.status == "error")

    print("\n=== Summary ===", flush=True)
    print(f"OK: {ok_count} | Skipped: {skip_count} | Errors: {err_count}", flush=True)

    if err_count:
        print("\nErrors:")
        for r in results:
            if r.status == "error":
                print(f"- {r.name}: {r.detail}")

    # Exit non-zero if any tool errored.
    return 1 if err_count else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))


