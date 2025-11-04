"""Tests for helper functions in nba_server."""
import sys
from pathlib import Path
from datetime import datetime

import pytest

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from nba_server import safe_get, format_stat, get_current_season


class TestSafeGet:
    """Test the safe_get helper function."""

    def test_simple_dict_access(self):
        """Test basic dictionary key access."""
        data = {"name": "LeBron James", "id": 2544}
        assert safe_get(data, "name") == "LeBron James"
        assert safe_get(data, "id") == 2544

    def test_nested_dict_access(self):
        """Test nested dictionary access."""
        data = {
            "player": {
                "name": "Kobe Bryant",
                "stats": {"points": 33643, "games": 1346}
            }
        }
        assert safe_get(data, "player", "name") == "Kobe Bryant"
        assert safe_get(data, "player", "stats", "points") == 33643

    def test_list_index_access(self):
        """Test list indexing."""
        data = ["first", "second", "third"]
        assert safe_get(data, 0) == "first"
        assert safe_get(data, 2) == "third"

    def test_nested_dict_and_list(self):
        """Test mixed dictionary and list access."""
        data = {
            "resultSets": [
                {"headers": ["PLAYER_ID", "PLAYER_NAME"], "rowSet": [[2544, "LeBron James"]]},
                {"headers": ["TEAM_ID"], "rowSet": [[1610612747]]}
            ]
        }
        assert safe_get(data, "resultSets", 0, "headers", 0) == "PLAYER_ID"
        assert safe_get(data, "resultSets", 0, "rowSet", 0, 0) == 2544
        assert safe_get(data, "resultSets", 0, "rowSet", 0, 1) == "LeBron James"

    def test_missing_key_returns_default(self):
        """Test that missing keys return the default value."""
        data = {"name": "Test"}
        assert safe_get(data, "missing") == "N/A"
        assert safe_get(data, "missing", default="DEFAULT") == "DEFAULT"

    def test_out_of_bounds_list_returns_default(self):
        """Test that out of bounds list access returns default."""
        data = ["a", "b", "c"]
        assert safe_get(data, 10) == "N/A"
        assert safe_get(data, -1) == "N/A"

    def test_none_values_return_default(self):
        """Test that None values return the default."""
        data = {"key": None}
        assert safe_get(data, "key") == "N/A"

    def test_empty_string_returns_default(self):
        """Test that empty strings return the default."""
        data = {"key": ""}
        assert safe_get(data, "key") == "N/A"

    def test_zero_values_preserved(self):
        """Test that zero values are preserved (not treated as falsy)."""
        data = {"points": 0, "games": 0}
        assert safe_get(data, "points") == 0
        assert safe_get(data, "games") == 0

    def test_deep_nested_missing_path(self):
        """Test deeply nested missing paths."""
        data = {"level1": {"level2": {}}}
        assert safe_get(data, "level1", "level2", "level3", "level4") == "N/A"


class TestFormatStat:
    """Test the format_stat helper function."""

    def test_format_regular_number(self):
        """Test formatting regular numbers."""
        assert format_stat(25.5) == "25.5"
        assert format_stat(10.0) == "10.0"
        assert format_stat(33.7) == "33.7"

    def test_format_percentage(self):
        """Test formatting percentages."""
        assert format_stat(0.456, is_percentage=True) == "45.6%"
        assert format_stat(0.333, is_percentage=True) == "33.3%"
        assert format_stat(0.888, is_percentage=True) == "88.8%"

    def test_format_none_returns_na(self):
        """Test that None returns N/A."""
        assert format_stat(None) == "N/A"
        assert format_stat(None, is_percentage=True) == "N/A"

    def test_format_empty_string_returns_na(self):
        """Test that empty string returns N/A."""
        assert format_stat("") == "N/A"

    def test_format_string_number(self):
        """Test formatting string representations of numbers."""
        assert format_stat("25.5") == "25.5"
        assert format_stat("0.456", is_percentage=True) == "45.6%"

    def test_format_zero(self):
        """Test that zero is formatted correctly."""
        assert format_stat(0) == "0.0"
        assert format_stat(0.0, is_percentage=True) == "0.0%"

    def test_format_invalid_value(self):
        """Test that invalid values return as string."""
        assert format_stat("invalid") == "invalid"
        assert format_stat([1, 2, 3]) == "[1, 2, 3]"


class TestGetCurrentSeason:
    """Test the get_current_season function."""

    def test_season_format(self):
        """Test that season is in correct format."""
        season = get_current_season()
        assert isinstance(season, str)
        assert "-" in season
        parts = season.split("-")
        assert len(parts) == 2
        assert len(parts[0]) == 4  # Year is 4 digits
        assert len(parts[1]) == 2  # Shortened year is 2 digits

    def test_season_year_logic(self):
        """Test that season year logic is correct."""
        season = get_current_season()
        parts = season.split("-")
        first_year = int(parts[0])
        second_year = int(parts[1])

        # Second year should be first year + 1 (last 2 digits)
        assert second_year == int(str(first_year + 1)[2:])

    def test_season_is_current_or_future(self):
        """Test that season is for current year or future."""
        season = get_current_season()
        first_year = int(season.split("-")[0])
        current_year = datetime.now().year

        # First year should be current year or previous year (if before October)
        assert first_year in [current_year - 1, current_year]


class TestNBAServerImport:
    """Test that the nba_server module imports correctly."""

    def test_module_imports(self):
        """Test that main components can be imported."""
        from nba_server import server, NBA_STATS_API, NBA_LIVE_API

        assert server is not None
        assert NBA_STATS_API == "https://stats.nba.com/stats"
        assert NBA_LIVE_API == "https://cdn.nba.com/static/json/liveData"

    def test_server_has_name(self):
        """Test that server is configured."""
        from nba_server import server

        # Server should be initialized with a name
        assert hasattr(server, "name")
