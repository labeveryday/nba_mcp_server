# 🏀 NBA MCP Server

Access comprehensive NBA statistics via Model Context Protocol

A Model Context Protocol (MCP) server that provides access to live and historical NBA data including player stats, game scores, team information, and advanced analytics.

## Quick Start with Claude Desktop

1. Install the server:
```bash
# Using uv (recommended)
git clone https://github.com/labeveryday/nba_mcp_server.git
cd nba_mcp_server
uv sync

# Or using pip
pip install nba-mcp-server
```

2. Add to your Claude Desktop config file:

**MacOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
**Windows**: `%APPDATA%/Claude/claude_desktop_config.json`

```json
{
  "mcpServers": {
    "nba-stats": {
      "command": "uv",
      "args": [
        "--directory",
        "/absolute/path/to/nba_mcp_server/",
        "run",
        "nba-mcp-server"
      ]
    }
  }
}
```

3. Restart Claude Desktop

## What You Can Ask

- "Show me today's NBA games"
- "What are LeBron James' stats this season?"
- "Get the box score for Lakers vs Warriors"
- "Who are the top 10 scorers this season?"
- "Show me all-time assists leaders"
- "When do the Celtics play next?"
- "Get Stephen Curry's shot chart"
- "Who are the league leaders in deflections?"
- "Show me Giannis' career awards"

## Available Tools (26 total)

### Player Stats
- `search_players` - Find players by name
- `get_player_info` - Player bio and details
- `get_player_season_stats` - Current/historical season stats
- `get_player_career_stats` - Career totals and averages
- `get_player_game_log` - Game-by-game performance
- `get_player_awards` - All awards and accolades
- `get_player_hustle_stats` - Deflections, charges, loose balls, box outs
- `get_player_defense_stats` - Opponent FG% when defended
- `get_player_advanced_stats` - TS%, ORtg, DRtg, USG%, PIE

### Team Stats
- `get_all_teams` - All 30 NBA teams
- `get_team_roster` - Team roster
- `get_team_advanced_stats` - Team efficiency metrics

### Live Games
- `get_todays_scoreboard` - Today's games with live scores
- `get_scoreboard_by_date` - Games for specific date
- `get_game_details` - Detailed game info with live stats
- `get_box_score` - Full box score with player stats
- `get_play_by_play` - Complete play-by-play data
- `get_game_rotation` - Player substitution patterns

### League Stats
- `get_standings` - Current NBA standings
- `get_league_leaders` - Statistical leaders (PTS, AST, REB, etc.)
- `get_all_time_leaders` - All-time career leaders
- `get_league_hustle_leaders` - League leaders in hustle stats
- `get_schedule` - Team schedule (up to 90 days ahead)
- `get_season_awards` - Season MVP and major awards

### Shooting Analytics
- `get_shot_chart` - Shot locations with X/Y coordinates
- `get_shooting_splits` - Shooting % by zone and distance

## Installation Options

### With uv (recommended)
```bash
git clone https://github.com/labeveryday/nba_mcp_server.git
cd nba_mcp_server
uv sync
```

### With pip
```bash
pip install nba-mcp-server
```

### From source
```bash
git clone https://github.com/labeveryday/nba_mcp_server.git
cd nba_mcp_server
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -e .
```

## Usage with Other MCP Clients

### Python/Strands
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

### Running Standalone (for testing)
```bash
uv run nba-mcp-server
# or
python -m nba_mcp_server
```

## Configuration

### Logging Levels

Control logging verbosity with the `NBA_MCP_LOG_LEVEL` environment variable (default: WARNING):

```bash
export NBA_MCP_LOG_LEVEL=INFO  # For debugging
uv run nba-mcp-server
```

In Claude Desktop config:
```json
{
  "mcpServers": {
    "nba-stats": {
      "command": "uv",
      "args": ["--directory", "/path/to/nba_mcp_server/", "run", "nba-mcp-server"],
      "env": {
        "NBA_MCP_LOG_LEVEL": "INFO"
      }
    }
  }
}
```

## Data Sources

This server uses official NBA APIs:
- **Live Data API** - Real-time scores and game data
- **Stats API** - Player stats, team info, historical data
- **Schedule API** - Full season schedule including future games

## Development

### Running Tests
```bash
uv sync --all-extras
uv run pytest
uv run pytest --cov=nba_mcp_server --cov-report=html
```

### Code Quality
```bash
uv run ruff check src/
uv run ruff format src/
```

## Requirements

- Python 3.10+
- mcp >= 1.0.0
- httpx >= 0.27.0

## License

MIT License - see LICENSE file for details.

## Contributing

Contributions welcome! Please submit a Pull Request.

## About the Author

>This project was created by **Du'An Lightfoot**, a developer passionate about AI agents, cloud infrastructure, and teaching in public.
>
>Learn more and connect:
>- 🌐 Website: [duanlightfoot.com](https://duanlightfoot.com)
>- 📺 YouTube: [@LabEveryday](https://www.youtube.com/@LabEveryday)
>- 🐙 GitHub: [@labeveryday](https://github.com/labeveryday)
