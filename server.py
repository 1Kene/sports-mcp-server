"""
Sports Analysis MCP Server v2 - Multi-API with fallbacks
Primary: API-Football (free key)
Fallback: TheSportsDB
Bonus: balldontlie (NBA, free no key), OpenLigaDB (Bundesliga, free no key)
"""
import httpx
import os
import json
import uvicorn
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

mcp = FastMCP(
    "Sports Analysis Server",
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=False,
    ),
)

# ── API endpoints ─────────────────────────────────────────────────────────────
API_FOOTBALL_KEY = os.getenv("API_FOOTBALL_KEY", "")
AF_BASE  = "https://v3.football.api-sports.io"
SDB_BASE = "https://www.thesportsdb.com/api/v1/json/3"
OL_BASE  = "https://api.openligadb.de"
BDL_BASE = "https://api.balldontlie.io/v1"  # NBA, free no key

AF_HEADERS = {"x-apisports-key": API_FOOTBALL_KEY} if API_FOOTBALL_KEY else {}

# ── Helpers ───────────────────────────────────────────────────────────────────
async def safe_get(client, url, **kwargs):
    """GET with error handling. Returns dict or None."""
    try:
        r = await client.get(url, timeout=15.0, **kwargs)
        if r.status_code != 200:
            return None
        text = r.text.strip()
        if not text:
            return None
        return r.json()
    except Exception:
        return None


# ═════════════════════════════════════════════════════════════════════════════
#  FOOTBALL / SOCCER
# ═════════════════════════════════════════════════════════════════════════════

@mcp.tool()
async def search_team(team_name: str) -> str:
    """Search for a football/soccer team by name. Uses API-Football first, falls back to TheSportsDB."""
    async with httpx.AsyncClient() as client:
        # Try API-Football
        if API_FOOTBALL_KEY:
            data = await safe_get(client, f"{AF_BASE}/teams",
                                  headers=AF_HEADERS,
                                  params={"search": team_name})
            if data and data.get("response"):
                t = data["response"][0]
                team = t.get("team", {})
                venue = t.get("venue", {})
                return json.dumps({
                    "source": "API-Football",
                    "id": team.get("id"),
                    "name": team.get("name"),
                    "country": team.get("country"),
                    "founded": team.get("founded"),
                    "logo": team.get("logo"),
                    "stadium": venue.get("name"),
                    "city": venue.get("city"),
                    "capacity": venue.get("capacity"),
                }, indent=2)
        # Fallback: TheSportsDB
        data = await safe_get(client, f"{SDB_BASE}/searchteams.php",
                              params={"t": team_name})
        if data and data.get("teams"):
            t = data["teams"][0]
            return json.dumps({
                "source": "TheSportsDB",
                "name": t.get("strTeam"),
                "country": t.get("strCountry"),
                "league": t.get("strLeague"),
                "founded": t.get("intFormedYear"),
                "stadium": t.get("strStadium"),
                "description": (t.get("strDescriptionEN") or "")[:500],
            }, indent=2)
        return f"No team found for '{team_name}'."


@mcp.tool()
async def get_team_last_matches(team_name: str) -> str:
    """Get a football team's last matches with detailed stats."""
    async with httpx.AsyncClient() as client:
        if API_FOOTBALL_KEY:
            search = await safe_get(client, f"{AF_BASE}/teams",
                                    headers=AF_HEADERS,
                                    params={"search": team_name})
            if search and search.get("response"):
                team_id = search["response"][0]["team"]["id"]
                fixtures = await safe_get(
                    client, f"{AF_BASE}/fixtures",
                    headers=AF_HEADERS,
                    params={"team": team_id, "last": 10},
                )
                if fixtures and fixtures.get("response"):
                    results = []
                    for f in fixtures["response"]:
                        league = f.get("league", {})
                        teams = f.get("teams", {})
                        goals = f.get("goals", {})
                        fix = f.get("fixture", {})
                        results.append({
                            "date": fix.get("date", "")[:10],
                            "league": league.get("name"),
                            "home": teams.get("home", {}).get("name"),
                            "away": teams.get("away", {}).get("name"),
                            "score": f"{goals.get('home')} - {goals.get('away')}",
                            "venue": fix.get("venue", {}).get("name"),
                            "winner": "home" if teams.get("home", {}).get("winner")
                                       else ("away" if teams.get("away", {}).get("winner") else "draw"),
                        })
                    return json.dumps({"source": "API-Football", "matches": results}, indent=2)
        # Fallback: TheSportsDB
        search = await safe_get(client, f"{SDB_BASE}/searchteams.php",
                                params={"t": team_name})
        if not search or not search.get("teams"):
            return f"Team '{team_name}' not found."
        team_id = search["teams"][0]["idTeam"]
        events = await safe_get(client, f"{SDB_BASE}/eventslast.php",
                                params={"id": team_id})
        if not events or not events.get("results"):
            return "No recent matches available."
        results = []
        for e in events["results"][:10]:
            results.append({
                "date": e.get("dateEvent"),
                "home": e.get("strHomeTeam"),
                "away": e.get("strAwayTeam"),
                "score": f"{e.get('intHomeScore')} - {e.get('intAwayScore')}",
                "league": e.get("strLeague"),
            })
        return json.dumps({"source": "TheSportsDB", "matches": results}, indent=2)


@mcp.tool()
async def get_team_next_matches(team_name: str) -> str:
    """Get a football team's upcoming fixtures."""
    async with httpx.AsyncClient() as client:
        if API_FOOTBALL_KEY:
            search = await safe_get(client, f"{AF_BASE}/teams",
                                    headers=AF_HEADERS,
                                    params={"search": team_name})
            if search and search.get("response"):
                team_id = search["response"][0]["team"]["id"]
                fixtures = await safe_get(
                    client, f"{AF_BASE}/fixtures",
                    headers=AF_HEADERS,
                    params={"team": team_id, "next": 5},
                )
                if fixtures and fixtures.get("response"):
                    results = []
                    for f in fixtures["response"]:
                        teams = f.get("teams", {})
                        fix = f.get("fixture", {})
                        results.append({
                            "date": fix.get("date", "")[:16].replace("T", " "),
                            "league": f.get("league", {}).get("name"),
                            "home": teams.get("home", {}).get("name"),
                            "away": teams.get("away", {}).get("name"),
                            "venue": fix.get("venue", {}).get("name"),
                        })
                    return json.dumps({"source": "API-Football", "matches": results}, indent=2)
        # Fallback: TheSportsDB
        search = await safe_get(client, f"{SDB_BASE}/searchteams.php",
                                params={"t": team_name})
        if not search or not search.get("teams"):
            return f"Team '{team_name}' not found."
        team_id = search["teams"][0]["idTeam"]
        events = await safe_get(client, f"{SDB_BASE}/eventsnext.php",
                                params={"id": team_id})
        if not events or not events.get("events"):
            return "No upcoming matches available."
        results = []
        for e in events["events"][:5]:
            results.append({
                "date": e.get("dateEvent"), "time": e.get("strTime"),
                "home": e.get("strHomeTeam"), "away": e.get("strAwayTeam"),
                "league": e.get("strLeague"), "venue": e.get("strVenue"),
            })
        return json.dumps({"source": "TheSportsDB", "matches": results}, indent=2)


@mcp.tool()
async def get_team_statistics(team_name: str, league: str = "Premier League") -> str:
    """Get deep team stats for a season: form, goals, possession, etc. (API-Football required)"""
    if not API_FOOTBALL_KEY:
        return "Add API_FOOTBALL_KEY env var on Render to use deep team stats."
    league_ids = {"premier league": 39, "la liga": 140, "serie a": 135,
                  "ligue 1": 61, "bundesliga": 78, "champions league": 2}
    lid = league_ids.get(league.lower())
    if not lid:
        return f"League '{league}' not mapped. Try: Premier League, La Liga, Serie A, Ligue 1, Bundesliga, Champions League."
    async with httpx.AsyncClient() as client:
        search = await safe_get(client, f"{AF_BASE}/teams", headers=AF_HEADERS,
                                params={"search": team_name})
        if not search or not search.get("response"):
            return f"Team '{team_name}' not found."
        team_id = search["response"][0]["team"]["id"]
        stats = await safe_get(client, f"{AF_BASE}/teams/statistics",
                               headers=AF_HEADERS,
                               params={"team": team_id, "league": lid, "season": 2024})
        if not stats or not stats.get("response"):
            return "No statistics available for that team/league/season."
        s = stats["response"]
        fixtures = s.get("fixtures", {})
        goals = s.get("goals", {})
        return json.dumps({
            "team": s.get("team", {}).get("name"),
            "league": s.get("league", {}).get("name"),
            "season": s.get("league", {}).get("season"),
            "form": s.get("form"),
            "played": fixtures.get("played", {}).get("total"),
            "wins": fixtures.get("wins", {}).get("total"),
            "draws": fixtures.get("draws", {}).get("total"),
            "losses": fixtures.get("loses", {}).get("total"),
            "goals_for_total": goals.get("for", {}).get("total", {}).get("total"),
            "goals_against_total": goals.get("against", {}).get("total", {}).get("total"),
            "clean_sheets": s.get("clean_sheet", {}).get("total"),
            "failed_to_score": s.get("failed_to_score", {}).get("total"),
            "biggest_win": s.get("biggest", {}).get("wins"),
            "biggest_loss": s.get("biggest", {}).get("loses"),
        }, indent=2)


@mcp.tool()
async def get_head_to_head(team1: str, team2: str) -> str:
    """Get head-to-head record between two football teams. (API-Football required)"""
    if not API_FOOTBALL_KEY:
        return "Add API_FOOTBALL_KEY env var on Render to use head-to-head data."
    async with httpx.AsyncClient() as client:
        s1 = await safe_get(client, f"{AF_BASE}/teams", headers=AF_HEADERS,
                            params={"search": team1})
        s2 = await safe_get(client, f"{AF_BASE}/teams", headers=AF_HEADERS,
                            params={"search": team2})
        if not (s1 and s1.get("response")) or not (s2 and s2.get("response")):
            return "One or both teams not found."
        id1 = s1["response"][0]["team"]["id"]
        id2 = s2["response"][0]["team"]["id"]
        h2h = await safe_get(client, f"{AF_BASE}/fixtures/headtohead",
                             headers=AF_HEADERS,
                             params={"h2h": f"{id1}-{id2}", "last": 10})
        if not h2h or not h2h.get("response"):
            return "No head-to-head data found."
        results = []
        for f in h2h["response"]:
            teams = f.get("teams", {})
            goals = f.get("goals", {})
            fix = f.get("fixture", {})
            results.append({
                "date": fix.get("date", "")[:10],
                "league": f.get("league", {}).get("name"),
                "home": teams.get("home", {}).get("name"),
                "away": teams.get("away", {}).get("name"),
                "score": f"{goals.get('home')} - {goals.get('away')}",
            })
        return json.dumps({"head_to_head": results}, indent=2)


@mcp.tool()
async def get_league_table(league_name: str) -> str:
    """Get standings for a league. Bundesliga works free, others use API-Football."""
    league_lower = league_name.lower()
    # Bundesliga via free OpenLigaDB
    if "bundesliga" in league_lower:
        league_key = "bl2" if "2" in league_lower else "bl1"
        async with httpx.AsyncClient() as client:
            data = await safe_get(client, f"{OL_BASE}/getbltable/{league_key}/2024")
            if not data:
                return "Bundesliga table unavailable right now."
            rows = []
            for i, t in enumerate(data[:18], 1):
                rows.append({
                    "pos": i, "team": t.get("teamName"),
                    "P": t.get("matches"), "W": t.get("won"),
                    "D": t.get("draw"), "L": t.get("lost"),
                    "GD": t.get("goalDiff"), "Pts": t.get("points"),
                })
            return json.dumps({"source": "OpenLigaDB", "table": rows}, indent=2)
    # Other leagues via API-Football
    if not API_FOOTBALL_KEY:
        return "Add API_FOOTBALL_KEY on Render. Bundesliga works free without it."
    league_ids = {"premier league": 39, "la liga": 140, "serie a": 135,
                  "ligue 1": 61, "champions league": 2, "europa league": 3,
                  "championship": 40, "mls": 253}
    lid = next((v for k, v in league_ids.items() if k in league_lower), None)
    if not lid:
        return "Try: Premier League, La Liga, Serie A, Ligue 1, Bundesliga, Champions League, MLS, Championship."
    async with httpx.AsyncClient() as client:
        data = await safe_get(client, f"{AF_BASE}/standings", headers=AF_HEADERS,
                              params={"league": lid, "season": 2024})
        if not data or not data.get("response"):
            return "Standings unavailable."
        table = data["response"][0]["league"]["standings"][0]
        rows = []
        for t in table:
            rows.append({
                "pos": t.get("rank"),
                "team": t.get("team", {}).get("name"),
                "P": t.get("all", {}).get("played"),
                "W": t.get("all", {}).get("win"),
                "D": t.get("all", {}).get("draw"),
                "L": t.get("all", {}).get("lose"),
                "GD": t.get("goalsDiff"),
                "Pts": t.get("points"),
                "form": t.get("form"),
            })
        return json.dumps({"source": "API-Football", "table": rows}, indent=2)


@mcp.tool()
async def get_top_scorers(league_name: str = "Premier League") -> str:
    """Get top scorers in a league. (API-Football required)"""
    if not API_FOOTBALL_KEY:
        return "Add API_FOOTBALL_KEY env var on Render to use top scorers."
    league_ids = {"premier league": 39, "la liga": 140, "serie a": 135,
                  "ligue 1": 61, "bundesliga": 78, "champions league": 2}
    lid = league_ids.get(league_name.lower())
    if not lid:
        return "Try: Premier League, La Liga, Serie A, Ligue 1, Bundesliga, Champions League."
    async with httpx.AsyncClient() as client:
        data = await safe_get(client, f"{AF_BASE}/players/topscorers",
                              headers=AF_HEADERS,
                              params={"league": lid, "season": 2024})
        if not data or not data.get("response"):
            return "Top scorers unavailable."
        scorers = []
        for p in data["response"][:15]:
            player = p.get("player", {})
            stats = (p.get("statistics") or [{}])[0]
            scorers.append({
                "player": player.get("name"),
                "age": player.get("age"),
                "nationality": player.get("nationality"),
                "team": stats.get("team", {}).get("name"),
                "goals": stats.get("goals", {}).get("total"),
                "assists": stats.get("goals", {}).get("assists"),
                "appearances": stats.get("games", {}).get("appearences"),
            })
        return json.dumps(scorers, indent=2)


# ═════════════════════════════════════════════════════════════════════════════
#  BASKETBALL (NBA via balldontlie - free, no key)
# ═════════════════════════════════════════════════════════════════════════════

@mcp.tool()
async def search_basketball_team(team_name: str) -> str:
    """Search for an NBA team using balldontlie (free, no key needed)."""
    async with httpx.AsyncClient() as client:
        data = await safe_get(client, f"{BDL_BASE}/teams")
        if not data or not data.get("data"):
            # fallback: TheSportsDB
            data2 = await safe_get(client, f"{SDB_BASE}/searchteams.php",
                                   params={"t": team_name})
            if data2 and data2.get("teams"):
                teams = [t for t in data2["teams"] if t.get("strSport") == "Basketball"]
                if teams:
                    t = teams[0]
                    return json.dumps({
                        "source": "TheSportsDB",
                        "name": t.get("strTeam"),
                        "league": t.get("strLeague"),
                        "country": t.get("strCountry"),
                        "arena": t.get("strStadium"),
                    }, indent=2)
            return f"No basketball team found for '{team_name}'."
        # Match against balldontlie data
        q = team_name.lower()
        for t in data["data"]:
            if (q in (t.get("full_name") or "").lower()
                or q in (t.get("name") or "").lower()
                or q in (t.get("city") or "").lower()):
                return json.dumps({
                    "source": "balldontlie",
                    "id": t.get("id"),
                    "full_name": t.get("full_name"),
                    "abbreviation": t.get("abbreviation"),
                    "city": t.get("city"),
                    "conference": t.get("conference"),
                    "division": t.get("division"),
                }, indent=2)
        return f"No NBA team matched '{team_name}'."


@mcp.tool()
async def get_basketball_team_results(team_name: str) -> str:
    """Get recent NBA game results for a team."""
    async with httpx.AsyncClient() as client:
        teams = await safe_get(client, f"{BDL_BASE}/teams")
        if not teams or not teams.get("data"):
            return "Basketball data unavailable right now."
        q = team_name.lower()
        team_id = None
        team_full = None
        for t in teams["data"]:
            if (q in (t.get("full_name") or "").lower()
                or q in (t.get("name") or "").lower()
                or q in (t.get("city") or "").lower()):
                team_id = t.get("id")
                team_full = t.get("full_name")
                break
        if not team_id:
            return f"NBA team '{team_name}' not found."
        games = await safe_get(client, f"{BDL_BASE}/games",
                               params={"team_ids[]": team_id, "per_page": 10,
                                       "seasons[]": 2024})
        if not games or not games.get("data"):
            return f"No recent games for {team_full}."
        results = []
        for g in games["data"][:10]:
            if g.get("status") == "Final":
                home = g.get("home_team", {}).get("full_name")
                visitor = g.get("visitor_team", {}).get("full_name")
                results.append({
                    "date": g.get("date", "")[:10],
                    "home": home,
                    "away": visitor,
                    "score": f"{g.get('home_team_score')} - {g.get('visitor_team_score')}",
                    "season": g.get("season"),
                })
        return json.dumps({"team": team_full, "games": results}, indent=2)


# ═════════════════════════════════════════════════════════════════════════════
#  PLAYERS (multi-sport)
# ═════════════════════════════════════════════════════════════════════════════

@mcp.tool()
async def search_player(player_name: str) -> str:
    """Search for a player across all sports."""
    async with httpx.AsyncClient() as client:
        # Try API-Football for football players first
        if API_FOOTBALL_KEY:
            data = await safe_get(client, f"{AF_BASE}/players/profiles",
                                  headers=AF_HEADERS,
                                  params={"search": player_name.split()[-1]})
            if data and data.get("response"):
                p = data["response"][0].get("player", {})
                return json.dumps({
                    "source": "API-Football",
                    "name": p.get("name"),
                    "first_name": p.get("firstname"),
                    "last_name": p.get("lastname"),
                    "age": p.get("age"),
                    "birth_date": p.get("birth", {}).get("date"),
                    "birth_country": p.get("birth", {}).get("country"),
                    "nationality": p.get("nationality"),
                    "height": p.get("height"),
                    "weight": p.get("weight"),
                    "position": p.get("position"),
                    "photo": p.get("photo"),
                }, indent=2)
        # Fallback: TheSportsDB
        data = await safe_get(client, f"{SDB_BASE}/searchplayers.php",
                              params={"p": player_name})
        if data and data.get("player"):
            p = data["player"][0]
            return json.dumps({
                "source": "TheSportsDB",
                "name": p.get("strPlayer"), "sport": p.get("strSport"),
                "team": p.get("strTeam"), "nationality": p.get("strNationality"),
                "position": p.get("strPosition"),
                "date_of_birth": p.get("dateBorn"),
                "height": p.get("strHeight"),
                "description": (p.get("strDescriptionEN") or "")[:500],
            }, indent=2)
        return f"No player found for '{player_name}'."


@mcp.tool()
async def search_tennis_player(player_name: str) -> str:
    """Search for a tennis player profile."""
    async with httpx.AsyncClient() as client:
        data = await safe_get(client, f"{SDB_BASE}/searchplayers.php",
                              params={"p": player_name})
        if not data or not data.get("player"):
            return f"Tennis player '{player_name}' not found."
        p = data["player"][0]
        return json.dumps({
            "name": p.get("strPlayer"),
            "nationality": p.get("strNationality"),
            "date_of_birth": p.get("dateBorn"),
            "height": p.get("strHeight"),
            "description": (p.get("strDescriptionEN") or "")[:600],
        }, indent=2)


# ═════════════════════════════════════════════════════════════════════════════
#  CRICKET
# ═════════════════════════════════════════════════════════════════════════════

@mcp.tool()
async def search_cricket_team(team_name: str) -> str:
    """Search for a cricket team."""
    async with httpx.AsyncClient() as client:
        data = await safe_get(client, f"{SDB_BASE}/searchteams.php",
                              params={"t": team_name})
        if not data or not data.get("teams"):
            return f"No cricket team found for '{team_name}'."
        teams = [t for t in data["teams"] if t.get("strSport") == "Cricket"]
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
        search = await safe_get(client, f"{SDB_BASE}/searchteams.php",
                                params={"t": team_name})
        if not search or not search.get("teams"):
            return f"Cricket team '{team_name}' not found."
        teams = [t for t in search["teams"] if t.get("strSport") == "Cricket"]
        if not teams:
            return f"Cricket team '{team_name}' not found."
        team_id = teams[0]["idTeam"]
        events = await safe_get(client, f"{SDB_BASE}/eventslast.php",
                                params={"id": team_id})
        if not events or not events.get("results"):
            return "No recent cricket matches available."
        results = []
        for e in events["results"][:5]:
            results.append({
                "date": e.get("dateEvent"),
                "match": f"{e.get('strHomeTeam')} vs {e.get('strAwayTeam')}",
                "score": f"{e.get('intHomeScore')} - {e.get('intAwayScore')}",
                "league": e.get("strLeague"),
            })
        return json.dumps(results, indent=2)


# ═════════════════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ═════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    app = mcp.streamable_http_app()
    uvicorn.run(app, host="0.0.0.0", port=port)
