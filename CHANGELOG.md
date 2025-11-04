# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Comprehensive endpoint verification system
- ENDPOINT_VERIFICATION.md report documenting all 17 working endpoints
- Verification script to test all tools with real API calls

### Fixed
- `get_player_season_stats` now uses `playercareerstats` endpoint (fixes 500 errors)
- `get_league_leaders` now uses `leaguegamelog` endpoint (fixes 500 errors)

### Changed
- All 17 endpoints verified working and production-ready

## [0.1.0] - 2025-11-03

### Added
- Initial release of NBA MCP Server
- 17 tools for comprehensive NBA data access:
  - **Live Game Tools**: Today's scoreboard, scoreboard by date, game details, box scores
  - **Player Tools**: Player search, player info, season stats, career stats, hustle stats, defense stats
  - **Team Tools**: List all teams, team rosters
  - **League Tools**: Standings, league leaders, all-time leaders, hustle leaders, team schedules
- Direct HTTP API integration with NBA's official endpoints
- Support for live game data, historical statistics, and future schedules
- Real-time score updates and player-by-player stats
- Advanced statistics including hustle stats and defensive impact
- Comprehensive test suite (25 tests)
- GitHub Actions CI/CD pipeline
- PyPI-ready package structure

### Technical
- Single-module implementation for simplicity
- Proper error handling and fallback strategies
- Support for Python 3.10+
- Uses MCP SDK 1.0.0+ and httpx for HTTP requests
- Pytest with coverage reporting
- Multi-platform CI testing (Ubuntu, macOS, Windows)

[0.1.0]: https://github.com/labeveryday/nba_mcp_server/releases/tag/v0.1.0
