"""Tests for NBA MCP server."""

import pytest
from unittest.mock import Mock, patch, AsyncMock
from nba_mcp_server.server import server, fetch_nba_data, call_tool
from mcp.types import TextContent


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
        """Test that all 20 tools are registered."""
        from nba_mcp_server.server import list_tools

        tools = await list_tools()
        assert len(tools) == 20

    @pytest.mark.asyncio
    async def test_list_tools_names(self):
        """Test that all expected tools are present."""
        from nba_mcp_server.server import list_tools

        tools = await list_tools()
        tool_names = [tool.name for tool in tools]

        expected_tools = [
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
        ]

        for expected in expected_tools:
            assert expected in tool_names
