"""Pytest configuration and fixtures."""

import pytest
from unittest.mock import Mock, AsyncMock


@pytest.fixture
def mock_httpx_response():
    """Create a mock httpx response."""
    def _create_response(status_code=200, json_data=None):
        response = Mock()
        response.status_code = status_code
        response.json.return_value = json_data or {}
        response.text = str(json_data) if json_data else ""
        response.raise_for_status = Mock()
        if status_code >= 400:
            import httpx
            response.raise_for_status.side_effect = httpx.HTTPStatusError(
                f"HTTP {status_code}",
                request=Mock(),
                response=response
            )
        return response
    return _create_response


@pytest.fixture
def sample_player_data():
    """Sample player data from NBA API."""
    return {
        "resultSets": [
            {
                "name": "CommonPlayerInfo",
                "headers": ["PERSON_ID", "FIRST_NAME", "LAST_NAME", "DISPLAY_FIRST_LAST"],
                "rowSet": [
                    [2544, "LeBron", "James", "LeBron James"]
                ]
            }
        ]
    }


@pytest.fixture
def sample_game_data():
    """Sample game data from NBA Live API."""
    return {
        "scoreboard": {
            "gameDate": "2025-11-03",
            "games": [
                {
                    "gameId": "0022500001",
                    "gameStatusText": "Final",
                    "homeTeam": {
                        "teamName": "Lakers",
                        "teamCity": "Los Angeles",
                        "score": 110
                    },
                    "awayTeam": {
                        "teamName": "Warriors",
                        "teamCity": "Golden State",
                        "score": 105
                    }
                }
            ]
        }
    }


@pytest.fixture
def sample_all_time_leaders_data():
    """Sample all-time leaders data."""
    return {
        "resultSets": [
            {
                "name": "PTSLeaders",
                "headers": ["PLAYER_ID", "PLAYER_NAME", "PTS", "IS_ACTIVE"],
                "rowSet": [
                    [2544, "LeBron James", 42184, 1],
                    [76003, "Kareem Abdul-Jabbar", 38387, 0],
                    [600, "Karl Malone", 36928, 0]
                ]
            }
        ]
    }
