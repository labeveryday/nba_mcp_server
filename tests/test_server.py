"""Tests for NBA MCP server."""

from unittest.mock import patch

import pytest
from mcp.types import TextContent

from nba_mcp_server.server import call_tool, fetch_nba_data, server


class TestServerInitialization:
    """Tests for server initialization."""

    def test_server_instance(self):
        """Test that server instance is created."""
        assert server is not None
        assert server.name == "nba-stats-server"


class TestFetchNBAData:
    """Tests for fetch_nba_data function."""

    @pytest.mark.asyncio
    async def test_fetch_nba_data_success(self, mock_httpx_response):
        """Test successful API fetch."""
        mock_data = {"test": "data"}
        mock_response = mock_httpx_response(200, mock_data)

        with patch('nba_mcp_server.server.http_client') as mock_client:
            mock_client.get.return_value = mock_response
            result = await fetch_nba_data("https://test.com")

            assert result == mock_data
            mock_client.get.assert_called_once()

    @pytest.mark.asyncio
    async def test_fetch_nba_data_http_error(self, mock_httpx_response):
        """Test HTTP error handling."""
        mock_response = mock_httpx_response(500, None)

        with patch('nba_mcp_server.server.http_client') as mock_client:
            mock_client.get.return_value = mock_response
            result = await fetch_nba_data("https://test.com")

            assert result is None

    @pytest.mark.asyncio
    async def test_fetch_nba_data_with_params(self, mock_httpx_response):
        """Test API fetch with parameters."""
        mock_data = {"test": "data"}
        mock_response = mock_httpx_response(200, mock_data)
        params = {"season": "2024-25"}

        with patch('nba_mcp_server.server.http_client') as mock_client:
            mock_client.get.return_value = mock_response
            result = await fetch_nba_data("https://test.com", params)

            assert result == mock_data
            mock_client.get.assert_called_once_with("https://test.com", params=params)


class TestCallTool:
    """Tests for call_tool function."""

    @pytest.mark.asyncio
    async def test_get_all_teams(self):
        """Test get_all_teams tool."""
        result = await call_tool("get_all_teams", {})

        assert len(result) == 1
        assert isinstance(result[0], TextContent)
        assert "NBA Teams:" in result[0].text
        assert "Lakers" in result[0].text
        assert "Warriors" in result[0].text

    @pytest.mark.asyncio
    async def test_get_all_time_leaders(self, sample_all_time_leaders_data):
        """Test get_all_time_leaders tool."""
        with patch('nba_mcp_server.server.fetch_nba_data') as mock_fetch:
            mock_fetch.return_value = sample_all_time_leaders_data

            result = await call_tool("get_all_time_leaders", {
                "stat_category": "points",
                "limit": 3
            })

            assert len(result) == 1
            assert isinstance(result[0], TextContent)
            assert "LeBron James" in result[0].text
            assert "42,184" in result[0].text
            assert "Kareem Abdul-Jabbar" in result[0].text

    @pytest.mark.asyncio
    async def test_unknown_tool(self):
        """Test calling unknown tool."""
        result = await call_tool("unknown_tool", {})

        assert len(result) == 1
        assert "Unknown tool" in result[0].text

    @pytest.mark.asyncio
    async def test_tool_error_handling(self):
        """Test tool error handling."""
        with patch('nba_mcp_server.server.fetch_nba_data') as mock_fetch:
            mock_fetch.side_effect = Exception("Test error")

            result = await call_tool("get_all_time_leaders", {
                "stat_category": "points"
            })

            assert len(result) == 1
            assert "Error" in result[0].text


class TestAwardsTools:
    """Tests for awards tools."""

    @pytest.mark.asyncio
    async def test_get_player_awards(self, sample_player_awards_data):
        """Test get_player_awards tool."""
        with patch('nba_mcp_server.server.fetch_nba_data') as mock_fetch:
            mock_fetch.return_value = sample_player_awards_data

            result = await call_tool("get_player_awards", {
                "player_id": "2544"
            })

            assert len(result) == 1
            assert isinstance(result[0], TextContent)
            assert "LeBron James" in result[0].text
            assert "NBA MVP" in result[0].text
            assert "2012-13" in result[0].text
            assert "Finals MVP" in result[0].text

    @pytest.mark.asyncio
    async def test_get_player_awards_no_data(self):
        """Test get_player_awards with no awards."""
        with patch('nba_mcp_server.server.fetch_nba_data') as mock_fetch:
            mock_fetch.return_value = {
                "resultSets": [
                    {
                        "headers": ["PERSON_ID", "FIRST_NAME", "LAST_NAME"],
                        "rowSet": []
                    }
                ]
            }

            result = await call_tool("get_player_awards", {
                "player_id": "9999"
            })

            assert len(result) == 1
            assert "No awards found" in result[0].text

    @pytest.mark.asyncio
    async def test_get_season_awards(self):
        """Test get_season_awards tool."""
        result = await call_tool("get_season_awards", {
            "season": "2002-03"
        })

        assert len(result) == 1
        assert isinstance(result[0], TextContent)
        assert "2002-03" in result[0].text
        assert "Tim Duncan" in result[0].text

    @pytest.mark.asyncio
    async def test_get_season_awards_unavailable(self):
        """Test get_season_awards with unavailable season."""
        result = await call_tool("get_season_awards", {
            "season": "1950-51"
        })

        assert len(result) == 1
        assert "not available" in result[0].text


class TestToolsListRegistration:
    """Test that all tools are registered."""

    @pytest.mark.asyncio
    async def test_list_tools_count(self):
        """Test that all tools are registered."""
        from nba_mcp_server.server import list_tools

        tools = await list_tools()
        assert len(tools) == 30

    @pytest.mark.asyncio
    async def test_list_tools_names(self):
        """Test that all expected tools are present."""
        from nba_mcp_server.server import list_tools

        tools = await list_tools()
        tool_names = [tool.name for tool in tools]

        expected_tools = [
            "get_server_info",
            "resolve_team_id",
            "resolve_player_id",
            "find_game_id",
            "get_todays_scoreboard",
            "get_scoreboard_by_date",
            "get_game_details",
            "get_box_score",
            "search_players",
            "get_player_info",
            "get_player_season_stats",
            "get_player_game_log",
            "get_player_career_stats",
            "get_player_hustle_stats",
            "get_league_hustle_leaders",
            "get_player_defense_stats",
            "get_all_time_leaders",
            "get_all_teams",
            "get_team_roster",
            "get_standings",
            "get_league_leaders",
            "get_schedule",
            "get_player_awards",
            "get_season_awards",
            "get_shot_chart",
            "get_shooting_splits",
            "get_play_by_play",
            "get_game_rotation",
            "get_player_advanced_stats",
            "get_team_advanced_stats",
        ]

        for expected in expected_tools:
            assert expected in tool_names


class TestServerInfoTool:
    """Tests for server info tool."""

    @pytest.mark.asyncio
    async def test_get_server_info(self):
        """Test get_server_info tool output."""
        result = await call_tool("get_server_info", {})

        assert len(result) == 1
        assert isinstance(result[0], TextContent)
        assert "NBA MCP Server Info" in result[0].text
        assert "Version:" in result[0].text
        assert "Max concurrency:" in result[0].text


class TestShotChartTools:
    """Test shot chart and shooting tools."""

    @pytest.mark.asyncio
    async def test_get_shot_chart(self, mock_httpx_response, sample_shot_chart_data):
        """Test get_shot_chart tool."""
        from nba_mcp_server.server import call_tool

        mock_response = mock_httpx_response(200, sample_shot_chart_data)

        with patch('nba_mcp_server.server.http_client') as mock_client:
            mock_client.get.return_value = mock_response
            result = await call_tool("get_shot_chart", {
                "player_id": "2544",
                "season": "2024-25"
            })

            assert len(result) == 1
            assert isinstance(result[0], TextContent)
            assert "Shot Chart" in result[0].text
            assert "Total Shots" in result[0].text
            assert "Shooting by Distance" in result[0].text
            assert "Top Shot Types" in result[0].text
            assert "Layup Shot" in result[0].text  # Verify shot types are parsed
            assert "5" in result[0].text  # Verify shot count

    @pytest.mark.asyncio
    async def test_get_shot_chart_no_data(self, mock_httpx_response):
        """Test get_shot_chart with no shot data."""
        from nba_mcp_server.server import call_tool

        empty_data = {
            "resultSets": [
                {
                    "name": "Shot_Chart_Detail",
                    "headers": ["PLAYER_NAME", "LOC_X", "LOC_Y", "SHOT_MADE_FLAG"],
                    "rowSet": []
                }
            ]
        }
        mock_response = mock_httpx_response(200, empty_data)

        with patch('nba_mcp_server.server.http_client') as mock_client:
            mock_client.get.return_value = mock_response
            result = await call_tool("get_shot_chart", {
                "player_id": "2544",
                "season": "2024-25"
            })

            assert len(result) == 1
            assert "No shot data found" in result[0].text

    @pytest.mark.asyncio
    async def test_get_shooting_splits(self, mock_httpx_response, sample_shooting_splits_data):
        """Test get_shooting_splits tool."""
        from nba_mcp_server.server import call_tool

        mock_response = mock_httpx_response(200, sample_shooting_splits_data)

        with patch('nba_mcp_server.server.http_client') as mock_client:
            mock_client.get.return_value = mock_response
            result = await call_tool("get_shooting_splits", {
                "player_id": "2544",
                "season": "2024-25"
            })

            assert len(result) == 1
            assert isinstance(result[0], TextContent)
            assert "Shooting Splits" in result[0].text
            assert "Shooting by Distance" in result[0].text
            assert "Shooting by Area" in result[0].text
            assert "Overall Shooting" in result[0].text
            assert "Restricted Area" in result[0].text  # Verify areas are parsed
            assert "Mid-Range" in result[0].text  # Verify zones are included

    @pytest.mark.asyncio
    async def test_get_shooting_splits_no_data(self, mock_httpx_response):
        """Test get_shooting_splits with no data."""
        from nba_mcp_server.server import call_tool

        empty_data = {
            "resultSets": []
        }
        mock_response = mock_httpx_response(200, empty_data)

        with patch('nba_mcp_server.server.http_client') as mock_client:
            mock_client.get.return_value = mock_response
            result = await call_tool("get_shooting_splits", {
                "player_id": "2544",
                "season": "2024-25"
            })

            assert len(result) == 1
            assert "No shooting data found" in result[0].text


class TestPlayByPlayAndRotationTools:
    """Test play-by-play and rotation tools."""

    @pytest.mark.asyncio
    async def test_get_play_by_play(self, mock_httpx_response, sample_play_by_play_data):
        """Test get_play_by_play tool."""
        from nba_mcp_server.server import call_tool

        mock_response = mock_httpx_response(200, sample_play_by_play_data)

        with patch('nba_mcp_server.server.http_client') as mock_client:
            mock_client.get.return_value = mock_response
            result = await call_tool("get_play_by_play", {
                "game_id": "0022400123"
            })

            assert len(result) == 1
            assert isinstance(result[0], TextContent)
            assert "Play-by-Play" in result[0].text
            assert "Game 0022400123" in result[0].text
            assert "Q1" in result[0].text  # Verify quarter header
            assert "Curry" in result[0].text  # Verify player names
            assert "James" in result[0].text
            assert "3 - 0" in result[0].text  # Verify score

    @pytest.mark.asyncio
    async def test_get_play_by_play_no_data(self, mock_httpx_response):
        """Test get_play_by_play with no play data."""
        from nba_mcp_server.server import call_tool

        empty_data = {
            "resultSets": [
                {
                    "name": "PlayByPlay",
                    "headers": ["GAME_ID", "PERIOD", "PCTIMESTRING", "HOMEDESCRIPTION"],
                    "rowSet": []
                }
            ]
        }
        mock_response = mock_httpx_response(200, empty_data)

        with patch('nba_mcp_server.server.http_client') as mock_client:
            mock_client.get.return_value = mock_response
            result = await call_tool("get_play_by_play", {
                "game_id": "0022400123"
            })

            assert len(result) == 1
            assert "No plays found" in result[0].text

    @pytest.mark.asyncio
    async def test_get_game_rotation(self, mock_httpx_response, sample_game_rotation_data):
        """Test get_game_rotation tool."""
        from nba_mcp_server.server import call_tool

        mock_response = mock_httpx_response(200, sample_game_rotation_data)

        with patch('nba_mcp_server.server.http_client') as mock_client:
            mock_client.get.return_value = mock_response
            result = await call_tool("get_game_rotation", {
                "game_id": "0022400123"
            })

            assert len(result) == 1
            assert isinstance(result[0], TextContent)
            assert "Game Rotation" in result[0].text
            assert "Game 0022400123" in result[0].text
            assert "Warriors" in result[0].text  # Verify team names
            assert "Lakers" in result[0].text
            assert "Stephen Curry" in result[0].text  # Verify player names
            assert "LeBron James" in result[0].text
            assert "In:" in result[0].text  # Verify time format
            assert "Out:" in result[0].text
            assert "+/-:" in result[0].text  # Verify stats

    @pytest.mark.asyncio
    async def test_get_game_rotation_no_data(self, mock_httpx_response):
        """Test get_game_rotation with no rotation data."""
        from nba_mcp_server.server import call_tool

        empty_data = {
            "resultSets": []
        }
        mock_response = mock_httpx_response(200, empty_data)

        with patch('nba_mcp_server.server.http_client') as mock_client:
            mock_client.get.return_value = mock_response
            result = await call_tool("get_game_rotation", {
                "game_id": "0022400123"
            })

            assert len(result) == 1
            assert "No rotation data found" in result[0].text


class TestAdvancedStatsTools:
    """Test advanced stats tools."""

    @pytest.mark.asyncio
    async def test_get_player_advanced_stats(self, mock_httpx_response, sample_player_advanced_stats_data):
        """Test get_player_advanced_stats tool."""
        from nba_mcp_server.server import call_tool

        mock_response = mock_httpx_response(200, sample_player_advanced_stats_data)

        with patch('nba_mcp_server.server.http_client') as mock_client:
            mock_client.get.return_value = mock_response
            result = await call_tool("get_player_advanced_stats", {
                "player_id": "2544",
                "season": "2024-25"
            })

            assert len(result) == 1
            assert isinstance(result[0], TextContent)
            assert "Advanced Stats" in result[0].text
            assert "LeBron James" in result[0].text
            assert "Efficiency Metrics" in result[0].text
            assert "True Shooting %" in result[0].text
            assert "Offensive Rating" in result[0].text
            assert "Defensive Rating" in result[0].text
            assert "Net Rating" in result[0].text
            assert "Usage %" in result[0].text

    @pytest.mark.asyncio
    async def test_get_player_advanced_stats_no_data(self, mock_httpx_response):
        """Test get_player_advanced_stats with no data."""
        from nba_mcp_server.server import call_tool

        empty_data = {
            "resultSets": []
        }
        mock_response = mock_httpx_response(200, empty_data)

        with patch('nba_mcp_server.server.http_client') as mock_client:
            mock_client.get.return_value = mock_response
            result = await call_tool("get_player_advanced_stats", {
                "player_id": "2544",
                "season": "2024-25"
            })

            assert len(result) == 1
            assert "No advanced stats found" in result[0].text

    @pytest.mark.asyncio
    async def test_get_team_advanced_stats(self, mock_httpx_response, sample_team_advanced_stats_data):
        """Test get_team_advanced_stats tool."""
        from nba_mcp_server.server import call_tool

        mock_response = mock_httpx_response(200, sample_team_advanced_stats_data)

        with patch('nba_mcp_server.server.http_client') as mock_client:
            mock_client.get.return_value = mock_response
            result = await call_tool("get_team_advanced_stats", {
                "team_id": "1610612747",
                "season": "2024-25"
            })

            assert len(result) == 1
            assert isinstance(result[0], TextContent)
            assert "Advanced Stats" in result[0].text
            assert "Lakers" in result[0].text
            assert "Team Ratings" in result[0].text
            assert "Offensive Rating" in result[0].text
            assert "Defensive Rating" in result[0].text
            assert "Net Rating" in result[0].text
            assert "Pace" in result[0].text
            assert "True Shooting %" in result[0].text

    @pytest.mark.asyncio
    async def test_get_team_advanced_stats_no_data(self, mock_httpx_response):
        """Test get_team_advanced_stats with no data."""
        from nba_mcp_server.server import call_tool

        empty_data = {
            "resultSets": []
        }
        mock_response = mock_httpx_response(200, empty_data)

        with patch('nba_mcp_server.server.http_client') as mock_client:
            mock_client.get.return_value = mock_response
            result = await call_tool("get_team_advanced_stats", {
                "team_id": "1610612747",
                "season": "2024-25"
            })

            assert len(result) == 1
            assert "No advanced stats found" in result[0].text
