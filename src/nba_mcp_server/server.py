#!/usr/bin/env python3
"""
NBA MCP Server - Provides access to NBA stats and data through direct API calls.

This server provides various tools to access NBA data including:
- Player stats and information
- Live game data and scores
- Team information and rosters
- League standings and leaders

Uses direct HTTP calls to NBA APIs for better reliability and control.
"""

import asyncio
import difflib
import json
import logging
import os
import random
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
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("nba-mcp-server")

# NBA API endpoints
NBA_LIVE_API = "https://cdn.nba.com/static/json/liveData"
NBA_STATS_API = "https://stats.nba.com/stats"

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


# TLS verification (default on). In some sandboxed/macOS privacy-restricted environments, reading CA files
# can raise PermissionError; we fall back safely if needed.
NBA_MCP_TLS_VERIFY = os.getenv("NBA_MCP_TLS_VERIFY", "1").strip().lower() not in {"0", "false", "no", "off"}

# HTTP client with timeout (sync client; we run requests in a thread to avoid blocking the MCP event loop)
# NOTE: Lazily initialized to avoid crashing the MCP server during import/init when SSL CA files are not readable.
http_client: Any = None


def _get_http_client() -> httpx.Client:
    """Get (and lazily initialize) the module-level HTTP client."""
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
        # Common in sandboxed environments or macOS privacy restrictions where cert bundles are not readable.
        # If TLS verification is enabled, try a system-default SSLContext that does NOT rely on certifi's file.
        if NBA_MCP_TLS_VERIFY:
            logger.warning(
                "Permission error initializing TLS verification (CA bundle not readable). "
                "Falling back to system default SSLContext (still verifies TLS). "
                "If you must disable TLS verification (NOT recommended), set NBA_MCP_TLS_VERIFY=0. "
                f"Error: {e}"
            )
            ctx = ssl.create_default_context()
            http_client = httpx.Client(
                timeout=NBA_MCP_HTTP_TIMEOUT_SECONDS,
                headers=NBA_HEADERS,
                follow_redirects=True,
                verify=ctx,
            )
            return http_client

        # TLS verify explicitly disabled by user.
        http_client = httpx.Client(
            timeout=NBA_MCP_HTTP_TIMEOUT_SECONDS,
            headers=NBA_HEADERS,
            follow_redirects=True,
            # TLS verify explicitly disabled by user via NBA_MCP_TLS_VERIFY=0 (NOT recommended).
            verify=False,  # nosec B501
        )
        return http_client

# Bound concurrent outbound requests so agents can safely parallelize calls.
_request_semaphore: Optional[asyncio.Semaphore] = None


def _get_request_semaphore() -> asyncio.Semaphore:
    """Get (and lazily initialize) the request semaphore."""
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


def _get_cache_lock() -> asyncio.Lock:
    """Get (and lazily initialize) the cache lock."""
    global _cache_lock
    if _cache_lock is None:
        _cache_lock = asyncio.Lock()
    return _cache_lock


def _cache_ttl_for_url(url: str) -> float:
    # Live endpoints update quickly; keep cache tight.
    if url.startswith(NBA_LIVE_API):
        return NBA_MCP_LIVE_CACHE_TTL_SECONDS
    return NBA_MCP_CACHE_TTL_SECONDS


def _cache_key(url: str, params: Optional[dict]) -> str:
    if not params:
        return url
    # Stable ordering for cache key.
    items = sorted((str(k), str(v)) for k, v in params.items())
    return f"{url}?{json.dumps(items, separators=(',', ':'), ensure_ascii=True)}"


def _team_name_from_id(team_id: Any) -> str:
    """Best-effort mapping from NBA team_id -> team name."""
    try:
        tid = int(team_id)
    except Exception:
        return str(team_id)
    return NBA_TEAMS.get(tid, str(tid))


def _to_int(value: Any) -> Optional[int]:
    """Best-effort int conversion."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


async def _get_scoreboard_games_stats_api(date_obj: datetime) -> Optional[list[dict[str, Any]]]:
    """
    Fallback scoreboard source via stats.nba.com (scoreboardv2).
    Returns a list of dicts: {game_id, home_name, away_name, home_score, away_score, status}.
    """
    url = f"{NBA_STATS_API}/scoreboardv2"
    params = {
        "GameDate": date_obj.strftime("%m/%d/%Y"),
        "LeagueID": "00",
        "DayOffset": "0",
    }
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

        status = safe_get(row, status_text_idx, default="Unknown") if status_text_idx >= 0 else "Unknown"
        games.append(
            {
                "game_id": game_id,
                "home_name": _team_name_from_id(home_id),
                "away_name": _team_name_from_id(away_id),
                "home_score": scores.get((game_id, home_id), "N/A"),
                "away_score": scores.get((game_id, away_id), "N/A"),
                "status": status,
            }
        )

    return games

# ==================== Helper Functions ====================

def safe_get(data: dict, *keys, default="N/A"):
    """Safely get nested dictionary and list values."""
    for key in keys:
        if isinstance(data, dict):
            data = data.get(key)
        elif isinstance(data, list):
            # Handle list indexing
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
    """Format a stat value for display."""
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
    """Fetch data from NBA API with error handling."""
    ttl = _cache_ttl_for_url(url)
    key = _cache_key(url, params)

    if ttl > 0:
        now = time.monotonic()
        async with _get_cache_lock():
            entry = _cache.get(key)
            if entry and entry.expires_at > now:
                logger.debug(f"Cache hit for {url}")
                return entry.value
            if entry:
                _cache.pop(key, None)

    # Retry with backoff for transient failures (429 / 5xx / network errors).
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
            # Only retry on 429 / 5xx.
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
                # Non-cryptographic jitter is fine for backoff timing.
                delay = retry_after if retry_after is not None else (0.5 * (2 ** attempt)) + random.random() * 0.2  # nosec B311
                logger.warning(f"HTTP {status} from NBA API; retrying in {delay:.2f}s (attempt {attempt+1}/{NBA_MCP_RETRIES})")
                await asyncio.sleep(delay)
                attempt += 1
                continue

            logger.error(f"HTTP status error fetching {url}: {e}")
            return None

        except (httpx.TimeoutException, httpx.TransportError) as e:
            last_error = e
            if attempt >= NBA_MCP_RETRIES:
                break
            # Non-cryptographic jitter is fine for backoff timing.
            delay = (0.5 * (2 ** attempt)) + random.random() * 0.2  # nosec B311
            logger.warning(f"Network error from NBA API; retrying in {delay:.2f}s (attempt {attempt+1}/{NBA_MCP_RETRIES}): {e}")
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
    """Clear the in-memory response cache."""
    async with _get_cache_lock():
        _cache.clear()


def get_current_season() -> str:
    """Get current NBA season in YYYY-YY format."""
    now = datetime.now()
    year = now.year
    # NBA season typically starts in October
    # Current year is 2024, so in Nov 2024 we're in 2024-25 season
    if now.month >= 10:
        return f"{year}-{str(year + 1)[2:]}"
    else:
        return f"{year - 1}-{str(year)[2:]}"


# ==================== Tool Handlers ====================

@server.list_tools()
async def list_tools() -> list[Tool]:
    """List all available NBA tools."""
    return [
        Tool(
            name="get_server_info",
            description="Get NBA MCP server runtime info (version, config, cache/concurrency settings). Useful for debugging and agent diagnostics.",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        Tool(
            name="resolve_team_id",
            description="Resolve an NBA team name (e.g., 'Lakers', 'Boston') to official NBA team IDs.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Team name, city, or nickname (e.g., 'Lakers', 'Boston', 'Warriors')"},
                    "limit": {"type": "integer", "description": "Max results to return (default 5)"},
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="resolve_player_id",
            description="Resolve an NBA player name (e.g., 'LeBron James') to NBA player IDs. Uses the official stats endpoint.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Player name or partial name (e.g., 'LeBron', 'Curry', 'Wembanyama')"},
                    "active_only": {"type": "boolean", "description": "If true, only return active players (default false)"},
                    "limit": {"type": "integer", "description": "Max results to return (default 10)"},
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="find_game_id",
            description="Find game IDs for a specific date and matchup (helps agents get the right game_id for box score, play-by-play, etc.).",
            inputSchema={
                "type": "object",
                "properties": {
                    "date": {"type": "string", "description": "Date in format YYYYMMDD (e.g., '20241103')"},
                    "home_team": {"type": "string", "description": "Home team name/city/nickname (optional)"},
                    "away_team": {"type": "string", "description": "Away team name/city/nickname (optional)"},
                    "team": {"type": "string", "description": "Single-team filter (matches either home or away) (optional)"},
                    "limit": {"type": "integer", "description": "Max results to return (default 10)"},
                },
                "required": ["date"],
            },
        ),
        # Live Game Tools
        Tool(
            name="get_todays_scoreboard",
            description="Get today's NBA games with live scores, status, and real-time updates. Most reliable for current games.",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        Tool(
            name="get_scoreboard_by_date",
            description="Get NBA games for a specific date with scores and status.",
            inputSchema={
                "type": "object",
                "properties": {
                    "date": {
                        "type": "string",
                        "description": "Date in format YYYYMMDD (e.g., '20241103')",
                    }
                },
                "required": ["date"],
            },
        ),
        Tool(
            name="get_game_details",
            description="Get detailed information about a specific game including live stats.",
            inputSchema={
                "type": "object",
                "properties": {
                    "game_id": {
                        "type": "string",
                        "description": "NBA game ID (e.g., '0022400123')",
                    }
                },
                "required": ["game_id"],
            },
        ),
        Tool(
            name="get_box_score",
            description="Get full box score with player-by-player statistics for a specific game. Best for detailed stats.",
            inputSchema={
                "type": "object",
                "properties": {
                    "game_id": {
                        "type": "string",
                        "description": "NBA game ID (e.g., '0022400123'). Use get_todays_scoreboard to find game IDs.",
                    }
                },
                "required": ["game_id"],
            },
        ),

        # Player Tools
        Tool(
            name="search_players",
            description="Search for NBA players by name. Returns a list of matching players with IDs.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Player name or partial name to search for (e.g., 'LeBron', 'Curry')",
                    }
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="get_player_info",
            description="Get detailed information about a specific player including bio and career info.",
            inputSchema={
                "type": "object",
                "properties": {
                    "player_id": {
                        "type": "string",
                        "description": "NBA player ID",
                    }
                },
                "required": ["player_id"],
            },
        ),
        Tool(
            name="get_player_season_stats",
            description="Get player statistics for a specific season.",
            inputSchema={
                "type": "object",
                "properties": {
                    "player_id": {
                        "type": "string",
                        "description": "NBA player ID",
                    },
                    "season": {
                        "type": "string",
                        "description": "Season in format YYYY-YY (e.g., '2024-25'). Defaults to current season.",
                    }
                },
                "required": ["player_id"],
            },
        ),
        Tool(
            name="get_player_game_log",
            description="Get game-by-game log for a player's season, showing all individual games with stats. Useful for finding highest-scoring games or specific performances.",
            inputSchema={
                "type": "object",
                "properties": {
                    "player_id": {
                        "type": "string",
                        "description": "NBA player ID",
                    },
                    "season": {
                        "type": "string",
                        "description": "Season in format YYYY-YY (e.g., '2002-03'). Defaults to current season.",
                    }
                },
                "required": ["player_id"],
            },
        ),
        Tool(
            name="get_player_career_stats",
            description="Get comprehensive career statistics for a player including total points, games, averages, and more.",
            inputSchema={
                "type": "object",
                "properties": {
                    "player_id": {
                        "type": "string",
                        "description": "NBA player ID",
                    }
                },
                "required": ["player_id"],
            },
        ),
        Tool(
            name="get_player_hustle_stats",
            description="Get hustle statistics including deflections, charges drawn, screen assists, loose balls recovered, and box outs.",
            inputSchema={
                "type": "object",
                "properties": {
                    "player_id": {
                        "type": "string",
                        "description": "NBA player ID",
                    },
                    "season": {
                        "type": "string",
                        "description": "Season in format YYYY-YY (e.g., '2024-25'). Defaults to current season.",
                    }
                },
                "required": ["player_id"],
            },
        ),
        Tool(
            name="get_league_hustle_leaders",
            description="Get league leaders in hustle stats categories (deflections, charges, screen assists, loose balls, box outs).",
            inputSchema={
                "type": "object",
                "properties": {
                    "stat_category": {
                        "type": "string",
                        "description": "Hustle stat category: 'deflections', 'charges', 'screen_assists', 'loose_balls', 'box_outs'. Defaults to 'deflections'.",
                        "default": "deflections"
                    },
                    "season": {
                        "type": "string",
                        "description": "Season in format YYYY-YY (e.g., '2024-25'). Defaults to current season.",
                    }
                },
            },
        ),
        Tool(
            name="get_player_defense_stats",
            description="Get defensive impact statistics showing opponent field goal percentage when defended by this player.",
            inputSchema={
                "type": "object",
                "properties": {
                    "player_id": {
                        "type": "string",
                        "description": "NBA player ID",
                    },
                    "season": {
                        "type": "string",
                        "description": "Season in format YYYY-YY (e.g., '2024-25'). Defaults to current season.",
                    }
                },
                "required": ["player_id"],
            },
        ),
        Tool(
            name="get_all_time_leaders",
            description="Get all-time career leaders across NBA history for any stat category (points, rebounds, assists, etc.).",
            inputSchema={
                "type": "object",
                "properties": {
                    "stat_category": {
                        "type": "string",
                        "description": "Stat category: 'points', 'rebounds', 'assists', 'steals', 'blocks', 'games', 'minutes'. Defaults to 'points'.",
                        "default": "points"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Number of leaders to return (default: 10, max: 50)",
                        "default": 10
                    }
                },
            },
        ),

        # Team Tools
        Tool(
            name="get_all_teams",
            description="Get list of all NBA teams with IDs, names, and basic info.",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        Tool(
            name="get_team_roster",
            description="Get current roster for a specific NBA team.",
            inputSchema={
                "type": "object",
                "properties": {
                    "team_id": {
                        "type": "string",
                        "description": "NBA team ID",
                    },
                    "season": {
                        "type": "string",
                        "description": "Season in format YYYY-YY (e.g., '2024-25'). Defaults to current season.",
                    }
                },
                "required": ["team_id"],
            },
        ),

        # League Tools
        Tool(
            name="get_standings",
            description="Get current NBA standings for all teams.",
            inputSchema={
                "type": "object",
                "properties": {
                    "season": {
                        "type": "string",
                        "description": "Season in format YYYY-YY (e.g., '2024-25'). Defaults to current season.",
                    }
                },
            },
        ),
        Tool(
            name="get_league_leaders",
            description="Get statistical leaders across the league for a specific stat category.",
            inputSchema={
                "type": "object",
                "properties": {
                    "stat_type": {
                        "type": "string",
                        "description": "Stat type: 'Points', 'Assists', 'Rebounds', 'Steals', 'Blocks', 'FG%', '3P%', 'FT%', etc.",
                        "default": "Points"
                    },
                    "season": {
                        "type": "string",
                        "description": "Season in format YYYY-YY (e.g., '2024-25'). Defaults to current season.",
                    }
                },
            },
        ),
        Tool(
            name="get_schedule",
            description="Get upcoming NBA games schedule for a specific team. Shows future games with dates, times, locations, and opponent info.",
            inputSchema={
                "type": "object",
                "properties": {
                    "team_id": {
                        "type": "string",
                        "description": "Team ID to get schedule for (required - use get_all_teams to find IDs)",
                    },
                    "days_ahead": {
                        "type": "integer",
                        "description": "Number of days ahead to fetch (default: 7, max: 90)",
                        "default": 7
                    }
                },
                "required": ["team_id"],
            },
        ),
        Tool(
            name="get_player_awards",
            description="Get all awards and accolades for a specific player including MVP, Championships, All-Star selections, All-NBA teams, and more.",
            inputSchema={
                "type": "object",
                "properties": {
                    "player_id": {
                        "type": "string",
                        "description": "NBA player ID (use search_players to find)",
                    }
                },
                "required": ["player_id"],
            },
        ),
        Tool(
            name="get_season_awards",
            description="Get major award winners for a specific NBA season including MVP, ROTY, DPOY, MIP, 6MOY, Finals MVP, and All-NBA teams.",
            inputSchema={
                "type": "object",
                "properties": {
                    "season": {
                        "type": "string",
                        "description": "Season in format YYYY-YY (e.g., '2002-03'). Defaults to current season.",
                    }
                },
            },
        ),

        # Shot Chart & Shooting Tools
        Tool(
            name="get_shot_chart",
            description="Get shot chart data with X/Y coordinates for every shot attempt by a player. Useful for visualizing shooting patterns and hot zones.",
            inputSchema={
                "type": "object",
                "properties": {
                    "player_id": {
                        "type": "string",
                        "description": "NBA player ID (use search_players to find)",
                    },
                    "season": {
                        "type": "string",
                        "description": "Season in format YYYY-YY (e.g., '2024-25'). Defaults to current season.",
                    },
                    "game_id": {
                        "type": "string",
                        "description": "Optional: Specific game ID to get shot chart for single game",
                    }
                },
                "required": ["player_id"],
            },
        ),
        Tool(
            name="get_shooting_splits",
            description="Get shooting percentages by zone and distance (paint, mid-range, 3PT, corner 3, etc.). Shows where player is most efficient.",
            inputSchema={
                "type": "object",
                "properties": {
                    "player_id": {
                        "type": "string",
                        "description": "NBA player ID (use search_players to find)",
                    },
                    "season": {
                        "type": "string",
                        "description": "Season in format YYYY-YY (e.g., '2024-25'). Defaults to current season.",
                    }
                },
                "required": ["player_id"],
            },
        ),

        # Play-by-Play & Rotation Tools
        Tool(
            name="get_play_by_play",
            description="Get detailed play-by-play data for a game including every action, timestamp, score changes, and descriptions. Shows the complete game narrative.",
            inputSchema={
                "type": "object",
                "properties": {
                    "game_id": {
                        "type": "string",
                        "description": "NBA game ID (10 digits, e.g., '0022400123')",
                    },
                    "start_period": {
                        "type": "integer",
                        "description": "Starting period/quarter (default: 1)",
                    },
                    "end_period": {
                        "type": "integer",
                        "description": "Ending period/quarter (default: 10 for overtime games)",
                    }
                },
                "required": ["game_id"],
            },
        ),
        Tool(
            name="get_game_rotation",
            description="Get player rotation and substitution patterns for a game. Shows when players entered/exited, minutes played, and performance during their time on court.",
            inputSchema={
                "type": "object",
                "properties": {
                    "game_id": {
                        "type": "string",
                        "description": "NBA game ID (10 digits, e.g., '0022400123')",
                    }
                },
                "required": ["game_id"],
            },
        ),

        # Advanced Stats Tools
        Tool(
            name="get_player_advanced_stats",
            description="Get advanced statistics for a player including TS%, ORtg/DRtg, USG%, AST%, REB%, PIE, and more. Shows efficiency and impact metrics.",
            inputSchema={
                "type": "object",
                "properties": {
                    "player_id": {
                        "type": "string",
                        "description": "NBA player ID (use search_players to find)",
                    },
                    "season": {
                        "type": "string",
                        "description": "Season in format YYYY-YY (e.g., '2024-25'). Defaults to current season.",
                    }
                },
                "required": ["player_id"],
            },
        ),
        Tool(
            name="get_team_advanced_stats",
            description="Get advanced team statistics including ORtg/DRtg, pace, net rating, TS%, and four factors. Shows team efficiency and playing style.",
            inputSchema={
                "type": "object",
                "properties": {
                    "team_id": {
                        "type": "string",
                        "description": "NBA team ID (use get_all_teams to find)",
                    },
                    "season": {
                        "type": "string",
                        "description": "Season in format YYYY-YY (e.g., '2024-25'). Defaults to current season.",
                    }
                },
                "required": ["team_id"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: Any) -> list[TextContent]:
    """Handle tool calls for NBA data."""

    try:
        if name == "get_server_info":
            from nba_mcp_server import __version__

            # We don't expose full env for safety; just key runtime knobs.
            result = "NBA MCP Server Info:\n\n"
            result += f"Version: {__version__}\n"
            result += f"HTTP timeout (s): {NBA_MCP_HTTP_TIMEOUT_SECONDS}\n"
            result += f"Max concurrency: {NBA_MCP_MAX_CONCURRENCY}\n"
            result += f"Retries: {NBA_MCP_RETRIES}\n"
            result += f"Cache TTL (stats, s): {NBA_MCP_CACHE_TTL_SECONDS}\n"
            result += f"Cache TTL (live, s): {NBA_MCP_LIVE_CACHE_TTL_SECONDS}\n"
            result += f"TLS verify enabled: {NBA_MCP_TLS_VERIFY}\n"
            result += f"Log level: {log_level}\n"
            return [TextContent(type="text", text=result)]

        if name == "resolve_team_id":
            query = str(arguments.get("query", "")).strip().lower()
            limit = int(arguments.get("limit", 5) or 5)

            if not query:
                return [TextContent(type="text", text="Please provide a non-empty team query.")]

            scored: list[tuple[float, int, str]] = []
            for team_id, team_name in NBA_TEAMS.items():
                name_l = team_name.lower()
                if query in name_l:
                    score = 1.0
                else:
                    score = difflib.SequenceMatcher(None, query, name_l).ratio()
                scored.append((score, team_id, team_name))

            scored.sort(key=lambda x: x[0], reverse=True)
            top = [s for s in scored if s[0] >= 0.3][: max(1, limit)]

            if not top:
                return [TextContent(type="text", text=f"No teams matched '{arguments.get('query')}'. Try a city or nickname (e.g., 'Boston', 'Lakers').")]

            result = f"Team ID matches for '{arguments.get('query')}':\n\n"
            for score, team_id, team_name in top:
                result += f"ID: {team_id} | {team_name} (match: {score:.2f})\n"
            return [TextContent(type="text", text=result)]

        if name == "resolve_player_id":
            query_raw = str(arguments.get("query", "")).strip()
            query = query_raw.lower()
            active_only = bool(arguments.get("active_only", False))
            limit = int(arguments.get("limit", 10) or 10)

            if not query_raw:
                return [TextContent(type="text", text="Please provide a non-empty player query.")]

            url = f"{NBA_STATS_API}/commonallplayers"
            params = {
                "LeagueID": "00",
                "Season": get_current_season(),
                "IsOnlyCurrentSeason": "0",
            }

            data = await fetch_nba_data(url, params)
            if not data:
                return [TextContent(type="text", text="Error fetching player data. Please try again.")]

            rows = safe_get(data, "resultSets", 0, "rowSet", default=[])
            if not rows or rows == "N/A":
                return [TextContent(type="text", text="No player data returned by the NBA API.")]

            matches: list[tuple[float, int, str, int]] = []
            for row in rows:
                # commonallplayers: PERSON_ID, ..., DISPLAY_FIRST_LAST at index 2, IS_ACTIVE near end (often 11)
                player_id = _to_int(row[0] if isinstance(row, list) and row else None)
                if player_id is None:
                    continue
                player_name = str(row[2]) if len(row) > 2 else ""
                is_active = int(row[11]) if len(row) > 11 and str(row[11]).isdigit() else 1

                if active_only and is_active != 1:
                    continue

                name_l = player_name.lower()
                if query in name_l:
                    score = 1.0
                else:
                    score = difflib.SequenceMatcher(None, query, name_l).ratio()
                if score >= 0.35:
                    matches.append((score, player_id, player_name, is_active))

            matches.sort(key=lambda x: (x[3], x[0]), reverse=True)  # active first, then score
            top = matches[: max(1, limit)]

            if not top:
                return [TextContent(type="text", text=f"No players matched '{query_raw}'. Try a different spelling or a shorter substring.")]

            result = f"Player ID matches for '{query_raw}':\n\n"
            for score, pid, name_, is_active in top:
                status = "Active" if is_active == 1 else "Inactive"
                result += f"ID: {pid} | Name: {name_} | Status: {status} (match: {score:.2f})\n"
            return [TextContent(type="text", text=result)]

        if name == "find_game_id":
            date_str = str(arguments.get("date", "")).strip()
            home_q = str(arguments.get("home_team", "")).strip().lower()
            away_q = str(arguments.get("away_team", "")).strip().lower()
            team_q = str(arguments.get("team", "")).strip().lower()
            limit = int(arguments.get("limit", 10) or 10)

            try:
                date_obj = datetime.strptime(date_str, "%Y%m%d")
                formatted_date = date_obj.strftime("%Y-%m-%d")
            except ValueError:
                return [TextContent(type="text", text="Invalid date format. Use YYYYMMDD (e.g., '20241103')")]

            # Try live scoreboard first; if blocked/unavailable (e.g. 403), fall back to stats API scoreboardv2.
            url = f"{NBA_LIVE_API}/scoreboard/scoreboard_{date_str}.json"
            data = await fetch_nba_data(url)

            games = safe_get(data, "scoreboard", "games", default=[]) if data else []
            live_ok = bool(games and games != "N/A")

            # Fallback: stats API scoreboardv2
            if not live_ok:
                stats_games = await _get_scoreboard_games_stats_api(date_obj)
                if stats_games is None:
                    return [TextContent(type="text", text=f"No data available for {formatted_date}. The NBA APIs may be unavailable or blocked.")]
                if not stats_games:
                    return [TextContent(type="text", text=f"No games found for {formatted_date}.")]

                # Filter using simple substring matching on team names.
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
                    return [TextContent(type="text", text=f"No games matched your filters for {formatted_date}. Try using only 'team' or check spelling.")]

                result = f"Game ID matches for {formatted_date}:\n\n"
                for g in filtered_stats[: max(1, limit)]:
                    result += f"Game ID: {g.get('game_id', 'N/A')}\n"
                    result += f"{g.get('away_name', 'Away')} @ {g.get('home_name', 'Home')}\n"
                    result += f"Status: {g.get('status', 'Unknown')}\n\n"
                return [TextContent(type="text", text=result)]

            def _matches(team_obj: dict, q: str) -> bool:
                if not q:
                    return True
                name = str(safe_get(team_obj, "teamName", default="")).lower()
                city = str(safe_get(team_obj, "teamCity", default="")).lower()
                return q in name or q in city or q in f"{city} {name}".strip()

            filtered = []
            for g in games:
                home = safe_get(g, "homeTeam", default={})
                away = safe_get(g, "awayTeam", default={})
                if home == "N/A" or away == "N/A":
                    continue

                if home_q and not _matches(home, home_q):
                    continue
                if away_q and not _matches(away, away_q):
                    continue
                if team_q and not (_matches(home, team_q) or _matches(away, team_q)):
                    continue

                filtered.append(g)

            if not filtered:
                return [TextContent(type="text", text=f"No games matched your filters for {formatted_date}. Try using only 'team' or check spelling.")]

            result = f"Game ID matches for {formatted_date}:\n\n"
            for g in filtered[: max(1, limit)]:
                gid = safe_get(g, "gameId", default="N/A")
                home = safe_get(g, "homeTeam", default={})
                away = safe_get(g, "awayTeam", default={})
                status = safe_get(g, "gameStatusText", default="Unknown")
                result += f"Game ID: {gid}\n"
                result += f"{safe_get(away, 'teamName')} @ {safe_get(home, 'teamName')}\n"
                result += f"Status: {status}\n\n"
            return [TextContent(type="text", text=result)]

        # Live Game Tools
        if name == "get_todays_scoreboard":
            # Get today's scoreboard
            url = f"{NBA_LIVE_API}/scoreboard/todaysScoreboard_00.json"
            data = await fetch_nba_data(url)

            if not data:
                # Fallback to stats API scoreboardv2 for today's date
                today = datetime.now()
                stats_games = await _get_scoreboard_games_stats_api(today)
                if stats_games is None:
                    return [TextContent(type="text", text="Error fetching today's scoreboard. Please try again.")]
                if not stats_games:
                    return [TextContent(type="text", text=f"No games scheduled for {today.strftime('%Y-%m-%d')}.")]

                result = f"NBA Games for {today.strftime('%Y-%m-%d')}:\n\n"
                for g in stats_games:
                    result += f"Game ID: {g.get('game_id', 'N/A')}\n"
                    result += f"{g.get('away_name', 'Away')} ({g.get('away_score', 'N/A')}) @ {g.get('home_name', 'Home')} ({g.get('home_score', 'N/A')})\n"
                    result += f"Status: {g.get('status', 'Unknown')}\n\n"
                return [TextContent(type="text", text=result)]

            scoreboard = safe_get(data, "scoreboard")
            if not scoreboard or scoreboard == "N/A":
                return [TextContent(type="text", text="No scoreboard data available.")]

            games = safe_get(scoreboard, "games", default=[])
            game_date = safe_get(scoreboard, "gameDate", default=datetime.now().strftime("%Y-%m-%d"))

            if not games:
                return [TextContent(type="text", text=f"No games scheduled for {game_date}.")]

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

                result += f"Game ID: {game_id}\n"
                result += f"{away_name} ({away_score}) @ {home_name} ({home_score})\n"
                result += f"Status: {game_status}\n"

                # Add quarter info if available
                period = safe_get(game, "period", default=0)
                if period > 0:
                    result += f"Period: Q{period}\n"

                # Add leaders if available
                game_leaders = safe_get(game, "gameLeaders")
                if game_leaders and game_leaders != "N/A":
                    home_leader = safe_get(game_leaders, "homeLeaders")
                    away_leader = safe_get(game_leaders, "awayLeaders")

                    if home_leader and home_leader != "N/A":
                        leader_name = safe_get(home_leader, "name")
                        leader_pts = safe_get(home_leader, "points")
                        if leader_name != "N/A":
                            result += f"  {home_name} Leader: {leader_name} ({leader_pts} PTS)\n"

                    if away_leader and away_leader != "N/A":
                        leader_name = safe_get(away_leader, "name")
                        leader_pts = safe_get(away_leader, "points")
                        if leader_name != "N/A":
                            result += f"  {away_name} Leader: {leader_name} ({leader_pts} PTS)\n"

                result += "\n"

            return [TextContent(type="text", text=result)]

        elif name == "get_scoreboard_by_date":
            date_str = arguments["date"]

            # Validate date format
            try:
                date_obj = datetime.strptime(date_str, "%Y%m%d")
                formatted_date = date_obj.strftime("%Y-%m-%d")
            except ValueError:
                return [TextContent(type="text", text="Invalid date format. Use YYYYMMDD (e.g., '20241103')")]

            url = f"{NBA_LIVE_API}/scoreboard/scoreboard_{date_str}.json"
            data = await fetch_nba_data(url)

            if not data:
                stats_games = await _get_scoreboard_games_stats_api(date_obj)
                if stats_games is None:
                    return [TextContent(type="text", text=f"No data available for {formatted_date}. The game data might not be available yet or the date might be incorrect.")]
                if not stats_games:
                    return [TextContent(type="text", text=f"No games found for {formatted_date}.")]

                result = f"NBA Games for {formatted_date}:\n\n"
                for g in stats_games:
                    result += f"Game ID: {g.get('game_id', 'N/A')}\n"
                    result += f"{g.get('away_name', 'Away')} ({g.get('away_score', 'N/A')}) @ {g.get('home_name', 'Home')} ({g.get('home_score', 'N/A')})\n"
                    result += f"Status: {g.get('status', 'Unknown')}\n\n"
                return [TextContent(type="text", text=result)]

            scoreboard = safe_get(data, "scoreboard")
            games = safe_get(scoreboard, "games", default=[])

            if not games:
                return [TextContent(type="text", text=f"No games found for {formatted_date}.")]

            result = f"NBA Games for {formatted_date}:\n\n"

            for game in games:
                home_team = safe_get(game, "homeTeam", default={})
                away_team = safe_get(game, "awayTeam", default={})

                result += f"Game ID: {safe_get(game, 'gameId')}\n"
                result += f"{safe_get(away_team, 'teamName')} ({safe_get(away_team, 'score')}) @ "
                result += f"{safe_get(home_team, 'teamName')} ({safe_get(home_team, 'score')})\n"
                result += f"Status: {safe_get(game, 'gameStatusText')}\n\n"

            return [TextContent(type="text", text=result)]

        elif name == "get_game_details":
            game_id = arguments["game_id"]

            # Extract date from game_id (format: 00SYYYYMMDD)
            # For season games, the format is typically 002SYYYYMMDDXXXX where S is season, YYYYMMDD is date
            try:
                # Try to get today's scoreboard and find the game
                url = f"{NBA_LIVE_API}/scoreboard/todaysScoreboard_00.json"
                data = await fetch_nba_data(url)

                if data:
                    games = safe_get(data, "scoreboard", "games", default=[])
                    game = next((g for g in games if safe_get(g, "gameId") == game_id), None)

                    if game:
                        home_team = safe_get(game, "homeTeam", default={})
                        away_team = safe_get(game, "awayTeam", default={})

                        result = f"Game Details for {game_id}:\n\n"
                        result += f"{safe_get(away_team, 'teamName')} @ {safe_get(home_team, 'teamName')}\n"
                        result += f"Score: {safe_get(away_team, 'score')} - {safe_get(home_team, 'score')}\n"
                        result += f"Status: {safe_get(game, 'gameStatusText')}\n"
                        result += f"Period: Q{safe_get(game, 'period', default=0)}\n\n"

                        # Team statistics
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

                        return [TextContent(type="text", text=result)]

                return [TextContent(type="text", text=f"Game {game_id} not found in today's games. Try using get_scoreboard_by_date first to find the correct game ID.")]

            except Exception as e:
                logger.error(f"Error fetching game details: {e}")
                return [TextContent(type="text", text=f"Error fetching game details: {str(e)}")]

        elif name == "get_box_score":
            game_id = arguments["game_id"]

            # First, try to get data from live boxscore endpoint (more reliable for recent/live games)
            url = f"{NBA_LIVE_API}/boxscore/boxscore_{game_id}.json"
            live_data = await fetch_nba_data(url)

            if live_data and safe_get(live_data, "game") != "N/A":
                game = safe_get(live_data, "game", default={})
                home_team = safe_get(game, "homeTeam", default={})
                away_team = safe_get(game, "awayTeam", default={})

                result = f"Box Score for Game {game_id}:\n"
                result += f"{safe_get(away_team, 'teamName')} @ {safe_get(home_team, 'teamName')}\n"
                result += f"Final Score: {safe_get(away_team, 'score')} - {safe_get(home_team, 'score')}\n\n"

                result += "TEAM STATS:\n"

                # Away team stats
                away_stats = safe_get(away_team, "statistics", default={})
                if away_stats != "N/A":
                    result += f"\n{safe_get(away_team, 'teamName')}:\n"
                    result += f"  FG: {safe_get(away_stats, 'fieldGoalsMade')}/{safe_get(away_stats, 'fieldGoalsAttempted')}"
                    fg_pct = safe_get(away_stats, 'fieldGoalsPercentage', default=0)
                    if fg_pct != "N/A":
                        result += f" ({format_stat(fg_pct, True)})"
                    result += f"\n  3P: {safe_get(away_stats, 'threePointersMade')}/{safe_get(away_stats, 'threePointersAttempted')}\n"
                    result += f"  FT: {safe_get(away_stats, 'freeThrowsMade')}/{safe_get(away_stats, 'freeThrowsAttempted')}\n"
                    result += f"  Rebounds: {safe_get(away_stats, 'reboundsTotal')} "
                    result += f"(OFF: {safe_get(away_stats, 'reboundsOffensive')}, DEF: {safe_get(away_stats, 'reboundsDefensive')})\n"
                    result += f"  Assists: {safe_get(away_stats, 'assists')}\n"
                    result += f"  Steals: {safe_get(away_stats, 'steals')}\n"
                    result += f"  Blocks: {safe_get(away_stats, 'blocks')}\n"
                    result += f"  Turnovers: {safe_get(away_stats, 'turnovers')}\n"

                # Home team stats
                home_stats = safe_get(home_team, "statistics", default={})
                if home_stats != "N/A":
                    result += f"\n{safe_get(home_team, 'teamName')}:\n"
                    result += f"  FG: {safe_get(home_stats, 'fieldGoalsMade')}/{safe_get(home_stats, 'fieldGoalsAttempted')}"
                    fg_pct = safe_get(home_stats, 'fieldGoalsPercentage', default=0)
                    if fg_pct != "N/A":
                        result += f" ({format_stat(fg_pct, True)})"
                    result += f"\n  3P: {safe_get(home_stats, 'threePointersMade')}/{safe_get(home_stats, 'threePointersAttempted')}\n"
                    result += f"  FT: {safe_get(home_stats, 'freeThrowsMade')}/{safe_get(home_stats, 'freeThrowsAttempted')}\n"
                    result += f"  Rebounds: {safe_get(home_stats, 'reboundsTotal')} "
                    result += f"(OFF: {safe_get(home_stats, 'reboundsOffensive')}, DEF: {safe_get(home_stats, 'reboundsDefensive')})\n"
                    result += f"  Assists: {safe_get(home_stats, 'assists')}\n"
                    result += f"  Steals: {safe_get(home_stats, 'steals')}\n"
                    result += f"  Blocks: {safe_get(home_stats, 'blocks')}\n"
                    result += f"  Turnovers: {safe_get(home_stats, 'turnovers')}\n"

                # Player stats
                result += "\n" + "="*70 + "\n"
                result += "PLAYER STATS:\n\n"

                # Away team players
                away_players = safe_get(away_team, "players", default=[])
                if away_players and away_players != "N/A" and len(away_players) > 0:
                    result += f"\n{safe_get(away_team, 'teamName')}:\n"
                    result += f"{'Player':<25} {'MIN':<6} {'PTS':<5} {'REB':<5} {'AST':<5} {'FG':<10} {'3P':<10}\n"
                    result += "-" * 75 + "\n"

                    for player in away_players:
                        stats = safe_get(player, "statistics", default={})
                        if stats == "N/A":
                            continue

                        name = safe_get(player, "name", default="Unknown")
                        minutes = safe_get(stats, "minutes", default="0:00")
                        pts = safe_get(stats, "points", default=0)
                        reb = safe_get(stats, "reboundsTotal", default=0)
                        ast = safe_get(stats, "assists", default=0)
                        fgm = safe_get(stats, "fieldGoalsMade", default=0)
                        fga = safe_get(stats, "fieldGoalsAttempted", default=0)
                        fg3m = safe_get(stats, "threePointersMade", default=0)
                        fg3a = safe_get(stats, "threePointersAttempted", default=0)

                        if minutes and minutes != "0:00":
                            fg_str = f"{fgm}/{fga}"
                            fg3_str = f"{fg3m}/{fg3a}"
                            result += f"{name:<25} {minutes:<6} {pts:<5} {reb:<5} {ast:<5} {fg_str:<10} {fg3_str:<10}\n"

                # Home team players
                home_players = safe_get(home_team, "players", default=[])
                if home_players and home_players != "N/A" and len(home_players) > 0:
                    result += f"\n{safe_get(home_team, 'teamName')}:\n"
                    result += f"{'Player':<25} {'MIN':<6} {'PTS':<5} {'REB':<5} {'AST':<5} {'FG':<10} {'3P':<10}\n"
                    result += "-" * 75 + "\n"

                    for player in home_players:
                        stats = safe_get(player, "statistics", default={})
                        if stats == "N/A":
                            continue

                        name = safe_get(player, "name", default="Unknown")
                        minutes = safe_get(stats, "minutes", default="0:00")
                        pts = safe_get(stats, "points", default=0)
                        reb = safe_get(stats, "reboundsTotal", default=0)
                        ast = safe_get(stats, "assists", default=0)
                        fgm = safe_get(stats, "fieldGoalsMade", default=0)
                        fga = safe_get(stats, "fieldGoalsAttempted", default=0)
                        fg3m = safe_get(stats, "threePointersMade", default=0)
                        fg3a = safe_get(stats, "threePointersAttempted", default=0)

                        if minutes and minutes != "0:00":
                            fg_str = f"{fgm}/{fga}"
                            fg3_str = f"{fg3m}/{fg3a}"
                            result += f"{name:<25} {minutes:<6} {pts:<5} {reb:<5} {ast:<5} {fg_str:<10} {fg3_str:<10}\n"

                return [TextContent(type="text", text=result)]

            # Fallback to stats API if live data not available
            url = f"{NBA_STATS_API}/boxscoretraditionalv2"
            params = {
                "GameID": game_id,
                "StartPeriod": "0",
                "EndPeriod": "10",
                "RangeType": "0",
                "StartRange": "0",
                "EndRange": "0"
            }

            data = await fetch_nba_data(url, params)

            if not data:
                return [TextContent(type="text", text="Error fetching box score. The game stats are not available yet.")]

            # Get player stats (first result set) and team stats (second result set)
            player_stats_rows = safe_get(data, "resultSets", 0, "rowSet", default=[])
            team_stats_rows = safe_get(data, "resultSets", 1, "rowSet", default=[])

            if not player_stats_rows or player_stats_rows == "N/A" or len(player_stats_rows) == 0:
                return [TextContent(type="text", text=f"Box score not available for game {game_id}. Try again in a few minutes as stats are still being processed.")]

            result = f"Box Score for Game {game_id}:\n\n"

            # Team Stats Summary
            if team_stats_rows:
                result += "TEAM STATS:\n"
                for team in team_stats_rows:
                    team_abbr = safe_get(team, 1, default="N/A")
                    pts = safe_get(team, 24, default=0)
                    fgm = safe_get(team, 6, default=0)
                    fga = safe_get(team, 7, default=0)
                    fg_pct = safe_get(team, 8, default=0)
                    fg3m = safe_get(team, 9, default=0)
                    fg3a = safe_get(team, 10, default=0)
                    ftm = safe_get(team, 13, default=0)
                    fta = safe_get(team, 14, default=0)
                    reb = safe_get(team, 18, default=0)
                    ast = safe_get(team, 19, default=0)
                    stl = safe_get(team, 21, default=0)
                    blk = safe_get(team, 22, default=0)
                    tov = safe_get(team, 23, default=0)

                    result += f"\n{team_abbr}: {pts} PTS\n"
                    result += f"  FG: {fgm}/{fga} ({format_stat(fg_pct, True)})\n"
                    result += f"  3P: {fg3m}/{fg3a}\n"
                    result += f"  FT: {ftm}/{fta}\n"
                    result += f"  REB: {reb} | AST: {ast} | STL: {stl} | BLK: {blk} | TOV: {tov}\n"

            # Player Stats by Team
            result += "\n" + "="*60 + "\n"
            result += "PLAYER STATS:\n\n"

            # Group players by team
            teams = {}
            for player in player_stats_rows:
                team_abbr = safe_get(player, 1, default="N/A")
                if team_abbr not in teams:
                    teams[team_abbr] = []
                teams[team_abbr].append(player)

            for team_abbr, players in teams.items():
                result += f"\n{team_abbr}:\n"
                result += f"{'Player':<20} {'MIN':<6} {'PTS':<5} {'REB':<5} {'AST':<5} {'FG':<8} {'3P':<8}\n"
                result += "-" * 70 + "\n"

                for player in players:
                    player_name = safe_get(player, 5, default="N/A")
                    minutes = safe_get(player, 8, default="0")
                    pts = safe_get(player, 26, default=0)
                    reb = safe_get(player, 20, default=0)
                    ast = safe_get(player, 21, default=0)
                    fgm = safe_get(player, 9, default=0)
                    fga = safe_get(player, 10, default=0)
                    fg3m = safe_get(player, 12, default=0)
                    fg3a = safe_get(player, 13, default=0)

                    # Skip players who didn't play
                    if minutes and minutes != "0" and minutes != 0:
                        fg_str = f"{fgm}/{fga}"
                        fg3_str = f"{fg3m}/{fg3a}"

                        result += f"{player_name:<20} {str(minutes):<6} {pts:<5} {reb:<5} {ast:<5} {fg_str:<8} {fg3_str:<8}\n"

            return [TextContent(type="text", text=result)]

        # Player Tools
        elif name == "search_players":
            query = arguments["query"].lower()

            # Get all players from stats API (including retired players)
            url = f"{NBA_STATS_API}/commonallplayers"
            params = {
                "LeagueID": "00",
                "Season": get_current_season(),
                "IsOnlyCurrentSeason": "0"  # 0 = all players including retired
            }

            data = await fetch_nba_data(url, params)

            if not data:
                return [TextContent(type="text", text="Error fetching player data. Please try again.")]

            # Parse response
            headers = safe_get(data, "resultSets", 0, "headers", default=[])
            rows = safe_get(data, "resultSets", 0, "rowSet", default=[])

            if not rows:
                return [TextContent(type="text", text="No players found.")]

            # Find matching players
            matching_players = []
            for row in rows:
                if len(row) > 2:
                    player_name = str(row[2]).lower()  # DISPLAY_FIRST_LAST
                    if query in player_name:
                        matching_players.append({
                            "id": row[0],  # PERSON_ID
                            "name": row[2],  # DISPLAY_FIRST_LAST
                            "is_active": row[11] if len(row) > 11 else 1  # IS_ACTIVE
                        })

            if not matching_players:
                return [TextContent(type="text", text=f"No players found matching '{arguments['query']}'.")]

            result = f"Found {len(matching_players)} player(s):\n\n"
            for player in matching_players[:20]:  # Limit to 20 results
                status = "Active" if player["is_active"] == 1 else "Inactive"
                result += f"ID: {player['id']} | Name: {player['name']} | Status: {status}\n"

            if len(matching_players) > 20:
                result += f"\n... and {len(matching_players) - 20} more. Try a more specific search."

            return [TextContent(type="text", text=result)]

        elif name == "get_player_info":
            player_id = arguments["player_id"]

            url = f"{NBA_STATS_API}/commonplayerinfo"
            params = {"PlayerID": player_id}

            data = await fetch_nba_data(url, params)

            if not data:
                return [TextContent(type="text", text="Error fetching player info. Please try again.")]

            # Parse player info
            player_data = safe_get(data, "resultSets", 0, "rowSet", 0, default=[])

            if not player_data or player_data == "N/A":
                return [TextContent(type="text", text="Player not found.")]

            result = "Player Information:\n\n"
            result += f"Name: {safe_get(player_data, 3)}\n"  # DISPLAY_FIRST_LAST
            result += f"Jersey: #{safe_get(player_data, 13)}\n"  # JERSEY
            result += f"Position: {safe_get(player_data, 14)}\n"  # POSITION
            result += f"Height: {safe_get(player_data, 10)}\n"  # HEIGHT
            result += f"Weight: {safe_get(player_data, 11)} lbs\n"  # WEIGHT
            result += f"Birth Date: {safe_get(player_data, 6)}\n"  # BIRTHDATE
            result += f"Country: {safe_get(player_data, 8)}\n"  # COUNTRY
            result += f"School: {safe_get(player_data, 7)}\n"  # SCHOOL
            result += f"Draft Year: {safe_get(player_data, 27)}\n"  # DRAFT_YEAR
            result += f"Draft Round: {safe_get(player_data, 28)}\n"  # DRAFT_ROUND
            result += f"Draft Number: {safe_get(player_data, 29)}\n"  # DRAFT_NUMBER
            result += f"Team: {safe_get(player_data, 18)}\n"  # TEAM_NAME

            return [TextContent(type="text", text=result)]

        elif name == "get_player_season_stats":
            player_id = arguments["player_id"]
            season = arguments.get("season", get_current_season())

            # Use playercareerstats which returns all seasons - more reliable than playerdashboardbyyearoveryear
            url = f"{NBA_STATS_API}/playercareerstats"
            params = {
                "PlayerID": player_id,
                "PerMode": "PerGame"  # Get per-game averages
            }

            data = await fetch_nba_data(url, params)

            if not data:
                return [TextContent(type="text", text="Error fetching player stats. Please try again.")]

            # Get SeasonTotalsRegularSeason resultSet (contains all regular season stats by year)
            headers = safe_get(data, "resultSets", 0, "headers", default=[])
            all_seasons = safe_get(data, "resultSets", 0, "rowSet", default=[])

            if not all_seasons:
                return [TextContent(type="text", text="No stats found for this player.")]

            # Find the specific season
            season_id_idx = headers.index("SEASON_ID") if "SEASON_ID" in headers else 1
            stats_data = None

            for season_row in all_seasons:
                if safe_get(season_row, season_id_idx) == season:
                    stats_data = season_row
                    break

            if not stats_data:
                return [TextContent(type="text", text=f"No stats found for season {season}. Player may not have played that season.")]

            # Map header indices
            gp_idx = headers.index("GP") if "GP" in headers else 6
            min_idx = headers.index("MIN") if "MIN" in headers else 8
            pts_idx = headers.index("PTS") if "PTS" in headers else 26
            reb_idx = headers.index("REB") if "REB" in headers else 18
            ast_idx = headers.index("AST") if "AST" in headers else 19
            stl_idx = headers.index("STL") if "STL" in headers else 21
            blk_idx = headers.index("BLK") if "BLK" in headers else 22
            fg_pct_idx = headers.index("FG_PCT") if "FG_PCT" in headers else 9
            fg3_pct_idx = headers.index("FG3_PCT") if "FG3_PCT" in headers else 12
            ft_pct_idx = headers.index("FT_PCT") if "FT_PCT" in headers else 15

            result = f"Season Stats ({season}):\n\n"
            result += f"Games Played: {safe_get(stats_data, gp_idx)}\n"
            result += f"Minutes Per Game: {format_stat(safe_get(stats_data, min_idx))}\n"
            result += f"Points Per Game: {format_stat(safe_get(stats_data, pts_idx))}\n"
            result += f"Rebounds Per Game: {format_stat(safe_get(stats_data, reb_idx))}\n"
            result += f"Assists Per Game: {format_stat(safe_get(stats_data, ast_idx))}\n"
            result += f"Steals Per Game: {format_stat(safe_get(stats_data, stl_idx))}\n"
            result += f"Blocks Per Game: {format_stat(safe_get(stats_data, blk_idx))}\n"
            result += f"FG%: {format_stat(safe_get(stats_data, fg_pct_idx), True)}\n"
            result += f"3P%: {format_stat(safe_get(stats_data, fg3_pct_idx), True)}\n"
            result += f"FT%: {format_stat(safe_get(stats_data, ft_pct_idx), True)}\n"

            return [TextContent(type="text", text=result)]

        elif name == "get_player_game_log":
            player_id = arguments["player_id"]
            season = arguments.get("season", get_current_season())

            url = f"{NBA_STATS_API}/playergamelog"
            params = {
                "PlayerID": player_id,
                "Season": season,
                "SeasonType": "Regular Season"
            }

            data = await fetch_nba_data(url, params)

            if not data:
                return [TextContent(type="text", text="Error fetching game log. Please try again.")]

            # Parse game log data
            headers = safe_get(data, "resultSets", 0, "headers", default=[])
            games = safe_get(data, "resultSets", 0, "rowSet", default=[])

            if not games:
                return [TextContent(type="text", text=f"No games found for season {season}.")]

            # Map header indices
            game_date_idx = headers.index("GAME_DATE") if "GAME_DATE" in headers else 2
            matchup_idx = headers.index("MATCHUP") if "MATCHUP" in headers else 3
            wl_idx = headers.index("WL") if "WL" in headers else 4
            min_idx = headers.index("MIN") if "MIN" in headers else 5
            pts_idx = headers.index("PTS") if "PTS" in headers else 24
            reb_idx = headers.index("REB") if "REB" in headers else 18
            ast_idx = headers.index("AST") if "AST" in headers else 19
            fg_pct_idx = headers.index("FG_PCT") if "FG_PCT" in headers else 9

            # Find highest scoring game
            max_pts = 0
            max_pts_game = None
            for game in games:
                pts = safe_get(game, pts_idx, default=0)
                try:
                    pts_val = float(pts) if pts else 0
                    if pts_val > max_pts:
                        max_pts = pts_val
                        max_pts_game = game
                except (ValueError, TypeError):
                    pass

            result = f"Game Log - {season} ({len(games)} games):\n\n"

            if max_pts_game:
                result += "HIGHEST SCORING GAME:\n"
                result += f"Date: {safe_get(max_pts_game, game_date_idx)}\n"
                result += f"Matchup: {safe_get(max_pts_game, matchup_idx)}\n"
                result += f"Result: {safe_get(max_pts_game, wl_idx)}\n"
                result += f"Points: {safe_get(max_pts_game, pts_idx)}\n"
                result += f"Rebounds: {safe_get(max_pts_game, reb_idx)}\n"
                result += f"Assists: {safe_get(max_pts_game, ast_idx)}\n"
                result += f"Minutes: {safe_get(max_pts_game, min_idx)}\n"
                result += f"FG%: {format_stat(safe_get(max_pts_game, fg_pct_idx), True)}\n"

            result += "\n\nALL GAMES (showing top 10 by points):\n\n"

            # Sort by points descending
            sorted_games = sorted(games, key=lambda g: float(safe_get(g, pts_idx, default=0)) if safe_get(g, pts_idx) else 0, reverse=True)

            for i, game in enumerate(sorted_games[:10], 1):
                result += f"{i}. {safe_get(game, game_date_idx)} - {safe_get(game, matchup_idx)} ({safe_get(game, wl_idx)})\n"
                result += f"   {safe_get(game, pts_idx)} PTS, {safe_get(game, reb_idx)} REB, {safe_get(game, ast_idx)} AST, {safe_get(game, min_idx)} MIN\n"

            return [TextContent(type="text", text=result)]

        elif name == "get_player_career_stats":
            player_id = arguments["player_id"]

            url = f"{NBA_STATS_API}/playercareerstats"
            params = {
                "PlayerID": player_id,
                "PerMode": "Totals"
            }

            data = await fetch_nba_data(url, params)

            if not data:
                return [TextContent(type="text", text="Error fetching career stats. Please try again.")]

            # Parse career totals (Regular Season)
            career_totals = safe_get(data, "resultSets", 0, "rowSet", default=[])

            if not career_totals or career_totals == "N/A" or len(career_totals) == 0:
                return [TextContent(type="text", text="No career stats found for this player.")]

            # Calculate career totals by summing all seasons
            total_games = 0
            total_points = 0
            total_rebounds = 0
            total_assists = 0
            total_steals = 0
            total_blocks = 0
            total_minutes = 0
            total_fgm = 0
            total_fga = 0
            total_fg3m = 0
            total_fg3a = 0
            total_ftm = 0
            total_fta = 0

            # Sum up all seasons
            for season in career_totals:
                if len(season) > 26:
                    total_games += float(season[6]) if season[6] else 0  # GP
                    total_minutes += float(season[8]) if season[8] else 0  # MIN
                    total_fgm += float(season[9]) if season[9] else 0  # FGM
                    total_fga += float(season[10]) if season[10] else 0  # FGA
                    total_fg3m += float(season[12]) if season[12] else 0  # FG3M
                    total_fg3a += float(season[13]) if season[13] else 0  # FG3A
                    total_ftm += float(season[15]) if season[15] else 0  # FTM
                    total_fta += float(season[16]) if season[16] else 0  # FTA
                    total_rebounds += float(season[20]) if season[20] else 0  # REB
                    total_assists += float(season[21]) if season[21] else 0  # AST
                    total_steals += float(season[22]) if season[22] else 0  # STL
                    total_blocks += float(season[23]) if season[23] else 0  # BLK
                    total_points += float(season[26]) if season[26] else 0  # PTS

            # Calculate career averages
            ppg = total_points / total_games if total_games > 0 else 0
            rpg = total_rebounds / total_games if total_games > 0 else 0
            apg = total_assists / total_games if total_games > 0 else 0
            fg_pct = total_fgm / total_fga if total_fga > 0 else 0
            fg3_pct = total_fg3m / total_fg3a if total_fg3a > 0 else 0
            ft_pct = total_ftm / total_fta if total_fta > 0 else 0

            result = "Career Statistics (Regular Season):\n\n"
            result += f"Total Points: {int(total_points):,}\n"
            result += f"Games Played: {int(total_games):,}\n"
            result += f"Total Rebounds: {int(total_rebounds):,}\n"
            result += f"Total Assists: {int(total_assists):,}\n"
            result += f"Total Steals: {int(total_steals):,}\n"
            result += f"Total Blocks: {int(total_blocks):,}\n"
            result += f"Total Minutes: {int(total_minutes):,}\n\n"
            result += "Career Averages:\n"
            result += f"Points Per Game: {ppg:.1f}\n"
            result += f"Rebounds Per Game: {rpg:.1f}\n"
            result += f"Assists Per Game: {apg:.1f}\n\n"
            result += "Shooting Percentages:\n"
            result += f"FG%: {fg_pct*100:.1f}%\n"
            result += f"3P%: {fg3_pct*100:.1f}%\n"
            result += f"FT%: {ft_pct*100:.1f}%\n"

            return [TextContent(type="text", text=result)]

        elif name == "get_player_hustle_stats":
            player_id = arguments["player_id"]
            season = arguments.get("season", get_current_season())

            url = f"{NBA_STATS_API}/leaguehustlestatsplayer"
            params = {
                "Season": season,
                "SeasonType": "Regular Season",
                "PerMode": "Totals"
            }

            data = await fetch_nba_data(url, params)

            if not data:
                return [TextContent(type="text", text="Error fetching hustle stats. Please try again.")]

            # Find player in results
            rows = safe_get(data, "resultSets", 0, "rowSet", default=[])

            player_stats = None
            for row in rows:
                if str(safe_get(row, 0)) == str(player_id):
                    player_stats = row
                    break

            if not player_stats:
                return [TextContent(type="text", text=f"No hustle stats found for player ID {player_id} in season {season}.")]

            player_name = safe_get(player_stats, 1, default="Player")
            team = safe_get(player_stats, 3, default="N/A")
            games = safe_get(player_stats, 5, default=0)

            result = f"Hustle Statistics - {player_name} ({team}) [{season}]:\n\n"
            result += f"Games Played: {games}\n\n"
            result += "Contest & Defense:\n"
            result += f"  Total Contested Shots: {safe_get(player_stats, 7, default=0)}\n"
            result += f"  Contested 2PT Shots: {safe_get(player_stats, 8, default=0)}\n"
            result += f"  Contested 3PT Shots: {safe_get(player_stats, 9, default=0)}\n"
            result += f"  Deflections: {safe_get(player_stats, 10, default=0)}\n"
            result += f"  Charges Drawn: {safe_get(player_stats, 11, default=0)}\n\n"
            result += "Screen Assists:\n"
            result += f"  Screen Assists: {safe_get(player_stats, 12, default=0)}\n"
            result += f"  Points from Screen Assists: {safe_get(player_stats, 13, default=0)}\n\n"
            result += "Loose Balls:\n"
            result += f"  Offensive Loose Balls: {safe_get(player_stats, 14, default=0)}\n"
            result += f"  Defensive Loose Balls: {safe_get(player_stats, 15, default=0)}\n"
            result += f"  Total Loose Balls Recovered: {safe_get(player_stats, 16, default=0)}\n\n"
            result += "Box Outs:\n"
            result += f"  Offensive Box Outs: {safe_get(player_stats, 19, default=0)}\n"
            result += f"  Defensive Box Outs: {safe_get(player_stats, 20, default=0)}\n"
            result += f"  Total Box Outs: {safe_get(player_stats, 23, default=0)}\n"

            return [TextContent(type="text", text=result)]

        elif name == "get_league_hustle_leaders":
            stat_category = arguments.get("stat_category", "deflections")
            season = arguments.get("season", get_current_season())

            url = f"{NBA_STATS_API}/leaguehustlestatsplayer"
            params = {
                "Season": season,
                "SeasonType": "Regular Season",
                "PerMode": "Totals"
            }

            data = await fetch_nba_data(url, params)

            if not data:
                return [TextContent(type="text", text="Error fetching hustle stats. Please try again.")]

            rows = safe_get(data, "resultSets", 0, "rowSet", default=[])

            # Map stat categories to column indices
            stat_map = {
                "deflections": (10, "Deflections"),
                "charges": (11, "Charges Drawn"),
                "screen_assists": (12, "Screen Assists"),
                "loose_balls": (16, "Loose Balls Recovered"),
                "box_outs": (23, "Box Outs")
            }

            if stat_category not in stat_map:
                return [TextContent(type="text", text=f"Invalid stat category. Choose from: {', '.join(stat_map.keys())}")]

            col_idx, stat_name = stat_map[stat_category]

            # Sort by the stat and get top 10
            sorted_players = sorted(rows, key=lambda x: float(safe_get(x, col_idx, default=0)), reverse=True)[:10]

            result = f"League Leaders - {stat_name} ({season}):\n\n"
            for i, player in enumerate(sorted_players, 1):
                name = safe_get(player, 1, default="Unknown")
                team = safe_get(player, 3, default="N/A")
                value = safe_get(player, col_idx, default=0)
                result += f"{i}. {name} ({team}): {value}\n"

            return [TextContent(type="text", text=result)]

        elif name == "get_player_defense_stats":
            player_id = arguments["player_id"]
            season = arguments.get("season", get_current_season())

            url = f"{NBA_STATS_API}/leaguedashptdefend"
            params = {
                "Season": season,
                "SeasonType": "Regular Season",
                "PerMode": "Totals",
                "DefenseCategory": "Overall"
            }

            data = await fetch_nba_data(url, params)

            if not data:
                return [TextContent(type="text", text="Error fetching defense stats. Please try again.")]

            rows = safe_get(data, "resultSets", 0, "rowSet", default=[])

            player_stats = None
            for row in rows:
                if str(safe_get(row, 0)) == str(player_id):
                    player_stats = row
                    break

            if not player_stats:
                return [TextContent(type="text", text=f"No defense stats found for player ID {player_id} in season {season}.")]

            player_name = safe_get(player_stats, 1, default="Player")
            team = safe_get(player_stats, 3, default="N/A")
            position = safe_get(player_stats, 4, default="N/A")
            games = safe_get(player_stats, 6, default=0)

            dfgm = safe_get(player_stats, 9, default=0)
            dfga = safe_get(player_stats, 10, default=0)
            dfg_pct = safe_get(player_stats, 11, default=0)
            normal_fg_pct = safe_get(player_stats, 12, default=0)
            diff = safe_get(player_stats, 13, default=0)

            result = f"Defensive Impact - {player_name} ({team}) [{season}]:\n\n"
            result += f"Position: {position}\n"
            result += f"Games: {games}\n\n"
            result += "When Defended By This Player:\n"
            result += f"  Opponent FGM: {dfgm}\n"
            result += f"  Opponent FGA: {dfga}\n"
            result += f"  Opponent FG%: {format_stat(dfg_pct, True)}\n\n"
            result += "Comparison:\n"
            result += f"  Opponent Normal FG%: {format_stat(normal_fg_pct, True)}\n"
            result += f"  Difference: {format_stat(diff, True)}\n"

            if float(diff) < 0:
                result += f"\n✓ This player holds opponents to {abs(float(diff)*100):.1f}% below their normal shooting."
            else:
                result += f"\n⚠ Opponents shoot {float(diff)*100:.1f}% better against this player."

            return [TextContent(type="text", text=result)]

        # Team Tools
        elif name == "get_all_teams":
            # Hardcoded list of NBA teams (more reliable than API for this)
            result = "NBA Teams:\n\n"
            for team_id, team_name in sorted(NBA_TEAMS.items(), key=lambda x: x[1]):
                result += f"ID: {team_id} | {team_name}\n"

            return [TextContent(type="text", text=result)]

        elif name == "get_team_roster":
            team_id = arguments["team_id"]
            season = arguments.get("season", get_current_season())

            url = f"{NBA_STATS_API}/commonteamroster"
            params = {
                "TeamID": team_id,
                "Season": season
            }

            data = await fetch_nba_data(url, params)

            if not data:
                return [TextContent(type="text", text="Error fetching roster. Please try again.")]

            roster_data = safe_get(data, "resultSets", 0, "rowSet", default=[])

            if not roster_data:
                return [TextContent(type="text", text="No roster found for this team.")]

            result = f"Team Roster ({season}):\n\n"

            for player in roster_data:
                result += f"#{safe_get(player, 4)} {safe_get(player, 3)} - {safe_get(player, 5)}\n"  # NUM, PLAYER, POSITION
                result += f"   Height: {safe_get(player, 6)} | Weight: {safe_get(player, 7)} lbs | "
                result += f"Age: {safe_get(player, 9)} | Exp: {safe_get(player, 8)}\n"

            return [TextContent(type="text", text=result)]

        # League Tools
        elif name == "get_standings":
            season = arguments.get("season", get_current_season())

            url = f"{NBA_STATS_API}/leaguestandingsv3"
            params = {
                "LeagueID": "00",
                "Season": season,
                "SeasonType": "Regular Season"
            }

            data = await fetch_nba_data(url, params)

            if not data:
                return [TextContent(type="text", text="Error fetching standings. Please try again.")]

            standings_data = safe_get(data, "resultSets", 0, "rowSet", default=[])

            if not standings_data:
                return [TextContent(type="text", text="No standings found.")]

            result = f"NBA Standings ({season}):\n\n"

            # Separate by conference
            east_teams = []
            west_teams = []

            for team in standings_data:
                conference = safe_get(team, 5)  # Conference
                if conference == "East":
                    east_teams.append(team)
                else:
                    west_teams.append(team)

            # Sort by conference rank
            east_teams.sort(key=lambda x: safe_get(x, 6, default=99))  # ConferenceRecord
            west_teams.sort(key=lambda x: safe_get(x, 6, default=99))

            result += "Eastern Conference:\n"
            for i, team in enumerate(east_teams, 1):
                result += f"{i}. {safe_get(team, 4)}: "  # TeamName
                result += f"{safe_get(team, 13)}-{safe_get(team, 14)} "  # WINS-LOSSES
                result += f"({format_stat(safe_get(team, 15))})\n"  # WinPCT

            result += "\nWestern Conference:\n"
            for i, team in enumerate(west_teams, 1):
                result += f"{i}. {safe_get(team, 4)}: "
                result += f"{safe_get(team, 13)}-{safe_get(team, 14)} "
                result += f"({format_stat(safe_get(team, 15))})\n"

            return [TextContent(type="text", text=result)]

        elif name == "get_league_leaders":
            stat_type = arguments.get("stat_type", "Points")
            season = arguments.get("season", get_current_season())

            # Map stat types to NBA API parameters
            stat_map = {
                "Points": "PTS",
                "Assists": "AST",
                "Rebounds": "REB",
                "Steals": "STL",
                "Blocks": "BLK",
                "FG%": "FG_PCT",
                "3P%": "FG3_PCT",
                "FT%": "FT_PCT"
            }

            stat_category = stat_map.get(stat_type, "PTS")

            # Use leaguegamelog endpoint which is more reliable
            url = f"{NBA_STATS_API}/leaguegamelog"
            params = {
                "LeagueID": "00",
                "Season": season,
                "SeasonType": "Regular Season",
                "PlayerOrTeam": "P",
                "Sorter": stat_category,
                "Direction": "DESC"
            }

            data = await fetch_nba_data(url, params)

            if not data:
                return [TextContent(type="text", text="Error fetching league leaders. Please try again.")]

            # Parse game log data
            headers = safe_get(data, "resultSets", 0, "headers", default=[])
            rows = safe_get(data, "resultSets", 0, "rowSet", default=[])

            if not rows or not headers:
                return [TextContent(type="text", text=f"No data found for {stat_type} leaders.")]

            # Find column indices
            player_id_idx = headers.index("PLAYER_ID") if "PLAYER_ID" in headers else 1
            player_name_idx = headers.index("PLAYER_NAME") if "PLAYER_NAME" in headers else 2
            team_idx = headers.index("TEAM_ABBREVIATION") if "TEAM_ABBREVIATION" in headers else 4
            stat_idx = headers.index(stat_category) if stat_category in headers else -1

            if stat_idx == -1:
                return [TextContent(type="text", text=f"Stat category {stat_type} not found in data.")]

            # Aggregate stats by player
            player_stats = {}
            for row in rows:
                player_id = safe_get(row, player_id_idx)
                player_name = safe_get(row, player_name_idx)
                team = safe_get(row, team_idx)
                stat_value = safe_get(row, stat_idx, default=0)

                if player_id not in player_stats:
                    player_stats[player_id] = {
                        "name": player_name,
                        "team": team,
                        "total": 0,
                        "games": 0
                    }

                # Add to total
                try:
                    player_stats[player_id]["total"] += float(stat_value) if stat_value else 0
                    player_stats[player_id]["games"] += 1
                except (ValueError, TypeError):
                    pass

            # Calculate averages and sort
            player_list = []
            for pid, stats in player_stats.items():
                if stats["games"] > 0:
                    avg = stats["total"] / stats["games"]
                    player_list.append({
                        "name": stats["name"],
                        "team": stats["team"],
                        "total": stats["total"],
                        "avg": avg,
                        "games": stats["games"]
                    })

            # Sort by average (per game)
            player_list.sort(key=lambda x: x["avg"], reverse=True)

            # Format result
            result = f"League Leaders - {stat_type} ({season}):\n\n"

            for i, player in enumerate(player_list[:10], 1):  # Top 10
                result += f"{i}. {player['name']} ({player['team']}): "

                # Show average per game
                if stat_category in ["FG_PCT", "FG3_PCT", "FT_PCT"]:
                    result += f"{format_stat(player['avg'], True)}"
                else:
                    result += f"{player['avg']:.1f}"

                result += f" | GP: {player['games']}\n"

            return [TextContent(type="text", text=result)]

        elif name == "get_all_time_leaders":
            stat_category = arguments.get("stat_category", "points").lower()
            limit = min(arguments.get("limit", 10), 50)

            # Map stat categories to result set names
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
                "personal_fouls": "PFLeaders"
            }

            if stat_category not in stat_map:
                valid_cats = ", ".join(sorted(stat_map.keys()))
                return [TextContent(type="text", text=f"Invalid stat category. Choose from: {valid_cats}")]

            result_set_name = stat_map[stat_category]

            url = f"{NBA_STATS_API}/alltimeleadersgrids"
            params = {
                "LeagueID": "00",
                "PerMode": "Totals",
                "SeasonType": "Regular Season",
                "TopX": str(limit)
            }

            data = await fetch_nba_data(url, params)

            if not data:
                return [TextContent(type="text", text="Error fetching all-time leaders. Please try again.")]

            # Find the correct result set
            leaders_data = None
            for result_set in safe_get(data, "resultSets", default=[]):
                if result_set.get("name") == result_set_name:
                    leaders_data = result_set.get("rowSet", [])
                    break

            if not leaders_data:
                return [TextContent(type="text", text=f"No all-time leaders found for {stat_category}.")]

            # Format stat category name nicely
            stat_display = stat_category.replace("_", " ").title()

            result = f"All-Time Career Leaders - {stat_display}:\n\n"

            for i, player in enumerate(leaders_data, 1):
                player_name = safe_get(player, 1, default="Unknown")
                stat_value = safe_get(player, 2, default=0)
                is_active = safe_get(player, 4, default=0)

                # Format the stat value
                if "pct" in stat_category:
                    stat_str = format_stat(stat_value, is_percentage=True)
                else:
                    # Add thousands separator for large numbers
                    try:
                        stat_str = f"{int(float(stat_value)):,}"
                    except (ValueError, TypeError):
                        stat_str = str(stat_value)

                active_marker = " ✓" if is_active == 1 else ""
                result += f"{i}. {player_name}: {stat_str}{active_marker}\n"

            if any(safe_get(p, 4, default=0) == 1 for p in leaders_data):
                result += "\n✓ = Active player"

            return [TextContent(type="text", text=result)]

        elif name == "get_schedule":
            team_id = arguments.get("team_id")
            days_ahead = min(arguments.get("days_ahead", 7), 90)  # Cap at 90 days

            if not team_id:
                return [TextContent(type="text", text="Please specify a team_id to get schedule. Use get_all_teams to find team IDs. For today's games, use get_todays_scoreboard instead.")]

            # Use NBA CDN scheduleLeagueV2.json - contains full season schedule including future games
            url = "https://cdn.nba.com/static/json/staticData/scheduleLeagueV2.json"
            data = await fetch_nba_data(url)

            if not data:
                return [TextContent(type="text", text="Error fetching schedule. Please try again.")]

            game_dates = safe_get(data, "leagueSchedule", "gameDates", default=[])

            if not game_dates:
                return [TextContent(type="text", text="No schedule data available.")]

            # Filter for games involving this team and within date range
            today = datetime.now()
            team_id_int = int(team_id)
            upcoming_games = []

            for date_entry in game_dates:
                for game in safe_get(date_entry, "games", default=[]):
                    home_id = safe_get(game, "homeTeam", "teamId")
                    away_id = safe_get(game, "awayTeam", "teamId")

                    # Check if this team is playing
                    if home_id == team_id_int or away_id == team_id_int:
                        try:
                            game_date_str = safe_get(game, "gameDateTimeEst")
                            if game_date_str == "N/A":
                                continue

                            game_date = datetime.fromisoformat(game_date_str.replace('Z', '+00:00'))

                            # Only include future games within days_ahead
                            if game_date.date() >= today.date():
                                days_until = (game_date.date() - today.date()).days
                                if days_until <= days_ahead:
                                    upcoming_games.append({
                                        "date": game_date,
                                        "game": game
                                    })
                        except (ValueError, TypeError, AttributeError):
                            continue

            # Sort by date
            upcoming_games.sort(key=lambda x: x["date"])

            if not upcoming_games:
                return [TextContent(type="text", text=f"No upcoming games found within the next {days_ahead} days for this team.")]

            # Get team name
            teams_dict = {
                1610612737: "Atlanta Hawks", 1610612738: "Boston Celtics",
                1610612751: "Brooklyn Nets", 1610612766: "Charlotte Hornets",
                1610612741: "Chicago Bulls", 1610612739: "Cleveland Cavaliers",
                1610612742: "Dallas Mavericks", 1610612743: "Denver Nuggets",
                1610612765: "Detroit Pistons", 1610612744: "Golden State Warriors",
                1610612745: "Houston Rockets", 1610612754: "Indiana Pacers",
                1610612746: "LA Clippers", 1610612747: "Los Angeles Lakers",
                1610612763: "Memphis Grizzlies", 1610612748: "Miami Heat",
                1610612749: "Milwaukee Bucks", 1610612750: "Minnesota Timberwolves",
                1610612740: "New Orleans Pelicans", 1610612752: "New York Knicks",
                1610612760: "Oklahoma City Thunder", 1610612753: "Orlando Magic",
                1610612755: "Philadelphia 76ers", 1610612756: "Phoenix Suns",
                1610612757: "Portland Trail Blazers", 1610612758: "Sacramento Kings",
                1610612759: "San Antonio Spurs", 1610612761: "Toronto Raptors",
                1610612762: "Utah Jazz", 1610612764: "Washington Wizards",
            }
            team_name = teams_dict.get(team_id_int, f"Team {team_id}")

            result = f"Upcoming Games for {team_name}:\n"
            result += f"(Next {days_ahead} days)\n\n"

            for item in upcoming_games:
                game_date = item["date"]
                game = item["game"]

                home_team = safe_get(game, "homeTeam", default={})
                away_team = safe_get(game, "awayTeam", default={})

                home_name = f"{safe_get(home_team, 'teamCity')} {safe_get(home_team, 'teamName')}"
                away_name = f"{safe_get(away_team, 'teamCity')} {safe_get(away_team, 'teamName')}"

                arena = safe_get(game, "arenaName")
                city = safe_get(game, "arenaCity")
                state = safe_get(game, "arenaState")

                result += f"{game_date.strftime('%A, %B %d, %Y')} at {game_date.strftime('%I:%M %p')} ET\n"
                result += f"  {away_name} @ {home_name}\n"
                result += f"  {arena}, {city}, {state}\n"
                result += f"  Game ID: {safe_get(game, 'gameId')}\n\n"

            return [TextContent(type="text", text=result)]

        elif name == "get_player_awards":
            player_id = arguments["player_id"]

            url = f"{NBA_STATS_API}/playerawards"
            params = {"PlayerID": player_id}

            data = await fetch_nba_data(url, params)

            if not data:
                return [TextContent(type="text", text="Error fetching player awards. Please try again.")]

            headers = safe_get(data, "resultSets", 0, "headers", default=[])
            awards = safe_get(data, "resultSets", 0, "rowSet", default=[])

            if not awards:
                return [TextContent(type="text", text="No awards found for this player.")]

            # Get player name from first award
            first_award = awards[0]
            player_name = f"{safe_get(first_award, 1)} {safe_get(first_award, 2)}"  # FIRST_NAME LAST_NAME

            # Find header indices
            desc_idx = headers.index("DESCRIPTION") if "DESCRIPTION" in headers else 4
            season_idx = headers.index("SEASON") if "SEASON" in headers else 6
            team_idx = headers.index("TEAM") if "TEAM" in headers else 3

            # Categorize awards
            mvp_awards = []
            finals_mvp = []
            allstar_mvp = []
            championships = []
            all_nba = []
            all_defensive = []
            all_star = []
            rookie_awards = []
            other_awards = []

            for award in awards:
                desc = safe_get(award, desc_idx, default="")
                season = safe_get(award, season_idx, default="")
                team = safe_get(award, team_idx, default="")

                if "NBA Most Valuable Player" in desc and "All-Star" not in desc and "Finals" not in desc:
                    mvp_awards.append(f"  {season}: {desc}")
                elif "Finals Most Valuable Player" in desc:
                    finals_mvp.append(f"  {season}: {desc} ({team})")
                elif "All-Star Most Valuable Player" in desc:
                    allstar_mvp.append(f"  {season}: {desc}")
                elif "NBA Champion" in desc:
                    championships.append(f"  {season}: {desc} ({team})")
                elif "All-NBA" in desc:
                    all_nba.append(f"  {season}: {desc}")
                elif "All-Defensive" in desc:
                    all_defensive.append(f"  {season}: {desc}")
                elif "NBA All-Star" in desc and "Most Valuable Player" not in desc:
                    all_star.append(f"  {season}: {desc}")
                elif "Rookie" in desc:
                    rookie_awards.append(f"  {season}: {desc}")
                else:
                    other_awards.append(f"  {season}: {desc}")

            result = f"Awards and Accolades - {player_name}\n\n"

            if mvp_awards:
                result += f"NBA MVP ({len(mvp_awards)}):\n" + "\n".join(mvp_awards) + "\n\n"

            if finals_mvp:
                result += f"Finals MVP ({len(finals_mvp)}):\n" + "\n".join(finals_mvp) + "\n\n"

            if championships:
                result += f"NBA Championships ({len(championships)}):\n" + "\n".join(championships) + "\n\n"

            if all_nba:
                result += f"All-NBA Teams ({len(all_nba)}):\n" + "\n".join(all_nba[:10])
                if len(all_nba) > 10:
                    result += f"\n  ... and {len(all_nba) - 10} more"
                result += "\n\n"

            if all_defensive:
                result += f"All-Defensive Teams ({len(all_defensive)}):\n" + "\n".join(all_defensive[:10])
                if len(all_defensive) > 10:
                    result += f"\n  ... and {len(all_defensive) - 10} more"
                result += "\n\n"

            if all_star:
                result += f"All-Star Selections ({len(all_star)}):\n" + "\n".join(all_star[:10])
                if len(all_star) > 10:
                    result += f"\n  ... and {len(all_star) - 10} more"
                result += "\n\n"

            if allstar_mvp:
                result += f"All-Star Game MVP ({len(allstar_mvp)}):\n" + "\n".join(allstar_mvp) + "\n\n"

            if rookie_awards:
                result += f"Rookie Awards ({len(rookie_awards)}):\n" + "\n".join(rookie_awards) + "\n\n"

            if other_awards:
                result += f"Other Honors ({len(other_awards)}):\n" + "\n".join(other_awards[:5])
                if len(other_awards) > 5:
                    result += f"\n  ... and {len(other_awards) - 5} more"
                result += "\n\n"

            result += f"Total Awards: {len(awards)}"

            return [TextContent(type="text", text=result)]

        elif name == "get_season_awards":
            season = arguments.get("season", get_current_season())

            # For season awards, we need to aggregate awards from multiple players
            # Since there's no direct endpoint, we'll query known award categories
            # This is a simplified implementation - in production, you might want to cache this data

            # Known MVPs by season (partial list for demonstration)
            # In a real implementation, you'd want a comprehensive database or API
            mvp_map = {
                "2023-24": ("Joel Embiid", "1610612755"),  # 76ers
                "2022-23": ("Joel Embiid", "1610612755"),
                "2021-22": ("Nikola Jokic", "1610612743"),  # Nuggets
                "2020-21": ("Nikola Jokic", "1610612743"),
                "2019-20": ("Giannis Antetokounmpo", "1610612749"),  # Bucks
                "2018-19": ("Giannis Antetokounmpo", "1610612749"),
                "2017-18": ("James Harden", "1610612745"),  # Rockets
                "2016-17": ("Russell Westbrook", "1610612760"),  # Thunder
                "2015-16": ("Stephen Curry", "1610612744"),  # Warriors
                "2014-15": ("Stephen Curry", "1610612744"),
                "2013-14": ("Kevin Durant", "1610612760"),
                "2012-13": ("LeBron James", "1610612748"),  # Heat
                "2011-12": ("LeBron James", "1610612748"),
                "2010-11": ("Derrick Rose", "1610612741"),  # Bulls
                "2009-10": ("LeBron James", "1610612739"),  # Cavaliers
                "2008-09": ("LeBron James", "1610612739"),
                "2007-08": ("Kobe Bryant", "1610612747"),  # Lakers
                "2006-07": ("Dirk Nowitzki", "1610612742"),  # Mavericks
                "2005-06": ("Steve Nash", "1610612756"),  # Suns
                "2004-05": ("Steve Nash", "1610612756"),
                "2003-04": ("Kevin Garnett", "1610612750"),  # Timberwolves
                "2002-03": ("Tim Duncan", "1610612759"),  # Spurs
                "2001-02": ("Tim Duncan", "1610612759"),
                "2000-01": ("Allen Iverson", "1610612755"),  # 76ers
            }

            if season not in mvp_map:
                return [TextContent(type="text", text=f"Award data for {season} season is not available. Try searching for individual players using get_player_awards instead.")]

            mvp_name, team_id = mvp_map[season]

            result = f"Major Awards - {season} Season\n\n"
            result += f"NBA Most Valuable Player (MVP):\n  {mvp_name}\n\n"

            result += "Note: For comprehensive award information including Finals MVP, ROTY, All-NBA teams, and other awards,\n"
            result += "use the get_player_awards tool to look up individual players. The NBA Stats API doesn't provide\n"
            result += "a single endpoint for all season awards, so this tool shows MVP only.\n\n"
            result += "To find other award winners:\n"
            result += "  - Search for players using search_players\n"
            result += "  - Get their awards using get_player_awards\n"

            return [TextContent(type="text", text=result)]

        elif name == "get_shot_chart":
            player_id = arguments.get("player_id")
            season = arguments.get("season", get_current_season())
            game_id = arguments.get("game_id", "")

            # Build parameters for shotchartdetail endpoint
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
                return [TextContent(type="text", text="Failed to fetch shot chart data. The NBA API may be unavailable.")]

            # Extract shot data
            headers = safe_get(data, "resultSets", 0, "headers", default=[])
            shots = safe_get(data, "resultSets", 0, "rowSet", default=[])

            if not shots:
                return [TextContent(type="text", text=f"No shot data found for this player in {season} season.")]

            # Get player name from parameters result set
            player_info = safe_get(data, "resultSets", 1, "rowSet", 0, default=[])
            player_name = safe_get(player_info, 4, default="Player") if player_info else "Player"

            # Find relevant column indices
            try:
                shot_made_idx = headers.index("SHOT_MADE_FLAG")
                shot_type_idx = headers.index("ACTION_TYPE")
                shot_distance_idx = headers.index("SHOT_DISTANCE")
            except ValueError as e:
                logger.error(f"Missing expected column in shot chart data: {e}")
                return [TextContent(type="text", text="Error parsing shot chart data structure.")]

            # Aggregate stats
            total_shots = len(shots)
            made_shots = sum(1 for shot in shots if safe_get(shot, shot_made_idx) == 1)
            missed_shots = total_shots - made_shots
            fg_pct = (made_shots / total_shots * 100) if total_shots > 0 else 0

            # Group by distance ranges
            distance_buckets = {
                "0-5 ft": [],
                "5-10 ft": [],
                "10-15 ft": [],
                "15-20 ft": [],
                "20-25 ft": [],
                "25+ ft": []
            }

            for shot in shots:
                distance = safe_get(shot, shot_distance_idx, default=0)
                made = safe_get(shot, shot_made_idx) == 1

                if distance < 5:
                    distance_buckets["0-5 ft"].append(made)
                elif distance < 10:
                    distance_buckets["5-10 ft"].append(made)
                elif distance < 15:
                    distance_buckets["10-15 ft"].append(made)
                elif distance < 20:
                    distance_buckets["15-20 ft"].append(made)
                elif distance < 25:
                    distance_buckets["20-25 ft"].append(made)
                else:
                    distance_buckets["25+ ft"].append(made)

            result = f"Shot Chart - {player_name} ({season})\n\n"
            result += "Overall Shooting:\n"
            result += f"  Total Shots: {total_shots}\n"
            result += f"  Made: {made_shots}\n"
            result += f"  Missed: {missed_shots}\n"
            result += f"  FG%: {fg_pct:.1f}%\n\n"

            result += "Shooting by Distance:\n"
            for distance_range, shots_list in distance_buckets.items():
                if shots_list:
                    made = sum(shots_list)
                    total = len(shots_list)
                    pct = (made / total * 100) if total > 0 else 0
                    result += f"  {distance_range}: {made}/{total} ({pct:.1f}%)\n"

            # Show shot type breakdown (top 5)
            shot_types = {}
            for shot in shots:
                shot_type = safe_get(shot, shot_type_idx, default="Unknown")
                made = safe_get(shot, shot_made_idx) == 1
                if shot_type not in shot_types:
                    shot_types[shot_type] = {"made": 0, "total": 0}
                shot_types[shot_type]["total"] += 1
                if made:
                    shot_types[shot_type]["made"] += 1

            # Sort by total attempts
            sorted_types = sorted(shot_types.items(), key=lambda x: x[1]["total"], reverse=True)[:5]

            if sorted_types:
                result += "\nTop Shot Types:\n"
                for shot_type, stats in sorted_types:
                    pct = (stats["made"] / stats["total"] * 100) if stats["total"] > 0 else 0
                    result += f"  {shot_type}: {stats['made']}/{stats['total']} ({pct:.1f}%)\n"

            result += f"\nNote: Shot chart contains {total_shots} total shot attempts with X/Y coordinates for visualization."

            return [TextContent(type="text", text=result)]

        elif name == "get_shooting_splits":
            player_id = arguments.get("player_id")
            season = arguments.get("season", get_current_season())

            # Build parameters for shooting splits endpoint
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
                return [TextContent(type="text", text="Failed to fetch shooting splits data. The NBA API may be unavailable.")]

            # Find the shooting splits result set
            # Look for "Shot5FTDistanceRange", "Shot8FTDistanceRange", or "ShotAreaOverall"
            result_sets = safe_get(data, "resultSets", default=[])

            # Try to find different result sets
            overall_data = None
            area_data = None
            distance_data = None

            for rs in result_sets:
                rs_name = safe_get(rs, "name", default="")
                if rs_name == "OverallPlayerDashboard":
                    overall_data = rs
                elif rs_name == "Shot5FTDistanceRange":
                    distance_data = rs
                elif rs_name == "ShotAreaOverall":
                    area_data = rs

            if not overall_data:
                return [TextContent(type="text", text=f"No shooting data found for this player in {season} season.")]

            # Get overall stats first
            headers = safe_get(overall_data, "headers", default=[])
            rows = safe_get(overall_data, "rowSet", default=[])

            if not rows:
                return [TextContent(type="text", text=f"No shooting data available for {season} season.")]

            player_name = safe_get(rows, 0, 1, default="Player")

            result = f"Shooting Splits - {player_name} ({season})\n\n"

            # Process distance data if available
            if distance_data:
                dist_headers = safe_get(distance_data, "headers", default=[])
                dist_rows = safe_get(distance_data, "rowSet", default=[])

                if dist_rows:
                    result += "Shooting by Distance:\n"
                    try:
                        fg_pct_idx = dist_headers.index("FG_PCT")
                        fga_idx = dist_headers.index("FGA")
                        fgm_idx = dist_headers.index("FGM")
                        group_value_idx = dist_headers.index("GROUP_VALUE")
                    except ValueError:
                        result += "  (Distance data structure not recognized)\n"
                    else:
                        for row in dist_rows:
                            distance_range = safe_get(row, group_value_idx, default="Unknown")
                            fgm = safe_get(row, fgm_idx, default=0)
                            fga = safe_get(row, fga_idx, default=0)
                            fg_pct = safe_get(row, fg_pct_idx, default=0)
                            if fga > 0:
                                result += f"  {distance_range}: {fgm}/{fga} ({format_stat(fg_pct, is_percentage=True)})\n"
                    result += "\n"

            # Process area data if available (paint, mid-range, 3PT, etc.)
            if area_data:
                area_headers = safe_get(area_data, "headers", default=[])
                area_rows = safe_get(area_data, "rowSet", default=[])

                if area_rows:
                    result += "Shooting by Area:\n"
                    try:
                        fg_pct_idx = area_headers.index("FG_PCT")
                        fga_idx = area_headers.index("FGA")
                        fgm_idx = area_headers.index("FGM")
                        group_value_idx = area_headers.index("GROUP_VALUE")
                    except ValueError:
                        result += "  (Area data structure not recognized)\n"
                    else:
                        for row in area_rows:
                            area = safe_get(row, group_value_idx, default="Unknown")
                            fgm = safe_get(row, fgm_idx, default=0)
                            fga = safe_get(row, fga_idx, default=0)
                            fg_pct = safe_get(row, fg_pct_idx, default=0)
                            if fga > 0:
                                result += f"  {area}: {fgm}/{fga} ({format_stat(fg_pct, is_percentage=True)})\n"
                    result += "\n"

            # Add overall stats
            try:
                fgm_idx = headers.index("FGM")
                fga_idx = headers.index("FGA")
                fg_pct_idx = headers.index("FG_PCT")
                fg3m_idx = headers.index("FG3M")
                fg3a_idx = headers.index("FG3A")
                fg3_pct_idx = headers.index("FG3_PCT")

                row = rows[0]
                fgm = safe_get(row, fgm_idx, default=0)
                fga = safe_get(row, fga_idx, default=0)
                fg_pct = safe_get(row, fg_pct_idx, default=0)
                fg3m = safe_get(row, fg3m_idx, default=0)
                fg3a = safe_get(row, fg3a_idx, default=0)
                fg3_pct = safe_get(row, fg3_pct_idx, default=0)

                # Calculate 2PT stats
                fg2m = fgm - fg3m
                fg2a = fga - fg3a
                fg2_pct = (fg2m / fg2a) if fg2a > 0 else 0

                result += "Overall Shooting:\n"
                result += f"  Total FG: {fgm}/{fga} ({format_stat(fg_pct, is_percentage=True)})\n"
                result += f"  2-Point FG: {fg2m}/{fg2a} ({format_stat(fg2_pct, is_percentage=True)})\n"
                result += f"  3-Point FG: {fg3m}/{fg3a} ({format_stat(fg3_pct, is_percentage=True)})\n"

            except (ValueError, IndexError) as e:
                logger.error(f"Error parsing overall shooting stats: {e}")
                result += "Overall stats not available\n"

            return [TextContent(type="text", text=result)]

        elif name == "get_play_by_play":
            game_id = arguments.get("game_id")
            start_period = arguments.get("start_period", 1)
            end_period = arguments.get("end_period", 10)

            # Build parameters for playbyplayv2 endpoint
            params = {
                "GameID": game_id,
                "StartPeriod": start_period,
                "EndPeriod": end_period,
            }

            url = f"{NBA_STATS_API}/playbyplayv2"
            data = await fetch_nba_data(url, params=params)

            if not data:
                return [TextContent(type="text", text="Failed to fetch play-by-play data. The NBA API may be unavailable or the game ID may be invalid.")]

            # Extract play-by-play data
            result_sets = safe_get(data, "resultSets", default=[])

            # Find the PlayByPlay result set
            play_by_play_data = None
            for rs in result_sets:
                if safe_get(rs, "name") == "PlayByPlay":
                    play_by_play_data = rs
                    break

            if not play_by_play_data:
                return [TextContent(type="text", text=f"No play-by-play data found for game {game_id}.")]

            headers = safe_get(play_by_play_data, "headers", default=[])
            plays = safe_get(play_by_play_data, "rowSet", default=[])

            if not plays:
                return [TextContent(type="text", text=f"No plays found for game {game_id}.")]

            # Find relevant column indices
            try:
                period_idx = headers.index("PERIOD")
                pctimestring_idx = headers.index("PCTIMESTRING")
                homedescription_idx = headers.index("HOMEDESCRIPTION")
                visitordescription_idx = headers.index("VISITORDESCRIPTION")
                score_idx = headers.index("SCORE")
                scoremargin_idx = headers.index("SCOREMARGIN")
            except ValueError as e:
                logger.error(f"Missing expected column in play-by-play data: {e}")
                return [TextContent(type="text", text="Error parsing play-by-play data structure.")]

            result = f"Play-by-Play - Game {game_id}\n"
            result += f"Showing periods {start_period} to {end_period}\n"
            result += "=" * 70 + "\n\n"

            current_period = None
            play_count = 0
            max_plays = 100  # Limit output to avoid overwhelming response

            for play in plays:
                period = safe_get(play, period_idx, default=0)
                time = safe_get(play, pctimestring_idx, default="")
                home_desc = safe_get(play, homedescription_idx, default="")
                visitor_desc = safe_get(play, visitordescription_idx, default="")
                score = safe_get(play, score_idx, default="")
                margin = safe_get(play, scoremargin_idx, default="")

                # Add period header when period changes
                if period != current_period:
                    current_period = period
                    period_name = f"Q{period}" if period <= 4 else f"OT{period - 4}"
                    result += f"\n{'=' * 70}\n"
                    result += f"{period_name}\n"
                    result += f"{'=' * 70}\n\n"

                # Determine which team's action to show
                description = home_desc if home_desc else visitor_desc

                if description:
                    play_count += 1
                    score_info = f" [{score}]" if score else ""
                    margin_info = f" ({margin})" if margin and score else ""
                    result += f"{time:>6} - {description}{score_info}{margin_info}\n"

                    # Limit output
                    if play_count >= max_plays:
                        result += f"\n... (showing first {max_plays} plays)\n"
                        result += f"Total plays in this range: {len(plays)}\n"
                        break

            result += f"\nTotal plays shown: {play_count}\n"
            return [TextContent(type="text", text=result)]

        elif name == "get_game_rotation":
            game_id = arguments.get("game_id")

            # Build parameters for gamerotation endpoint
            params = {
                "GameID": game_id,
                "LeagueID": "00",  # NBA league ID
            }

            url = f"{NBA_STATS_API}/gamerotation"
            data = await fetch_nba_data(url, params=params)

            if not data:
                return [TextContent(type="text", text="Failed to fetch game rotation data. The NBA API may be unavailable or the game ID may be invalid.")]

            # Extract rotation data - separate result sets for home and away
            result_sets = safe_get(data, "resultSets", default=[])

            away_team_data = None
            home_team_data = None

            for rs in result_sets:
                rs_name = safe_get(rs, "name", default="")
                if rs_name == "AwayTeam":
                    away_team_data = rs
                elif rs_name == "HomeTeam":
                    home_team_data = rs

            if not away_team_data and not home_team_data:
                return [TextContent(type="text", text=f"No rotation data found for game {game_id}. The game may not have started yet.")]

            result = f"Game Rotation - Game {game_id}\n"
            result += "=" * 70 + "\n\n"

            # Process each team's rotation data
            for team_data, team_label in [(away_team_data, "Away Team"), (home_team_data, "Home Team")]:
                if not team_data:
                    continue

                headers = safe_get(team_data, "headers", default=[])
                rotations = safe_get(team_data, "rowSet", default=[])

                if not rotations:
                    continue

                # Get team name from first row
                team_name = safe_get(rotations, 0, headers.index("TEAM_NAME") if "TEAM_NAME" in headers else 4, default=team_label)

                result += f"{team_name} Rotation:\n"
                result += "-" * 70 + "\n"

                try:
                    player_first_idx = headers.index("PLAYER_FIRST")
                    player_last_idx = headers.index("PLAYER_LAST")
                    in_time_idx = headers.index("IN_TIME_REAL")
                    out_time_idx = headers.index("OUT_TIME_REAL")
                    player_pts_idx = headers.index("PLAYER_PTS")
                    pt_diff_idx = headers.index("PT_DIFF")
                    usg_pct_idx = headers.index("USG_PCT")
                except ValueError as e:
                    logger.error(f"Missing expected column in rotation data: {e}")
                    result += "  (Rotation data structure not recognized)\n\n"
                    continue

                # Group rotations by player
                player_rotations = {}
                for rotation in rotations:
                    first_name = safe_get(rotation, player_first_idx, default="")
                    last_name = safe_get(rotation, player_last_idx, default="")
                    player_name = f"{first_name} {last_name}"

                    if player_name not in player_rotations:
                        player_rotations[player_name] = []

                    player_rotations[player_name].append({
                        "in": safe_get(rotation, in_time_idx, default=""),
                        "out": safe_get(rotation, out_time_idx, default=""),
                        "pts": safe_get(rotation, player_pts_idx, default=0),
                        "diff": safe_get(rotation, pt_diff_idx, default=0),
                        "usg": safe_get(rotation, usg_pct_idx, default=0),
                    })

                # Display each player's rotations
                for player_name, player_stints in player_rotations.items():
                    result += f"\n  {player_name}:\n"
                    for i, stint in enumerate(player_stints, 1):
                        in_time = stint["in"]
                        out_time = stint["out"]
                        pts = stint["pts"]
                        diff = stint["diff"]
                        usg = stint["usg"]

                        # Format time display
                        time_display = f"In: {in_time}, Out: {out_time}" if out_time else f"In: {in_time}"
                        result += f"    Stint {i}: {time_display}\n"
                        result += f"      Points: {pts}, +/-: {diff:+}, Usage: {format_stat(usg, is_percentage=True)}\n"

                result += "\n"

            return [TextContent(type="text", text=result)]

        elif name == "get_player_advanced_stats":
            player_id = arguments.get("player_id")
            season = arguments.get("season", get_current_season())

            # Build parameters for playerdashboardbygeneralsplits endpoint with Advanced MeasureType
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
                return [TextContent(type="text", text="Failed to fetch player advanced stats. The NBA API may be unavailable.")]

            # Extract advanced stats from OverallPlayerDashboard result set
            result_sets = safe_get(data, "resultSets", default=[])

            overall_data = None
            for rs in result_sets:
                if safe_get(rs, "name") == "OverallPlayerDashboard":
                    overall_data = rs
                    break

            if not overall_data:
                return [TextContent(type="text", text=f"No advanced stats found for this player in {season} season.")]

            headers = safe_get(overall_data, "headers", default=[])
            rows = safe_get(overall_data, "rowSet", default=[])

            if not rows:
                return [TextContent(type="text", text=f"No advanced stats available for {season} season.")]

            # Get player name and basic info
            row = rows[0]
            # Find PLAYER_NAME index in headers
            player_name_idx = headers.index("PLAYER_NAME") if "PLAYER_NAME" in headers else 1
            player_name = safe_get(row, player_name_idx, default="Player")

            result = f"Advanced Stats - {player_name} ({season})\n\n"

            # Extract key advanced metrics
            try:
                # Find indices for advanced metrics
                gp_idx = headers.index("GP") if "GP" in headers else -1
                min_idx = headers.index("MIN") if "MIN" in headers else -1
                off_rating_idx = headers.index("OFF_RATING") if "OFF_RATING" in headers else -1
                def_rating_idx = headers.index("DEF_RATING") if "DEF_RATING" in headers else -1
                net_rating_idx = headers.index("NET_RATING") if "NET_RATING" in headers else -1
                ts_pct_idx = headers.index("TS_PCT") if "TS_PCT" in headers else -1
                efg_pct_idx = headers.index("EFG_PCT") if "EFG_PCT" in headers else -1
                usg_pct_idx = headers.index("USG_PCT") if "USG_PCT" in headers else -1
                pace_idx = headers.index("PACE") if "PACE" in headers else -1
                pie_idx = headers.index("PIE") if "PIE" in headers else -1
                ast_pct_idx = headers.index("AST_PCT") if "AST_PCT" in headers else -1
                ast_ratio_idx = headers.index("AST_RATIO") if "AST_RATIO" in headers else -1
                oreb_pct_idx = headers.index("OREB_PCT") if "OREB_PCT" in headers else -1
                dreb_pct_idx = headers.index("DREB_PCT") if "DREB_PCT" in headers else -1
                reb_pct_idx = headers.index("REB_PCT") if "REB_PCT" in headers else -1

                # Basic info
                gp = safe_get(row, gp_idx, default=0) if gp_idx >= 0 else 0
                minutes = safe_get(row, min_idx, default=0) if min_idx >= 0 else 0

                result += f"Games Played: {gp}\n"
                result += f"Minutes Per Game: {format_stat(minutes)}\n\n"

                # Efficiency Metrics
                result += "Efficiency Metrics:\n"
                if ts_pct_idx >= 0:
                    ts_pct = safe_get(row, ts_pct_idx, default=0)
                    result += f"  True Shooting %: {format_stat(ts_pct, is_percentage=True)}\n"
                if efg_pct_idx >= 0:
                    efg_pct = safe_get(row, efg_pct_idx, default=0)
                    result += f"  Effective FG %: {format_stat(efg_pct, is_percentage=True)}\n"
                if pie_idx >= 0:
                    pie = safe_get(row, pie_idx, default=0)
                    result += f"  Player Impact Estimate (PIE): {format_stat(pie, is_percentage=True)}\n"
                result += "\n"

                # Offensive Impact
                result += "Offensive Impact:\n"
                if off_rating_idx >= 0:
                    off_rating = safe_get(row, off_rating_idx, default=0)
                    result += f"  Offensive Rating: {format_stat(off_rating)}\n"
                if usg_pct_idx >= 0:
                    usg_pct = safe_get(row, usg_pct_idx, default=0)
                    result += f"  Usage %: {format_stat(usg_pct, is_percentage=True)}\n"
                if ast_pct_idx >= 0:
                    ast_pct = safe_get(row, ast_pct_idx, default=0)
                    result += f"  Assist %: {format_stat(ast_pct, is_percentage=True)}\n"
                if ast_ratio_idx >= 0:
                    ast_ratio = safe_get(row, ast_ratio_idx, default=0)
                    result += f"  Assist Ratio: {format_stat(ast_ratio)}\n"
                result += "\n"

                # Defensive Impact
                result += "Defensive Impact:\n"
                if def_rating_idx >= 0:
                    def_rating = safe_get(row, def_rating_idx, default=0)
                    result += f"  Defensive Rating: {format_stat(def_rating)}\n"
                if dreb_pct_idx >= 0:
                    dreb_pct = safe_get(row, dreb_pct_idx, default=0)
                    result += f"  Defensive Rebound %: {format_stat(dreb_pct, is_percentage=True)}\n"
                result += "\n"

                # Rebounding
                result += "Rebounding:\n"
                if reb_pct_idx >= 0:
                    reb_pct = safe_get(row, reb_pct_idx, default=0)
                    result += f"  Total Rebound %: {format_stat(reb_pct, is_percentage=True)}\n"
                if oreb_pct_idx >= 0:
                    oreb_pct = safe_get(row, oreb_pct_idx, default=0)
                    result += f"  Offensive Rebound %: {format_stat(oreb_pct, is_percentage=True)}\n"
                if dreb_pct_idx >= 0:
                    dreb_pct = safe_get(row, dreb_pct_idx, default=0)
                    result += f"  Defensive Rebound %: {format_stat(dreb_pct, is_percentage=True)}\n"
                result += "\n"

                # Net Impact
                result += "Net Impact:\n"
                if net_rating_idx >= 0:
                    net_rating = safe_get(row, net_rating_idx, default=0)
                    result += f"  Net Rating: {format_stat(net_rating)}\n"
                if pace_idx >= 0:
                    pace = safe_get(row, pace_idx, default=0)
                    result += f"  Pace: {format_stat(pace)}\n"

            except (ValueError, IndexError) as e:
                logger.error(f"Error parsing advanced stats: {e}")
                result += "Unable to parse some advanced statistics\n"

            return [TextContent(type="text", text=result)]

        elif name == "get_team_advanced_stats":
            team_id = arguments.get("team_id")
            season = arguments.get("season", get_current_season())

            # Build parameters for teamdashboardbygeneralsplits endpoint with Advanced MeasureType
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
                return [TextContent(type="text", text="Failed to fetch team advanced stats. The NBA API may be unavailable.")]

            # Extract advanced stats from OverallTeamDashboard result set
            result_sets = safe_get(data, "resultSets", default=[])

            overall_data = None
            for rs in result_sets:
                if safe_get(rs, "name") == "OverallTeamDashboard":
                    overall_data = rs
                    break

            if not overall_data:
                return [TextContent(type="text", text=f"No advanced stats found for this team in {season} season.")]

            headers = safe_get(overall_data, "headers", default=[])
            rows = safe_get(overall_data, "rowSet", default=[])

            if not rows:
                return [TextContent(type="text", text=f"No advanced stats available for {season} season.")]

            # Get team name and basic info
            row = rows[0]

            # Find TEAM_NAME index in headers
            team_name_idx = headers.index("TEAM_NAME") if "TEAM_NAME" in headers else -1
            if team_name_idx >= 0:
                team_name = safe_get(row, team_name_idx, default="Team")
            else:
                # Fallback to GROUP_VALUE if TEAM_NAME not found
                team_name_idx = headers.index("GROUP_VALUE") if "GROUP_VALUE" in headers else 1
                team_name = safe_get(row, team_name_idx, default="Team")

            result = f"Advanced Stats - {team_name} ({season})\n\n"

            # Extract key advanced metrics
            try:
                # Find indices for advanced metrics
                gp_idx = headers.index("GP") if "GP" in headers else -1
                w_idx = headers.index("W") if "W" in headers else -1
                l_idx = headers.index("L") if "L" in headers else -1
                off_rating_idx = headers.index("OFF_RATING") if "OFF_RATING" in headers else -1
                def_rating_idx = headers.index("DEF_RATING") if "DEF_RATING" in headers else -1
                net_rating_idx = headers.index("NET_RATING") if "NET_RATING" in headers else -1
                ts_pct_idx = headers.index("TS_PCT") if "TS_PCT" in headers else -1
                efg_pct_idx = headers.index("EFG_PCT") if "EFG_PCT" in headers else -1
                pace_idx = headers.index("PACE") if "PACE" in headers else -1
                pie_idx = headers.index("PIE") if "PIE" in headers else -1
                ast_pct_idx = headers.index("AST_PCT") if "AST_PCT" in headers else -1
                ast_ratio_idx = headers.index("AST_RATIO") if "AST_RATIO" in headers else -1
                oreb_pct_idx = headers.index("OREB_PCT") if "OREB_PCT" in headers else -1
                dreb_pct_idx = headers.index("DREB_PCT") if "DREB_PCT" in headers else -1
                reb_pct_idx = headers.index("REB_PCT") if "REB_PCT" in headers else -1

                # Basic info
                gp = safe_get(row, gp_idx, default=0) if gp_idx >= 0 else 0
                wins = safe_get(row, w_idx, default=0) if w_idx >= 0 else 0
                losses = safe_get(row, l_idx, default=0) if l_idx >= 0 else 0

                result += f"Record: {wins}-{losses} ({gp} games)\n\n"

                # Team Ratings
                result += "Team Ratings:\n"
                if off_rating_idx >= 0:
                    off_rating = safe_get(row, off_rating_idx, default=0)
                    result += f"  Offensive Rating: {format_stat(off_rating)} (points per 100 possessions)\n"
                if def_rating_idx >= 0:
                    def_rating = safe_get(row, def_rating_idx, default=0)
                    result += f"  Defensive Rating: {format_stat(def_rating)} (points allowed per 100 possessions)\n"
                if net_rating_idx >= 0:
                    net_rating = safe_get(row, net_rating_idx, default=0)
                    result += f"  Net Rating: {format_stat(net_rating)} (point differential per 100 possessions)\n"
                if pace_idx >= 0:
                    pace = safe_get(row, pace_idx, default=0)
                    result += f"  Pace: {format_stat(pace)} (possessions per 48 minutes)\n"
                result += "\n"

                # Shooting Efficiency
                result += "Shooting Efficiency:\n"
                if ts_pct_idx >= 0:
                    ts_pct = safe_get(row, ts_pct_idx, default=0)
                    result += f"  True Shooting %: {format_stat(ts_pct, is_percentage=True)}\n"
                if efg_pct_idx >= 0:
                    efg_pct = safe_get(row, efg_pct_idx, default=0)
                    result += f"  Effective FG %: {format_stat(efg_pct, is_percentage=True)}\n"
                result += "\n"

                # Ball Movement
                result += "Ball Movement:\n"
                if ast_pct_idx >= 0:
                    ast_pct = safe_get(row, ast_pct_idx, default=0)
                    result += f"  Assist %: {format_stat(ast_pct, is_percentage=True)}\n"
                if ast_ratio_idx >= 0:
                    ast_ratio = safe_get(row, ast_ratio_idx, default=0)
                    result += f"  Assist Ratio: {format_stat(ast_ratio)}\n"
                result += "\n"

                # Rebounding
                result += "Rebounding:\n"
                if reb_pct_idx >= 0:
                    reb_pct = safe_get(row, reb_pct_idx, default=0)
                    result += f"  Total Rebound %: {format_stat(reb_pct, is_percentage=True)}\n"
                if oreb_pct_idx >= 0:
                    oreb_pct = safe_get(row, oreb_pct_idx, default=0)
                    result += f"  Offensive Rebound %: {format_stat(oreb_pct, is_percentage=True)}\n"
                if dreb_pct_idx >= 0:
                    dreb_pct = safe_get(row, dreb_pct_idx, default=0)
                    result += f"  Defensive Rebound %: {format_stat(dreb_pct, is_percentage=True)}\n"
                result += "\n"

                # Overall Impact
                if pie_idx >= 0:
                    pie = safe_get(row, pie_idx, default=0)
                    result += f"Team Impact Estimate (PIE): {format_stat(pie, is_percentage=True)}\n"

            except (ValueError, IndexError) as e:
                logger.error(f"Error parsing team advanced stats: {e}")
                result += "Unable to parse some advanced statistics\n"

            return [TextContent(type="text", text=result)]

        else:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]

    except Exception as e:
        logger.error(f"Error in {name}: {e}", exc_info=True)
        return [TextContent(type="text", text=f"Error executing {name}: {str(e)}")]


async def main():
    """Run the NBA MCP server."""
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        logger.info("NBA MCP Server starting...")
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options()
        )


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
