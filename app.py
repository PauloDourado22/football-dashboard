import os

from dotenv import load_dotenv
from flask import Flask, render_template, request
from flask_caching import Cache

import football_api as api

load_dotenv()

app = Flask(__name__)

API_KEY = os.environ.get("API_KEY")
if not API_KEY:
    # Fail fast at startup rather than surfacing a confusing 401 on first request.
    raise RuntimeError(
        "API_KEY is not set. Copy .env.example to .env and add your "
        "football-data.org API key."
    )

# How long to cache a successful API response, in seconds. football-data.org's
# free tier allows only 10 requests/minute; standings and fixtures don't
# change second-to-second, so a few minutes of staleness is a good trade.
# NOTE: SimpleCache is in-process memory. It resets on restart and is NOT
# shared across workers if you later run this under gunicorn -w >1 — swap
# CACHE_TYPE to "RedisCache" (with CACHE_REDIS_URL) if you scale to multiple
# workers/dynos.
CACHE_TTL = 300
cache = Cache(app, config={"CACHE_TYPE": "SimpleCache", "CACHE_DEFAULT_TIMEOUT": CACHE_TTL})


@app.route("/", methods=["GET"])
def home():
    # GET (query string) instead of POST, so a league selection is a real,
    # shareable/bookmarkable URL and browser back/forward works as expected.
    requested_league = request.args.get("league") or "PL"  # default Premier League

    # Whitelist the league id before it ever reaches the outbound URL.
    if requested_league not in api.LEAGUES:
        requested_league = "PL"

    league_id = requested_league
    headers = {"X-Auth-Token": API_KEY}

    def render_error(message):
        return render_template(
            "index.html",
            table=[],
            matches=[],
            results=[],
            leagues=api.LEAGUES,
            selected_league=league_id,
            matchday=None,
            zones=api.ZONE_CONFIG.get(league_id),
            leader=None,
            next_match=None,
            error=message,
        ), 502

    # Fetch standings
    standings_data, error = api.fetch_json(api.standings_url(league_id), headers, cache=cache)
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
    matches_data, error = api.fetch_json(api.matches_url(league_id, "SCHEDULED"), headers, cache=cache)
    if error:
        return render_error(f"Error fetching matches: {error}")

    matches = matches_data.get("matches", [])[:5]

    # Fetch recent (finished) matches. The API returns these in ascending
    # date order, so reverse to show most-recent-first and take the last 5.
    results_data, error = api.fetch_json(api.matches_url(league_id, "FINISHED"), headers, cache=cache)
    if error:
        return render_error(f"Error fetching recent results: {error}")

    finished_matches = results_data.get("matches", [])
    results = list(reversed(finished_matches))[:5]

    # Attach recent form to each standings row. Doesn't require a new API
    # call — it's derived from the finished-matches list fetched above.
    for team in table:
        team["form"] = api.compute_form(team["team"]["id"], finished_matches)

    return render_template(
        "index.html",
        table=table,
        matches=matches,
        results=results,
        leagues=api.LEAGUES,
        selected_league=league_id,
        matchday=current_matchday,
        zones=api.ZONE_CONFIG.get(league_id),
        leader=table[0] if table else None,
        next_match=matches[0] if matches else None,
        error=None,
    )


if __name__ == "__main__":
    app.run(debug=False)
