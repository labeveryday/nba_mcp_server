#!/usr/bin/env python3
"""
NBA MCP Server (JSON-first)

This server exposes the full NBA toolset (30 tools) but returns JSON in every response so
agents/frontends can parse results reliably.

Response shape (always JSON string in TextContent.text):
{
  "entity_type": "tool_result",
  "schema_version": "2.0",
  "tool_name": "...",
  "arguments": {...},
  "text": "...",            # legacy human-readable text (kept for robustness / debugging)
  "entities": {...},        # best-effort extracted ids + CDN asset URLs
  "error": "..."            # only when errors occur
}
"""

from __future__ import annotations

import asyncio
import difflib
import json
import logging
import os
import random
import re
import ssl
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

import httpx
import mcp.server.stdio
from mcp.server import Server
from mcp.types import TextContent, Tool

# Configure logging - default to WARNING for production, can be overridden with NBA_MCP_LOG_LEVEL
log_level = os.getenv("NBA_MCP_LOG_LEVEL", "WARNING").upper()
logging.basicConfig(
    level=getattr(logging, log_level, logging.WARNING),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("nba-mcp-server")

# NBA API endpoints
NBA_LIVE_API = "https://cdn.nba.com/static/json/liveData"
NBA_STATS_API = "https://stats.nba.com/stats"

# NBA public CDN assets (no API key required)
NBA_CDN_HEADSHOTS_BASE = "https://cdn.nba.com/headshots/nba/latest"
NBA_CDN_LOGOS_BASE = "https://cdn.nba.com/logos/nba"


def get_player_headshot_url(player_id: Any, size: str = "1040x760") -> str:
    pid = str(player_id).strip()
    return f"{NBA_CDN_HEADSHOTS_BASE}/{size}/{pid}.png"


def get_player_headshot_thumbnail_url(player_id: Any) -> str:
    return get_player_headshot_url(player_id, size="260x190")


def get_team_logo_url(team_id: Any) -> str:
    tid = str(team_id).strip()
    return f"{NBA_CDN_LOGOS_BASE}/{tid}/global/L/logo.svg"


# Hardcoded team mapping (fast + reliable; also used by resolver tools)
NBA_TEAMS: dict[int, str] = {
    1610612737: "Atlanta Hawks",
    1610612738: "Boston Celtics",
    1610612751: "Brooklyn Nets",
    1610612766: "Charlotte Hornets",
    1610612741: "Chicago Bulls",
    1610612739: "Cleveland Cavaliers",
    1610612742: "Dallas Mavericks",
    1610612743: "Denver Nuggets",
    1610612765: "Detroit Pistons",
    1610612744: "Golden State Warriors",
    1610612745: "Houston Rockets",
    1610612754: "Indiana Pacers",
    1610612746: "LA Clippers",
    1610612747: "Los Angeles Lakers",
    1610612763: "Memphis Grizzlies",
    1610612748: "Miami Heat",
    1610612749: "Milwaukee Bucks",
    1610612750: "Minnesota Timberwolves",
    1610612740: "New Orleans Pelicans",
    1610612752: "New York Knicks",
    1610612760: "Oklahoma City Thunder",
    1610612753: "Orlando Magic",
    1610612755: "Philadelphia 76ers",
    1610612756: "Phoenix Suns",
    1610612757: "Portland Trail Blazers",
    1610612758: "Sacramento Kings",
    1610612759: "San Antonio Spurs",
    1610612761: "Toronto Raptors",
    1610612762: "Utah Jazz",
    1610612764: "Washington Wizards",
}

# Standard headers for NBA API requests
NBA_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nba.com/",
    "Origin": "https://www.nba.com",
}

# Create server instance
server = Server("nba-stats-server")


# ==================== Runtime Configuration ====================


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


# HTTP client config
NBA_MCP_HTTP_TIMEOUT_SECONDS = _env_float("NBA_MCP_HTTP_TIMEOUT_SECONDS", 30.0)
NBA_MCP_MAX_CONCURRENCY = max(1, _env_int("NBA_MCP_MAX_CONCURRENCY", 8))
NBA_MCP_RETRIES = max(0, _env_int("NBA_MCP_RETRIES", 2))
NBA_MCP_CACHE_TTL_SECONDS = max(0.0, _env_float("NBA_MCP_CACHE_TTL_SECONDS", 120.0))
NBA_MCP_LIVE_CACHE_TTL_SECONDS = max(0.0, _env_float("NBA_MCP_LIVE_CACHE_TTL_SECONDS", 5.0))

# TLS verification (default on).
NBA_MCP_TLS_VERIFY = os.getenv("NBA_MCP_TLS_VERIFY", "1").strip().lower() not in {
    "0",
    "false",
    "no",
    "off",
}

# HTTP client (sync) + lazy init
http_client: Any = None


def _get_http_client() -> httpx.Client:
    global http_client
    if http_client is not None:
        return http_client

    try:
        http_client = httpx.Client(
            timeout=NBA_MCP_HTTP_TIMEOUT_SECONDS,
            headers=NBA_HEADERS,
            follow_redirects=True,
            verify=NBA_MCP_TLS_VERIFY,
        )
        return http_client
    except PermissionError as e:
        if NBA_MCP_TLS_VERIFY:
            logger.warning(
                "Permission error initializing TLS verification (CA bundle not readable). "
                "Falling back to system default SSLContext (still verifies TLS). "
                "If you must disable TLS verification (NOT recommended), set NBA_MCP_TLS_VERIFY=0. "
                f"Error: {e}",
            )
            ctx = ssl.create_default_context()
            http_client = httpx.Client(
                timeout=NBA_MCP_HTTP_TIMEOUT_SECONDS,
                headers=NBA_HEADERS,
                follow_redirects=True,
                verify=ctx,
            )
            return http_client

        http_client = httpx.Client(
            timeout=NBA_MCP_HTTP_TIMEOUT_SECONDS,
            headers=NBA_HEADERS,
            follow_redirects=True,
            verify=False,  # nosec B501
        )
        return http_client


# Bound concurrent outbound requests so agents can safely parallelize calls.
_request_semaphore: Optional[asyncio.Semaphore] = None


def _get_request_semaphore() -> asyncio.Semaphore:
    global _request_semaphore
    if _request_semaphore is None:
        _request_semaphore = asyncio.Semaphore(NBA_MCP_MAX_CONCURRENCY)
    return _request_semaphore


@dataclass(frozen=True)
class _CacheEntry:
    expires_at: float
    value: dict


_cache: dict[str, _CacheEntry] = {}
_cache_lock: Optional[asyncio.Lock] = None
# Negative cache for known-unavailable requests (e.g., live scoreboard 403 in some environments).
_negative_cache: dict[str, float] = {}


def _get_cache_lock() -> asyncio.Lock:
    global _cache_lock
    if _cache_lock is None:
        _cache_lock = asyncio.Lock()
    return _cache_lock


def _cache_ttl_for_url(url: str) -> float:
    if url.startswith(NBA_LIVE_API):
        return NBA_MCP_LIVE_CACHE_TTL_SECONDS
    return NBA_MCP_CACHE_TTL_SECONDS


def _cache_key(url: str, params: Optional[dict]) -> str:
    if not params:
        return url
    items = sorted((str(k), str(v)) for k, v in params.items())
    return f"{url}?{json.dumps(items, separators=(',', ':'), ensure_ascii=True)}"


def _team_name_from_id(team_id: Any) -> str:
    try:
        tid = int(team_id)
    except Exception:
        return str(team_id)
    return NBA_TEAMS.get(tid, str(tid))


def _to_int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _best_team_id_from_query(query: str) -> Optional[int]:
    q = str(query or "").strip().lower()
    if not q:
        return None
    best: tuple[float, int] | None = None
    for tid, name in NBA_TEAMS.items():
        name_l = name.lower()
        if q in name_l:
            score = 1.0
        else:
            score = difflib.SequenceMatcher(None, q, name_l).ratio()
        if best is None or score > best[0]:
            best = (score, tid)
    if not best or best[0] < 0.3:
        return None
    return best[1]


# ==================== Helper Functions ====================


def safe_get(data: Any, *keys, default="N/A"):
    for key in keys:
        if isinstance(data, dict):
            data = data.get(key)
        elif isinstance(data, list):
            try:
                if isinstance(key, int) and 0 <= key < len(data):
                    data = data[key]
                else:
                    return default
            except (TypeError, IndexError):
                return default
        else:
            return default
        if data is None:
            return default
    return data if data != "" else default


def format_stat(value: Any, is_percentage: bool = False) -> str:
    if value is None or value == "":
        return "N/A"
    try:
        num = float(value)
        if is_percentage:
            return f"{num * 100:.1f}%"
        return f"{num:.1f}"
    except (ValueError, TypeError):
        return str(value)


async def fetch_nba_data(url: str, params: Optional[dict] = None) -> Optional[dict]:
    ttl = _cache_ttl_for_url(url)
    key = _cache_key(url, params)

    if ttl > 0:
        now = time.monotonic()
        async with _get_cache_lock():
            neg_exp = _negative_cache.get(key)
            if neg_exp and neg_exp > now:
                logger.debug(f"Negative cache hit for {url}")
                return None
            if neg_exp:
                _negative_cache.pop(key, None)

            entry = _cache.get(key)
            if entry and entry.expires_at > now:
                logger.debug(f"Cache hit for {url}")
                return entry.value
            if entry:
                _cache.pop(key, None)

    attempt = 0
    last_error: Optional[Exception] = None

    while attempt <= NBA_MCP_RETRIES:
        try:
            client = _get_http_client()
            async with _get_request_semaphore():
                response = await asyncio.to_thread(client.get, url, params=params)
            response.raise_for_status()
            data = response.json()

            if ttl > 0:
                async with _get_cache_lock():
                    _cache[key] = _CacheEntry(expires_at=time.monotonic() + ttl, value=data)
            return data

        except httpx.HTTPStatusError as e:
            last_error = e
            status = getattr(e.response, "status_code", None)
            if status in (429,) or (isinstance(status, int) and status >= 500):
                if attempt >= NBA_MCP_RETRIES:
                    break
                retry_after = None
                try:
                    ra = e.response.headers.get("Retry-After")
                    if ra:
                        retry_after = float(ra)
                except Exception:
                    retry_after = None
                delay = (
                    retry_after
                    if retry_after is not None
                    else (0.5 * (2**attempt)) + random.random() * 0.2  # nosec B311
                )
                logger.warning(
                    f"HTTP {status} from NBA API; retrying in {delay:.2f}s (attempt {attempt + 1}/{NBA_MCP_RETRIES})",
                )
                await asyncio.sleep(delay)
                attempt += 1
                continue

            if status == 403 and url.startswith(NBA_LIVE_API):
                # Expected in some environments; callers usually have a stats API fallback.
                logger.info(f"HTTP 403 from live NBA endpoint (will fall back): {url}")
                neg_ttl = max(10.0, float(ttl or 0.0))
                async with _get_cache_lock():
                    _negative_cache[key] = time.monotonic() + neg_ttl
                return None

            logger.error(f"HTTP status error fetching {url}: {e}")
            return None

        except (httpx.TimeoutException, httpx.TransportError) as e:
            last_error = e
            if attempt >= NBA_MCP_RETRIES:
                break
            delay = (0.5 * (2**attempt)) + random.random() * 0.2  # nosec B311
            logger.warning(
                f"Network error from NBA API; retrying in {delay:.2f}s (attempt {attempt + 1}/{NBA_MCP_RETRIES}): {e}",
            )
            await asyncio.sleep(delay)
            attempt += 1
            continue

        except json.JSONDecodeError as e:
            logger.error(f"JSON decode error for {url}: {e}")
            return None

        except Exception as e:
            logger.error(f"Unexpected error fetching {url}: {e}")
            return None

    logger.error(f"Failed fetching {url} after retries: {last_error}")
    return None


async def clear_cache() -> None:
    async with _get_cache_lock():
        _cache.clear()
        _negative_cache.clear()


def get_current_season() -> str:
    now = datetime.now()
    year = now.year
    if now.month >= 10:
        return f"{year}-{str(year + 1)[2:]}"
    return f"{year - 1}-{str(year)[2:]}"


async def _get_scoreboard_games_stats_api(date_obj: datetime) -> Optional[list[dict[str, Any]]]:
    """
    Fallback scoreboard source via stats.nba.com (scoreboardv2).
    Returns: {game_id, home_name, away_name, home_score, away_score, status}
    """
    url = f"{NBA_STATS_API}/scoreboardv2"
    params = {"GameDate": date_obj.strftime("%m/%d/%Y"), "LeagueID": "00", "DayOffset": "0"}
    data = await fetch_nba_data(url, params)
    if not data:
        return None

    result_sets = safe_get(data, "resultSets", default=[])
    if not result_sets or result_sets == "N/A":
        return None

    game_header = None
    line_score = None
    for rs in result_sets:
        name = safe_get(rs, "name", default="")
        if name == "GameHeader":
            game_header = rs
        elif name == "LineScore":
            line_score = rs

    if not game_header:
        return None

    gh_headers = safe_get(game_header, "headers", default=[])
    gh_rows = safe_get(game_header, "rowSet", default=[])
    if not gh_headers or not gh_rows:
        return []

    def _idx(headers: list, col: str, fallback: int) -> int:
        try:
            return headers.index(col)
        except ValueError:
            return fallback

    gid_idx = _idx(gh_headers, "GAME_ID", 2)
    home_id_idx = _idx(gh_headers, "HOME_TEAM_ID", 6)
    away_id_idx = _idx(gh_headers, "VISITOR_TEAM_ID", 7)
    status_text_idx = _idx(gh_headers, "GAME_STATUS_TEXT", -1)

    scores: dict[tuple[str, int], Any] = {}
    if line_score:
        ls_headers = safe_get(line_score, "headers", default=[])
        ls_rows = safe_get(line_score, "rowSet", default=[])
        if ls_headers and ls_rows:
            ls_gid_idx = _idx(ls_headers, "GAME_ID", 0)
            ls_team_id_idx = _idx(ls_headers, "TEAM_ID", 1)
            ls_pts_idx = _idx(ls_headers, "PTS", -1)
            for row in ls_rows:
                game_id = str(safe_get(row, ls_gid_idx, default=""))
                team_id = _to_int(safe_get(row, ls_team_id_idx, default=0))
                if team_id is None:
                    continue
                pts = safe_get(row, ls_pts_idx, default="N/A") if ls_pts_idx >= 0 else "N/A"
                scores[(game_id, team_id)] = pts

    games: list[dict[str, Any]] = []
    for row in gh_rows:
        game_id = str(safe_get(row, gid_idx, default="N/A"))
        home_id_val = safe_get(row, home_id_idx, default="N/A")
        away_id_val = safe_get(row, away_id_idx, default="N/A")
        try:
            home_id = int(home_id_val)
        except Exception:
            home_id = 0
        try:
            away_id = int(away_id_val)
        except Exception:
            away_id = 0

        status = (
            safe_get(row, status_text_idx, default="Unknown") if status_text_idx >= 0 else "Unknown"
        )
        games.append(
            {
                "game_id": game_id,
                "home_name": _team_name_from_id(home_id),
                "away_name": _team_name_from_id(away_id),
                "home_score": scores.get((game_id, home_id), "N/A"),
                "away_score": scores.get((game_id, away_id), "N/A"),
                "status": status,
            },
        )

    return games


# ==================== JSON Wrapping ====================


def _extract_entities(text: str, arguments: Any) -> dict[str, Any]:
    args = arguments if isinstance(arguments, dict) else {}
    players: list[dict[str, Any]] = []
    teams: list[dict[str, Any]] = []
    games: list[dict[str, Any]] = []

    if args.get("player_id"):
        pid = str(args["player_id"]).strip()
        players.append(
            {
                "player_id": pid,
                "headshot_url": get_player_headshot_url(pid),
                "thumbnail_url": get_player_headshot_thumbnail_url(pid),
            },
        )
    if args.get("team_id"):
        tid = str(args["team_id"]).strip()
        teams.append({"team_id": tid, "team_logo_url": get_team_logo_url(tid)})
    if args.get("game_id"):
        gid = str(args["game_id"]).strip()
        games.append({"game_id": gid})

    for tid in sorted(set(re.findall(r"\b1610612\d{3}\b", text))):
        teams.append({"team_id": tid, "team_logo_url": get_team_logo_url(tid)})

    for gid in sorted(set(re.findall(r"\b00\d{8}\b|\b00\d{9}\b", text))):
        games.append({"game_id": gid})

    for pid in sorted(set(re.findall(r"\bID:\s*(\d{3,10})\b", text))):
        if pid.startswith("1610612"):
            continue
        players.append(
            {
                "player_id": pid,
                "headshot_url": get_player_headshot_url(pid),
                "thumbnail_url": get_player_headshot_thumbnail_url(pid),
            },
        )

    def _dedupe(items: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
        seen: set[str] = set()
        out: list[dict[str, Any]] = []
        for it in items:
            v = it.get(key)
            if not v or v in seen:
                continue
            seen.add(v)
            out.append(it)
        return out

    return {
        "players": _dedupe(players, "player_id"),
        "teams": _dedupe(teams, "team_id"),
        "games": _dedupe(games, "game_id"),
    }


def _wrap_tool_result(
    *, tool_name: str, arguments: Any, text: str = "", error: Optional[str] = None
) -> list[TextContent]:
    payload: dict[str, Any] = {
        "entity_type": "tool_result",
        "schema_version": "2.0",
        "tool_name": tool_name,
        "arguments": arguments if isinstance(arguments, dict) else {},
    }
    if error:
        payload["error"] = error
    if text is not None:
        payload["text"] = text
        payload["entities"] = _extract_entities(text, arguments)
    return [
        TextContent(
            type="text", text=json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        )
    ]


# ==================== Tools ====================


@server.list_tools()
async def list_tools() -> list[Tool]:
    """List all available NBA tools."""
    return [
        Tool(
            name="get_server_info",
            description="Server version + runtime settings (timeouts, retries, cache, concurrency).",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="resolve_team_id",
            description="Resolve team name/city/nickname → team_id.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer"},
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="resolve_player_id",
            description="Resolve player name → player_id (official stats endpoint).",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "active_only": {"type": "boolean"},
                    "limit": {"type": "integer"},
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="find_game_id",
            description="Find game_id by date and matchup. If date omitted, finds most recent matchup via schedule.",
            inputSchema={
                "type": "object",
                "properties": {
                    "date": {"type": "string"},
                    "home_team": {"type": "string"},
                    "away_team": {"type": "string"},
                    "team": {"type": "string"},
                    "lookback_days": {"type": "integer"},
                    "limit": {"type": "integer"},
                },
            },
        ),
        Tool(
            name="get_todays_scoreboard",
            description="Today's games.",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="get_scoreboard_by_date",
            description="Games for a specific date.",
            inputSchema={
                "type": "object",
                "properties": {"date": {"type": "string"}},
                "required": ["date"],
            },
        ),
        Tool(
            name="get_game_details",
            description="Detailed game info for a specific game_id.",
            inputSchema={
                "type": "object",
                "properties": {"game_id": {"type": "string"}},
                "required": ["game_id"],
            },
        ),
        Tool(
            name="get_box_score",
            description="Full box score for a game_id.",
            inputSchema={
                "type": "object",
                "properties": {"game_id": {"type": "string"}},
                "required": ["game_id"],
            },
        ),
        # Player tools
        Tool(
            name="search_players",
            description="Search players by name substring.",
            inputSchema={
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        ),
        Tool(
            name="get_player_info",
            description="Player bio/profile info.",
            inputSchema={
                "type": "object",
                "properties": {"player_id": {"type": "string"}},
                "required": ["player_id"],
            },
        ),
        Tool(
            name="get_player_season_stats",
            description="Player stats for a season.",
            inputSchema={
                "type": "object",
                "properties": {"player_id": {"type": "string"}, "season": {"type": "string"}},
                "required": ["player_id"],
            },
        ),
        Tool(
            name="get_player_game_log",
            description="Player game log for a season.",
            inputSchema={
                "type": "object",
                "properties": {"player_id": {"type": "string"}, "season": {"type": "string"}},
                "required": ["player_id"],
            },
        ),
        Tool(
            name="get_player_career_stats",
            description="Player career totals/averages.",
            inputSchema={
                "type": "object",
                "properties": {"player_id": {"type": "string"}},
                "required": ["player_id"],
            },
        ),
        Tool(
            name="get_player_hustle_stats",
            description="Player hustle stats.",
            inputSchema={
                "type": "object",
                "properties": {"player_id": {"type": "string"}, "season": {"type": "string"}},
                "required": ["player_id"],
            },
        ),
        Tool(
            name="get_league_hustle_leaders",
            description="League leaders in a hustle stat category.",
            inputSchema={
                "type": "object",
                "properties": {"stat_category": {"type": "string"}, "season": {"type": "string"}},
            },
        ),
        Tool(
            name="get_player_defense_stats",
            description="Opponent FG% when defended by player.",
            inputSchema={
                "type": "object",
                "properties": {"player_id": {"type": "string"}, "season": {"type": "string"}},
                "required": ["player_id"],
            },
        ),
        Tool(
            name="get_all_time_leaders",
            description="All-time leaders for a stat category.",
            inputSchema={
                "type": "object",
                "properties": {"stat_category": {"type": "string"}, "limit": {"type": "integer"}},
            },
        ),
        # Team tools
        Tool(
            name="get_all_teams",
            description="All teams.",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="get_team_roster",
            description="Team roster.",
            inputSchema={
                "type": "object",
                "properties": {"team_id": {"type": "string"}, "season": {"type": "string"}},
                "required": ["team_id"],
            },
        ),
        # League tools
        Tool(
            name="get_standings",
            description="League standings.",
            inputSchema={"type": "object", "properties": {"season": {"type": "string"}}},
        ),
        Tool(
            name="get_league_leaders",
            description="Current season per-game league leaders for a stat category (Points/Assists/Rebounds/etc.).",
            inputSchema={
                "type": "object",
                "properties": {
                    "stat_type": {
                        "type": "string",
                        "description": "Stat type like 'Points', 'Assists', 'Rebounds', 'Steals', 'Blocks', 'FG%', '3P%', 'FT%'",
                    },
                    "season": {
                        "type": "string",
                        "description": "Season in format YYYY-YY (defaults to current season)",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Number of leaders to return (default 10, max 50)",
                    },
                },
            },
        ),
        Tool(
            name="get_schedule",
            description="Team upcoming schedule.",
            inputSchema={
                "type": "object",
                "properties": {"team_id": {"type": "string"}, "days_ahead": {"type": "integer"}},
                "required": ["team_id"],
            },
        ),
        Tool(
            name="get_player_awards",
            description="Player awards/accolades.",
            inputSchema={
                "type": "object",
                "properties": {"player_id": {"type": "string"}},
                "required": ["player_id"],
            },
        ),
        Tool(
            name="get_season_awards",
            description="Major awards for a season.",
            inputSchema={"type": "object", "properties": {"season": {"type": "string"}}},
        ),
        # Shooting
        Tool(
            name="get_shot_chart",
            description="Shot chart data summary.",
            inputSchema={
                "type": "object",
                "properties": {
                    "player_id": {"type": "string"},
                    "season": {"type": "string"},
                    "game_id": {"type": "string"},
                },
                "required": ["player_id"],
            },
        ),
        Tool(
            name="get_shooting_splits",
            description="Shooting splits summary.",
            inputSchema={
                "type": "object",
                "properties": {"player_id": {"type": "string"}, "season": {"type": "string"}},
                "required": ["player_id"],
            },
        ),
        # Play-by-play / rotation
        Tool(
            name="get_play_by_play",
            description="Play-by-play summary.",
            inputSchema={
                "type": "object",
                "properties": {
                    "game_id": {"type": "string"},
                    "start_period": {"type": "integer"},
                    "end_period": {"type": "integer"},
                },
                "required": ["game_id"],
            },
        ),
        Tool(
            name="get_game_rotation",
            description="Rotation/substitution summary.",
            inputSchema={
                "type": "object",
                "properties": {"game_id": {"type": "string"}},
                "required": ["game_id"],
            },
        ),
        # Advanced
        Tool(
            name="get_player_advanced_stats",
            description="Player advanced metrics summary.",
            inputSchema={
                "type": "object",
                "properties": {"player_id": {"type": "string"}, "season": {"type": "string"}},
                "required": ["player_id"],
            },
        ),
        Tool(
            name="get_team_advanced_stats",
            description="Team advanced metrics summary.",
            inputSchema={
                "type": "object",
                "properties": {"team_id": {"type": "string"}, "season": {"type": "string"}},
                "required": ["team_id"],
            },
        ),
    ]


# ==================== Tool Implementation (text generation) ====================


async def _call_tool_text(name: str, arguments: Any) -> str:
    """Legacy computation/formatting (string). JSON wrapper calls this for every tool."""
    # NOTE: This is intentionally the same behavior as before for correctness,
    # but the public MCP return is always JSON (see call_tool()).

    # Only implement the key tools for tests + agent workflows here, and return a clear error for others.
    # In practice, you can expand this progressively (but still JSON-wrapped).
    #
    # This keeps the file size manageable in this session.

    if name == "get_server_info":
        from nba_mcp_server import __version__

        result = "NBA MCP Server Info:\n\n"
        result += f"Version: {__version__}\n"
        result += f"HTTP timeout (s): {NBA_MCP_HTTP_TIMEOUT_SECONDS}\n"
        result += f"Max concurrency: {NBA_MCP_MAX_CONCURRENCY}\n"
        result += f"Retries: {NBA_MCP_RETRIES}\n"
        result += f"Cache TTL (stats, s): {NBA_MCP_CACHE_TTL_SECONDS}\n"
        result += f"Cache TTL (live, s): {NBA_MCP_LIVE_CACHE_TTL_SECONDS}\n"
        result += f"TLS verify enabled: {NBA_MCP_TLS_VERIFY}\n"
        result += f"Log level: {log_level}\n"
        return result

    if name == "get_all_teams":
        result = "NBA Teams:\n\n"
        for team_id, team_name in sorted(NBA_TEAMS.items(), key=lambda x: x[1]):
            result += f"ID: {team_id} | {team_name} | Logo: {get_team_logo_url(team_id)}\n"
        return result

    if name == "resolve_team_id":
        query = str(arguments.get("query", "")).strip().lower()
        limit = int(arguments.get("limit", 5) or 5)
        if not query:
            return "Please provide a non-empty team query."

        scored: list[tuple[float, int, str]] = []
        for team_id, team_name in NBA_TEAMS.items():
            name_l = team_name.lower()
            score = 1.0 if query in name_l else difflib.SequenceMatcher(None, query, name_l).ratio()
            scored.append((score, team_id, team_name))
        scored.sort(key=lambda x: x[0], reverse=True)
        top = [s for s in scored if s[0] >= 0.3][: max(1, limit)]
        if not top:
            return f"No teams matched '{arguments.get('query')}'. Try a city or nickname (e.g., 'Boston', 'Lakers')."

        result = f"Team ID matches for '{arguments.get('query')}':\n\n"
        for score, team_id, team_name in top:
            result += f"ID: {team_id} | {team_name} (match: {score:.2f}) | Logo: {get_team_logo_url(team_id)}\n"
        return result

    if name == "resolve_player_id":
        query_raw = str(arguments.get("query", "")).strip()
        query = query_raw.lower()
        active_only = bool(arguments.get("active_only", False))
        limit = int(arguments.get("limit", 10) or 10)
        if not query_raw:
            return "Please provide a non-empty player query."

        url = f"{NBA_STATS_API}/commonallplayers"
        params = {"LeagueID": "00", "Season": get_current_season(), "IsOnlyCurrentSeason": "0"}
        data = await fetch_nba_data(url, params)
        if not data:
            return "Error fetching player data. Please try again."

        rows = safe_get(data, "resultSets", 0, "rowSet", default=[])
        if not rows or rows == "N/A":
            return "No player data returned by the NBA API."

        matches: list[tuple[float, int, str, int]] = []
        for row in rows:
            player_id = _to_int(row[0] if isinstance(row, list) and row else None)
            if player_id is None:
                continue
            player_name = str(row[2]) if len(row) > 2 else ""
            is_active = int(row[11]) if len(row) > 11 and str(row[11]).isdigit() else 1
            if active_only and is_active != 1:
                continue
            name_l = player_name.lower()
            score = 1.0 if query in name_l else difflib.SequenceMatcher(None, query, name_l).ratio()
            if score >= 0.35:
                matches.append((score, player_id, player_name, is_active))
        matches.sort(key=lambda x: (x[3], x[0]), reverse=True)
        top = matches[: max(1, limit)]
        if not top:
            return f"No players matched '{query_raw}'. Try a different spelling or a shorter substring."

        result = f"Player ID matches for '{query_raw}':\n\n"
        for score, pid, name_, is_active in top:
            status = "Active" if is_active == 1 else "Inactive"
            result += (
                f"ID: {pid} | Name: {name_} | Status: {status} (match: {score:.2f}) | "
                f"Headshot: {get_player_headshot_url(pid)} | Thumb: {get_player_headshot_thumbnail_url(pid)}\n"
            )
        return result

    if name == "find_game_id":
        date_str = str(arguments.get("date", "")).strip()
        home_q = str(arguments.get("home_team", "")).strip().lower()
        away_q = str(arguments.get("away_team", "")).strip().lower()
        team_q = str(arguments.get("team", "")).strip().lower()
        limit = int(arguments.get("limit", 10) or 10)

        if not date_str:
            lookback_days = int(arguments.get("lookback_days", 365) or 365)
            lookback_days = max(1, min(3650, lookback_days))
            home_id = _best_team_id_from_query(home_q) if home_q else None
            away_id = _best_team_id_from_query(away_q) if away_q else None
            single_id = _best_team_id_from_query(team_q) if team_q else None
            if not ((home_id and away_id) or single_id):
                return "Please provide 'home_team' + 'away_team' or 'team'."

            url = "https://cdn.nba.com/static/json/staticData/scheduleLeagueV2.json"
            data = await fetch_nba_data(url)
            if not data:
                return "Error fetching league schedule. Please try again."

            game_dates = safe_get(data, "leagueSchedule", "gameDates", default=[])
            if not game_dates:
                return "No schedule data available."

            cutoff_date = datetime.now().date()
            matches: list[dict[str, Any]] = []
            for date_entry in game_dates:
                for game in safe_get(date_entry, "games", default=[]):
                    game_dt_str = safe_get(game, "gameDateTimeEst")
                    if game_dt_str == "N/A":
                        continue
                    try:
                        game_dt = datetime.fromisoformat(str(game_dt_str).replace("Z", "+00:00"))
                    except ValueError:
                        continue

                    days_back = (cutoff_date - game_dt.date()).days
                    if days_back < 0 or days_back > lookback_days:
                        continue

                    hid = _to_int(safe_get(game, "homeTeam", "teamId"))
                    aid = _to_int(safe_get(game, "awayTeam", "teamId"))
                    if hid is None or aid is None:
                        continue

                    if home_id and away_id:
                        if {hid, aid} != {home_id, away_id}:
                            continue
                    elif single_id:
                        if hid != single_id and aid != single_id:
                            continue

                    status_text = safe_get(game, "gameStatusText", default="Unknown")
                    status_num = _to_int(safe_get(game, "gameStatus", default=None))
                    matches.append(
                        {
                            "game_id": safe_get(game, "gameId", default="N/A"),
                            "date": game_dt.strftime("%Y-%m-%d"),
                            "home_team_id": hid,
                            "away_team_id": aid,
                            "home_name": f"{safe_get(game, 'homeTeam', 'teamCity')} {safe_get(game, 'homeTeam', 'teamName')}".strip(),
                            "away_name": f"{safe_get(game, 'awayTeam', 'teamCity')} {safe_get(game, 'awayTeam', 'teamName')}".strip(),
                            "status": status_text,
                            "status_num": status_num,
                        }
                    )

            def _sort_key(m: dict[str, Any]) -> tuple[int, str]:
                completed = (
                    1
                    if m.get("status_num") == 3
                    or str(m.get("status", "")).lower().startswith("final")
                    else 0
                )
                return (completed, str(m.get("date", "")))

            matches.sort(key=_sort_key, reverse=True)
            top = matches[: max(1, limit)]
            if not top:
                return "No games found in the schedule for the given filters/window."

            result = "Most recent game ID matches:\n\n"
            for g in top:
                result += f"Game ID: {g.get('game_id')}\n"
                result += f"Date: {g.get('date')}\n"
                result += f"{g.get('away_name')} @ {g.get('home_name')}\n"
                result += f"Status: {g.get('status')}\n"
                result += (
                    f"Home Team ID: {g.get('home_team_id')} | Logo: {get_team_logo_url(g.get('home_team_id'))}\n"
                    f"Away Team ID: {g.get('away_team_id')} | Logo: {get_team_logo_url(g.get('away_team_id'))}\n\n"
                )
            return result

        try:
            date_obj = datetime.strptime(date_str, "%Y%m%d")
            formatted_date = date_obj.strftime("%Y-%m-%d")
        except ValueError:
            return "Invalid date format. Use YYYYMMDD (e.g., '20241103')"

        url = f"{NBA_LIVE_API}/scoreboard/scoreboard_{date_str}.json"
        data = await fetch_nba_data(url)
        games = safe_get(data, "scoreboard", "games", default=[]) if data else []
        live_ok = bool(games and games != "N/A")

        if not live_ok:
            stats_games = await _get_scoreboard_games_stats_api(date_obj)
            if stats_games is None:
                return f"No data available for {formatted_date}. The NBA APIs may be unavailable or blocked."
            if not stats_games:
                return f"No games found for {formatted_date}."

            filtered_stats = []
            for g in stats_games:
                home_name = str(g.get("home_name", "")).lower()
                away_name = str(g.get("away_name", "")).lower()
                if home_q and home_q not in home_name:
                    continue
                if away_q and away_q not in away_name:
                    continue
                if team_q and team_q not in home_name and team_q not in away_name:
                    continue
                filtered_stats.append(g)

            if not filtered_stats:
                return f"No games matched your filters for {formatted_date}. Try using only 'team' or check spelling."

            result = f"Game ID matches for {formatted_date}:\n\n"
            for g in filtered_stats[: max(1, limit)]:
                result += f"Game ID: {g.get('game_id', 'N/A')}\n"
                result += f"{g.get('away_name', 'Away')} @ {g.get('home_name', 'Home')}\n"
                result += f"Status: {g.get('status', 'Unknown')}\n\n"
            return result

        return f"Game ID matches for {formatted_date}:\n\n(Use scoreboard tools for detailed listings.)\n"

    if name == "get_scoreboard_by_date":
        date_str = str(arguments.get("date", "")).strip()
        try:
            date_obj = datetime.strptime(date_str, "%Y%m%d")
            formatted_date = date_obj.strftime("%Y-%m-%d")
        except ValueError:
            return "Invalid date format. Use YYYYMMDD (e.g., '20241103')"

        url = f"{NBA_LIVE_API}/scoreboard/scoreboard_{date_str}.json"
        data = await fetch_nba_data(url)

        if not data:
            stats_games = await _get_scoreboard_games_stats_api(date_obj)
            if stats_games is None:
                return f"No data available for {formatted_date}. The game data might not be available yet or the date might be incorrect."
            if not stats_games:
                return f"No games found for {formatted_date}."

            result = f"NBA Games for {formatted_date}:\n\n"
            for g in stats_games:
                result += f"Game ID: {g.get('game_id', 'N/A')}\n"
                result += f"{g.get('away_name', 'Away')} ({g.get('away_score', 'N/A')}) @ {g.get('home_name', 'Home')} ({g.get('home_score', 'N/A')})\n"
                result += f"Status: {g.get('status', 'Unknown')}\n\n"
            return result

        scoreboard = safe_get(data, "scoreboard")
        games = safe_get(scoreboard, "games", default=[])
        if not games:
            return f"No games found for {formatted_date}."

        result = f"NBA Games for {formatted_date}:\n\n"
        for game in games:
            home_team = safe_get(game, "homeTeam", default={})
            away_team = safe_get(game, "awayTeam", default={})
            gid = safe_get(game, "gameId", default="N/A")
            status = safe_get(game, "gameStatusText", default="Unknown")

            home_id = safe_get(home_team, "teamId", default="")
            away_id = safe_get(away_team, "teamId", default="")

            result += f"Game ID: {gid}\n"
            result += (
                f"{safe_get(away_team, 'teamName')} ({safe_get(away_team, 'score')}) @ "
                f"{safe_get(home_team, 'teamName')} ({safe_get(home_team, 'score')})\n"
            )
            result += f"Status: {status}\n"
            if home_id not in ("", "N/A"):
                result += f"Home Team ID: {home_id} | Logo: {get_team_logo_url(home_id)}\n"
            if away_id not in ("", "N/A"):
                result += f"Away Team ID: {away_id} | Logo: {get_team_logo_url(away_id)}\n"
            result += "\n"

        return result

    if name == "get_todays_scoreboard":
        url = f"{NBA_LIVE_API}/scoreboard/todaysScoreboard_00.json"
        data = await fetch_nba_data(url)

        if not data:
            today = datetime.now()
            stats_games = await _get_scoreboard_games_stats_api(today)
            if stats_games is None:
                return "Error fetching today's scoreboard. Please try again."
            if not stats_games:
                return f"No games scheduled for {today.strftime('%Y-%m-%d')}."

            result = f"NBA Games for {today.strftime('%Y-%m-%d')}:\n\n"
            for g in stats_games:
                result += f"Game ID: {g.get('game_id', 'N/A')}\n"
                result += f"{g.get('away_name', 'Away')} ({g.get('away_score', 'N/A')}) @ {g.get('home_name', 'Home')} ({g.get('home_score', 'N/A')})\n"
                result += f"Status: {g.get('status', 'Unknown')}\n\n"
            return result

        scoreboard = safe_get(data, "scoreboard")
        if not scoreboard or scoreboard == "N/A":
            return "No scoreboard data available."

        games = safe_get(scoreboard, "games", default=[])
        game_date = safe_get(scoreboard, "gameDate", default=datetime.now().strftime("%Y-%m-%d"))
        if not games:
            return f"No games scheduled for {game_date}."

        result = f"NBA Games for {game_date}:\n\n"
        for game in games:
            home_team = safe_get(game, "homeTeam", default={})
            away_team = safe_get(game, "awayTeam", default={})

            home_name = safe_get(home_team, "teamName", default="Home Team")
            away_name = safe_get(away_team, "teamName", default="Away Team")
            home_score = safe_get(home_team, "score", default=0)
            away_score = safe_get(away_team, "score", default=0)
            game_status = safe_get(game, "gameStatusText", default="Unknown")
            game_id = safe_get(game, "gameId", default="N/A")

            home_id = safe_get(home_team, "teamId", default="")
            away_id = safe_get(away_team, "teamId", default="")

            result += f"Game ID: {game_id}\n"
            result += f"{away_name} ({away_score}) @ {home_name} ({home_score})\n"
            result += f"Status: {game_status}\n"
            if home_id not in ("", "N/A"):
                result += f"Home Team ID: {home_id} | Logo: {get_team_logo_url(home_id)}\n"
            if away_id not in ("", "N/A"):
                result += f"Away Team ID: {away_id} | Logo: {get_team_logo_url(away_id)}\n"
            result += "\n"

        return result

    if name == "get_all_time_leaders":
        stat_category = str(arguments.get("stat_category", "points")).lower()
        limit = min(int(arguments.get("limit", 10) or 10), 50)

        stat_map = {
            "points": "PTSLeaders",
            "rebounds": "REBLeaders",
            "assists": "ASTLeaders",
            "steals": "STLLeaders",
            "blocks": "BLKLeaders",
            "games": "GPLeaders",
            "offensive_rebounds": "OREBLeaders",
            "defensive_rebounds": "DREBLeaders",
            "field_goals_made": "FGMLeaders",
            "field_goals_attempted": "FGALeaders",
            "field_goal_pct": "FG_PCTLeaders",
            "three_pointers_made": "FG3MLeaders",
            "three_pointers_attempted": "FG3ALeaders",
            "three_point_pct": "FG3_PCTLeaders",
            "free_throws_made": "FTMLeaders",
            "free_throws_attempted": "FTALeaders",
            "free_throw_pct": "FT_PCTLeaders",
            "turnovers": "TOVLeaders",
            "personal_fouls": "PFLeaders",
        }

        if stat_category not in stat_map:
            valid_cats = ", ".join(sorted(stat_map.keys()))
            return f"Invalid stat category. Choose from: {valid_cats}"

        result_set_name = stat_map[stat_category]
        url = f"{NBA_STATS_API}/alltimeleadersgrids"
        params = {
            "LeagueID": "00",
            "PerMode": "Totals",
            "SeasonType": "Regular Season",
            "TopX": str(limit),
        }
        data = await fetch_nba_data(url, params)
        if not data:
            return "Error fetching all-time leaders. Please try again."

        leaders_data = None
        for result_set in safe_get(data, "resultSets", default=[]):
            if result_set.get("name") == result_set_name:
                leaders_data = result_set.get("rowSet", [])
                break
        if not leaders_data:
            return f"No all-time leaders found for {stat_category}."

        stat_display = stat_category.replace("_", " ").title()
        result = f"All-Time Career Leaders - {stat_display}:\n\n"
        for i, player in enumerate(leaders_data, 1):
            player_name = safe_get(player, 1, default="Unknown")
            stat_value = safe_get(player, 2, default=0)
            is_active = safe_get(player, 4, default=0)

            if "pct" in stat_category:
                stat_str = format_stat(stat_value, is_percentage=True)
            else:
                try:
                    stat_str = f"{int(float(stat_value)):,}"
                except (ValueError, TypeError):
                    stat_str = str(stat_value)

            active_marker = " ✓" if is_active == 1 else ""
            result += f"{i}. {player_name}: {stat_str}{active_marker}\n"

        if any(safe_get(p, 4, default=0) == 1 for p in leaders_data):
            result += "\n✓ = Active player"
        return result

    if name == "get_player_info":
        player_id = arguments.get("player_id")
        if not player_id:
            return "Please provide player_id."

        url = f"{NBA_STATS_API}/commonplayerinfo"
        params = {"PlayerID": player_id}
        data = await fetch_nba_data(url, params)
        if not data:
            return "Error fetching player info. Please try again."

        info_headers = safe_get(data, "resultSets", 0, "headers", default=[])
        player_data = safe_get(data, "resultSets", 0, "rowSet", 0, default=[])
        if not player_data or player_data == "N/A":
            return "Player not found."

        result = "Player Information:\n\n"
        result += f"Player ID: {player_id}\n"
        result += f"Headshot (1040x760): {get_player_headshot_url(player_id)}\n"
        result += f"Headshot (260x190): {get_player_headshot_thumbnail_url(player_id)}\n"

        # Common fields (best-effort; indices vary by endpoint versions)
        # DISPLAY_FIRST_LAST is commonly index 3.
        result += f"Name: {safe_get(player_data, 3)}\n"

        # Prefer header-based lookups when possible
        def _hidx(col: str, fallback: Optional[int] = None) -> Optional[int]:
            try:
                return info_headers.index(col)
            except Exception:
                return fallback

        jersey_idx = _hidx("JERSEY", 13)
        pos_idx = _hidx("POSITION", 14)
        height_idx = _hidx("HEIGHT", 10)
        weight_idx = _hidx("WEIGHT", 11)
        birth_idx = _hidx("BIRTHDATE", 6)
        country_idx = _hidx("COUNTRY", 8)
        school_idx = _hidx("SCHOOL", 7)
        roster_idx = _hidx("ROSTERSTATUS", None)
        team_id_idx = _hidx("TEAM_ID", None)
        team_name_idx = _hidx("TEAM_NAME", None)
        team_abbr_idx = _hidx("TEAM_ABBREVIATION", None)

        if jersey_idx is not None:
            result += f"Jersey: #{safe_get(player_data, jersey_idx)}\n"
        if pos_idx is not None:
            result += f"Position: {safe_get(player_data, pos_idx)}\n"
        if roster_idx is not None:
            result += f"Status: {safe_get(player_data, roster_idx)}\n"
        if height_idx is not None:
            result += f"Height: {safe_get(player_data, height_idx)}\n"
        if weight_idx is not None:
            result += f"Weight: {safe_get(player_data, weight_idx)} lbs\n"
        if birth_idx is not None:
            result += f"Birth Date: {safe_get(player_data, birth_idx)}\n"
        if country_idx is not None:
            result += f"Country: {safe_get(player_data, country_idx)}\n"
        if school_idx is not None:
            result += f"School: {safe_get(player_data, school_idx)}\n"

        team_id_val = (
            safe_get(player_data, team_id_idx, default="") if team_id_idx is not None else ""
        )
        team_name_val = (
            safe_get(player_data, team_name_idx, default="") if team_name_idx is not None else ""
        )
        team_abbr_val = (
            safe_get(player_data, team_abbr_idx, default="") if team_abbr_idx is not None else ""
        )

        if team_id_val:
            result += f"Team: {team_name_val} (ID: {team_id_val})"
            if team_abbr_val and team_abbr_val != "N/A":
                result += f" [{team_abbr_val}]"
            result += f" | Logo: {get_team_logo_url(team_id_val)}\n"
        elif team_name_val:
            result += f"Team: {team_name_val}\n"

        return result

    if name == "get_league_leaders":
        stat_type = str(arguments.get("stat_type", "Points"))
        season = str(arguments.get("season", get_current_season()))
        limit = min(int(arguments.get("limit", 10) or 10), 50)

        # Map friendly stat names to NBA Stats API columns.
        stat_map = {
            "Points": "PTS",
            "Assists": "AST",
            "Rebounds": "REB",
            "Steals": "STL",
            "Blocks": "BLK",
            "FG%": "FG_PCT",
            "3P%": "FG3_PCT",
            "FT%": "FT_PCT",
        }
        stat_category = stat_map.get(stat_type, stat_map.get(stat_type.title(), "PTS"))

        # Use leaguedashplayerstats (PerGame) so results are already per-game and sortable.
        url = f"{NBA_STATS_API}/leaguedashplayerstats"
        params = {
            "LeagueID": "00",
            "Season": season,
            "SeasonType": "Regular Season",
            "PerMode": "PerGame",
            "MeasureType": "Base",
            "PlusMinus": "N",
            "PaceAdjust": "N",
            "Rank": "N",
            "Outcome": "",
            "Location": "",
            "Month": "0",
            "SeasonSegment": "",
            "DateFrom": "",
            "DateTo": "",
            "OpponentTeamID": "0",
            "VsConference": "",
            "VsDivision": "",
            "GameSegment": "",
            "Period": "0",
            "LastNGames": "0",
        }

        data = await fetch_nba_data(url, params)
        if not data:
            return "Error fetching league leaders. Please try again."

        headers = safe_get(data, "resultSets", 0, "headers", default=[])
        rows = safe_get(data, "resultSets", 0, "rowSet", default=[])
        if not rows or not headers:
            return f"No data found for {stat_type} leaders."

        try:
            player_id_idx = headers.index("PLAYER_ID")
        except ValueError:
            player_id_idx = 0
        try:
            player_name_idx = headers.index("PLAYER_NAME")
        except ValueError:
            player_name_idx = 1
        try:
            team_abbr_idx = headers.index("TEAM_ABBREVIATION")
        except ValueError:
            team_abbr_idx = 3

        if stat_category not in headers:
            valid = ", ".join(sorted(stat_map.keys()))
            return f"Unsupported stat_type '{stat_type}'. Try one of: {valid}"
        stat_idx = headers.index(stat_category)

        # Sort descending by the stat. Some pct fields may be strings; coerce carefully.
        def _val(row: list[Any]) -> float:
            v = safe_get(row, stat_idx, default=0)
            try:
                return float(v)
            except Exception:
                return 0.0

        sorted_rows = sorted(rows, key=_val, reverse=True)

        stat_display = stat_type
        result = f"League Leaders - {stat_display} ({season}) [Per Game]:\n\n"
        for i, row in enumerate(sorted_rows[:limit], 1):
            pid = safe_get(row, player_id_idx, default="N/A")
            name_ = safe_get(row, player_name_idx, default="Unknown")
            team_ = safe_get(row, team_abbr_idx, default="N/A")
            val = safe_get(row, stat_idx, default="N/A")

            # Format percentages nicely
            if stat_category.endswith("_PCT"):
                try:
                    val_f = float(val)
                    val_s = f"{val_f * 100:.1f}%"
                except Exception:
                    val_s = str(val)
            else:
                val_s = str(val)

            result += f"{i}. {name_} ({team_}) - {val_s} | Player ID: {pid}\n"

        return result

    # -------------------- Remaining tools (ported from last full server) --------------------

    if name == "get_game_details":
        game_id = str(arguments.get("game_id", "")).strip()
        if not game_id:
            return "Please provide game_id."

        # Try today's scoreboard first
        try:
            url = f"{NBA_LIVE_API}/scoreboard/todaysScoreboard_00.json"
            data = await fetch_nba_data(url)
            if data:
                games = safe_get(data, "scoreboard", "games", default=[])
                game = next((g for g in games if safe_get(g, "gameId") == game_id), None)
                if game:
                    home_team = safe_get(game, "homeTeam", default={})
                    away_team = safe_get(game, "awayTeam", default={})
                    home_id = safe_get(home_team, "teamId", default="")
                    away_id = safe_get(away_team, "teamId", default="")

                    result = f"Game Details for {game_id}:\n\n"
                    result += (
                        f"{safe_get(away_team, 'teamName')} @ {safe_get(home_team, 'teamName')}\n"
                    )
                    result += (
                        f"Score: {safe_get(away_team, 'score')} - {safe_get(home_team, 'score')}\n"
                    )
                    result += f"Status: {safe_get(game, 'gameStatusText')}\n"
                    result += f"Period: Q{safe_get(game, 'period', default=0)}\n"
                    if home_id not in ("", "N/A"):
                        result += f"Home Team ID: {home_id} | Logo: {get_team_logo_url(home_id)}\n"
                    if away_id not in ("", "N/A"):
                        result += f"Away Team ID: {away_id} | Logo: {get_team_logo_url(away_id)}\n"
                    result += "\n"

                    away_stats = safe_get(away_team, "statistics", default={})
                    home_stats = safe_get(home_team, "statistics", default={})
                    if away_stats != "N/A" and home_stats != "N/A":
                        result += "Team Statistics:\n"
                        result += f"{safe_get(away_team, 'teamName')}:\n"
                        result += f"  FG: {safe_get(away_stats, 'fieldGoalsMade')}/{safe_get(away_stats, 'fieldGoalsAttempted')}\n"
                        result += f"  3P: {safe_get(away_stats, 'threePointersMade')}/{safe_get(away_stats, 'threePointersAttempted')}\n"
                        result += f"  FT: {safe_get(away_stats, 'freeThrowsMade')}/{safe_get(away_stats, 'freeThrowsAttempted')}\n"
                        result += f"  Rebounds: {safe_get(away_stats, 'reboundsTotal')}\n"
                        result += f"  Assists: {safe_get(away_stats, 'assists')}\n\n"

                        result += f"{safe_get(home_team, 'teamName')}:\n"
                        result += f"  FG: {safe_get(home_stats, 'fieldGoalsMade')}/{safe_get(home_stats, 'fieldGoalsAttempted')}\n"
                        result += f"  3P: {safe_get(home_stats, 'threePointersMade')}/{safe_get(home_stats, 'threePointersAttempted')}\n"
                        result += f"  FT: {safe_get(home_stats, 'freeThrowsMade')}/{safe_get(home_stats, 'freeThrowsAttempted')}\n"
                        result += f"  Rebounds: {safe_get(home_stats, 'reboundsTotal')}\n"
                        result += f"  Assists: {safe_get(home_stats, 'assists')}\n"

                    return result

            return f"Game {game_id} not found in today's games. Try get_scoreboard_by_date to find the correct game_id."
        except Exception as e:
            logger.error(f"Error fetching game details: {e}")
            return f"Error fetching game details: {str(e)}"

    if name == "get_box_score":
        game_id = str(arguments.get("game_id", "")).strip()
        if not game_id:
            return "Please provide game_id."

        # Live boxscore first
        url = f"{NBA_LIVE_API}/boxscore/boxscore_{game_id}.json"
        live_data = await fetch_nba_data(url)
        if live_data and safe_get(live_data, "game") != "N/A":
            game = safe_get(live_data, "game", default={})
            home_team = safe_get(game, "homeTeam", default={})
            away_team = safe_get(game, "awayTeam", default={})

            result = f"Box Score for Game {game_id}:\n"
            result += f"{safe_get(away_team, 'teamName')} @ {safe_get(home_team, 'teamName')}\n"
            result += (
                f"Final Score: {safe_get(away_team, 'score')} - {safe_get(home_team, 'score')}\n\n"
            )
            result += "TEAM STATS:\n"

            away_stats = safe_get(away_team, "statistics", default={})
            if away_stats != "N/A":
                result += f"\n{safe_get(away_team, 'teamName')}:\n"
                result += f"  FG: {safe_get(away_stats, 'fieldGoalsMade')}/{safe_get(away_stats, 'fieldGoalsAttempted')}"
                fg_pct = safe_get(away_stats, "fieldGoalsPercentage", default=0)
                if fg_pct != "N/A":
                    result += f" ({format_stat(fg_pct, True)})"
                result += "\n"

            home_stats = safe_get(home_team, "statistics", default={})
            if home_stats != "N/A":
                result += f"\n{safe_get(home_team, 'teamName')}:\n"
                result += f"  FG: {safe_get(home_stats, 'fieldGoalsMade')}/{safe_get(home_stats, 'fieldGoalsAttempted')}"
                fg_pct = safe_get(home_stats, "fieldGoalsPercentage", default=0)
                if fg_pct != "N/A":
                    result += f" ({format_stat(fg_pct, True)})"
                result += "\n"

            result += "\n" + "=" * 70 + "\nPLAYER STATS:\n\n"
            away_players = safe_get(away_team, "players", default=[])
            if away_players and away_players != "N/A":
                result += f"{safe_get(away_team, 'teamName')}:\n"
                result += f"{'Player':<25} {'MIN':<6} {'PTS':<5} {'REB':<5} {'AST':<5}\n"
                result += "-" * 55 + "\n"
                for player in away_players:
                    stats = safe_get(player, "statistics", default={})
                    if stats == "N/A":
                        continue
                    minutes = safe_get(stats, "minutes", default="0:00")
                    if not minutes or minutes == "0:00":
                        continue
                    result += f"{safe_get(player, 'name', default='Unknown'):<25} {minutes:<6} {safe_get(stats, 'points', default=0):<5} {safe_get(stats, 'reboundsTotal', default=0):<5} {safe_get(stats, 'assists', default=0):<5}\n"

            home_players = safe_get(home_team, "players", default=[])
            if home_players and home_players != "N/A":
                result += f"\n{safe_get(home_team, 'teamName')}:\n"
                result += f"{'Player':<25} {'MIN':<6} {'PTS':<5} {'REB':<5} {'AST':<5}\n"
                result += "-" * 55 + "\n"
                for player in home_players:
                    stats = safe_get(player, "statistics", default={})
                    if stats == "N/A":
                        continue
                    minutes = safe_get(stats, "minutes", default="0:00")
                    if not minutes or minutes == "0:00":
                        continue
                    result += f"{safe_get(player, 'name', default='Unknown'):<25} {minutes:<6} {safe_get(stats, 'points', default=0):<5} {safe_get(stats, 'reboundsTotal', default=0):<5} {safe_get(stats, 'assists', default=0):<5}\n"

            return result

        # Stats API fallback
        url = f"{NBA_STATS_API}/boxscoretraditionalv2"
        params = {
            "GameID": game_id,
            "StartPeriod": "0",
            "EndPeriod": "10",
            "RangeType": "0",
            "StartRange": "0",
            "EndRange": "0",
        }
        data = await fetch_nba_data(url, params)
        if not data:
            return "Error fetching box score. The game stats may not be available yet."

        player_stats_rows = safe_get(data, "resultSets", 0, "rowSet", default=[])
        team_stats_rows = safe_get(data, "resultSets", 1, "rowSet", default=[])
        if not player_stats_rows or player_stats_rows == "N/A":
            return f"Box score not available for game {game_id}."

        result = f"Box Score for Game {game_id} (Stats API):\n\n"
        if team_stats_rows and team_stats_rows != "N/A":
            result += "TEAM STATS:\n"
            for team in team_stats_rows:
                team_abbr = safe_get(team, 1, default="N/A")
                pts = safe_get(team, 24, default=0)
                result += f"  {team_abbr}: {pts} PTS\n"
        result += "\nPLAYER STATS: (summary)\n"
        result += f"Players returned: {len(player_stats_rows)}\n"
        return result

    if name == "search_players":
        query = str(arguments.get("query", "")).strip().lower()
        if not query:
            return "Please provide a non-empty query."

        url = f"{NBA_STATS_API}/commonallplayers"
        params = {"LeagueID": "00", "Season": get_current_season(), "IsOnlyCurrentSeason": "0"}
        data = await fetch_nba_data(url, params)
        if not data:
            return "Error fetching player data. Please try again."

        rows = safe_get(data, "resultSets", 0, "rowSet", default=[])
        if not rows:
            return "No players found."

        matching = []
        for row in rows:
            if len(row) > 2:
                name_ = str(row[2]).lower()
                if query in name_:
                    matching.append(
                        {"id": row[0], "name": row[2], "is_active": row[11] if len(row) > 11 else 1}
                    )

        if not matching:
            return f"No players found matching '{arguments.get('query')}'."

        result = f"Found {len(matching)} player(s):\n\n"
        for p in matching[:20]:
            status = "Active" if p["is_active"] == 1 else "Inactive"
            pid = p["id"]
            result += f"ID: {pid} | Name: {p['name']} | Status: {status} | Headshot: {get_player_headshot_url(pid)} | Thumb: {get_player_headshot_thumbnail_url(pid)}\n"
        if len(matching) > 20:
            result += f"\n... and {len(matching) - 20} more."
        return result

    if name == "get_player_season_stats":
        player_id = str(arguments.get("player_id", "")).strip()
        season = str(arguments.get("season", get_current_season()))
        if not player_id:
            return "Please provide player_id."

        url = f"{NBA_STATS_API}/playercareerstats"
        params = {"PlayerID": player_id, "PerMode": "PerGame"}
        data = await fetch_nba_data(url, params)
        if not data:
            return "Error fetching player stats. Please try again."

        headers = safe_get(data, "resultSets", 0, "headers", default=[])
        all_seasons = safe_get(data, "resultSets", 0, "rowSet", default=[])
        if not all_seasons:
            return "No stats found for this player."

        season_id_idx = headers.index("SEASON_ID") if "SEASON_ID" in headers else 1
        stats_row = next(
            (r for r in all_seasons if str(safe_get(r, season_id_idx)) == season), None
        )
        if not stats_row:
            return f"No stats found for season {season}."

        def _idx(col: str, fallback: int) -> int:
            try:
                return headers.index(col)
            except ValueError:
                return fallback

        gp_idx = _idx("GP", 6)
        min_idx = _idx("MIN", 8)
        pts_idx = _idx("PTS", 26)
        reb_idx = _idx("REB", 18)
        ast_idx = _idx("AST", 19)
        stl_idx = _idx("STL", 21)
        blk_idx = _idx("BLK", 22)
        fg_pct_idx = _idx("FG_PCT", 9)
        fg3_pct_idx = _idx("FG3_PCT", 12)
        ft_pct_idx = _idx("FT_PCT", 15)

        result = f"Season Stats ({season}) - Player ID {player_id}:\n\n"
        result += f"Headshot: {get_player_headshot_url(player_id)}\n"
        result += f"GP: {safe_get(stats_row, gp_idx)} | MIN: {format_stat(safe_get(stats_row, min_idx))}\n"
        result += f"PTS: {format_stat(safe_get(stats_row, pts_idx))} | REB: {format_stat(safe_get(stats_row, reb_idx))} | AST: {format_stat(safe_get(stats_row, ast_idx))}\n"
        result += f"STL: {format_stat(safe_get(stats_row, stl_idx))} | BLK: {format_stat(safe_get(stats_row, blk_idx))}\n"
        result += f"FG%: {format_stat(safe_get(stats_row, fg_pct_idx), True)} | 3P%: {format_stat(safe_get(stats_row, fg3_pct_idx), True)} | FT%: {format_stat(safe_get(stats_row, ft_pct_idx), True)}\n"
        return result

    if name == "get_player_game_log":
        player_id = str(arguments.get("player_id", "")).strip()
        season = str(arguments.get("season", get_current_season()))
        if not player_id:
            return "Please provide player_id."

        url = f"{NBA_STATS_API}/playergamelog"
        params = {"PlayerID": player_id, "Season": season, "SeasonType": "Regular Season"}
        data = await fetch_nba_data(url, params)
        if not data:
            return "Error fetching game log. Please try again."

        headers = safe_get(data, "resultSets", 0, "headers", default=[])
        games = safe_get(data, "resultSets", 0, "rowSet", default=[])
        if not games:
            return f"No games found for season {season}."

        def _idx(col: str, fallback: int) -> int:
            try:
                return headers.index(col)
            except ValueError:
                return fallback

        date_idx = _idx("GAME_DATE", 2)
        matchup_idx = _idx("MATCHUP", 3)
        wl_idx = _idx("WL", 4)
        min_idx = _idx("MIN", 5)
        pts_idx = _idx("PTS", 24)
        reb_idx = _idx("REB", 18)
        ast_idx = _idx("AST", 19)

        result = f"Game Log - Player {player_id} ({season}):\n\n"
        for g in games[:10]:
            result += (
                f"{safe_get(g, date_idx)} | {safe_get(g, matchup_idx)} | {safe_get(g, wl_idx)} | "
            )
            result += f"{safe_get(g, pts_idx)} PTS, {safe_get(g, reb_idx)} REB, {safe_get(g, ast_idx)} AST | MIN {safe_get(g, min_idx)}\n"
        if len(games) > 10:
            result += f"\n... {len(games) - 10} more games."
        return result

    if name == "get_player_career_stats":
        player_id = str(arguments.get("player_id", "")).strip()
        if not player_id:
            return "Please provide player_id."

        url = f"{NBA_STATS_API}/playercareerstats"
        params = {"PlayerID": player_id, "PerMode": "Totals"}
        data = await fetch_nba_data(url, params)
        if not data:
            return "Error fetching career stats. Please try again."

        rows = safe_get(data, "resultSets", 0, "rowSet", default=[])
        if not rows or rows == "N/A":
            return "No career stats found for this player."

        total_games = total_points = total_rebounds = total_assists = total_steals = (
            total_blocks
        ) = total_minutes = 0.0
        for season_row in rows:
            if len(season_row) > 26:
                total_games += float(season_row[6]) if season_row[6] else 0
                total_minutes += float(season_row[8]) if season_row[8] else 0
                total_rebounds += float(season_row[20]) if season_row[20] else 0
                total_assists += float(season_row[21]) if season_row[21] else 0
                total_steals += float(season_row[22]) if season_row[22] else 0
                total_blocks += float(season_row[23]) if season_row[23] else 0
                total_points += float(season_row[26]) if season_row[26] else 0

        ppg = total_points / total_games if total_games > 0 else 0
        rpg = total_rebounds / total_games if total_games > 0 else 0
        apg = total_assists / total_games if total_games > 0 else 0

        result = "Career Statistics (Regular Season):\n\n"
        result += f"Player ID: {player_id}\n"
        result += f"Headshot: {get_player_headshot_url(player_id)}\n\n"
        result += f"Total Points: {int(total_points):,}\n"
        result += f"Games Played: {int(total_games):,}\n"
        result += f"Total Rebounds: {int(total_rebounds):,}\n"
        result += f"Total Assists: {int(total_assists):,}\n"
        result += f"Total Steals: {int(total_steals):,}\n"
        result += f"Total Blocks: {int(total_blocks):,}\n"
        result += f"Total Minutes: {int(total_minutes):,}\n\n"
        result += "Career Averages:\n"
        result += f"PPG: {ppg:.1f} | RPG: {rpg:.1f} | APG: {apg:.1f}\n"
        return result

    if name == "get_player_hustle_stats":
        player_id = str(arguments.get("player_id", "")).strip()
        season = str(arguments.get("season", get_current_season()))
        if not player_id:
            return "Please provide player_id."

        url = f"{NBA_STATS_API}/leaguehustlestatsplayer"
        params = {"Season": season, "SeasonType": "Regular Season", "PerMode": "Totals"}
        data = await fetch_nba_data(url, params)
        if not data:
            return "Error fetching hustle stats. Please try again."

        rows = safe_get(data, "resultSets", 0, "rowSet", default=[])
        player_stats = next((r for r in rows if str(safe_get(r, 0)) == str(player_id)), None)
        if not player_stats:
            return f"No hustle stats found for player ID {player_id} in season {season}."

        player_name = safe_get(player_stats, 1, default="Player")
        team = safe_get(player_stats, 3, default="N/A")
        games = safe_get(player_stats, 5, default=0)
        result = f"Hustle Statistics - {player_name} ({team}) [{season}]:\n\n"
        result += f"Games Played: {games}\n\n"
        result += f"Deflections: {safe_get(player_stats, 10, default=0)}\n"
        result += f"Charges Drawn: {safe_get(player_stats, 11, default=0)}\n"
        result += f"Screen Assists: {safe_get(player_stats, 12, default=0)}\n"
        result += f"Loose Balls Recovered: {safe_get(player_stats, 16, default=0)}\n"
        result += f"Box Outs: {safe_get(player_stats, 23, default=0)}\n"
        return result

    if name == "get_league_hustle_leaders":
        stat_category = str(arguments.get("stat_category", "deflections"))
        season = str(arguments.get("season", get_current_season()))

        url = f"{NBA_STATS_API}/leaguehustlestatsplayer"
        params = {"Season": season, "SeasonType": "Regular Season", "PerMode": "Totals"}
        data = await fetch_nba_data(url, params)
        if not data:
            return "Error fetching hustle stats. Please try again."

        rows = safe_get(data, "resultSets", 0, "rowSet", default=[])
        stat_map = {
            "deflections": (10, "Deflections"),
            "charges": (11, "Charges Drawn"),
            "screen_assists": (12, "Screen Assists"),
            "loose_balls": (16, "Loose Balls Recovered"),
            "box_outs": (23, "Box Outs"),
        }
        if stat_category not in stat_map:
            return f"Invalid stat category. Choose from: {', '.join(stat_map.keys())}"

        col_idx, stat_name = stat_map[stat_category]
        sorted_players = sorted(
            rows, key=lambda x: float(safe_get(x, col_idx, default=0) or 0), reverse=True
        )[:10]
        result = f"League Hustle Leaders - {stat_name} ({season}):\n\n"
        for i, player in enumerate(sorted_players, 1):
            name_ = safe_get(player, 1, default="Unknown")
            team = safe_get(player, 3, default="N/A")
            val = safe_get(player, col_idx, default=0)
            result += f"{i}. {name_} ({team}): {val}\n"
        return result

    if name == "get_player_defense_stats":
        player_id = str(arguments.get("player_id", "")).strip()
        season = str(arguments.get("season", get_current_season()))
        if not player_id:
            return "Please provide player_id."

        url = f"{NBA_STATS_API}/leaguedashptdefend"
        params = {
            "Season": season,
            "SeasonType": "Regular Season",
            "PerMode": "Totals",
            "DefenseCategory": "Overall",
        }
        data = await fetch_nba_data(url, params)
        if not data:
            return "Error fetching defense stats. Please try again."

        rows = safe_get(data, "resultSets", 0, "rowSet", default=[])
        player_stats = next((r for r in rows if str(safe_get(r, 0)) == str(player_id)), None)
        if not player_stats:
            return f"No defense stats found for player ID {player_id} in season {season}."

        player_name = safe_get(player_stats, 1, default="Player")
        team = safe_get(player_stats, 3, default="N/A")
        position = safe_get(player_stats, 4, default="N/A")
        games = safe_get(player_stats, 6, default=0)
        dfg_pct = safe_get(player_stats, 11, default=0)
        normal_fg_pct = safe_get(player_stats, 12, default=0)
        diff = safe_get(player_stats, 13, default=0)
        result = f"Defensive Impact - {player_name} ({team}) [{season}]:\n\n"
        result += f"Position: {position}\nGames: {games}\n\n"
        result += f"Opponent FG% when defended: {format_stat(dfg_pct, True)}\n"
        result += f"Opponent normal FG%: {format_stat(normal_fg_pct, True)}\n"
        result += f"Difference: {format_stat(diff, True)}\n"
        return result

    if name == "get_team_roster":
        team_id = str(arguments.get("team_id", "")).strip()
        season = str(arguments.get("season", get_current_season()))
        if not team_id:
            return "Please provide team_id."

        url = f"{NBA_STATS_API}/commonteamroster"
        params = {"TeamID": team_id, "Season": season}
        data = await fetch_nba_data(url, params)
        if not data:
            return "Error fetching roster. Please try again."

        roster_data = safe_get(data, "resultSets", 0, "rowSet", default=[])
        if not roster_data:
            return "No roster found for this team."

        result = (
            f"Team Roster ({season}) - Team ID {team_id} | Logo: {get_team_logo_url(team_id)}\n\n"
        )
        for player in roster_data:
            player_name = safe_get(player, 3)
            num = safe_get(player, 4)
            pos = safe_get(player, 5)
            pid = safe_get(player, 14, default="")  # PLAYER_ID often at 14
            result += f"#{num} {player_name} - {pos}"
            if pid not in ("", "N/A"):
                result += f" | Player ID: {pid} | Headshot: {get_player_headshot_url(pid)}"
            result += "\n"
        return result

    if name == "get_standings":
        season = str(arguments.get("season", get_current_season()))
        url = f"{NBA_STATS_API}/leaguestandingsv3"
        params = {"LeagueID": "00", "Season": season, "SeasonType": "Regular Season"}
        data = await fetch_nba_data(url, params)
        if not data:
            return "Error fetching standings. Please try again."

        headers = safe_get(data, "resultSets", 0, "headers", default=[])
        rows = safe_get(data, "resultSets", 0, "rowSet", default=[])
        if not rows:
            return "No standings found."

        def _idx(col: str, fallback: Optional[int] = None) -> Optional[int]:
            try:
                return headers.index(col)
            except Exception:
                return fallback

        team_name_idx = _idx("TeamName", 4)
        conf_idx = _idx("Conference", 5)
        wins_idx = _idx("WINS", 13)
        losses_idx = _idx("LOSSES", 14)
        pct_idx = _idx("WinPCT", 15)
        team_id_idx = _idx("TeamID", _idx("TEAM_ID", None))

        east = [r for r in rows if safe_get(r, conf_idx, default="") == "East"]
        west = [r for r in rows if safe_get(r, conf_idx, default="") != "East"]

        # sort by win pct desc
        def _pct(row: list[Any]) -> float:
            try:
                return float(safe_get(row, pct_idx, default=0) or 0)
            except Exception:
                return 0.0

        east.sort(key=_pct, reverse=True)
        west.sort(key=_pct, reverse=True)

        result = f"NBA Standings ({season}):\n\nEastern Conference:\n"
        for i, r in enumerate(east, 1):
            name_ = safe_get(r, team_name_idx)
            tid = safe_get(r, team_id_idx, default="") if team_id_idx is not None else ""
            result += f"{i}. {name_}: {safe_get(r, wins_idx)}-{safe_get(r, losses_idx)} ({format_stat(safe_get(r, pct_idx))})"
            if tid not in ("", "N/A"):
                result += f" | Team ID: {tid} | Logo: {get_team_logo_url(tid)}"
            result += "\n"

        result += "\nWestern Conference:\n"
        for i, r in enumerate(west, 1):
            name_ = safe_get(r, team_name_idx)
            tid = safe_get(r, team_id_idx, default="") if team_id_idx is not None else ""
            result += f"{i}. {name_}: {safe_get(r, wins_idx)}-{safe_get(r, losses_idx)} ({format_stat(safe_get(r, pct_idx))})"
            if tid not in ("", "N/A"):
                result += f" | Team ID: {tid} | Logo: {get_team_logo_url(tid)}"
            result += "\n"

        return result

    if name == "get_schedule":
        team_id = str(arguments.get("team_id", "")).strip()
        days_ahead = min(int(arguments.get("days_ahead", 7) or 7), 90)
        if not team_id:
            return "Please specify team_id."

        url = "https://cdn.nba.com/static/json/staticData/scheduleLeagueV2.json"
        data = await fetch_nba_data(url)
        if not data:
            return "Error fetching schedule. Please try again."

        game_dates = safe_get(data, "leagueSchedule", "gameDates", default=[])
        if not game_dates:
            return "No schedule data available."

        today = datetime.now()
        team_id_int = int(team_id)
        upcoming = []
        for date_entry in game_dates:
            for game in safe_get(date_entry, "games", default=[]):
                home_id = safe_get(game, "homeTeam", "teamId")
                away_id = safe_get(game, "awayTeam", "teamId")
                if home_id == team_id_int or away_id == team_id_int:
                    game_date_str = safe_get(game, "gameDateTimeEst")
                    if game_date_str == "N/A":
                        continue
                    try:
                        game_date = datetime.fromisoformat(
                            str(game_date_str).replace("Z", "+00:00")
                        )
                    except ValueError:
                        continue
                    if game_date.date() >= today.date():
                        days_until = (game_date.date() - today.date()).days
                        if days_until <= days_ahead:
                            upcoming.append((game_date, game))
        upcoming.sort(key=lambda x: x[0])
        if not upcoming:
            return f"No upcoming games found within the next {days_ahead} days for this team."

        team_name = NBA_TEAMS.get(team_id_int, f"Team {team_id}")
        result = f"Upcoming Games for {team_name} (Team ID {team_id}):\n"
        result += f"(Next {days_ahead} days) | Logo: {get_team_logo_url(team_id)}\n\n"
        for game_date, game in upcoming:
            home_team = safe_get(game, "homeTeam", default={})
            away_team = safe_get(game, "awayTeam", default={})
            home_name = f"{safe_get(home_team, 'teamCity')} {safe_get(home_team, 'teamName')}"
            away_name = f"{safe_get(away_team, 'teamCity')} {safe_get(away_team, 'teamName')}"
            result += f"{game_date.strftime('%Y-%m-%d')} - {away_name} @ {home_name}\n"
            result += (
                f"  Arena: {safe_get(game, 'arenaName')} | Game ID: {safe_get(game, 'gameId')}\n\n"
            )
        return result

    if name == "get_player_awards":
        player_id = str(arguments.get("player_id", "")).strip()
        if not player_id:
            return "Please provide player_id."

        url = f"{NBA_STATS_API}/playerawards"
        params = {"PlayerID": player_id}
        data = await fetch_nba_data(url, params)
        if not data:
            return "Error fetching player awards. Please try again."

        headers = safe_get(data, "resultSets", 0, "headers", default=[])
        awards = safe_get(data, "resultSets", 0, "rowSet", default=[])
        if not awards:
            return "No awards found for this player."

        def _idx(col: str, fallback: int) -> int:
            try:
                return headers.index(col)
            except Exception:
                return fallback

        desc_idx = _idx("DESCRIPTION", 4)
        season_idx = _idx("SEASON", 6)
        team_idx = _idx("TEAM", 3)

        first = awards[0]
        player_name = f"{safe_get(first, 1)} {safe_get(first, 2)}".strip()
        result = f"Awards and Accolades - {player_name} (Player ID {player_id})\n\n"
        result += f"Headshot: {get_player_headshot_url(player_id)}\n\n"

        for award in awards[:50]:
            result += f"{safe_get(award, season_idx)}: {safe_get(award, desc_idx)}"
            t = safe_get(award, team_idx, default="")
            if t and t != "N/A":
                result += f" ({t})"
            result += "\n"
        if len(awards) > 50:
            result += f"\n... and {len(awards) - 50} more."
        return result

    if name == "get_season_awards":
        season = str(arguments.get("season", get_current_season()))
        # MVP-only minimal, as in prior implementation
        mvp_map = {
            "2023-24": ("Joel Embiid", "1610612755"),
            "2022-23": ("Joel Embiid", "1610612755"),
            "2021-22": ("Nikola Jokic", "1610612743"),
            "2020-21": ("Nikola Jokic", "1610612743"),
            "2019-20": ("Giannis Antetokounmpo", "1610612749"),
            "2018-19": ("Giannis Antetokounmpo", "1610612749"),
            "2017-18": ("James Harden", "1610612745"),
            "2016-17": ("Russell Westbrook", "1610612760"),
            "2015-16": ("Stephen Curry", "1610612744"),
            "2014-15": ("Stephen Curry", "1610612744"),
        }
        if season not in mvp_map:
            return f"Award data for {season} season is not available. Use get_player_awards for individual awards."
        mvp_name, team_id = mvp_map[season]
        result = f"Major Awards - {season} Season\n\n"
        result += f"MVP: {mvp_name} | Team ID: {team_id} | Logo: {get_team_logo_url(team_id)}\n"
        return result

    if name == "get_shot_chart":
        player_id = str(arguments.get("player_id", "")).strip()
        season = str(arguments.get("season", get_current_season()))
        game_id = str(arguments.get("game_id", "")).strip()
        if not player_id:
            return "Please provide player_id."

        params = {
            "PlayerID": player_id,
            "Season": season,
            "SeasonType": "Regular Season",
            "TeamID": "0",
            "GameID": game_id,
            "Outcome": "",
            "Location": "",
            "Month": "0",
            "SeasonSegment": "",
            "DateFrom": "",
            "DateTo": "",
            "OpponentTeamID": "0",
            "VsConference": "",
            "VsDivision": "",
            "Position": "",
            "RookieYear": "",
            "GameSegment": "",
            "Period": "0",
            "LastNGames": "0",
            "ContextMeasure": "FGA",
        }
        url = f"{NBA_STATS_API}/shotchartdetail"
        data = await fetch_nba_data(url, params=params)
        if not data:
            return "Failed to fetch shot chart data."

        headers = safe_get(data, "resultSets", 0, "headers", default=[])
        shots = safe_get(data, "resultSets", 0, "rowSet", default=[])
        if not shots:
            return f"No shot data found for this player in {season}."

        try:
            made_idx = headers.index("SHOT_MADE_FLAG")
            dist_idx = headers.index("SHOT_DISTANCE")
        except ValueError:
            return "Error parsing shot chart data structure."

        total = len(shots)
        made = sum(1 for s in shots if safe_get(s, made_idx) == 1)
        pct = (made / total * 100) if total > 0 else 0.0
        avg_dist = 0.0
        try:
            avg_dist = sum(float(safe_get(s, dist_idx, default=0) or 0) for s in shots) / total
        except Exception:
            avg_dist = 0.0

        result = f"Shot Chart Summary - Player {player_id} ({season})\n\n"
        result += f"Headshot: {get_player_headshot_url(player_id)}\n"
        result += f"Shots: {made}/{total} ({pct:.1f}%) | Avg Distance: {avg_dist:.1f} ft\n"
        result += (
            "Note: For visualization, use the raw coordinates from the shotchartdetail endpoint."
        )
        return result

    if name == "get_shooting_splits":
        player_id = str(arguments.get("player_id", "")).strip()
        season = str(arguments.get("season", get_current_season()))
        if not player_id:
            return "Please provide player_id."

        params = {
            "PlayerID": player_id,
            "Season": season,
            "SeasonType": "Regular Season",
            "PerMode": "Totals",
            "MeasureType": "Base",
            "PlusMinus": "N",
            "PaceAdjust": "N",
            "Rank": "N",
            "Outcome": "",
            "Location": "",
            "Month": "0",
            "SeasonSegment": "",
            "DateFrom": "",
            "DateTo": "",
            "OpponentTeamID": "0",
            "VsConference": "",
            "VsDivision": "",
            "GameSegment": "",
            "Period": "0",
            "LastNGames": "0",
        }
        url = f"{NBA_STATS_API}/playerdashboardbyshootingsplits"
        data = await fetch_nba_data(url, params=params)
        if not data:
            return "Failed to fetch shooting splits data."

        result_sets = safe_get(data, "resultSets", default=[])
        overall = next(
            (rs for rs in result_sets if safe_get(rs, "name") == "OverallPlayerDashboard"), None
        )
        if not overall:
            return f"No shooting data found for {season}."

        headers = safe_get(overall, "headers", default=[])
        rows = safe_get(overall, "rowSet", default=[])
        if not rows:
            return f"No shooting data available for {season}."

        row = rows[0]
        player_name = safe_get(row, 1, default="Player")
        try:
            fgm_idx = headers.index("FGM")
            fga_idx = headers.index("FGA")
            fg_pct_idx = headers.index("FG_PCT")
            fg3m_idx = headers.index("FG3M")
            fg3a_idx = headers.index("FG3A")
            fg3_pct_idx = headers.index("FG3_PCT")
        except ValueError:
            return "Unable to parse shooting splits."

        fgm = safe_get(row, fgm_idx, default=0)
        fga = safe_get(row, fga_idx, default=0)
        fg_pct = safe_get(row, fg_pct_idx, default=0)
        fg3m = safe_get(row, fg3m_idx, default=0)
        fg3a = safe_get(row, fg3a_idx, default=0)
        fg3_pct = safe_get(row, fg3_pct_idx, default=0)

        result = f"Shooting Splits - {player_name} ({season})\n\n"
        result += f"Player ID: {player_id} | Headshot: {get_player_headshot_url(player_id)}\n"
        result += f"FG: {fgm}/{fga} ({format_stat(fg_pct, True)})\n"
        result += f"3P: {fg3m}/{fg3a} ({format_stat(fg3_pct, True)})\n"
        return result

    if name == "get_play_by_play":
        game_id = str(arguments.get("game_id", "")).strip()
        start_period = int(arguments.get("start_period", 1) or 1)
        end_period = int(arguments.get("end_period", 10) or 10)
        if not game_id:
            return "Please provide game_id."

        params = {"GameID": game_id, "StartPeriod": start_period, "EndPeriod": end_period}
        url = f"{NBA_STATS_API}/playbyplayv2"
        data = await fetch_nba_data(url, params=params)
        if not data:
            return "Failed to fetch play-by-play data."

        result_sets = safe_get(data, "resultSets", default=[])
        pbp = next((rs for rs in result_sets if safe_get(rs, "name") == "PlayByPlay"), None)
        if not pbp:
            return f"No play-by-play data found for game {game_id}."

        headers = safe_get(pbp, "headers", default=[])
        plays = safe_get(pbp, "rowSet", default=[])
        if not plays:
            return f"No plays found for game {game_id}."

        def _idx(col: str, fallback: int) -> int:
            try:
                return headers.index(col)
            except ValueError:
                return fallback

        period_idx = _idx("PERIOD", 4)
        time_idx = _idx("PCTIMESTRING", 6)
        home_desc_idx = _idx("HOMEDESCRIPTION", 7)
        visitor_desc_idx = _idx("VISITORDESCRIPTION", 9)
        score_idx = _idx("SCORE", 10)

        result = f"Play-by-Play (sample) - Game {game_id}\nShowing periods {start_period} to {end_period}\n\n"
        count = 0
        for play in plays:
            desc = safe_get(play, home_desc_idx, default="") or safe_get(
                play, visitor_desc_idx, default=""
            )
            if not desc or desc == "N/A":
                continue
            count += 1
            result += f"Q{safe_get(play, period_idx, default='')} {safe_get(play, time_idx, default='')}: {desc}"
            s = safe_get(play, score_idx, default="")
            if s and s != "N/A":
                result += f" [{s}]"
            result += "\n"
            if count >= 25:
                break
        if len(plays) > count:
            result += f"\n... showing first {count} plays (out of {len(plays)})."
        return result

    if name == "get_game_rotation":
        game_id = str(arguments.get("game_id", "")).strip()
        if not game_id:
            return "Please provide game_id."

        params = {"GameID": game_id, "LeagueID": "00"}
        url = f"{NBA_STATS_API}/gamerotation"
        data = await fetch_nba_data(url, params=params)
        if not data:
            return "Failed to fetch game rotation data."

        result_sets = safe_get(data, "resultSets", default=[])
        away = next((rs for rs in result_sets if safe_get(rs, "name") == "AwayTeam"), None)
        home = next((rs for rs in result_sets if safe_get(rs, "name") == "HomeTeam"), None)
        if not away and not home:
            return f"No rotation data found for game {game_id}."

        def _summ(team_data: dict, label: str) -> str:
            headers = safe_get(team_data, "headers", default=[])
            rows = safe_get(team_data, "rowSet", default=[])
            if not rows:
                return ""
            try:
                first_idx = headers.index("PLAYER_FIRST")
                last_idx = headers.index("PLAYER_LAST")
                pts_idx = headers.index("PLAYER_PTS")
            except ValueError:
                return ""
            # aggregate points by player name
            pts_by = {}
            for r in rows:
                name_ = f"{safe_get(r, first_idx, default='')} {safe_get(r, last_idx, default='')}".strip()
                try:
                    pts_by[name_] = max(
                        pts_by.get(name_, 0), int(float(safe_get(r, pts_idx, default=0) or 0))
                    )
                except Exception:
                    pts_by[name_] = pts_by.get(name_, 0)
            top = sorted(pts_by.items(), key=lambda x: x[1], reverse=True)[:10]
            out = f"{label} Rotation Summary (top points):\n"
            for n, p in top:
                out += f"  {n}: {p} pts\n"
            return out + "\n"

        result = f"Game Rotation Summary - Game {game_id}\n\n"
        if away:
            result += _summ(away, "Away")
        if home:
            result += _summ(home, "Home")
        return result

    if name == "get_player_advanced_stats":
        player_id = str(arguments.get("player_id", "")).strip()
        season = str(arguments.get("season", get_current_season()))
        if not player_id:
            return "Please provide player_id."

        params = {
            "PlayerID": player_id,
            "Season": season,
            "SeasonType": "Regular Season",
            "MeasureType": "Advanced",
            "PerMode": "PerGame",
            "PlusMinus": "N",
            "PaceAdjust": "N",
            "Rank": "N",
            "LastNGames": "0",
            "Month": "0",
            "OpponentTeamID": "0",
            "Period": "0",
            "DateFrom": "",
            "DateTo": "",
            "GameSegment": "",
            "LeagueID": "00",
            "Location": "",
            "Outcome": "",
            "PORound": "0",
            "SeasonSegment": "",
            "ShotClockRange": "",
            "VsConference": "",
            "VsDivision": "",
        }
        url = f"{NBA_STATS_API}/playerdashboardbygeneralsplits"
        data = await fetch_nba_data(url, params=params)
        if not data:
            return "Failed to fetch player advanced stats."

        result_sets = safe_get(data, "resultSets", default=[])
        overall = next(
            (rs for rs in result_sets if safe_get(rs, "name") == "OverallPlayerDashboard"), None
        )
        if not overall:
            return f"No advanced stats found for {season}."

        headers = safe_get(overall, "headers", default=[])
        rows = safe_get(overall, "rowSet", default=[])
        if not rows:
            return f"No advanced stats available for {season}."

        row = rows[0]

        def _idx(col: str) -> Optional[int]:
            try:
                return headers.index(col)
            except ValueError:
                return None

        name_idx = _idx("PLAYER_NAME") or 1
        player_name = safe_get(row, name_idx, default="Player")
        off_idx = _idx("OFF_RATING")
        def_idx = _idx("DEF_RATING")
        net_idx = _idx("NET_RATING")
        ts_idx = _idx("TS_PCT")
        usg_idx = _idx("USG_PCT")

        result = f"Advanced Stats - {player_name} ({season})\n\n"
        result += f"Player ID: {player_id} | Headshot: {get_player_headshot_url(player_id)}\n"
        if off_idx is not None:
            result += f"OffRtg: {format_stat(safe_get(row, off_idx))}\n"
        if def_idx is not None:
            result += f"DefRtg: {format_stat(safe_get(row, def_idx))}\n"
        if net_idx is not None:
            result += f"NetRtg: {format_stat(safe_get(row, net_idx))}\n"
        if ts_idx is not None:
            result += f"TS%: {format_stat(safe_get(row, ts_idx), True)}\n"
        if usg_idx is not None:
            result += f"USG%: {format_stat(safe_get(row, usg_idx), True)}\n"
        return result

    if name == "get_team_advanced_stats":
        team_id = str(arguments.get("team_id", "")).strip()
        season = str(arguments.get("season", get_current_season()))
        if not team_id:
            return "Please provide team_id."

        params = {
            "TeamID": team_id,
            "Season": season,
            "SeasonType": "Regular Season",
            "MeasureType": "Advanced",
            "PerMode": "PerGame",
            "PlusMinus": "N",
            "PaceAdjust": "N",
            "Rank": "N",
            "LastNGames": "0",
            "Month": "0",
            "OpponentTeamID": "0",
            "Period": "0",
            "DateFrom": "",
            "DateTo": "",
            "GameSegment": "",
            "LeagueID": "00",
            "Location": "",
            "Outcome": "",
            "PORound": "0",
            "SeasonSegment": "",
            "ShotClockRange": "",
            "VsConference": "",
            "VsDivision": "",
        }
        url = f"{NBA_STATS_API}/teamdashboardbygeneralsplits"
        data = await fetch_nba_data(url, params=params)
        if not data:
            return "Failed to fetch team advanced stats."

        result_sets = safe_get(data, "resultSets", default=[])
        overall = next(
            (rs for rs in result_sets if safe_get(rs, "name") == "OverallTeamDashboard"), None
        )
        if not overall:
            return f"No advanced stats found for {season}."

        headers = safe_get(overall, "headers", default=[])
        rows = safe_get(overall, "rowSet", default=[])
        if not rows:
            return f"No advanced stats available for {season}."

        row = rows[0]

        def _idx(col: str) -> Optional[int]:
            try:
                return headers.index(col)
            except ValueError:
                return None

        name_idx = _idx("TEAM_NAME") or _idx("GROUP_VALUE") or 1
        team_name = safe_get(row, name_idx, default="Team")
        off_idx = _idx("OFF_RATING")
        def_idx = _idx("DEF_RATING")
        net_idx = _idx("NET_RATING")
        pace_idx = _idx("PACE")
        result = f"Advanced Stats - {team_name} ({season})\n\n"
        result += f"Team ID: {team_id} | Logo: {get_team_logo_url(team_id)}\n"
        if off_idx is not None:
            result += f"OffRtg: {format_stat(safe_get(row, off_idx))}\n"
        if def_idx is not None:
            result += f"DefRtg: {format_stat(safe_get(row, def_idx))}\n"
        if net_idx is not None:
            result += f"NetRtg: {format_stat(safe_get(row, net_idx))}\n"
        if pace_idx is not None:
            result += f"Pace: {format_stat(safe_get(row, pace_idx))}\n"
        return result

    return f"Unknown tool: {name}"


# ==================== MCP call_tool (JSON-only) ====================


@server.call_tool()
async def call_tool(name: str, arguments: Any) -> list[TextContent]:
    try:
        text = await _call_tool_text(name, arguments)
        return _wrap_tool_result(tool_name=name, arguments=arguments, text=text)
    except Exception as e:  # pragma: no cover
        logger.error(f"Error in {name}: {e}", exc_info=True)
        return _wrap_tool_result(
            tool_name=name, arguments=arguments, error=f"{type(e).__name__}: {e}"
        )


async def async_main() -> None:
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        logger.info("NBA MCP Server starting...")
        await server.run(read_stream, write_stream, server.create_initialization_options())


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
