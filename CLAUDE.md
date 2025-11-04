# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is an **NBA MCP (Model Context Protocol) Server** that provides access to comprehensive NBA statistics and data through direct HTTP API calls to official NBA endpoints. The server exposes 18 tools for fetching player stats, game data, team information, and league-wide statistics.

**Key Design Decision**: This project uses **direct HTTP calls** to NBA APIs instead of third-party wrappers like `nba_api` for better reliability, control, easier debugging, and to stay always up-to-date with NBA's API structure.

**Architecture**: Single-module implementation (`src/nba_mcp_server/server.py`) containing all server logic, tool handlers, and utilities (~1528 lines).

## Development Commands

### Running the Server

```bash
# With uv (recommended - fast package manager)
uv run nba-mcp-server

# With activated virtualenv
source .venv/bin/activate  # Always use .venv
nba-mcp-server

# Or run directly with Python
python -m nba_mcp_server
```

### Setting Up Development Environment

```bash
# Using uv (recommended)
uv sync --all-extras  # Installs dev dependencies including pytest

# Using pip
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"  # Installs package in editable mode with dev dependencies
```

### Running Tests

```bash
# Run all tests
uv run pytest

# Run with coverage report
uv run pytest --cov=nba_mcp_server --cov-report=html

# Run specific test file or function
uv run pytest tests/test_helpers.py
uv run pytest tests/test_server.py::TestGetAllTeams

# Run with verbose output
uv run pytest -v
```

The test suite includes:
- **Unit tests** (`tests/test_helpers.py`): Tests for utility functions (safe_get, format_stat, get_current_season)
- **Integration tests** (`tests/test_server.py`): Tests for server initialization, tool registration, and API calls with mocking
- **Fixtures** (`tests/conftest.py`): Reusable test fixtures for mock data and responses

### Testing with MCP Clients

The server is designed to be used with MCP clients like Claude Desktop or Strands. Configuration examples:

**Claude Desktop** (add to `~/Library/Application Support/Claude/claude_desktop_config.json`):
```json
{
  "mcpServers": {
    "nba-stats": {
      "command": "uv",
      "args": ["--directory", "/absolute/path/to/nba_mcp_server/", "run", "nba-mcp-server"]
    }
  }
}
```

**Strands or Python MCP Clients**:
```python
from mcp import stdio_client, StdioServerParameters
from strands.tools.mcp import MCPClient

mcp_client = MCPClient(lambda: stdio_client(
    StdioServerParameters(
        command="uv",
        args=["--directory", "/path/to/nba_mcp_server/", "run", "nba-mcp-server"]
    )
))
```

## Architecture

### Core Components

1. **src/nba_mcp_server/** - Python package containing:
   - **server.py** - Main MCP server implementation with:
     - Server initialization and tool registration
     - Tool handlers for all NBA data operations
     - HTTP client setup with proper headers
     - Error handling and data parsing utilities
   - **__init__.py** - Package initialization with version and exports

2. **NBA API Endpoints**:
   - `https://cdn.nba.com/static/json/liveData` - Live game data, scoreboards, box scores
   - `https://cdn.nba.com/static/json/staticData/scheduleLeagueV2.json` - Full season schedule with future games
   - `https://stats.nba.com/stats` - Historical stats, player info, standings, team data

### Tool Categories

The server exposes 18 MCP tools organized into 4 categories:

**Live Game Tools** (lines 394-741):
- `get_todays_scoreboard` - Today's games with live scores
- `get_scoreboard_by_date` - Games for specific date
- `get_game_details` - Detailed game info with live stats
- `get_box_score` - Full box score with player-by-player stats

**Player Tools** (lines 744-1164):
- `search_players` - Search players by name (searches all players including retired)
- `get_player_info` - Player bio and career info
- `get_player_season_stats` - Season statistics
- `get_player_game_log` - Game-by-game log with highest-scoring games **NEW**
- `get_player_career_stats` - Comprehensive career totals and averages
- `get_player_hustle_stats` - Deflections, charges drawn, screen assists, loose balls, box outs
- `get_player_defense_stats` - Defensive impact (opponent FG% when defended by player)

**Team Tools** (lines 1096-1164):
- `get_all_teams` - List all 30 NBA teams (hardcoded for reliability)
- `get_team_roster` - Current team roster

**League Tools** (lines 1167-1450):
- `get_standings` - Current NBA standings
- `get_league_leaders` - Statistical leaders by category (current season)
- `get_all_time_leaders` - All-time career leaders across NBA history
- `get_league_hustle_leaders` - League leaders in hustle stats
- `get_schedule` - Team schedule with future games (up to 90 days ahead)

### Helper Functions

- **safe_get()** (line 50) - Safely extract nested dictionary/list values with default fallback; handles both dict keys and list indices
- **format_stat()** (line 71) - Format stat values for display, with optional percentage formatting
- **fetch_nba_data()** (line 84) - Central async HTTP fetch wrapper with comprehensive error handling (HTTP errors, JSON decode, exceptions)
- **get_current_season()** (line 101) - Calculate current NBA season in YYYY-YY format (switches in October)

### NBA API Headers

Standard headers are required for NBA API requests (lines 33-39):
- User-Agent, Accept, Referer, Origin headers to mimic browser requests
- These prevent 403 errors from NBA's API

## NBA API Implementation Details

### Season Format
NBA seasons use YYYY-YY format (e.g., "2024-25"). The season year switches in October when the new season starts (line 101-110).

### Game ID Format
Game IDs follow pattern: `00SYYYYMMDDXXXX` where S is season type, YYYYMMDD is date, XXXX is game sequence.

### Error Handling Strategy
- All API calls go through `fetch_nba_data()` with comprehensive error handling
- HTTP errors, JSON decode errors, and unexpected errors are logged and return None
- Tool handlers check for None and return user-friendly error messages

### Data Parsing Patterns

**NBA Stats API** returns data in `resultSets` array with `headers` and `rowSet`:
```python
headers = safe_get(data, "resultSets", 0, "headers", default=[])
rows = safe_get(data, "resultSets", 0, "rowSet", default=[])
# Access specific values by numeric index based on header position
player_name = safe_get(row, 2)  # Index 2 corresponds to player name
```

**NBA Live Data API** returns nested objects directly:
```python
games = safe_get(data, "scoreboard", "games", default=[])
home_team = safe_get(game, "homeTeam", default={})
score = safe_get(home_team, "score", default=0)
```

**Schedule API** uses nested objects with different structure than Stats API (no resultSets).

### Known API Limitations
1. **Box Score Timing**: Detailed player stats may take minutes to appear after game ends. The `get_box_score` tool tries live data API first, then falls back to stats API.
2. **Rate Limiting**: NBA APIs may rate limit requests - handled gracefully with error messages
3. **Schedule API Data**: The scheduleLeagueV2.json endpoint provides the full season schedule including future games, but data structure differs from Stats API (uses nested objects instead of resultSets arrays)
4. **Player Search**: The `search_players` tool sets `IsOnlyCurrentSeason=0` to include retired players in results
5. **League Leaders Endpoint**: The original `leagueleaders` endpoint frequently returns 500 errors. The `get_league_leaders` tool now uses `leaguegamelog` and aggregates game-by-game data to calculate season averages (lines 1218-1321)
6. **Player Season Stats Endpoint**: The `playerdashboardbyyearoveryear` endpoint frequently returns 500 errors. The `get_player_season_stats` tool now uses `playercareerstats` and filters by season (lines 825-884)

## Working with the Code

### Adding New Tools
1. Add tool definition in `@server.list_tools()` handler (lines 115-385)
   - Define the tool name, description, and inputSchema
   - Follow existing patterns for parameter definitions
2. Implement tool logic in `@server.call_tool()` handler (lines 388-1457)
   - Add new `elif name == "tool_name":` block
   - Use `fetch_nba_data()` for all API calls
   - Use `safe_get()` for data extraction
   - Return list of `TextContent` objects
3. Test thoroughly with MCP client

### Testing API Endpoints
The server uses synchronous httpx client (`http_client` on line 45) within async handlers. When testing new endpoints:
1. Check NBA Stats API documentation or use browser network tab to reverse-engineer endpoints
2. Replicate required headers (already set in NBA_HEADERS) and parameters
3. Use `fetch_nba_data()` wrapper for consistent error handling
4. Remember: Stats API uses resultSets/rowSet, Live Data API uses nested objects

### Debugging
- Logging is configured at INFO level (line 25)
- All errors are logged with full context and stack traces (`logger.error(..., exc_info=True)`)
- Check logs for HTTP errors, JSON parsing issues, or unexpected exceptions
- Use `logger.info()` to add debug logging if needed

## Code Organization & Design Decisions

### Single-Module Design
- The entire server is implemented in one module (`src/nba_mcp_server/server.py`) for simplicity
- No need to navigate multiple modules - all logic is in one place
- ~1528 lines total including all tools, helpers, and server setup
- Package structure follows Python best practices for PyPI distribution

### Hardcoded Team Data
- Team IDs and names are hardcoded in two places:
  - `get_all_teams` tool (lines 1098-1135)
  - `get_schedule` tool (lines 1409-1426)
- This is intentional and more reliable than API lookups
- All 30 NBA teams are included

### API Preference Strategy
- Live Data API is preferred over Stats API when both are available
- `get_box_score` tries Live Data first (line 548), falls back to Stats API (line 657)
- Live Data provides cleaner, more real-time data during games
- Stats API is better for historical data and detailed statistics
- When primary endpoints fail (e.g., `leagueleaders`), we use alternative endpoints like `leaguegamelog` with data aggregation

### Response Format
- All tool responses are formatted as human-readable text, not JSON
- Formatting includes tables, headers, and organized sections
- Uses consistent formatting patterns (e.g., player stats tables with aligned columns)

### Virtual Environment
- Always use `.venv` virtual environment (per user's global instructions)
- Server expects to run from project root or via MCP client configuration

## Dependencies

- **Python 3.10+** required (specified in pyproject.toml)
- **mcp >= 1.0.0** - Model Context Protocol SDK
- **httpx >= 0.27.0** - HTTP client (synchronous mode used within async handlers)
- **uv** (optional but recommended) - Fast Python package manager for installation
