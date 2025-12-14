"""Tests for helper functions."""

from datetime import datetime

from nba_mcp_server.server import format_stat, get_current_season, safe_get


class TestSafeGet:
    """Tests for safe_get helper function."""

    def test_safe_get_dict_simple(self):
        """Test safe_get with simple dictionary."""
        data = {"key": "value"}
        assert safe_get(data, "key") == "value"

    def test_safe_get_dict_nested(self):
        """Test safe_get with nested dictionary."""
        data = {"level1": {"level2": {"level3": "value"}}}
        assert safe_get(data, "level1", "level2", "level3") == "value"

    def test_safe_get_list_index(self):
        """Test safe_get with list indexing."""
        data = ["a", "b", "c"]
        assert safe_get(data, 0) == "a"
        assert safe_get(data, 2) == "c"

    def test_safe_get_mixed(self):
        """Test safe_get with mixed dict and list."""
        data = {
            "items": [
                {"name": "first"},
                {"name": "second"}
            ]
        }
        assert safe_get(data, "items", 0, "name") == "first"
        assert safe_get(data, "items", 1, "name") == "second"

    def test_safe_get_missing_key(self):
        """Test safe_get with missing key returns default."""
        data = {"key": "value"}
        assert safe_get(data, "missing") == "N/A"
        assert safe_get(data, "missing", default="custom") == "custom"

    def test_safe_get_index_out_of_range(self):
        """Test safe_get with out of range index."""
        data = ["a", "b"]
        assert safe_get(data, 5) == "N/A"
        assert safe_get(data, -1, default="custom") == "custom"

    def test_safe_get_none_value(self):
        """Test safe_get with None value."""
        data = {"key": None}
        assert safe_get(data, "key") == "N/A"

    def test_safe_get_empty_string(self):
        """Test safe_get with empty string."""
        data = {"key": ""}
        assert safe_get(data, "key") == "N/A"


class TestFormatStat:
    """Tests for format_stat helper function."""

    def test_format_stat_number(self):
        """Test format_stat with regular number."""
        assert format_stat(25.6) == "25.6"
        assert format_stat(10) == "10.0"

    def test_format_stat_percentage(self):
        """Test format_stat with percentage."""
        assert format_stat(0.456, is_percentage=True) == "45.6%"
        assert format_stat(0.5, is_percentage=True) == "50.0%"

    def test_format_stat_none(self):
        """Test format_stat with None."""
        assert format_stat(None) == "N/A"

    def test_format_stat_empty_string(self):
        """Test format_stat with empty string."""
        assert format_stat("") == "N/A"

    def test_format_stat_invalid(self):
        """Test format_stat with invalid value."""
        assert format_stat("invalid") == "invalid"


class TestGetCurrentSeason:
    """Tests for get_current_season function."""

    def test_get_current_season_format(self):
        """Test that current season returns correct format."""
        season = get_current_season()
        # Should be in format YYYY-YY
        assert len(season) == 7
        assert season[4] == "-"

        # Parse the years
        year1 = int(season[:4])
        year2 = int(season[5:7])

        # Second year should be year1 + 1 (last 2 digits)
        expected_year2 = (year1 + 1) % 100
        assert year2 == expected_year2

    def test_get_current_season_month_logic(self):
        """Test season changes based on month."""
        now = datetime.now()
        season = get_current_season()
        year = now.year

        if now.month >= 10:
            # October or later: should be current year to next year
            expected = f"{year}-{str(year + 1)[2:]}"
        else:
            # Before October: should be previous year to current year
            expected = f"{year - 1}-{str(year)[2:]}"

        assert season == expected
