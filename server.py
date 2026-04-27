"""
Sports Analysis MCP Server
Connects Claude to free sports APIs — no cost, no credit card needed.
APIs used:
  - TheSportsDB (free, no key needed for basic use)
  - API-Football (free tier, 100 calls/day — key needed, free signup)
  - OpenLigaDB (100% free, no key)
"""

import httpx
import os
import json
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("Sports Analysis Server")

# --- API-Football key (free signup at dashboard.api-football.com) ---
API_FOOTBALL_KEY = os.getenv("API_FOOTBALL_KEY", "")
AF_BASE = "https://v3.football.api-sports.io"
SDB_BASE = "https://www.thesportsdb.com/api/v1/json/3"  # free tier key = 3
OL_BASE = "https://api.openligadb.de"


# ─────────────────────────────────────────────
#  FOOTBALL / SOCCER
# ─────────────────────────────────────────────

@mcp.tool()
async def search_team(team_name: str) -> str:
    """Search for a football/soccer team by name and get basic info."""
    async with httpx.AsyncClient() as client:
        r = await client.get(f"{SDB_BASE}/searchteams.php", params={"t": team_name})
        data = r.json()
        teams = data.get("teams") or []
        if not teams:
            return f"No team found for '{team_name}'."
        t = teams[0]
        return json.dumps({
            "name": t.get("strTeam"),
            "country": t.get("strCountry"),
            "league": t.get("strLeague"),
            "founded": t.get("intFormedYear"),
            "stadium": t.get("strStadium"),
            "stadium_capacity": t.get("intStadiumCapacity"),
            "description": (t.get("strDescriptionEN") or "")[:500],
            "website": t.get("strWebsite"),
        }, indent=2)


@mcp.tool()
async def get_team_last_matches(team_name: str) -> str:
    """Get a football team's last 5 match results."""
    async with httpx.AsyncClient() as client:
        # First find the team ID
        r = await client.get(f"{SDB_BASE}/searchteams.php", params={"t": team_name})
        teams = (r.json().get("teams") or [])
        if not teams:
            return f"Team '{team_name}' not found."
        team_id = teams[0]["idTeam"]

        r2 = await client.get(f"{SDB_BASE}/eventslast.php", params={"id": team_id})
        events = r2.json().get("results") or []
        if not events:
            return "No recent matches found."

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
        teams = (r.json().get("teams") or [])
        if not teams:
            return f"Team '{team_name}' not found."
        team_id = teams[0]["idTeam"]

        r2 = await client.get(f"{SDB_BASE}/eventsnext.php", params={"id": team_id})
        events = r2.json().get("events") or []
        if not events:
            return "No upcoming matches found."

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
    """Search for a player across all sports and get their profile."""
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
            "weight": p.get("strWeight"),
            "description": (p.get("strDescriptionEN") or "")[:500],
        }, indent=2)


@mcp.tool()
async def get_league_table(league_name: str, season: str = "2024-2025") -> str:
    """
    Get the current standings/table for a league.
    Works best for Bundesliga via OpenLigaDB.
    For other leagues use the league name e.g. 'Premier League'.
    """
    # Try OpenLigaDB for Bundesliga
    league_lower = league_name.lower()
    if "bundesliga" in league_lower:
        league_key = "bl1" if "2" not in league_lower else "bl2"
        async with httpx.AsyncClient() as client:
            r = await client.get(f"{OL_BASE}/getbltable/{league_key}/2024")
            table = r.json()
            rows = []
            for i, t in enumerate(table[:10], 1):
                rows.append({
                    "pos": i,
                    "team": t.get("teamName"),
                    "played": t.get("matches"),
                    "won": t.get("won"),
                    "drawn": t.get("draw"),
                    "lost": t.get("lost"),
                    "gf": t.get("goals"),
                    "ga": t.get("opponentGoals"),
                    "gd": t.get("goalDiff"),
                    "points": t.get("points"),
                })
            return json.dumps(rows, indent=2)

    # Use API-Football for other leagues
    if not API_FOOTBALL_KEY:
        return ("API-Football key not set. For non-Bundesliga standings, "
                "add your free API_FOOTBALL_KEY environment variable. "
                "Sign up free at dashboard.api-football.com")

    league_ids = {
        "premier league": 39,
        "la liga": 140,
        "serie a": 135,
        "ligue 1": 61,
        "champions league": 2,
    }
    lid = None
    for name, lid_val in league_ids.items():
        if name in league_lower:
            lid = lid_val
            break
    if not lid:
        return f"League '{league_name}' not mapped. Try: Premier League, La Liga, Serie A, Ligue 1, Champions League, Bundesliga."

    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{AF_BASE}/standings",
            headers={"x-apisports-key": API_FOOTBALL_KEY},
            params={"league": lid, "season": season.split("-")[0]},
        )
        data = r.json()
        standings = (data.get("response") or [{}])[0]
        league_data = standings.get("league", {})
        table = (league_data.get("standings") or [[]])[0]
        rows = []
        for t in table[:10]:
            rows.append({
                "pos": t.get("rank"),
                "team": t.get("team", {}).get("name"),
                "played": t.get("all", {}).get("played"),
                "won": t.get("all", {}).get("win"),
                "drawn": t.get("all", {}).get("draw"),
                "lost": t.get("all", {}).get("lose"),
                "gd": t.get("goalsDiff"),
                "points": t.get("points"),
            })
        return json.dumps(rows, indent=2)


# ─────────────────────────────────────────────
#  BASKETBALL
# ─────────────────────────────────────────────

@mcp.tool()
async def search_basketball_team(team_name: str) -> str:
    """Search for an NBA or international basketball team."""
    async with httpx.AsyncClient() as client:
        r = await client.get(f"{SDB_BASE}/searchteams.php", params={"t": team_name})
        teams = [t for t in (r.json().get("teams") or []) if t.get("strSport") == "Basketball"]
        if not teams:
            return f"No basketball team found for '{team_name}'."
        t = teams[0]
        return json.dumps({
            "name": t.get("strTeam"),
            "league": t.get("strLeague"),
            "country": t.get("strCountry"),
            "founded": t.get("intFormedYear"),
            "arena": t.get("strStadium"),
            "description": (t.get("strDescriptionEN") or "")[:500],
        }, indent=2)


@mcp.tool()
async def get_basketball_team_results(team_name: str) -> str:
    """Get last 5 results for a basketball team."""
    async with httpx.AsyncClient() as client:
        r = await client.get(f"{SDB_BASE}/searchteams.php", params={"t": team_name})
        teams = [t for t in (r.json().get("teams") or []) if t.get("strSport") == "Basketball"]
        if not teams:
            return f"Basketball team '{team_name}' not found."
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
            })
        return json.dumps(results, indent=2)


# ─────────────────────────────────────────────
#  TENNIS
# ─────────────────────────────────────────────

@mcp.tool()
async def search_tennis_player(player_name: str) -> str:
    """Search for a tennis player and get their profile."""
    async with httpx.AsyncClient() as client:
        r = await client.get(f"{SDB_BASE}/searchplayers.php", params={"p": player_name})
        players = [p for p in (r.json().get("player") or []) if p.get("strSport") == "Tennis"]
        if not players:
            # fallback: return first result
            r2 = await client.get(f"{SDB_BASE}/searchplayers.php", params={"p": player_name})
            players = r2.json().get("player") or []
        if not players:
            return f"Tennis player '{player_name}' not found."
        p = players[0]
        return json.dumps({
            "name": p.get("strPlayer"),
            "nationality": p.get("strNationality"),
            "date_of_birth": p.get("dateBorn"),
            "height": p.get("strHeight"),
            "description": (p.get("strDescriptionEN") or "")[:600],
        }, indent=2)


@mcp.tool()
async def get_tennis_events(league_name: str = "ATP") -> str:
    """Get recent tennis events/tournaments for ATP or WTA."""
    async with httpx.AsyncClient() as client:
        r = await client.get(f"{SDB_BASE}/search_all_leagues.php", params={"s": "Tennis"})
        leagues = r.json().get("countrys") or []
        matched = [l for l in leagues if league_name.upper() in (l.get("strLeague") or "").upper()]
        if not matched:
            return f"No tennis league found matching '{league_name}'."
        lid = matched[0]["idLeague"]
        r2 = await client.get(f"{SDB_BASE}/eventspastleague.php", params={"id": lid})
        events = r2.json().get("events") or []
        results = []
        for e in events[:8]:
            results.append({
                "tournament": e.get("strEvent"),
                "date": e.get("dateEvent"),
                "home_player": e.get("strHomeTeam"),
                "away_player": e.get("strAwayTeam"),
                "score": f"{e.get('intHomeScore')} - {e.get('intAwayScore')}",
            })
        return json.dumps(results, indent=2)


# ─────────────────────────────────────────────
#  CRICKET
# ─────────────────────────────────────────────

@mcp.tool()
async def search_cricket_team(team_name: str) -> str:
    """Search for a cricket team and get their profile."""
    async with httpx.AsyncClient() as client:
        r = await client.get(f"{SDB_BASE}/searchteams.php", params={"t": team_name})
        teams = [t for t in (r.json().get("teams") or []) if t.get("strSport") == "Cricket"]
        if not teams:
            return f"No cricket team found for '{team_name}'."
        t = teams[0]
        return json.dumps({
            "name": t.get("strTeam"),
            "league": t.get("strLeague"),
            "country": t.get("strCountry"),
            "founded": t.get("intFormedYear"),
            "ground": t.get("strStadium"),
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
                "league": e.get("strLeague"),
            })
        return json.dumps(results, indent=2)


# ─────────────────────────────────────────────
#  GENERAL / MULTI-SPORT
# ─────────────────────────────────────────────

@mcp.tool()
async def search_league(sport: str, country: str = "") -> str:
    """
    Find leagues for a given sport (Football, Basketball, Tennis, Cricket, etc.)
    Optionally filter by country.
    """
    async with httpx.AsyncClient() as client:
        params = {"s": sport}
        if country:
            params["c"] = country
        r = await client.get(f"{SDB_BASE}/search_all_leagues.php", params=params)
        leagues = r.json().get("countrys") or []
        results = []
        for l in leagues[:15]:
            results.append({
                "league": l.get("strLeague"),
                "country": l.get("strCountry"),
                "sport": l.get("strSport"),
            })
        return json.dumps(results, indent=2)


@mcp.tool()
async def get_live_scores_football(league_short: str = "bl1") -> str:
    """
    Get today's football match results via OpenLigaDB.
    league_short options: bl1 (Bundesliga 1), bl2 (Bundesliga 2)
    """
    async with httpx.AsyncClient() as client:
        r = await client.get(f"{OL_BASE}/getmatchdata/{league_short}/2024")
        matches = r.json()
        results = []
        for m in matches[:10]:
            score = m.get("matchResults") or []
            final = next((s for s in score if s.get("resultTypeID") == 2), None)
            results.append({
                "match": f"{m['team1']['teamName']} vs {m['team2']['teamName']}",
                "date": m.get("matchDateTime"),
                "score": f"{final['pointsTeam1']} - {final['pointsTeam2']}" if final else "Not played",
                "is_finished": m.get("matchIsFinished"),
            })
        return json.dumps(results, indent=2)


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
