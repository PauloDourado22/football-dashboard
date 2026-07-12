import os

from dotenv import load_dotenv
from flask import Flask, render_template, request
from flask_caching import Cache
import requests

load_dotenv()

app = Flask(__name__)

API_KEY = os.environ.get("API_KEY")
if not API_KEY:
    # Fail fast at startup rather than surfacing a confusing 401 on first request.
    raise RuntimeError(
        "API_KEY is not set. Copy .env.example to .env and add your "
        "football-data.org API key."
    )

# Timeout (seconds) for outbound API calls, so a slow/dead upstream can't
# hang the whole app (the Flask dev server is single-threaded by default).
REQUEST_TIMEOUT = 5

# How long to cache a successful API response, in seconds. football-data.org's
# free tier allows only 10 requests/minute; standings and fixtures don't
# change second-to-second, so a few minutes of staleness is a good trade.
# NOTE: SimpleCache is in-process memory. It resets on restart and is NOT
# shared across workers if you later run this under gunicorn -w >1 — swap
# CACHE_TYPE to "RedisCache" (with CACHE_REDIS_URL) if you scale to multiple
# workers/dynos.
CACHE_TTL = 300
cache = Cache(app, config={"CACHE_TYPE": "SimpleCache", "CACHE_DEFAULT_TIMEOUT": CACHE_TTL})

# Supported leagues: key = API league ID, value = readable name
LEAGUES = {
    "PL": "Premier League",
    "PD": "La Liga",
    "BL1": "Bundesliga",
    "SA": "Serie A",
    "FL1": "Ligue 1",
    "PPL": "Primeira Liga",
    "CL": "Champions League"
}

# Rough qualification/relegation zones per league, used to highlight rows in
# the standings table. These are approximations (exact spot counts shift
# season to season with playoff rules etc.) — good enough for an at-a-glance
# visual cue, not meant to be authoritative. CL has no zone highlighting: its
# 36-team league phase (top 8 through, 9-24 playoff, rest out) doesn't map
# cleanly onto "continental vs relegation" the way domestic leagues do.
ZONE_CONFIG = {
    "PL": {"continental": 4, "relegation": 3},
    "PD": {"continental": 4, "relegation": 3},
    "BL1": {"continental": 4, "relegation": 2},
    "SA": {"continental": 4, "relegation": 3},
    "FL1": {"continental": 3, "relegation": 3},
    "PPL": {"continental": 2, "relegation": 3},
}


def compute_form(team_id, finished_matches, limit=5):
    """Return the last `limit` results for a team, most recent first, as a
    list of "W"/"D"/"L". Derived from the finished-matches list we already
    fetch for the "Recent Results" section — no extra API call needed.
    """
    team_matches = [
        m for m in finished_matches
        if m.get("homeTeam", {}).get("id") == team_id
        or m.get("awayTeam", {}).get("id") == team_id
    ]
    team_matches.sort(key=lambda m: m.get("utcDate", ""))
    recent = list(reversed(team_matches[-limit:]))

    form = []
    for m in recent:
        score = m.get("score", {}).get("fullTime", {})
        home_goals, away_goals = score.get("home"), score.get("away")
        if home_goals is None or away_goals is None:
            continue  # incomplete data, skip rather than guess
        is_home = m.get("homeTeam", {}).get("id") == team_id
        team_goals = home_goals if is_home else away_goals
        opponent_goals = away_goals if is_home else home_goals
        if team_goals > opponent_goals:
            form.append("W")
        elif team_goals < opponent_goals:
            form.append("L")
        else:
            form.append("D")
    return form


def fetch_json(url, headers):
    """GET a URL (using the cache when possible) and return (data, error_message).

    Never raises. Only successful responses are cached — an error should
    never get "stuck" for the full TTL, it should retry live next request.
    """
    cached_data = cache.get(url)
    if cached_data is not None:
        return cached_data, None

    try:
        response = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
    except requests.exceptions.Timeout:
        return None, "The football data service took too long to respond. Please try again."
    except requests.exceptions.RequestException:
        return None, "Could not reach the football data service. Please try again shortly."

    if response.status_code != 200:
        return None, f"Football data service returned an error ({response.status_code})."

    data = response.json()
    cache.set(url, data)
    return data, None


@app.route("/", methods=["GET"])
def home():
    # GET (query string) instead of POST, so a league selection is a real,
    # shareable/bookmarkable URL and browser back/forward works as expected.
    requested_league = request.args.get("league") or "PL"  # default Premier League

    # Whitelist the league id before it ever reaches the outbound URL.
    if requested_league not in LEAGUES:
        requested_league = "PL"

    league_id = requested_league
    headers = {"X-Auth-Token": API_KEY}

    def render_error(message):
        return render_template(
            "index.html",
            table=[],
            matches=[],
            results=[],
            leagues=LEAGUES,
            selected_league=league_id,
            matchday=None,
            zones=ZONE_CONFIG.get(league_id),
            leader=None,
            next_match=None,
            error=message,
        ), 502

    # Fetch standings
    standings_url = f"https://api.football-data.org/v4/competitions/{league_id}/standings"
    standings_data, error = fetch_json(standings_url, headers)
    if error:
        return render_error(f"Error fetching standings: {error}")

    standings_list = standings_data.get("standings", [])
    if not standings_list:
        return render_error("No standings are available for this competition right now.")
    table = standings_list[0].get("table", [])

    # Get current matchday from competition data
    competition_info = standings_data.get("competition", {})
    current_matchday = competition_info.get("currentSeason", {}).get("currentMatchday", 1)

    # Fetch upcoming (scheduled) matches
    matches_url = f"https://api.football-data.org/v4/competitions/{league_id}/matches?status=SCHEDULED"
    matches_data, error = fetch_json(matches_url, headers)
    if error:
        return render_error(f"Error fetching matches: {error}")

    matches = matches_data.get("matches", [])[:5]

    # Fetch recent (finished) matches. The API returns these in ascending
    # date order, so reverse to show most-recent-first and take the last 5.
    results_url = f"https://api.football-data.org/v4/competitions/{league_id}/matches?status=FINISHED"
    results_data, error = fetch_json(results_url, headers)
    if error:
        return render_error(f"Error fetching recent results: {error}")

    finished_matches = results_data.get("matches", [])
    results = list(reversed(finished_matches))[:5]

    # Attach recent form to each standings row. Doesn't require a new API
    # call — it's derived from the finished-matches list fetched above.
    for team in table:
        team["form"] = compute_form(team["team"]["id"], finished_matches)

    return render_template(
        "index.html",
        table=table,
        matches=matches,
        results=results,
        leagues=LEAGUES,
        selected_league=league_id,
        matchday=current_matchday,
        zones=ZONE_CONFIG.get(league_id),
        leader=table[0] if table else None,
        next_match=matches[0] if matches else None,
        error=None,
    )


if __name__ == "__main__":
    app.run(debug=False)
