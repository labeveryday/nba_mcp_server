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

import logging
from typing import Any, Optional
from datetime import datetime, timedelta
import json

from mcp.server import Server
from mcp.types import Tool, TextContent
import mcp.server.stdio
import httpx

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nba-mcp-server")

# NBA API endpoints
NBA_LIVE_API = "https://cdn.nba.com/static/json/liveData"
NBA_STATS_API = "https://stats.nba.com/stats"

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

# HTTP client with timeout
http_client = httpx.Client(timeout=30.0, headers=NBA_HEADERS)


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
    try:
        response = http_client.get(url, params=params)
        response.raise_for_status()
        return response.json()
    except httpx.HTTPError as e:
        logger.error(f"HTTP error fetching {url}: {e}")
        return None
    except json.JSONDecodeError as e:
        logger.error(f"JSON decode error for {url}: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error fetching {url}: {e}")
        return None


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
    ]


@server.call_tool()
async def call_tool(name: str, arguments: Any) -> list[TextContent]:
    """Handle tool calls for NBA data."""

    try:
        # Live Game Tools
        if name == "get_todays_scoreboard":
            # Get today's scoreboard
            url = f"{NBA_LIVE_API}/scoreboard/todaysScoreboard_00.json"
            data = await fetch_nba_data(url)

            if not data:
                return [TextContent(type="text", text="Error fetching today's scoreboard. Please try again.")]

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
                return [TextContent(type="text", text=f"No data available for {formatted_date}. The game data might not be available yet or the date might be incorrect.")]

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

            url = f"{NBA_STATS_API}/playerdashboardbyyearoveryear"
            params = {
                "PlayerID": player_id,
                "Season": season,
                "SeasonType": "Regular Season"
            }

            data = await fetch_nba_data(url, params)

            if not data:
                return [TextContent(type="text", text="Error fetching player stats. Please try again.")]

            # Parse season stats
            stats_data = safe_get(data, "resultSets", 0, "rowSet", 0, default=[])

            if not stats_data or stats_data == "N/A":
                return [TextContent(type="text", text=f"No stats found for season {season}.")]

            result = f"Season Stats ({season}):\n\n"
            result += f"Games Played: {safe_get(stats_data, 3)}\n"  # GP
            result += f"Minutes Per Game: {format_stat(safe_get(stats_data, 8))}\n"  # MIN
            result += f"Points Per Game: {format_stat(safe_get(stats_data, 26))}\n"  # PTS
            result += f"Rebounds Per Game: {format_stat(safe_get(stats_data, 18))}\n"  # REB
            result += f"Assists Per Game: {format_stat(safe_get(stats_data, 19))}\n"  # AST
            result += f"Steals Per Game: {format_stat(safe_get(stats_data, 21))}\n"  # STL
            result += f"Blocks Per Game: {format_stat(safe_get(stats_data, 22))}\n"  # BLK
            result += f"FG%: {format_stat(safe_get(stats_data, 9), True)}\n"  # FG_PCT
            result += f"3P%: {format_stat(safe_get(stats_data, 12), True)}\n"  # FG3_PCT
            result += f"FT%: {format_stat(safe_get(stats_data, 15), True)}\n"  # FT_PCT

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

            result = f"Career Statistics (Regular Season):\n\n"
            result += f"Total Points: {int(total_points):,}\n"
            result += f"Games Played: {int(total_games):,}\n"
            result += f"Total Rebounds: {int(total_rebounds):,}\n"
            result += f"Total Assists: {int(total_assists):,}\n"
            result += f"Total Steals: {int(total_steals):,}\n"
            result += f"Total Blocks: {int(total_blocks):,}\n"
            result += f"Total Minutes: {int(total_minutes):,}\n\n"
            result += f"Career Averages:\n"
            result += f"Points Per Game: {ppg:.1f}\n"
            result += f"Rebounds Per Game: {rpg:.1f}\n"
            result += f"Assists Per Game: {apg:.1f}\n\n"
            result += f"Shooting Percentages:\n"
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
            result += f"Contest & Defense:\n"
            result += f"  Total Contested Shots: {safe_get(player_stats, 7, default=0)}\n"
            result += f"  Contested 2PT Shots: {safe_get(player_stats, 8, default=0)}\n"
            result += f"  Contested 3PT Shots: {safe_get(player_stats, 9, default=0)}\n"
            result += f"  Deflections: {safe_get(player_stats, 10, default=0)}\n"
            result += f"  Charges Drawn: {safe_get(player_stats, 11, default=0)}\n\n"
            result += f"Screen Assists:\n"
            result += f"  Screen Assists: {safe_get(player_stats, 12, default=0)}\n"
            result += f"  Points from Screen Assists: {safe_get(player_stats, 13, default=0)}\n\n"
            result += f"Loose Balls:\n"
            result += f"  Offensive Loose Balls: {safe_get(player_stats, 14, default=0)}\n"
            result += f"  Defensive Loose Balls: {safe_get(player_stats, 15, default=0)}\n"
            result += f"  Total Loose Balls Recovered: {safe_get(player_stats, 16, default=0)}\n\n"
            result += f"Box Outs:\n"
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
            result += f"When Defended By This Player:\n"
            result += f"  Opponent FGM: {dfgm}\n"
            result += f"  Opponent FGA: {dfga}\n"
            result += f"  Opponent FG%: {format_stat(dfg_pct, True)}\n\n"
            result += f"Comparison:\n"
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
            teams = {
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

            result = "NBA Teams:\n\n"
            for team_id, team_name in sorted(teams.items(), key=lambda x: x[1]):
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
