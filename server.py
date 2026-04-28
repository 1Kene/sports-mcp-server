"""
Sports Analysis MCP Server - Minimal, Render-compatible
"""
import httpx
import os
import json
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("Sports Analysis Server")

API_FOOTBALL_KEY = os.getenv("API_FOOTBALL_KEY", "")
AF_BASE = "https://v3.football.api-sports.io"
SDB_BASE = "https://www.thesportsdb.com/api/v1/json/3"
OL_BASE  = "https://api.openligadb.de"


@mcp.tool()
async def search_team(team_name: str) -> str:
    """Search for a football/soccer team by name."""
    async with httpx.AsyncClient() as client:
        r = await client.get(f"{SDB_BASE}/searchteams.php", params={"t": team_name})
        teams = r.json().get("teams") or []
        if not teams:
            return f"No team found for '{team_name}'."
        t = teams[0]
        return json.dumps({
            "name": t.get("strTeam"),
            "country": t.get("strCountry"),
            "league": t.get("strLeague"),
            "founded": t.get("intFormedYear"),
            "stadium": t.get("strStadium"),
            "description": (t.get("strDescriptionEN") or "")[:500],
        }, indent=2)


@mcp.tool()
async def get_team_last_matches(team_name: str) -> str:
    """Get a football team's last 5 match results."""
    async with httpx.AsyncClient() as client:
        r = await client.get(f"{SDB_BASE}/searchteams.php", params={"t": team_name})
        teams = r.json().get("teams") or []
        if not teams:
            return f"Team '{team_name}' not found."
        team_id = teams[0]["idTeam"]
        r2 = await client.get(f"{SDB_BASE}/eventslast.php", params={"id": team_id})
        events = r2.json().get("results") or []
        results = []
        for e in events[:5]:
            results.append({
                "date": e.get("dateEvent"),
                "home": e.get("strHomeTeam"),
                "away": e.get("strAwayTeam"),
                "score": f"{e.get('intHomeScore')} - {e.get('intAwayScore')}",
                "league": e.get("strLeague"),
            })
        return json.dumps(results, indent=2)


@mcp.tool()
async def get_team_next_matches(team_name: str) -> str:
    """Get a football team's next 5 upcoming fixtures."""
    async with httpx.AsyncClient() as client:
        r = await client.get(f"{SDB_BASE}/searchteams.php", params={"t": team_name})
        teams = r.json().get("teams") or []
        if not teams:
            return f"Team '{team_name}' not found."
        team_id = teams[0]["idTeam"]
        r2 = await client.get(f"{SDB_BASE}/eventsnext.php", params={"id": team_id})
        events = r2.json().get("events") or []
        results = []
        for e in events[:5]:
            results.append({
                "date": e.get("dateEvent"),
                "time": e.get("strTime"),
                "home": e.get("strHomeTeam"),
                "away": e.get("strAwayTeam"),
                "league": e.get("strLeague"),
                "venue": e.get("strVenue"),
            })
        return json.dumps(results, indent=2)


@mcp.tool()
async def search_player(player_name: str) -> str:
    """Search for a player across all sports."""
    async with httpx.AsyncClient() as client:
        r = await client.get(f"{SDB_BASE}/searchplayers.php", params={"p": player_name})
        players = r.json().get("player") or []
        if not players:
            return f"No player found for '{player_name}'."
        p = players[0]
        return json.dumps({
            "name": p.get("strPlayer"),
            "sport": p.get("strSport"),
            "team": p.get("strTeam"),
            "nationality": p.get("strNationality"),
            "position": p.get("strPosition"),
            "date_of_birth": p.get("dateBorn"),
            "height": p.get("strHeight"),
            "description": (p.get("strDescriptionEN") or "")[:500],
        }, indent=2)


@mcp.tool()
async def get_league_table(league_name: str) -> str:
    """Get standings for Bundesliga (always free) or other leagues with API key."""
    league_lower = league_name.lower()
    if "bundesliga" in league_lower:
        league_key = "bl2" if "2" in league_lower else "bl1"
        async with httpx.AsyncClient() as client:
            r = await client.get(f"{OL_BASE}/getbltable/{league_key}/2024")
            table = r.json()
            rows = []
            for i, t in enumerate(table[:10], 1):
                rows.append({
                    "pos": i, "team": t.get("teamName"),
                    "played": t.get("matches"), "won": t.get("won"),
                    "drawn": t.get("draw"), "lost": t.get("lost"),
                    "gd": t.get("goalDiff"), "points": t.get("points"),
                })
            return json.dumps(rows, indent=2)
    return "Add API_FOOTBALL_KEY env var on Render for Premier League etc. Bundesliga works free."


@mcp.tool()
async def search_basketball_team(team_name: str) -> str:
    """Search for a basketball team."""
    async with httpx.AsyncClient() as client:
        r = await client.get(f"{SDB_BASE}/searchteams.php", params={"t": team_name})
        teams = [t for t in (r.json().get("teams") or []) if t.get("strSport") == "Basketball"]
        if not teams:
            return f"No basketball team found for '{team_name}'."
        t = teams[0]
        return json.dumps({
            "name": t.get("strTeam"), "league": t.get("strLeague"),
            "country": t.get("strCountry"), "arena": t.get("strStadium"),
            "description": (t.get("strDescriptionEN") or "")[:500],
        }, indent=2)


@mcp.tool()
async def search_tennis_player(player_name: str) -> str:
    """Search for a tennis player profile."""
    async with httpx.AsyncClient() as client:
        r = await client.get(f"{SDB_BASE}/searchplayers.php", params={"p": player_name})
        players = r.json().get("player") or []
        if not players:
            return f"Tennis player '{player_name}' not found."
        p = players[0]
        return json.dumps({
            "name": p.get("strPlayer"), "nationality": p.get("strNationality"),
            "date_of_birth": p.get("dateBorn"), "height": p.get("strHeight"),
            "description": (p.get("strDescriptionEN") or "")[:600],
        }, indent=2)


@mcp.tool()
async def search_cricket_team(team_name: str) -> str:
    """Search for a cricket team."""
    async with httpx.AsyncClient() as client:
        r = await client.get(f"{SDB_BASE}/searchteams.php", params={"t": team_name})
        teams = [t for t in (r.json().get("teams") or []) if t.get("strSport") == "Cricket"]
        if not teams:
            return f"No cricket team found for '{team_name}'."
        t = teams[0]
        return json.dumps({
            "name": t.get("strTeam"), "league": t.get("strLeague"),
            "country": t.get("strCountry"), "ground": t.get("strStadium"),
            "description": (t.get("strDescriptionEN") or "")[:500],
        }, indent=2)


@mcp.tool()
async def get_cricket_team_results(team_name: str) -> str:
    """Get last 5 match results for a cricket team."""
    async with httpx.AsyncClient() as client:
        r = await client.get(f"{SDB_BASE}/searchteams.php", params={"t": team_name})
        teams = [t for t in (r.json().get("teams") or []) if t.get("strSport") == "Cricket"]
        if not teams:
            return f"Cricket team '{team_name}' not found."
        team_id = teams[0]["idTeam"]
        r2 = await client.get(f"{SDB_BASE}/eventslast.php", params={"id": team_id})
        events = r2.json().get("results") or []
        results = []
        for e in events[:5]:
            results.append({
                "date": e.get("dateEvent"),
                "match": f"{e.get('strHomeTeam')} vs {e.get('strAwayTeam')}",
                "score": f"{e.get('intHomeScore')} - {e.get('intAwayScore')}",
            })
        return json.dumps(results, indent=2)


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    mcp.run(transport="streamable-http", host="0.0.0.0", port=port)
