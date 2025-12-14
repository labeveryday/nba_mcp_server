# 🏀 NBA MCP Server

Access comprehensive NBA statistics via Model Context Protocol

Get live scores, player stats, team data, and advanced analytics through a simple MCP server interface.

## Quick Start

### With uvx (Recommended - No Install Required)

Add to your MCP client config (e.g., Claude Desktop):

**MacOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
**Windows**: `%APPDATA%/Claude/claude_desktop_config.json`

```json
{
  "mcpServers": {
    "nba-stats": {
      "command": "uvx",
      "args": ["nba-stats-mcp"]
    }
  }
}
```

Restart your client and start asking!

### With pip

```bash
pip install nba-stats-mcp
```

Then configure your MCP client:

```json
{
  "mcpServers": {
    "nba-stats": {
      "command": "nba-stats-mcp"
    }
  }
}
```

## What You Can Ask

- "Show me today's NBA games"
- "What are LeBron James' stats this season?"
- "Get the box score for Lakers vs Warriors"
- "Who are the top 10 scorers this season?"
- "Show me all-time assists leaders"
- "When do the Celtics play next?"
- "Get Stephen Curry's shot chart"
- "Show me Giannis' career awards"

## Features

**30 comprehensive tools** providing access to:
- Live game scores and play-by-play
- Player stats, career data, and awards
- Team rosters and advanced metrics
- League standings and leaders
- Shot charts and shooting analytics
- Historical NBA data

📖 **[Full Documentation & Tool Reference →](https://github.com/labeveryday/nba_mcp_server)**

## Requirements

- Python 3.10+
- An MCP-compatible client

## License

MIT License - See [LICENSE](https://github.com/labeveryday/nba_mcp_server/blob/main/LICENSE) for details.
