# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2025-11-03

### Added
- Initial release of NBA MCP Server
- 16 tools for comprehensive NBA data access:
  - **Live Game Tools**: Today's scoreboard, scoreboard by date, game details, box scores
  - **Player Tools**: Player search, player info, season stats, career stats, hustle stats, defense stats
  - **Team Tools**: List all teams, team rosters
  - **League Tools**: Standings, league leaders, all-time leaders, hustle leaders, team schedules
- Direct HTTP API integration with NBA's official endpoints
- Support for live game data, historical statistics, and future schedules
- Real-time score updates and player-by-player stats
- Advanced statistics including hustle stats and defensive impact

### Changed
- League leaders tool now uses `leaguegamelog` endpoint with aggregation for better reliability

### Technical
- Single-file MCP server implementation for simplicity
- Proper error handling and fallback strategies
- Support for Python 3.10+
- Uses MCP SDK 1.0.0+ and httpx for HTTP requests

[0.1.0]: https://github.com/labeveryday/nba_mcp_server/releases/tag/v0.1.0
