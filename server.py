"""
Sports Analysis MCP Server v3 - Multi-API resilient
Football APIs (in fallback order): football-data.org, API-Football, OpenLigaDB, TheSportsDB
NBA: balldontlie (free, no key)
Cricket / Tennis: TheSportsDB
"""
import httpx
import os
import json
import uvicorn
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

mcp = FastMCP(
    "Sports Analysis Server",
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)

# ── Keys & endpoints ──────────────────────────────────────────────────────────
FD_KEY = os.getenv("FOOTBALL_DATA_KEY", "")          # football-data.org (primary)
API_FOOTBALL_KEY = os.getenv("API_FOOTBALL_KEY", "")  # api-football (secondary)

FD_BASE  = "https://api.football-data.org/v4"
AF_BASE  = "https://v3.football.api-sports.io"
SDB_BASE = "https://www.thesportsdb.com/api/v1/json/3"
OL_BASE  = "https://api.openligadb.de"
BDL_BASE = "https://api.balldontlie.io/v1"

FD_HEADERS = {"X-Auth-Token": FD_KEY} if FD_KEY else {}
AF_HEADERS = {"x-apisports-key": API_FOOTBALL_KEY} if API_FOOTBALL_KEY else {}

# football-data.org competition codes
FD_LEAGUE_CODES = {
    "premier league": "PL", "epl": "PL", "english premier league": "PL",
    "la liga": "PD", "primera division": "PD", "spanish la liga": "PD",
    "serie a": "SA", "italian serie a": "SA",
    "bundesliga": "BL1",
    "ligue 1": "FL1", "french ligue 1": "FL1",
    "champions league": "CL", "ucl": "CL",
    "championship": "ELC",
    "eredivisie": "DED",
    "primeira liga": "PPL",
    "world cup": "WC",
    "european championship": "EC", "euro": "EC",
    "brasileirao": "BSA", "brazilian serie a": "BSA",
}

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


def fd_competition_code(league_name: str):
    return FD_LEAGUE_CODES.get(league_name.lower())


# ═════════════════════════════════════════════════════════════════════════════
#  FOOTBALL / SOCCER
# ═════════════════════════════════════════════════════════════════════════════

@mcp.tool()
async def search_team(team_name: str) -> str:
    """Search for a football/soccer team. Tries football-data.org → API-Football → TheSportsDB."""
    async with httpx.AsyncClient() as client:
        # Try football-data.org
        if FD_KEY:
            data = await safe_get(client, f"{FD_BASE}/teams",
                                  headers=FD_HEADERS, params={"limit": 500})
            if data and data.get("teams"):
                q = team_name.lower()
                matches = [t for t in data["teams"]
                           if q in (t.get("name") or "").lower()
                           or q in (t.get("shortName") or "").lower()
                           or q in (t.get("tla") or "").lower()]
                if matches:
                    t = matches[0]
                    area = t.get("area", {})
                    return json.dumps({
                        "source": "football-data.org",
                        "id": t.get("id"),
                        "name": t.get("name"),
                        "short_name": t.get("shortName"),
                        "tla": t.get("tla"),
                        "country": area.get("name"),
                        "founded": t.get("founded"),
                        "venue": t.get("venue"),
                        "website": t.get("website"),
                        "club_colors": t.get("clubColors"),
                    }, indent=2)
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
                    "venue": venue.get("name"),
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
        # Try football-data.org
        if FD_KEY:
            teams = await safe_get(client, f"{FD_BASE}/teams",
                                   headers=FD_HEADERS, params={"limit": 500})
            if teams and teams.get("teams"):
                q = team_name.lower()
                tm = next((t for t in teams["teams"]
                           if q in (t.get("name") or "").lower()
                           or q in (t.get("shortName") or "").lower()), None)
                if tm:
                    matches = await safe_get(
                        client,
                        f"{FD_BASE}/teams/{tm['id']}/matches",
                        headers=FD_HEADERS,
                        params={"status": "FINISHED", "limit": 10},
                    )
                    if matches and matches.get("matches"):
                        results = []
                        for m in matches["matches"][-10:][::-1]:
                            score = m.get("score", {}).get("fullTime", {})
                            results.append({
                                "date": (m.get("utcDate") or "")[:10],
                                "competition": m.get("competition", {}).get("name"),
                                "home": m.get("homeTeam", {}).get("name"),
                                "away": m.get("awayTeam", {}).get("name"),
                                "score": f"{score.get('home')} - {score.get('away')}",
                                "winner": m.get("score", {}).get("winner"),
                            })
                        return json.dumps({"source": "football-data.org",
                                           "team": tm["name"],
                                           "matches": results}, indent=2)
        # Fallback to API-Football and TheSportsDB
        if API_FOOTBALL_KEY:
            search = await safe_get(client, f"{AF_BASE}/teams",
                                    headers=AF_HEADERS, params={"search": team_name})
            if search and search.get("response"):
                team_id = search["response"][0]["team"]["id"]
                fixtures = await safe_get(client, f"{AF_BASE}/fixtures",
                                          headers=AF_HEADERS,
                                          params={"team": team_id, "last": 10})
                if fixtures and fixtures.get("response"):
                    results = []
                    for f in fixtures["response"]:
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
                    return json.dumps({"source": "API-Football", "matches": results}, indent=2)
        # TheSportsDB last
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
        if FD_KEY:
            teams = await safe_get(client, f"{FD_BASE}/teams",
                                   headers=FD_HEADERS, params={"limit": 500})
            if teams and teams.get("teams"):
                q = team_name.lower()
                tm = next((t for t in teams["teams"]
                           if q in (t.get("name") or "").lower()
                           or q in (t.get("shortName") or "").lower()), None)
                if tm:
                    matches = await safe_get(client,
                                             f"{FD_BASE}/teams/{tm['id']}/matches",
                                             headers=FD_HEADERS,
                                             params={"status": "SCHEDULED", "limit": 5})
                    if matches and matches.get("matches"):
                        results = []
                        for m in matches["matches"][:5]:
                            results.append({
                                "date": (m.get("utcDate") or "")[:16].replace("T", " "),
                                "competition": m.get("competition", {}).get("name"),
                                "matchday": m.get("matchday"),
                                "home": m.get("homeTeam", {}).get("name"),
                                "away": m.get("awayTeam", {}).get("name"),
                            })
                        return json.dumps({"source": "football-data.org",
                                           "team": tm["name"],
                                           "fixtures": results}, indent=2)
        # Fallback chain
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
        return json.dumps({"source": "TheSportsDB", "fixtures": results}, indent=2)


@mcp.tool()
async def get_league_table(league_name: str) -> str:
    """Get standings for a league. Works for: Premier League, La Liga, Serie A, Bundesliga, Ligue 1, Champions League, Championship, Eredivisie, Primeira Liga, Brasileirao, World Cup, Euro."""
    league_lower = league_name.lower()
    # Bundesliga via OpenLigaDB always free
    if "bundesliga" in league_lower and "2" not in league_lower:
        async with httpx.AsyncClient() as client:
            data = await safe_get(client, f"{OL_BASE}/getbltable/bl1/2024")
            if data:
                rows = []
                for i, t in enumerate(data[:18], 1):
                    rows.append({
                        "pos": i, "team": t.get("teamName"),
                        "P": t.get("matches"), "W": t.get("won"),
                        "D": t.get("draw"), "L": t.get("lost"),
                        "GD": t.get("goalDiff"), "Pts": t.get("points"),
                    })
                return json.dumps({"source": "OpenLigaDB", "league": "Bundesliga", "table": rows}, indent=2)

    # Try football-data.org
    if FD_KEY:
        code = fd_competition_code(league_name)
        if code:
            async with httpx.AsyncClient() as client:
                data = await safe_get(client, f"{FD_BASE}/competitions/{code}/standings",
                                      headers=FD_HEADERS)
                if data and data.get("standings"):
                    table = next((s for s in data["standings"] if s.get("type") == "TOTAL"),
                                 data["standings"][0])
                    rows = []
                    for t in table.get("table", []):
                        rows.append({
                            "pos": t.get("position"),
                            "team": t.get("team", {}).get("name"),
                            "P": t.get("playedGames"),
                            "W": t.get("won"),
                            "D": t.get("draw"),
                            "L": t.get("lost"),
                            "GF": t.get("goalsFor"),
                            "GA": t.get("goalsAgainst"),
                            "GD": t.get("goalDifference"),
                            "Pts": t.get("points"),
                            "form": t.get("form"),
                        })
                    return json.dumps({
                        "source": "football-data.org",
                        "league": data.get("competition", {}).get("name"),
                        "season": data.get("season", {}).get("startDate", "")[:4],
                        "matchday": data.get("season", {}).get("currentMatchday"),
                        "table": rows
                    }, indent=2)

    # API-Football fallback
    if API_FOOTBALL_KEY:
        af_ids = {"premier league": 39, "la liga": 140, "serie a": 135,
                  "ligue 1": 61, "champions league": 2}
        lid = next((v for k, v in af_ids.items() if k in league_lower), None)
        if lid:
            async with httpx.AsyncClient() as client:
                data = await safe_get(client, f"{AF_BASE}/standings", headers=AF_HEADERS,
                                      params={"league": lid, "season": 2024})
                if data and data.get("response"):
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

    return f"Standings for '{league_name}' unavailable. Add FOOTBALL_DATA_KEY env var on Render."


@mcp.tool()
async def get_top_scorers(league_name: str = "Premier League") -> str:
    """Get top scorers in a league. Try football-data.org first."""
    if FD_KEY:
        code = fd_competition_code(league_name)
        if code:
            async with httpx.AsyncClient() as client:
                data = await safe_get(client, f"{FD_BASE}/competitions/{code}/scorers",
                                      headers=FD_HEADERS, params={"limit": 15})
                if data and data.get("scorers"):
                    scorers = []
                    for s in data["scorers"]:
                        p = s.get("player", {})
                        t = s.get("team", {})
                        scorers.append({
                            "player": p.get("name"),
                            "nationality": p.get("nationality"),
                            "team": t.get("name"),
                            "goals": s.get("goals"),
                            "assists": s.get("assists"),
                            "penalties": s.get("penalties"),
                            "appearances": s.get("playedMatches"),
                        })
                    return json.dumps({
                        "source": "football-data.org",
                        "league": data.get("competition", {}).get("name"),
                        "scorers": scorers,
                    }, indent=2)

    if API_FOOTBALL_KEY:
        af_ids = {"premier league": 39, "la liga": 140, "serie a": 135,
                  "ligue 1": 61, "bundesliga": 78, "champions league": 2}
        lid = af_ids.get(league_name.lower())
        if lid:
            async with httpx.AsyncClient() as client:
                data = await safe_get(client, f"{AF_BASE}/players/topscorers",
                                      headers=AF_HEADERS,
                                      params={"league": lid, "season": 2024})
                if data and data.get("response"):
                    scorers = []
                    for p in data["response"][:15]:
                        player = p.get("player", {})
                        stats = (p.get("statistics") or [{}])[0]
                        scorers.append({
                            "player": player.get("name"),
                            "team": stats.get("team", {}).get("name"),
                            "goals": stats.get("goals", {}).get("total"),
                            "assists": stats.get("goals", {}).get("assists"),
                        })
                    return json.dumps({"source": "API-Football", "scorers": scorers}, indent=2)

    return "Top scorers unavailable. Add FOOTBALL_DATA_KEY env var on Render."


@mcp.tool()
async def get_match_results_for_league(league_name: str, matchday: int = 0) -> str:
    """Get all match results for a specific matchday in a league. Use matchday=0 for latest finished matchday."""
    if not FD_KEY:
        return "This requires FOOTBALL_DATA_KEY env var on Render."
    code = fd_competition_code(league_name)
    if not code:
        return f"League '{league_name}' not supported. Try: Premier League, La Liga, Serie A, Bundesliga, Ligue 1, Champions League."
    async with httpx.AsyncClient() as client:
        params = {"status": "FINISHED"}
        if matchday > 0:
            params["matchday"] = matchday
        data = await safe_get(client, f"{FD_BASE}/competitions/{code}/matches",
                              headers=FD_HEADERS, params=params)
        if not data or not data.get("matches"):
            return "No matches found."
        all_matches = data["matches"]
        if matchday == 0:
            max_md = max((m.get("matchday") or 0) for m in all_matches)
            all_matches = [m for m in all_matches if m.get("matchday") == max_md]
        results = []
        for m in all_matches:
            score = m.get("score", {}).get("fullTime", {})
            results.append({
                "matchday": m.get("matchday"),
                "date": (m.get("utcDate") or "")[:10],
                "home": m.get("homeTeam", {}).get("name"),
                "away": m.get("awayTeam", {}).get("name"),
                "score": f"{score.get('home')} - {score.get('away')}",
            })
        return json.dumps({"league": code, "matches": results}, indent=2)


@mcp.tool()
async def get_head_to_head(team1: str, team2: str) -> str:
    """Get head-to-head record between two football teams."""
    async with httpx.AsyncClient() as client:
        if FD_KEY:
            teams = await safe_get(client, f"{FD_BASE}/teams",
                                   headers=FD_HEADERS, params={"limit": 500})
            if teams and teams.get("teams"):
                q1, q2 = team1.lower(), team2.lower()
                t1 = next((t for t in teams["teams"]
                           if q1 in (t.get("name") or "").lower()
                           or q1 in (t.get("shortName") or "").lower()), None)
                t2 = next((t for t in teams["teams"]
                           if q2 in (t.get("name") or "").lower()
                           or q2 in (t.get("shortName") or "").lower()), None)
                if t1 and t2:
                    matches = await safe_get(client,
                                             f"{FD_BASE}/teams/{t1['id']}/matches",
                                             headers=FD_HEADERS,
                                             params={"status": "FINISHED", "limit": 100})
                    if matches and matches.get("matches"):
                        h2h = []
                        for m in matches["matches"]:
                            home_id = m.get("homeTeam", {}).get("id")
                            away_id = m.get("awayTeam", {}).get("id")
                            if t2["id"] in (home_id, away_id):
                                score = m.get("score", {}).get("fullTime", {})
                                h2h.append({
                                    "date": (m.get("utcDate") or "")[:10],
                                    "competition": m.get("competition", {}).get("name"),
                                    "home": m.get("homeTeam", {}).get("name"),
                                    "away": m.get("awayTeam", {}).get("name"),
                                    "score": f"{score.get('home')} - {score.get('away')}",
                                    "winner": m.get("score", {}).get("winner"),
                                })
                        if h2h:
                            return json.dumps({
                                "source": "football-data.org",
                                "matchups": h2h[:10],
                                "total_recent_meetings": len(h2h),
                            }, indent=2)
        # API-Football fallback
        if API_FOOTBALL_KEY:
            s1 = await safe_get(client, f"{AF_BASE}/teams", headers=AF_HEADERS,
                                params={"search": team1})
            s2 = await safe_get(client, f"{AF_BASE}/teams", headers=AF_HEADERS,
                                params={"search": team2})
            if (s1 and s1.get("response")) and (s2 and s2.get("response")):
                id1 = s1["response"][0]["team"]["id"]
                id2 = s2["response"][0]["team"]["id"]
                h2h = await safe_get(client, f"{AF_BASE}/fixtures/headtohead",
                                     headers=AF_HEADERS,
                                     params={"h2h": f"{id1}-{id2}", "last": 10})
                if h2h and h2h.get("response"):
                    results = []
                    for f in h2h["response"]:
                        teams = f.get("teams", {})
                        goals = f.get("goals", {})
                        results.append({
                            "date": f.get("fixture", {}).get("date", "")[:10],
                            "home": teams.get("home", {}).get("name"),
                            "away": teams.get("away", {}).get("name"),
                            "score": f"{goals.get('home')} - {goals.get('away')}",
                        })
                    return json.dumps({"source": "API-Football",
                                       "matchups": results}, indent=2)
        return "Head-to-head unavailable. Add FOOTBALL_DATA_KEY env var."


@mcp.tool()
async def get_team_statistics(team_name: str, league: str = "Premier League") -> str:
    """Get deep team stats for a season: form, position, goals, etc."""
    if FD_KEY:
        async with httpx.AsyncClient() as client:
            code = fd_competition_code(league)
            if code:
                data = await safe_get(client, f"{FD_BASE}/competitions/{code}/standings",
                                      headers=FD_HEADERS)
                if data and data.get("standings"):
                    table = next((s for s in data["standings"] if s.get("type") == "TOTAL"),
                                 data["standings"][0]).get("table", [])
                    q = team_name.lower()
                    row = next((r for r in table
                                if q in (r.get("team", {}).get("name") or "").lower()
                                or q in (r.get("team", {}).get("shortName") or "").lower()), None)
                    if row:
                        played = row.get("playedGames", 0) or 0
                        won = row.get("won", 0) or 0
                        return json.dumps({
                            "source": "football-data.org",
                            "team": row.get("team", {}).get("name"),
                            "league": data.get("competition", {}).get("name"),
                            "position": row.get("position"),
                            "played": played,
                            "won": won,
                            "drawn": row.get("draw"),
                            "lost": row.get("lost"),
                            "win_rate_pct": round(won / played * 100, 1) if played else 0,
                            "goals_for": row.get("goalsFor"),
                            "goals_against": row.get("goalsAgainst"),
                            "goal_difference": row.get("goalDifference"),
                            "goals_per_game": round((row.get("goalsFor") or 0) / played, 2) if played else 0,
                            "points": row.get("points"),
                            "points_per_game": round((row.get("points") or 0) / played, 2) if played else 0,
                            "form_last_5": row.get("form"),
                        }, indent=2)
    if API_FOOTBALL_KEY:
        league_ids = {"premier league": 39, "la liga": 140, "serie a": 135,
                      "ligue 1": 61, "bundesliga": 78, "champions league": 2}
        lid = league_ids.get(league.lower())
        if lid:
            async with httpx.AsyncClient() as client:
                search = await safe_get(client, f"{AF_BASE}/teams", headers=AF_HEADERS,
                                        params={"search": team_name})
                if search and search.get("response"):
                    team_id = search["response"][0]["team"]["id"]
                    stats = await safe_get(client, f"{AF_BASE}/teams/statistics",
                                           headers=AF_HEADERS,
                                           params={"team": team_id, "league": lid, "season": 2024})
                    if stats and stats.get("response"):
                        s = stats["response"]
                        return json.dumps({
                            "source": "API-Football",
                            "team": s.get("team", {}).get("name"),
                            "form": s.get("form"),
                            "fixtures": s.get("fixtures"),
                            "goals": s.get("goals"),
                            "clean_sheets": s.get("clean_sheet"),
                            "biggest": s.get("biggest"),
                        }, indent=2)
    return "Team statistics unavailable. Add FOOTBALL_DATA_KEY env var."


# ═════════════════════════════════════════════════════════════════════════════
#  BASKETBALL (NBA via balldontlie)
# ═════════════════════════════════════════════════════════════════════════════

@mcp.tool()
async def search_basketball_team(team_name: str) -> str:
    """Search for an NBA team using balldontlie (free, no key needed)."""
    async with httpx.AsyncClient() as client:
        data = await safe_get(client, f"{BDL_BASE}/teams")
        if not data or not data.get("data"):
            return f"NBA data unavailable right now."
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
        team_id, team_full = None, None
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
                results.append({
                    "date": g.get("date", "")[:10],
                    "home": g.get("home_team", {}).get("full_name"),
                    "away": g.get("visitor_team", {}).get("full_name"),
                    "score": f"{g.get('home_team_score')} - {g.get('visitor_team_score')}",
                })
        return json.dumps({"team": team_full, "games": results}, indent=2)


# ═════════════════════════════════════════════════════════════════════════════
#  PLAYERS (multi-sport)
# ═════════════════════════════════════════════════════════════════════════════

@mcp.tool()
async def search_player(player_name: str) -> str:
    """Search for a player across all sports."""
    async with httpx.AsyncClient() as client:
        if API_FOOTBALL_KEY:
            data = await safe_get(client, f"{AF_BASE}/players/profiles",
                                  headers=AF_HEADERS,
                                  params={"search": player_name.split()[-1]})
            if data and data.get("response"):
                p = data["response"][0].get("player", {})
                return json.dumps({
                    "source": "API-Football",
                    "name": p.get("name"),
                    "age": p.get("age"),
                    "nationality": p.get("nationality"),
                    "height": p.get("height"),
                    "weight": p.get("weight"),
                    "position": p.get("position"),
                }, indent=2)
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
