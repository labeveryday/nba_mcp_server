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


@pytest.fixture
def sample_player_awards_data():
    """Sample player awards data from NBA API."""
    return {
        "resultSets": [
            {
                "name": "PlayerAwards",
                "headers": ["PERSON_ID", "FIRST_NAME", "LAST_NAME", "TEAM", "DESCRIPTION", "ALL_NBA_TEAM_NUMBER", "SEASON", "MONTH", "WEEK", "CONFERENCE", "TYPE", "SUBTYPE1", "SUBTYPE2", "SUBTYPE3"],
                "rowSet": [
                    [2544, "LeBron", "James", "Miami Heat", "NBA Most Valuable Player", None, "2012-13", None, None, None, "Award", None, None, None],
                    [2544, "LeBron", "James", "Miami Heat", "NBA Most Valuable Player", None, "2011-12", None, None, None, "Award", None, None, None],
                    [2544, "LeBron", "James", "Miami Heat", "NBA Finals Most Valuable Player", None, "2012-13", None, None, None, "Award", None, None, None],
                    [2544, "LeBron", "James", "Miami Heat", "NBA Champion", None, "2012-13", None, None, None, "Award", None, None, None],
                    [2544, "LeBron", "James", "Cleveland Cavaliers", "NBA All-Star", None, "2012-13", None, None, "East", "Award", None, None, None],
                    [2544, "LeBron", "James", "Cleveland Cavaliers", "All-NBA", "1", "2012-13", None, None, None, "Award", None, None, None],
                    [2544, "LeBron", "James", "Cleveland Cavaliers", "All-Defensive Team", "1", "2012-13", None, None, None, "Award", None, None, None],
                ]
            }
        ]
    }


@pytest.fixture
def sample_shot_chart_data():
    """Sample shot chart data from NBA API."""
    return {
        "resultSets": [
            {
                "name": "Shot_Chart_Detail",
                "headers": ["GRID_TYPE", "GAME_ID", "GAME_EVENT_ID", "PLAYER_ID", "PLAYER_NAME", "TEAM_ID", "TEAM_NAME", "PERIOD", "MINUTES_REMAINING", "SECONDS_REMAINING", "EVENT_TYPE", "ACTION_TYPE", "SHOT_TYPE", "SHOT_ZONE_BASIC", "SHOT_ZONE_AREA", "SHOT_ZONE_RANGE", "SHOT_DISTANCE", "LOC_X", "LOC_Y", "SHOT_ATTEMPTED_FLAG", "SHOT_MADE_FLAG", "GAME_DATE", "HTM", "VTM"],
                "rowSet": [
                    ["Shot Chart Detail", "0022400123", 1, 2544, "LeBron James", 1610612747, "Lakers", 1, 10, 30, "Made Shot", "Layup Shot", "2PT Field Goal", "Restricted Area", "Center(C)", "Less Than 8 ft.", 2, 5, 10, 1, 1, "2024-11-03", "LAL", "GSW"],
                    ["Shot Chart Detail", "0022400123", 2, 2544, "LeBron James", 1610612747, "Lakers", 1, 9, 45, "Missed Shot", "Jump Shot", "2PT Field Goal", "Mid-Range", "Center(C)", "8-16 ft.", 12, -15, 120, 1, 0, "2024-11-03", "LAL", "GSW"],
                    ["Shot Chart Detail", "0022400123", 3, 2544, "LeBron James", 1610612747, "Lakers", 1, 8, 20, "Made Shot", "Jump Shot", "3PT Field Goal", "Above the Break 3", "Center(C)", "24+ ft.", 25, 0, 240, 1, 1, "2024-11-03", "LAL", "GSW"],
                    ["Shot Chart Detail", "0022400123", 4, 2544, "LeBron James", 1610612747, "Lakers", 2, 11, 15, "Missed Shot", "Jump Shot", "3PT Field Goal", "Left Corner 3", "Left Side(L)", "24+ ft.", 23, -220, 30, 1, 0, "2024-11-03", "LAL", "GSW"],
                    ["Shot Chart Detail", "0022400123", 5, 2544, "LeBron James", 1610612747, "Lakers", 2, 10, 5, "Made Shot", "Dunk Shot", "2PT Field Goal", "Restricted Area", "Center(C)", "Less Than 8 ft.", 1, 0, 5, 1, 1, "2024-11-03", "LAL", "GSW"],
                ]
            },
            {
                "name": "LeagueAverages",
                "headers": ["GRID_TYPE", "SHOT_ZONE_BASIC", "SHOT_ZONE_AREA", "SHOT_ZONE_RANGE", "FGA", "FGM", "FG_PCT"],
                "rowSet": [
                    ["League Averages", "Restricted Area", "Center(C)", "Less Than 8 ft.", 1000, 650, 0.65],
                ]
            }
        ]
    }


@pytest.fixture
def sample_shooting_splits_data():
    """Sample shooting splits data from NBA API."""
    return {
        "resultSets": [
            {
                "name": "OverallPlayerDashboard",
                "headers": ["GROUP_SET", "GROUP_VALUE", "PLAYER_ID", "PLAYER_NAME", "GP", "W", "L", "W_PCT", "MIN", "FGM", "FGA", "FG_PCT", "FG3M", "FG3A", "FG3_PCT", "FTM", "FTA", "FT_PCT"],
                "rowSet": [
                    ["Overall", "2024-25", 2544, "LeBron James", 10, 7, 3, 0.7, 350, 95, 200, 0.475, 20, 60, 0.333, 45, 50, 0.9]
                ]
            },
            {
                "name": "Shot5FTDistanceRange",
                "headers": ["GROUP_SET", "GROUP_VALUE", "FGM", "FGA", "FG_PCT"],
                "rowSet": [
                    ["5ft Range", "Less Than 5 ft.", 40, 60, 0.667],
                    ["5ft Range", "5-9 ft.", 15, 30, 0.500],
                    ["5ft Range", "10-14 ft.", 10, 25, 0.400],
                    ["5ft Range", "15-19 ft.", 10, 30, 0.333],
                    ["5ft Range", "20-24 ft.", 5, 15, 0.333],
                    ["5ft Range", "25-29 ft.", 15, 40, 0.375],
                ]
            },
            {
                "name": "ShotAreaOverall",
                "headers": ["GROUP_SET", "GROUP_VALUE", "FGM", "FGA", "FG_PCT"],
                "rowSet": [
                    ["Shot Area", "Restricted Area", 35, 50, 0.700],
                    ["Shot Area", "In The Paint (Non-RA)", 20, 40, 0.500],
                    ["Shot Area", "Mid-Range", 20, 50, 0.400],
                    ["Shot Area", "Left Corner 3", 5, 15, 0.333],
                    ["Shot Area", "Right Corner 3", 7, 15, 0.467],
                    ["Shot Area", "Above the Break 3", 8, 30, 0.267],
                ]
            }
        ]
    }
