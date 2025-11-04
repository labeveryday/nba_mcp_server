#!/usr/bin/env python3
"""Comprehensive verification of all NBA MCP Server endpoints."""

import asyncio
import sys
from datetime import datetime

sys.path.insert(0, 'src')

from nba_mcp_server.server import call_tool

# Test data
LEBRON_ID = "2544"
LAKERS_TEAM_ID = "1610612747"
TEST_DATE = "20241103"
MICHAEL_JORDAN_ID = "893"

async def test_tool(name, args, description):
    """Test a single tool and return results."""
    print(f"\n{'='*70}")
    print(f"Testing: {name}")
    print(f"Description: {description}")
    print(f"Args: {args}")
    print(f"{'='*70}")

    try:
        result = await call_tool(name, args)
        if result and len(result) > 0:
            text = result[0].text

            # Check for error indicators
            if "Error" in text or "error" in text.lower() or "failed" in text.lower():
                print(f"⚠️  PARTIAL SUCCESS (returned data but with errors)")
                print(f"Response preview: {text[:200]}...")
                return "warning"
            else:
                print(f"✅ SUCCESS")
                print(f"Response preview: {text[:200]}...")
                return "success"
        else:
            print(f"❌ FAILED - No response")
            return "failed"
    except Exception as e:
        print(f"❌ FAILED - Exception: {type(e).__name__}: {str(e)[:100]}")
        return "failed"

async def verify_all_endpoints():
    """Test all 17 endpoints."""

    print("="*70)
    print("NBA MCP SERVER - COMPREHENSIVE ENDPOINT VERIFICATION")
    print("="*70)
    print(f"Test Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*70)

    results = {}

    # Live Game Tools (4 tools)
    results["get_todays_scoreboard"] = await test_tool(
        "get_todays_scoreboard",
        {},
        "Get today's games with live scores"
    )

    results["get_scoreboard_by_date"] = await test_tool(
        "get_scoreboard_by_date",
        {"date": TEST_DATE},
        "Get games for specific date"
    )

    # Note: These need valid game IDs, so they might fail if no games today
    results["get_game_details"] = await test_tool(
        "get_game_details",
        {"game_id": "0022400001"},
        "Get detailed game info (may fail if game doesn't exist)"
    )

    results["get_box_score"] = await test_tool(
        "get_box_score",
        {"game_id": "0022400001"},
        "Get box score (may fail if game doesn't exist)"
    )

    # Player Tools (6 tools)
    results["search_players"] = await test_tool(
        "search_players",
        {"query": "LeBron"},
        "Search for players"
    )

    results["get_player_info"] = await test_tool(
        "get_player_info",
        {"player_id": LEBRON_ID},
        "Get player information"
    )

    results["get_player_season_stats"] = await test_tool(
        "get_player_season_stats",
        {"player_id": MICHAEL_JORDAN_ID, "season": "2002-03"},
        "Get player season stats (just fixed)"
    )

    results["get_player_career_stats"] = await test_tool(
        "get_player_career_stats",
        {"player_id": LEBRON_ID},
        "Get player career stats"
    )

    results["get_player_hustle_stats"] = await test_tool(
        "get_player_hustle_stats",
        {"player_id": LEBRON_ID, "season": "2024-25"},
        "Get player hustle stats"
    )

    results["get_player_defense_stats"] = await test_tool(
        "get_player_defense_stats",
        {"player_id": LEBRON_ID, "season": "2024-25"},
        "Get player defense stats"
    )

    # Team Tools (2 tools)
    results["get_all_teams"] = await test_tool(
        "get_all_teams",
        {},
        "Get all NBA teams"
    )

    results["get_team_roster"] = await test_tool(
        "get_team_roster",
        {"team_id": LAKERS_TEAM_ID, "season": "2024-25"},
        "Get team roster"
    )

    # League Tools (5 tools)
    results["get_standings"] = await test_tool(
        "get_standings",
        {"season": "2024-25"},
        "Get NBA standings"
    )

    results["get_league_leaders"] = await test_tool(
        "get_league_leaders",
        {"stat_type": "Points", "season": "2024-25"},
        "Get league leaders (fixed earlier)"
    )

    results["get_all_time_leaders"] = await test_tool(
        "get_all_time_leaders",
        {"stat_category": "points", "limit": 5},
        "Get all-time leaders"
    )

    results["get_league_hustle_leaders"] = await test_tool(
        "get_league_hustle_leaders",
        {"stat_category": "deflections", "season": "2024-25"},
        "Get league hustle leaders"
    )

    results["get_schedule"] = await test_tool(
        "get_schedule",
        {"team_id": LAKERS_TEAM_ID, "days_ahead": 7},
        "Get team schedule"
    )

    # Summary
    print(f"\n\n{'='*70}")
    print("VERIFICATION SUMMARY")
    print(f"{'='*70}")

    success_count = sum(1 for v in results.values() if v == "success")
    warning_count = sum(1 for v in results.values() if v == "warning")
    failed_count = sum(1 for v in results.values() if v == "failed")
    total_count = len(results)

    print(f"\nTotal Tools: {total_count}")
    print(f"✅ Success: {success_count}")
    print(f"⚠️  Warnings: {warning_count}")
    print(f"❌ Failed: {failed_count}")

    print(f"\n{'Tool Name':<35} {'Status':<10}")
    print("-" * 70)
    for tool, status in sorted(results.items()):
        icon = "✅" if status == "success" else "⚠️" if status == "warning" else "❌"
        print(f"{tool:<35} {icon} {status}")

    print(f"\n{'='*70}")

    if failed_count > 0:
        print("\n⚠️  Some endpoints failed. Review the detailed output above.")
        print("Failed tools may need endpoint fixes or alternative implementations.")
    elif warning_count > 0:
        print("\n⚠️  Some endpoints returned errors but provided data.")
        print("These may need additional investigation.")
    else:
        print("\n✅ All endpoints verified successfully!")

    return results

if __name__ == "__main__":
    asyncio.run(verify_all_endpoints())
