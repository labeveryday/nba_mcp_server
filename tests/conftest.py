"""Pytest configuration and fixtures."""

from unittest.mock import Mock

import pytest


@pytest.fixture(autouse=True)
async def _clear_server_cache_between_tests():
    """Ensure cache does not leak across tests (keeps tests deterministic)."""
    from nba_mcp_server.server import clear_cache
    await clear_cache()
    yield


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


@pytest.fixture
def sample_play_by_play_data():
    """Sample play-by-play data from NBA API."""
    return {
        "resultSets": [
            {
                "name": "PlayByPlay",
                "headers": ["GAME_ID", "EVENTNUM", "EVENTMSGTYPE", "EVENTMSGACTIONTYPE", "PERIOD", "WCTIMESTRING", "PCTIMESTRING", "HOMEDESCRIPTION", "NEUTRALDESCRIPTION", "VISITORDESCRIPTION", "SCORE", "SCOREMARGIN", "PERSON1TYPE", "PLAYER1_ID", "PLAYER1_NAME", "PLAYER1_TEAM_ID", "PLAYER1_TEAM_CITY", "PLAYER1_TEAM_NICKNAME", "PLAYER1_TEAM_ABBREVIATION", "PERSON2TYPE", "PLAYER2_ID", "PLAYER2_NAME", "PLAYER2_TEAM_ID", "PLAYER2_TEAM_CITY", "PLAYER2_TEAM_NICKNAME", "PLAYER2_TEAM_ABBREVIATION", "PERSON3TYPE", "PLAYER3_ID", "PLAYER3_NAME", "PLAYER3_TEAM_ID", "PLAYER3_TEAM_CITY", "PLAYER3_TEAM_NICKNAME", "PLAYER3_TEAM_ABBREVIATION", "VIDEO_AVAILABLE_FLAG"],
                "rowSet": [
                    ["0022400123", 1, 12, 0, 1, "7:00 PM", "12:00", None, "Period Start", None, None, None, 0, None, None, None, None, None, None, 0, None, None, None, None, None, None, 0, None, None, None, None, None, None, 1],
                    ["0022400123", 2, 10, 0, 1, "7:00 PM", "11:47", None, "Jump Ball won by Lakers", None, None, None, 0, None, None, None, None, None, None, 0, None, None, None, None, None, None, 0, None, None, None, None, None, None, 1],
                    ["0022400123", 3, 1, 1, 1, "7:01 PM", "11:30", None, None, "Curry 25' 3PT Jump Shot (3 PTS)", "3 - 0", "3", 4, 201939, "Stephen Curry", 1610612744, "Golden State", "Warriors", "GSW", 0, None, None, None, None, None, None, 0, None, None, None, None, None, None, 1],
                    ["0022400123", 4, 2, 1, 1, "7:01 PM", "11:15", "James Missed Layup", None, None, "3 - 0", "3", 4, 2544, "LeBron James", 1610612747, "Los Angeles", "Lakers", "LAL", 0, None, None, None, None, None, None, 0, None, None, None, None, None, None, 1],
                    ["0022400123", 5, 1, 1, 1, "7:02 PM", "10:58", "Davis Layup (2 PTS) (Assist: James)", None, None, "3 - 2", "1", 5, 203076, "Anthony Davis", 1610612747, "Los Angeles", "Lakers", "LAL", 0, 2544, "LeBron James", 1610612747, "Los Angeles", "Lakers", "LAL", 0, None, None, None, None, None, None, 1],
                    ["0022400123", 6, 3, 0, 1, "7:02 PM", "10:45", None, None, "Thompson Defensive Rebound", None, None, 4, 202691, "Klay Thompson", 1610612744, "Golden State", "Warriors", "GSW", 0, None, None, None, None, None, None, 0, None, None, None, None, None, None, 1],
                    ["0022400123", 7, 5, 0, 1, "7:03 PM", "10:30", None, "Turnover by Curry (Bad Pass)", None, "3 - 2", "1", 1, 201939, "Stephen Curry", 1610612744, "Golden State", "Warriors", "GSW", 0, None, None, None, None, None, None, 0, None, None, None, None, None, None, 1],
                ]
            },
            {
                "name": "AvailableVideo",
                "headers": ["VIDEO_AVAILABLE_FLAG"],
                "rowSet": [[1]]
            }
        ]
    }


@pytest.fixture
def sample_game_rotation_data():
    """Sample game rotation data from NBA API."""
    return {
        "resultSets": [
            {
                "name": "AwayTeam",
                "headers": ["GAME_ID", "TEAM_ID", "TEAM_CITY", "TEAM_NAME", "PERSON_ID", "PLAYER_FIRST", "PLAYER_LAST", "IN_TIME_REAL", "OUT_TIME_REAL", "PLAYER_PTS", "PT_DIFF", "USG_PCT"],
                "rowSet": [
                    ["0022400123", 1610612744, "Golden State", "Warriors", 201939, "Stephen", "Curry", "12:00", "8:30", 8, 3, 0.28],
                    ["0022400123", 1610612744, "Golden State", "Warriors", 201939, "Stephen", "Curry", "6:15", "0:00", 5, -2, 0.25],
                    ["0022400123", 1610612744, "Golden State", "Warriors", 202691, "Klay", "Thompson", "12:00", "7:45", 6, 2, 0.22],
                    ["0022400123", 1610612744, "Golden State", "Warriors", 202691, "Klay", "Thompson", "5:30", "0:00", 4, 0, 0.20],
                    ["0022400123", 1610612744, "Golden State", "Warriors", 203110, "Draymond", "Green", "12:00", "9:00", 2, 1, 0.15],
                ]
            },
            {
                "name": "HomeTeam",
                "headers": ["GAME_ID", "TEAM_ID", "TEAM_CITY", "TEAM_NAME", "PERSON_ID", "PLAYER_FIRST", "PLAYER_LAST", "IN_TIME_REAL", "OUT_TIME_REAL", "PLAYER_PTS", "PT_DIFF", "USG_PCT"],
                "rowSet": [
                    ["0022400123", 1610612747, "Los Angeles", "Lakers", 2544, "LeBron", "James", "12:00", "7:30", 10, 5, 0.32],
                    ["0022400123", 1610612747, "Los Angeles", "Lakers", 2544, "LeBron", "James", "4:00", "0:00", 7, 3, 0.30],
                    ["0022400123", 1610612747, "Los Angeles", "Lakers", 203076, "Anthony", "Davis", "12:00", "8:00", 8, 4, 0.28],
                    ["0022400123", 1610612747, "Los Angeles", "Lakers", 203076, "Anthony", "Davis", "5:00", "0:00", 6, 2, 0.26],
                    ["0022400123", 1610612747, "Los Angeles", "Lakers", 1628398, "Austin", "Reaves", "12:00", "10:00", 4, 1, 0.18],
                ]
            }
        ]
    }


@pytest.fixture
def sample_player_advanced_stats_data():
    """Sample player advanced stats data from NBA API."""
    return {
        "resultSets": [
            {
                "name": "OverallPlayerDashboard",
                "headers": ["GROUP_SET", "GROUP_VALUE", "PLAYER_ID", "PLAYER_NAME", "GP", "W", "L", "W_PCT", "MIN", "OFF_RATING", "DEF_RATING", "NET_RATING", "AST_PCT", "AST_TO", "AST_RATIO", "OREB_PCT", "DREB_PCT", "REB_PCT", "TM_TOV_PCT", "EFG_PCT", "TS_PCT", "USG_PCT", "PACE", "PIE"],
                "rowSet": [
                    ["Overall", "2024-25", 2544, "LeBron James", 10, 7, 3, 0.7, 35.5, 115.2, 108.5, 6.7, 35.8, 2.15, 18.5, 3.2, 22.5, 12.8, 14.2, 0.580, 0.625, 28.5, 100.5, 0.185]
                ]
            }
        ]
    }


@pytest.fixture
def sample_team_advanced_stats_data():
    """Sample team advanced stats data from NBA API."""
    return {
        "resultSets": [
            {
                "name": "OverallTeamDashboard",
                "headers": ["GROUP_SET", "GROUP_VALUE", "TEAM_ID", "TEAM_NAME", "GP", "W", "L", "W_PCT", "MIN", "OFF_RATING", "DEF_RATING", "NET_RATING", "AST_PCT", "AST_TO", "AST_RATIO", "OREB_PCT", "DREB_PCT", "REB_PCT", "TM_TOV_PCT", "EFG_PCT", "TS_PCT", "PACE", "PIE"],
                "rowSet": [
                    ["Overall", "2024-25", 1610612747, "Lakers", 10, 7, 3, 0.7, 240.0, 112.5, 110.2, 2.3, 62.5, 1.85, 16.2, 8.5, 75.8, 51.2, 12.8, 0.545, 0.575, 98.5, 0.525]
                ]
            }
        ]
    }
