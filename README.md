# 🏀 NBA MCP SERVER

Access comprehensive NBA statistics via Model Context Protocol

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

A Model Context Protocol (MCP) server that provides access to comprehensive NBA statistics and data. This server allows MCP clients to fetch player stats, game data, team information, and league-wide statistics.

## Features

### Player Tools
- **search_players**: Search for NBA players by name
- **get_player_career_stats**: Get comprehensive career statistics
- **get_player_season_stats**: Get player stats for a specific season
- **get_player_game_log**: Get game-by-game statistics for a player's season
- **get_player_info**: Get detailed player information (bio, height, weight, position, etc.)
- **get_player_awards**: Get all awards and accolades for a specific player

### Team Tools
- **get_all_teams**: Get list of all NBA teams with IDs and names
- **get_team_roster**: Get current roster for a specific team

### Game Tools
- **get_todays_scoreboard**: Get today's NBA games with live scores and real-time updates
- **get_scoreboard_by_date**: Get games for a specific date
- **get_game_details**: Get detailed information about a specific game including live stats
- **get_box_score**: Get full box score with player-by-player statistics (best for detailed stat sheets)

### League Tools
- **get_standings**: Get current NBA standings
- **get_league_leaders**: Get statistical leaders for current season (points, assists, rebounds, etc.)
- **get_all_time_leaders**: Get all-time career leaders across NBA history (points, rebounds, assists, steals, blocks, etc.)
- **get_schedule**: Get upcoming games schedule for a team (supports future games up to 90 days ahead)
- **get_season_awards**: Get major award winners for a specific season (MVP, ROTY, etc.)

### Advanced Stats Tools
- **get_player_hustle_stats**: Get hustle statistics (deflections, charges drawn, screen assists, loose balls recovered, box outs)
- **get_league_hustle_leaders**: Get league leaders in hustle stat categories
- **get_player_defense_stats**: Get defensive impact statistics showing opponent FG% when defended by player

### Shot Chart & Shooting Tools
- **get_shot_chart**: Get shot chart data with X/Y coordinates for every shot attempt, showing shooting patterns by distance and shot type
- **get_shooting_splits**: Get detailed shooting percentages by zone (restricted area, paint, mid-range, corner 3, above the break 3) and distance ranges

## Why Direct API Calls?

This server uses **direct HTTP calls** to NBA APIs instead of third-party wrappers like `nba_api`. This approach provides:

- **Better reliability**: No dependency on third-party package maintenance
- **More control**: Direct access to NBA's official endpoints
- **Easier debugging**: Clear HTTP requests and responses
- **Better error handling**: Custom error handling for API issues
- **Always up-to-date**: Works directly with NBA's current API structure

## Installation

### Option 1: Using uv (Recommended)

[uv](https://github.com/astral-sh/uv) is a fast Python package installer and resolver.

1. Install uv if you haven't already:
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

2. Clone and set up the project:
```bash
git clone https://github.com/labeveryday/nba_mcp_server.git
cd nba_mcp_server
uv sync
```

### Option 2: Using pip

1. Clone the repository:
```bash
git clone https://github.com/labeveryday/nba_mcp_server.git
cd nba_mcp_server
```

2. Create and activate a virtual environment:
```bash
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

## Usage

### Using with Strands (or other MCP clients)

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

Or with direct Python:

```python
mcp_client = MCPClient(lambda: stdio_client(
    StdioServerParameters(
        command="/path/to/nba_mcp_server/.venv/bin/nba-mcp-server",
        args=[]
    )
))
```

### Using with Claude Desktop

Add this configuration to your Claude Desktop config file:

**MacOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
**Windows**: `%APPDATA%/Claude/claude_desktop_config.json`

#### With uv:
```json
{
  "mcpServers": {
    "nba-stats": {
      "command": "uv",
      "args": [
        "--directory",
        "/absolute/path/to/nba_mcp_server/",
        "run", "nba-mcp-server"
      ]
    }
  }
}
```

#### With Python directly:
```json
{
  "mcpServers": {
    "nba-stats": {
      "command": "/absolute/path/to/nba_mcp_server/.venv/bin/nba-mcp-server",
      "args": []
    }
  }
}
```

### Running the Server Directly (for testing)

```bash
# With uv
uv run nba-mcp-server

# Or with activated virtualenv
source .venv/bin/activate
nba-mcp-server

# Or run as Python module
python -m nba_mcp_server
```

## Example Queries

Once the server is running and connected to your MCP client, you can ask questions like:

- "Show me today's NBA games"
- "Get the full stat sheet for [team] vs [team]" (will use get_box_score)
- "Who was the leading scorer in the Timberwolves vs Nets game?"
- "Who led in rebounds for [team] vs [team]?"
- "Search for LeBron James and get his player info"
- "What are Stephen Curry's stats for this season?"
- "Get the current NBA standings"
- "Who are the top 10 scorers this season?"
- "Who are the top 5 scorers of all time?"
- "Show me the all-time assists leaders"
- "Show me all NBA teams"
- "Get the roster for the Lakers"
- "When do the Lakers play next?"
- "Show me the Grizzlies schedule for the next 30 days"
- "Get hustle stats for Jayson Tatum"
- "Who are the league leaders in deflections?"
- "Show me defensive impact stats for this player"
- "Who draws the most charges in the NBA?"
- "Show me all of LeBron James' awards and accolades"
- "Who won MVP in the 2002-03 season?"
- "Get Tim Duncan's career awards"
- "Show me Stephen Curry's shot chart for this season"
- "Get shooting splits by zone for Kevin Durant"
- "Where does LeBron shoot best on the court?"

## Tool Reference

### search_players
Search for NBA players by name.

**Parameters:**
- `name` (string, required): Player name or partial name to search for

**Example:**
```
name: "LeBron"
```

### get_player_career_stats
Get comprehensive career statistics for a specific player.

**Parameters:**
- `player_id` (string, required): NBA player ID (use search_players to find)

**Example:**
```
player_id: "2544"
```

### get_player_season_stats
Get player statistics for a specific season.

**Parameters:**
- `player_id` (string, required): NBA player ID
- `season` (string, optional): Season in format YYYY-YY (e.g., '2023-24'). Defaults to current season.

**Example:**
```
player_id: "2544"
season: "2023-24"
```

### get_player_game_log
Get game-by-game log for a player's season, showing all individual games with stats. Useful for finding highest-scoring games or specific performances.

**Parameters:**
- `player_id` (string, required): NBA player ID
- `season` (string, optional): Season in format YYYY-YY (e.g., '2002-03'). Defaults to current season.

**Example:**
```
player_id: "893"
season: "2002-03"
```

### get_player_info
Get detailed information about a player.

**Parameters:**
- `player_id` (string, required): NBA player ID

**Example:**
```
player_id: "2544"
```

### get_all_teams
Get list of all NBA teams with IDs and names.

**Parameters:** None

### get_team_roster
Get current roster for a specific NBA team.

**Parameters:**
- `team_id` (string, required): NBA team ID (use get_all_teams to find)
- `season` (string, optional): Season in format YYYY-YY (e.g., '2024-25'). Defaults to current season.

**Example:**
```
team_id: "1610612747"
season: "2024-25"
```

### get_todays_scoreboard
Get today's NBA games with live scores and status. Returns game IDs for use with other tools.

**Parameters:** None

### get_scoreboard_by_date
Get games for a specific date.

**Parameters:**
- `date` (string, required): Date in format YYYYMMDD (e.g., '20241103')

**Example:**
```
date: "20241103"
```

### get_game_details
Get detailed information about a specific game including live stats.

**Parameters:**
- `game_id` (string, required): NBA game ID from get_todays_scoreboard

**Example:**
```
game_id: "0022400123"
```

### get_box_score
Get full box score with player-by-player statistics. Best for detailed stat sheets.

**Parameters:**
- `game_id` (string, required): NBA game ID from get_todays_scoreboard

**Example:**
```
game_id: "0022400123"
```

**Returns:**
- Team statistics (FG%, 3P, FT, rebounds, assists, etc.)
- Player-by-player stats table with minutes, points, rebounds, assists, shooting percentages

### get_standings
Get current NBA standings for all teams.

**Parameters:**
- `season` (string, optional): Season in format YYYY-YY (e.g., '2023-24'). Defaults to current season.

**Example:**
```
season: "2023-24"
```

### get_league_leaders
Get statistical leaders across the league.

**Parameters:**
- `stat_category` (string, optional): Stat category: 'PTS' (points), 'AST' (assists), 'REB' (rebounds), 'STL' (steals), 'BLK' (blocks), 'FG_PCT' (field goal %), etc. Defaults to 'PTS'.
- `season` (string, optional): Season in format YYYY-YY (e.g., '2023-24'). Defaults to current season.

**Example:**
```
stat_category: "PTS"
season: "2023-24"
```

### get_all_time_leaders
Get all-time career leaders across NBA history for any stat category.

**Parameters:**
- `stat_category` (string, optional): Stat category to rank. Options: 'points', 'rebounds', 'assists', 'steals', 'blocks', 'games', 'offensive_rebounds', 'defensive_rebounds', 'field_goals_made', 'field_goal_pct', 'three_pointers_made', 'three_point_pct', 'free_throws_made', 'free_throw_pct', 'turnovers', 'personal_fouls'. Defaults to 'points'.
- `limit` (integer, optional): Number of leaders to return (default: 10, max: 50)

**Examples:**
```
# Get top 10 all-time scoring leaders
stat_category: "points"
limit: 10

# Get top 5 all-time assist leaders
stat_category: "assists"
limit: 5
```

**Returns:**
- Ranked list of all-time leaders
- Player names and career totals
- Active player indicator (✓)

### get_schedule
Get upcoming games schedule for a specific team.

**Parameters:**
- `team_id` (string, required): Team ID to get games for (use get_all_teams to find IDs)
- `days_ahead` (integer, optional): Number of days to look ahead (default: 7, max: 90)

**Examples:**
```
# Get next 30 days of Wizards games
team_id: "1610612764"
days_ahead: 30
```

**Returns:**
- Upcoming games for the specified team
- Game dates, times (ET), and locations
- Opponent information
- Arena details (name, city, state)
- Game IDs for use with other tools

### get_player_hustle_stats
Get comprehensive hustle statistics for a specific player.

**Parameters:**
- `player_id` (string, required): NBA player ID
- `season` (string, optional): Season in format YYYY-YY (e.g., '2024-25'). Defaults to current season.

**Examples:**
```
# Get Jayson Tatum's hustle stats for 2024-25
player_id: "1628369"
season: "2024-25"
```

**Returns:**
- Contested shots (total, 2PT, 3PT)
- Deflections
- Charges drawn
- Screen assists and points generated
- Loose balls recovered (offensive, defensive, total)
- Box outs (offensive, defensive, total)

### get_league_hustle_leaders
Get league leaders in various hustle stat categories.

**Parameters:**
- `stat_category` (string, optional): Category to rank: 'deflections', 'charges', 'screen_assists', 'loose_balls', 'box_outs'. Defaults to 'deflections'.
- `season` (string, optional): Season in format YYYY-YY (e.g., '2024-25'). Defaults to current season.

**Examples:**
```
# Get top deflection leaders
stat_category: "deflections"
season: "2024-25"

# Get top charge-takers
stat_category: "charges"
```

**Returns:**
- Top 10 players in the selected hustle category
- Player names, teams, and stat values

### get_player_defense_stats
Get defensive impact statistics showing how opponents shoot when defended by a player.

**Parameters:**
- `player_id` (string, required): NBA player ID
- `season` (string, optional): Season in format YYYY-YY (e.g., '2024-25'). Defaults to current season.

**Examples:**
```
# Get defensive impact for a player
player_id: "1628369"
season: "2024-25"
```

**Returns:**
- Opponent FG%, FGM, FGA when defended by this player
- Opponent normal FG% (league average)
- Percentage point difference
- Analysis of defensive effectiveness

### get_player_awards
Get all awards and accolades for a specific player.

**Parameters:**
- `player_id` (string, required): NBA player ID (use search_players to find)

**Example:**
```
player_id: "2544"  # LeBron James
```

**Returns:**
- NBA MVP awards
- Finals MVP awards
- NBA Championships
- All-NBA Team selections
- All-Defensive Team selections
- All-Star selections
- All-Star Game MVP awards
- Rookie awards
- Other honors and achievements
- Total award count

### get_season_awards
Get major award winners for a specific NBA season.

**Parameters:**
- `season` (string, optional): Season in format YYYY-YY (e.g., '2002-03'). Defaults to current season.

**Example:**
```
season: "2002-03"
```

**Returns:**
- NBA Most Valuable Player (MVP)
- Note: For comprehensive season award information including Finals MVP, ROTY, DPOY, MIP, 6MOY, and All-NBA teams, use the get_player_awards tool to look up individual award winners.

**Available Seasons:**
- 2000-01 through 2023-24

### get_shot_chart
Get shot chart data with X/Y coordinates for every shot attempt by a player. Useful for visualizing shooting patterns and identifying hot zones.

**Parameters:**
- `player_id` (string, required): NBA player ID (use search_players to find)
- `season` (string, optional): Season in format YYYY-YY (e.g., '2024-25'). Defaults to current season.
- `game_id` (string, optional): Specific game ID to get shot chart for single game

**Example:**
```
player_id: "2544"
season: "2024-25"
```

**Returns:**
- Overall shooting statistics (total shots, makes, misses, FG%)
- Shooting by distance ranges (0-5 ft, 5-10 ft, 10-15 ft, etc.)
- Top shot types with accuracy (layups, jump shots, dunks, etc.)
- Note: Contains X/Y coordinates for all shots for visualization

### get_shooting_splits
Get detailed shooting percentages by zone and distance. Shows where a player is most efficient on the court.

**Parameters:**
- `player_id` (string, required): NBA player ID (use search_players to find)
- `season` (string, optional): Season in format YYYY-YY (e.g., '2024-25'). Defaults to current season.

**Example:**
```
player_id: "2544"
season: "2024-25"
```

**Returns:**
- Shooting by distance ranges (Less than 5 ft, 5-9 ft, 10-14 ft, etc.)
- Shooting by area (Restricted Area, In The Paint, Mid-Range, Left Corner 3, Right Corner 3, Above the Break 3)
- Overall shooting stats (Total FG, 2-Point FG, 3-Point FG with percentages)

## Data Sources

This server uses direct HTTP calls to official NBA APIs:

- **Live Data API**: `https://cdn.nba.com/static/json/liveData` - For live scores and game data
- **Schedule API**: `https://cdn.nba.com/static/json/staticData/scheduleLeagueV2.json` - For full season schedule with future games
- **Stats API**: `https://stats.nba.com/stats` - For player stats, team info, standings, and historical data

### Why These APIs?

- **Official**: Direct access to NBA's official data
- **Reliable**: Well-maintained by NBA
- **Comprehensive**: Full coverage of stats, games, players, and teams
- **Real-time**: Live game updates and scores

## Known Limitations

- **Box Score Timing**: Detailed player stats may take a few minutes to appear after a game ends.
- **Rate Limiting**: The NBA APIs may rate limit requests. The server handles errors gracefully.

## Development

### Running Tests

```bash
# Install dev dependencies
uv sync --all-extras

# Run tests
uv run pytest

# Run tests with coverage
uv run pytest --cov=nba_mcp_server --cov-report=html

# Run specific test file
uv run pytest tests/test_helpers.py

# Run with verbose output
uv run pytest -v
```

### Code Quality

```bash
# Install ruff
uv pip install ruff

# Check code
uv run ruff check src/

# Format code
uv run ruff format src/
```

## Requirements

- Python 3.10+
- mcp >= 1.0.0
- httpx >= 0.27.0

### Optional
- uv (recommended for faster package management)

## License

See LICENSE file for details.

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.
