# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is an **NBA MCP (Model Context Protocol) Server** that provides access to comprehensive NBA statistics and data through direct HTTP API calls to official NBA endpoints. The server exposes various tools for fetching player stats, game data, team information, and league-wide statistics.

**Key Design Decision**: This project uses **direct HTTP calls** to NBA APIs instead of third-party wrappers like `nba_api` for better reliability, control, easier debugging, and to stay always up-to-date with NBA's API structure.

## Development Commands

### Running the Server

```bash
# With uv (recommended - fast package manager)
uv run python src/nba_server.py

# With activated virtualenv
source .venv/bin/activate  # Always use .venv
python src/nba_server.py
```

### Setting Up Development Environment

```bash
# Using uv (recommended)
uv sync

# Using pip
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Testing with MCP Clients

The server is designed to be used with MCP clients like Claude Desktop or Strands. Configuration examples:

**Claude Desktop** (add to `~/Library/Application Support/Claude/claude_desktop_config.json`):
```json
{
  "mcpServers": {
    "nba-stats": {
      "command": "uv",
      "args": ["--directory", "/absolute/path/to/nba_mcp_server/src/", "run", "nba_server.py"]
    }
  }
}
```

## Architecture

### Core Components

1. **nba_server.py** - Single-file MCP server implementation containing:
   - Server initialization and tool registration
   - Tool handlers for all NBA data operations
   - HTTP client setup with proper headers
   - Error handling and data parsing utilities

2. **NBA API Endpoints**:
   - `https://cdn.nba.com/static/json/liveData` - Live game data, scoreboards, box scores
   - `https://cdn.nba.com/static/json/staticData/scheduleLeagueV2.json` - Full season schedule with future games
   - `https://stats.nba.com/stats` - Historical stats, player info, standings, team data

### Tool Categories

The server exposes 13 MCP tools organized into 4 categories:

**Live Game Tools** (lines 297-644):
- `get_todays_scoreboard` - Today's games with live scores
- `get_scoreboard_by_date` - Games for specific date
- `get_game_details` - Detailed game info with live stats
- `get_box_score` - Full box score with player-by-player stats

**Player Tools** (lines 647-762):
- `search_players` - Search players by name
- `get_player_info` - Player bio and career info
- `get_player_season_stats` - Season statistics

**Team Tools** (lines 765-833):
- `get_all_teams` - List all NBA teams (hardcoded for reliability)
- `get_team_roster` - Current team roster

**League Tools** (lines 836-1049):
- `get_standings` - Current NBA standings
- `get_league_leaders` - Statistical leaders by category
- `get_schedule` - Team schedule with future games (up to 90 days ahead)

### Helper Functions

- **safe_get()** (line 50) - Safely extract nested dictionary values with default fallback
- **format_stat()** (line 62) - Format stat values, handling percentages
- **fetch_nba_data()** (line 75) - Central HTTP fetch with error handling
- **get_current_season()** (line 92) - Calculate current NBA season (YYYY-YY format)

### NBA API Headers

Standard headers are required for NBA API requests (lines 33-39):
- User-Agent, Accept, Referer, Origin headers to mimic browser requests
- These prevent 403 errors from NBA's API

## Important Implementation Details

### Season Format
NBA seasons use YYYY-YY format (e.g., "2024-25"). The season year switches in October when the new season starts (line 92-101).

### Game ID Format
Game IDs follow pattern: `00SYYYYMMDDXXXX` where S is season type, YYYYMMDD is date, XXXX is game sequence.

### Error Handling Strategy
- All API calls go through `fetch_nba_data()` with comprehensive error handling
- HTTP errors, JSON decode errors, and unexpected errors are logged and return None
- Tool handlers check for None and return user-friendly error messages

### Data Parsing Pattern
NBA Stats API returns data in `resultSets` array with `headers` and `rowSet`:
```python
headers = safe_get(data, "resultSets", 0, "headers", default=[])
rows = safe_get(data, "resultSets", 0, "rowSet", default=[])
```
Access specific values by index based on header position.

### Known API Limitations
1. **Box Score Timing**: Detailed player stats may take minutes to appear after game ends
2. **Rate Limiting**: NBA APIs may rate limit requests - handled gracefully with error messages
3. **Schedule API Data**: The scheduleLeagueV2.json endpoint provides the full season schedule, but data structure differs from other NBA APIs (uses nested objects instead of resultSets arrays)

## Working with the Code

### Adding New Tools
1. Add tool definition in `list_tools()` handler (lines 106-288)
2. Implement tool logic in `call_tool()` handler (lines 292-1056)
3. Use `fetch_nba_data()` for API calls
4. Use `safe_get()` for data extraction
5. Return list of `TextContent` objects

### Testing API Endpoints
The server uses synchronous httpx client (`http_client` on line 45) within async handlers. When testing new endpoints:
1. Check NBA Stats API documentation or browser network tab
2. Replicate required headers and parameters
3. Use `fetch_nba_data()` wrapper for consistent error handling

### Debugging
- Logging is configured at INFO level (line 25)
- All errors are logged with context (using `logger.error()`)
- Check logs for HTTP errors, JSON parsing issues, or unexpected exceptions

## Dependencies

- **Python 3.10+** required
- **mcp >= 1.0.0** - Model Context Protocol SDK
- **httpx >= 0.27.0** - Modern async HTTP client
- **uv** (optional) - Fast Python package manager

## Notes for Development

- Always use the `.venv` virtual environment (per user's global instructions)
- The server is designed as a single-file implementation for simplicity
- Hardcoded team IDs (lines 767-798) are more reliable than API lookups
- Live data API is preferred over Stats API when both are available
- All tool responses are formatted as human-readable text, not JSON
