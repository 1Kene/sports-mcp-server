"""
Sports Analysis MCP Server v4 - Now with soccerdata (fbref) for deep analysis
APIs in fallback order:
  1. football-data.org   (primary for standings/fixtures - reliable, fast)
  2. fbref via soccerdata (deep stats, xG, goal logs, hundreds of leagues)
  3. API-Football        (if user has key)
  4. OpenLigaDB / balldontlie / TheSportsDB (free fallbacks)
"""
import asyncio
import httpx
import os
import json
import uvicorn
import time
import tempfile
from pathlib import Path
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

mcp = FastMCP(
    "Sports Analysis Server",
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)

# ── Keys & endpoints ──────────────────────────────────────────────────────────
FD_KEY = os.getenv("FOOTBALL_DATA_KEY", "")
API_FOOTBALL_KEY = os.getenv("API_FOOTBALL_KEY", "")

FD_BASE  = "https://api.football-data.org/v4"
AF_BASE  = "https://v3.football.api-sports.io"
SDB_BASE = "https://www.thesportsdb.com/api/v1/json/3"
OL_BASE  = "https://api.openligadb.de"
BDL_BASE = "https://api.balldontlie.io/v1"

FD_HEADERS = {"X-Auth-Token": FD_KEY} if FD_KEY else {}
AF_HEADERS = {"x-apisports-key": API_FOOTBALL_KEY} if API_FOOTBALL_KEY else {}

# soccerdata cache directory - use /tmp on Render (writable, but ephemeral)
SOCCERDATA_DIR = Path(tempfile.gettempdir()) / "soccerdata"
SOCCERDATA_DIR.mkdir(parents=True, exist_ok=True)
os.environ["SOCCERDATA_DIR"] = str(SOCCERDATA_DIR)

# football-data.org competition codes
FD_LEAGUE_CODES = {
    "premier league": "PL", "epl": "PL", "english premier league": "PL",
    "la liga": "PD", "primera division": "PD",
    "serie a": "SA", "italian serie a": "SA",
    "bundesliga": "BL1",
    "ligue 1": "FL1",
    "champions league": "CL", "ucl": "CL",
    "championship": "ELC",
    "eredivisie": "DED",
    "primeira liga": "PPL",
    "world cup": "WC",
    "european championship": "EC", "euro": "EC",
    "brasileirao": "BSA",
}

# soccerdata league name mapping
SD_LEAGUES = {
    "premier league": "ENG-Premier League",
    "epl": "ENG-Premier League",
    "championship": "ENG-Championship",
    "la liga": "ESP-La Liga",
    "la liga 2": "ESP-La Liga 2",
    "serie a": "ITA-Serie A",
    "serie b": "ITA-Serie B",
    "bundesliga": "GER-Bundesliga",
    "bundesliga 2": "GER-2. Bundesliga",
    "ligue 1": "FRA-Ligue 1",
    "ligue 2": "FRA-Ligue 2",
    "eredivisie": "NED-Eredivisie",
    "primeira liga": "POR-Primeira Liga",
    "champions league": "INT-Champions League",
    "europa league": "INT-Europa League",
    "big5": "Big 5 European Leagues Combined",
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


def sd_league_name(league_name: str):
    return SD_LEAGUES.get(league_name.lower())


# ─── Soccerdata wrapper (sync, run in executor) ───────────────────────────────
# soccerdata is sync - we wrap it so it doesn't block the event loop.

def _sd_get_fbref(league_sd: str, season: str = "2024-2025"):
    """Lazy import + instantiate FBref scraper. Returns instance or None."""
    try:
        import soccerdata as sd
        return sd.FBref(leagues=league_sd, seasons=season, no_cache=False)
    except Exception as e:
        return {"_error": str(e)}


async def sd_run(func, *args, **kwargs):
    """Run a blocking soccerdata call in a worker thread."""
    return await asyncio.to_thread(func, *args, **kwargs)


# ═════════════════════════════════════════════════════════════════════════════
#  FOOTBALL — basic (football-data.org primary)
# ═════════════════════════════════════════════════════════════════════════════

@mcp.tool()
async def search_team(team_name: str) -> str:
    """Search for a football/soccer team. Tries football-data.org → API-Football → TheSportsDB."""
    async with httpx.AsyncClient() as client:
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
                    return json.dumps({
                        "source": "football-data.org",
                        "id": t.get("id"),
                        "name": t.get("name"),
                        "short_name": t.get("shortName"),
                        "tla": t.get("tla"),
                        "country": t.get("area", {}).get("name"),
                        "founded": t.get("founded"),
                        "venue": t.get("venue"),
                        "club_colors": t.get("clubColors"),
                    }, indent=2)
        # TheSportsDB fallback
        data = await safe_get(client, f"{SDB_BASE}/searchteams.php", params={"t": team_name})
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
    """Get a football team's last matches."""
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
                    matches = await safe_get(
                        client, f"{FD_BASE}/teams/{tm['id']}/matches",
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
        # TheSportsDB fallback
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
        # TheSportsDB fallback
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
    """Get standings for a league. Premier League, La Liga, Serie A, Bundesliga, Ligue 1, Champions League, Championship, Eredivisie, Primeira Liga, Brasileirao, World Cup, Euro."""
    league_lower = league_name.lower()
    if "bundesliga" in league_lower and "2" not in league_lower:
        async with httpx.AsyncClient() as client:
            data = await safe_get(client, f"{OL_BASE}/getbltable/bl1/2024")
            if data:
                rows = []
                for i, t in enumerate(data[:18], 1):
                    rows.append({"pos": i, "team": t.get("teamName"),
                                 "P": t.get("matches"), "W": t.get("won"),
                                 "D": t.get("draw"), "L": t.get("lost"),
                                 "GD": t.get("goalDiff"), "Pts": t.get("points")})
                return json.dumps({"source": "OpenLigaDB", "league": "Bundesliga",
                                   "table": rows}, indent=2)
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
                            "P": t.get("playedGames"), "W": t.get("won"),
                            "D": t.get("draw"), "L": t.get("lost"),
                            "GF": t.get("goalsFor"), "GA": t.get("goalsAgainst"),
                            "GD": t.get("goalDifference"), "Pts": t.get("points"),
                            "form": t.get("form"),
                        })
                    return json.dumps({
                        "source": "football-data.org",
                        "league": data.get("competition", {}).get("name"),
                        "matchday": data.get("season", {}).get("currentMatchday"),
                        "table": rows
                    }, indent=2)
    return f"Standings for '{league_name}' unavailable."


@mcp.tool()
async def get_top_scorers(league_name: str = "Premier League") -> str:
    """Get top scorers in a league."""
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
                    return json.dumps({"source": "football-data.org",
                                       "league": data.get("competition", {}).get("name"),
                                       "scorers": scorers}, indent=2)
    return "Top scorers unavailable."


# ═════════════════════════════════════════════════════════════════════════════
#  FBREF DEEP STATS via soccerdata
# ═════════════════════════════════════════════════════════════════════════════

@mcp.tool()
async def fbref_team_season_stats(league_name: str = "Premier League",
                                   season: str = "2024-2025",
                                   stat_type: str = "standard") -> str:
    """
    Get advanced fbref team season stats: xG, possession, pressing intensity, etc.
    Covers: Premier League, La Liga, Serie A, Bundesliga, Ligue 1, Eredivisie,
            Primeira Liga, Championship, La Liga 2, Serie B, Ligue 2, 2. Bundesliga,
            Big 5 Combined, and many more.
    stat_type options: standard, keeper, keeper_adv, shooting, passing, passing_types,
                       goal_shot_creation, defense, possession, playing_time, misc.
    """
    sd_name = sd_league_name(league_name)
    if not sd_name:
        return (f"League '{league_name}' not mapped. Try: Premier League, La Liga, Serie A, "
                f"Bundesliga, Ligue 1, Eredivisie, Primeira Liga, Championship, La Liga 2, "
                f"Serie B, Ligue 2, 2. Bundesliga, Champions League, Europa League, big5.")

    def _fetch():
        try:
            import soccerdata as sd
            fbref = sd.FBref(leagues=sd_name, seasons=season)
            df = fbref.read_team_season_stats(stat_type=stat_type)
            df = df.reset_index()
            return df.to_dict(orient="records")
        except Exception as e:
            return {"_error": str(e)}

    result = await sd_run(_fetch)
    if isinstance(result, dict) and "_error" in result:
        return f"fbref fetch failed: {result['_error']}. (rate limit or Cloudflare blocked)"
    if not result:
        return "No stats found."

    # Trim noisy columns; keep top 20 teams to stay under MCP response size
    cleaned = []
    for row in result[:25]:
        cleaned.append({k: (v if not isinstance(v, float) or v == v else None)
                        for k, v in row.items()
                        if not (isinstance(v, str) and len(v) > 200)})
    return json.dumps({
        "source": "fbref via soccerdata",
        "league": sd_name,
        "season": season,
        "stat_type": stat_type,
        "teams": cleaned,
    }, indent=2, default=str)


@mcp.tool()
async def fbref_player_season_stats(league_name: str = "Premier League",
                                     season: str = "2024-2025",
                                     stat_type: str = "standard",
                                     top_n: int = 20) -> str:
    """
    Get top players by stat from fbref for a league/season.
    stat_type options: standard, shooting, passing, passing_types, goal_shot_creation,
                       defense, possession, playing_time, misc, keeper, keeper_adv.
    Returns top N players sorted by goals (or relevant stat for type).
    """
    sd_name = sd_league_name(league_name)
    if not sd_name:
        return f"League '{league_name}' not mapped."

    def _fetch():
        try:
            import soccerdata as sd
            fbref = sd.FBref(leagues=sd_name, seasons=season)
            df = fbref.read_player_season_stats(stat_type=stat_type)
            df = df.reset_index()
            # Sort by goals if available
            sort_col = None
            for cand in [("Performance", "Gls"), ("performance", "goals"), "goals", "Gls"]:
                if cand in df.columns:
                    sort_col = cand
                    break
            if sort_col is not None:
                df = df.sort_values(by=sort_col, ascending=False)
            return df.head(top_n).to_dict(orient="records")
        except Exception as e:
            return {"_error": str(e)}

    result = await sd_run(_fetch)
    if isinstance(result, dict) and "_error" in result:
        return f"fbref fetch failed: {result['_error']}"
    if not result:
        return "No data."

    cleaned = []
    for row in result:
        cleaned.append({str(k): v for k, v in row.items()
                        if not (isinstance(v, str) and len(v) > 200)})
    return json.dumps({
        "source": "fbref via soccerdata",
        "league": sd_name,
        "season": season,
        "stat_type": stat_type,
        "players": cleaned,
    }, indent=2, default=str)


@mcp.tool()
async def fbref_match_events(league_name: str = "Premier League",
                              season: str = "2024-2025",
                              team_name: str = "",
                              last_n: int = 5) -> str:
    """
    Get match events (goals, cards, subs) with MINUTES for a team's recent matches.
    THIS is the data needed for 'goals in a row' / scoring patterns analysis.
    Heavy on rate limits — use sparingly. Returns last_n matches.
    """
    sd_name = sd_league_name(league_name)
    if not sd_name:
        return f"League '{league_name}' not mapped."
    if not team_name:
        return "Provide team_name to limit fbref scraping (rate-limited)."

    def _fetch():
        try:
            import soccerdata as sd
            fbref = sd.FBref(leagues=sd_name, seasons=season)
            schedule = fbref.read_schedule()
            schedule = schedule.reset_index()
            # filter to team
            tn = team_name.lower()
            mask = (schedule["home_team"].astype(str).str.lower().str.contains(tn) |
                    schedule["away_team"].astype(str).str.lower().str.contains(tn))
            tm_matches = schedule[mask]
            if tm_matches.empty:
                return {"_error": f"No matches found for '{team_name}' in {sd_name}."}
            # Take only matches that are FINISHED, descending by date
            if "score" in tm_matches.columns:
                tm_matches = tm_matches[tm_matches["score"].notna()]
            tm_matches = tm_matches.sort_values(by="date", ascending=False).head(last_n)
            game_ids = tm_matches["game_id"].tolist() if "game_id" in tm_matches.columns else None
            events = fbref.read_events(match_id=game_ids) if game_ids else fbref.read_events()
            events = events.reset_index()
            return events.to_dict(orient="records")
        except Exception as e:
            return {"_error": str(e)}

    result = await sd_run(_fetch)
    if isinstance(result, dict) and "_error" in result:
        return f"fbref events fetch failed: {result['_error']}"
    if not result:
        return "No events found."

    cleaned = []
    for row in result[:200]:
        cleaned.append({str(k): v for k, v in row.items()
                        if not (isinstance(v, str) and len(v) > 200)})
    return json.dumps({
        "source": "fbref via soccerdata",
        "league": sd_name,
        "team": team_name,
        "events": cleaned,
    }, indent=2, default=str)


@mcp.tool()
async def fbref_schedule(league_name: str = "Premier League",
                          season: str = "2024-2025") -> str:
    """Get the full season schedule from fbref including dates, teams, scores."""
    sd_name = sd_league_name(league_name)
    if not sd_name:
        return f"League '{league_name}' not mapped."

    def _fetch():
        try:
            import soccerdata as sd
            fbref = sd.FBref(leagues=sd_name, seasons=season)
            df = fbref.read_schedule()
            df = df.reset_index()
            return df.to_dict(orient="records")
        except Exception as e:
            return {"_error": str(e)}

    result = await sd_run(_fetch)
    if isinstance(result, dict) and "_error" in result:
        return f"fbref schedule fetch failed: {result['_error']}"

    cleaned = [{str(k): v for k, v in row.items()} for row in result[:50]]
    return json.dumps({
        "source": "fbref via soccerdata",
        "league": sd_name,
        "season": season,
        "matches": cleaned,
    }, indent=2, default=str)


@mcp.tool()
async def fbref_supported_leagues() -> str:
    """List all leagues supported by soccerdata/fbref. Use these names with the fbref_* tools."""
    return json.dumps({
        "supported_leagues": list(SD_LEAGUES.keys()),
        "note": "soccerdata supports many more — these are the curated mappings. "
                "Pass season as 'YYYY-YYYY' format e.g. '2024-2025'.",
    }, indent=2)


# ═════════════════════════════════════════════════════════════════════════════
#  HEAD TO HEAD / TEAM STATS (football-data.org)
# ═════════════════════════════════════════════════════════════════════════════

@mcp.tool()
async def get_head_to_head(team1: str, team2: str) -> str:
    """Get head-to-head record between two football teams."""
    if not FD_KEY:
        return "Add FOOTBALL_DATA_KEY env var on Render."
    async with httpx.AsyncClient() as client:
        teams = await safe_get(client, f"{FD_BASE}/teams",
                               headers=FD_HEADERS, params={"limit": 500})
        if not teams or not teams.get("teams"):
            return "Could not fetch teams list."
        q1, q2 = team1.lower(), team2.lower()
        t1 = next((t for t in teams["teams"]
                   if q1 in (t.get("name") or "").lower()
                   or q1 in (t.get("shortName") or "").lower()), None)
        t2 = next((t for t in teams["teams"]
                   if q2 in (t.get("name") or "").lower()
                   or q2 in (t.get("shortName") or "").lower()), None)
        if not t1 or not t2:
            return "One or both teams not found."
        matches = await safe_get(client, f"{FD_BASE}/teams/{t1['id']}/matches",
                                 headers=FD_HEADERS,
                                 params={"status": "FINISHED", "limit": 100})
        if not matches or not matches.get("matches"):
            return "No data."
        h2h = []
        for m in matches["matches"]:
            if t2["id"] in (m.get("homeTeam", {}).get("id"),
                            m.get("awayTeam", {}).get("id")):
                score = m.get("score", {}).get("fullTime", {})
                h2h.append({
                    "date": (m.get("utcDate") or "")[:10],
                    "competition": m.get("competition", {}).get("name"),
                    "home": m.get("homeTeam", {}).get("name"),
                    "away": m.get("awayTeam", {}).get("name"),
                    "score": f"{score.get('home')} - {score.get('away')}",
                    "winner": m.get("score", {}).get("winner"),
                })
        if not h2h:
            return "No matchups found."
        return json.dumps({"source": "football-data.org",
                           "matchups": h2h[:10],
                           "total": len(h2h)}, indent=2)


@mcp.tool()
async def get_team_statistics(team_name: str, league: str = "Premier League") -> str:
    """Get computed team stats: position, win rate, goals/game, points/game, form."""
    if not FD_KEY:
        return "Add FOOTBALL_DATA_KEY env var on Render."
    async with httpx.AsyncClient() as client:
        code = fd_competition_code(league)
        if not code:
            return f"League '{league}' not mapped."
        data = await safe_get(client, f"{FD_BASE}/competitions/{code}/standings",
                              headers=FD_HEADERS)
        if not data or not data.get("standings"):
            return "No data."
        table = next((s for s in data["standings"] if s.get("type") == "TOTAL"),
                     data["standings"][0]).get("table", [])
        q = team_name.lower()
        row = next((r for r in table
                    if q in (r.get("team", {}).get("name") or "").lower()
                    or q in (r.get("team", {}).get("shortName") or "").lower()), None)
        if not row:
            return f"'{team_name}' not found in {league}."
        played = row.get("playedGames", 0) or 0
        won = row.get("won", 0) or 0
        return json.dumps({
            "source": "football-data.org",
            "team": row.get("team", {}).get("name"),
            "league": data.get("competition", {}).get("name"),
            "position": row.get("position"),
            "played": played, "won": won,
            "drawn": row.get("draw"), "lost": row.get("lost"),
            "win_rate_pct": round(won / played * 100, 1) if played else 0,
            "goals_for": row.get("goalsFor"),
            "goals_against": row.get("goalsAgainst"),
            "goal_difference": row.get("goalDifference"),
            "goals_per_game": round((row.get("goalsFor") or 0) / played, 2) if played else 0,
            "goals_conceded_per_game": round((row.get("goalsAgainst") or 0) / played, 2) if played else 0,
            "points": row.get("points"),
            "points_per_game": round((row.get("points") or 0) / played, 2) if played else 0,
            "form_last_5": row.get("form"),
        }, indent=2)


# ═════════════════════════════════════════════════════════════════════════════
#  BASKETBALL (NBA via balldontlie)
# ═════════════════════════════════════════════════════════════════════════════

@mcp.tool()
async def search_basketball_team(team_name: str) -> str:
    """Search for an NBA team using balldontlie (free, no key needed)."""
    async with httpx.AsyncClient() as client:
        data = await safe_get(client, f"{BDL_BASE}/teams")
        if not data or not data.get("data"):
            return "NBA data unavailable right now."
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
                team_id, team_full = t.get("id"), t.get("full_name")
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
#  PLAYERS / TENNIS / CRICKET
# ═════════════════════════════════════════════════════════════════════════════

@mcp.tool()
async def search_player(player_name: str) -> str:
    """Search for a player across all sports."""
    async with httpx.AsyncClient() as client:
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
