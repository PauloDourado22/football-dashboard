import os
from datetime import timedelta

from dotenv import load_dotenv
from flask import Flask, redirect, render_template, request, session, url_for
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

# Needed to sign the session cookie that stores favorites. Same "fail fast,
# no silent default" philosophy as API_KEY: a randomly-generated fallback
# would invalidate every visitor's session on every restart, which is a
# confusing way to discover you forgot to set this.
app.secret_key = os.environ.get("SECRET_KEY")
if not app.secret_key:
    raise RuntimeError(
        "SECRET_KEY is not set. Add a random string to .env — used to sign "
        "the favorites session cookie. Any long random string works, e.g. "
        "`python -c \"import secrets; print(secrets.token_hex(32))\"`."
    )

# How long to cache a successful API response, in seconds. football-data.org's
# free tier allows only 10 requests/minute; standings and fixtures don't
# change second-to-second, so a few minutes of staleness is a good trade.
# Raised from 5 to 15 minutes after hitting 429s during normal manual
# testing — a page load fires up to 4 calls, so browsing a few leagues/teams
# within a minute exhausts the free-tier budget fast without a longer cache.
# NOTE: SimpleCache is in-process memory. It resets on restart and is NOT
# shared across workers if you later run this under gunicorn -w >1 — swap
# CACHE_TYPE to "RedisCache" (with CACHE_REDIS_URL) if you scale to multiple
# workers/dynos.
CACHE_TTL = 900
cache = Cache(app, config={"CACHE_TYPE": "SimpleCache", "CACHE_DEFAULT_TIMEOUT": CACHE_TTL})

# Flask sessions are browser-session-only (wiped when the browser fully
# closes) unless marked permanent. Favorites should survive that, so every
# request gets a long-lived, signed cookie instead of a here-today-gone-
# tomorrow one.
app.permanent_session_lifetime = timedelta(days=365)


@app.before_request
def _make_session_permanent():
    session.permanent = True


def _favorite_teams():
    return session.setdefault("favorite_teams", [])


def _favorite_leagues():
    return session.setdefault("favorite_leagues", [])


def _api_headers():
    return {"X-Auth-Token": API_KEY}


@app.context_processor
def inject_sidebar_context():
    """The sidebar (leagues nav + favorite teams) renders on every page, so
    every template needs this data — including team.html and match.html,
    which never fetched it before. A context processor beats passing the
    same three kwargs from every render_template call.

    `selected_league` defaults to None here (no page-level relevance on the
    team/match pages); home() overrides it explicitly with the active league,
    and Flask always lets an explicit render_template kwarg win over a
    context processor's value for the same key.
    """
    return {
        "leagues": api.LEAGUES,
        "favorite_teams": _favorite_teams(),
        "favorite_leagues": _favorite_leagues(),
        "selected_league": None,
    }


@app.route("/", methods=["GET"])
def home():
    # GET (query string) instead of POST, so a league selection is a real,
    # shareable/bookmarkable URL and browser back/forward works as expected.
    requested_league = request.args.get("league") or "PL"  # default Premier League

    # Whitelist the league id before it ever reaches the outbound URL.
    if requested_league not in api.LEAGUES:
        requested_league = "PL"

    league_id = requested_league
    headers = _api_headers()

    def render_error(message):
        return render_template(
            "index.html",
            table=[],
            matches=[],
            results=[],
            scorers=[],
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

    # Top scorers are a "nice to have", not core to the page — if this call
    # fails (some competitions/tiers don't expose it), just show nothing
    # rather than blocking standings/fixtures behind it.
    scorers_data, scorers_error = api.fetch_json(api.scorers_url(league_id), headers, cache=cache)
    scorers = [] if scorers_error else scorers_data.get("scorers", [])

    return render_template(
        "index.html",
        table=table,
        matches=matches,
        results=results,
        scorers=scorers,
        selected_league=league_id,
        matchday=current_matchday,
        zones=api.ZONE_CONFIG.get(league_id),
        leader=table[0] if table else None,
        next_match=matches[0] if matches else None,
        error=None,
    )


@app.route("/team/<int:team_id>", methods=["GET"])
def team_profile(team_id):
    headers = _api_headers()

    team_data, error = api.fetch_json(api.team_url(team_id), headers, cache=cache)
    if error:
        return render_template("error.html", message=f"Error fetching team: {error}"), 502

    # Recent/upcoming matches are treated as optional extras for this page:
    # some free-tier plans restrict the team/matches subresource, so a
    # failure here shouldn't take down the whole profile — just that section.
    recent_data, recent_error = api.fetch_json(
        api.team_matches_url(team_id, "FINISHED"), headers, cache=cache
    )
    recent_matches = [] if recent_error else list(reversed(recent_data.get("matches", [])))[:5]

    upcoming_data, upcoming_error = api.fetch_json(
        api.team_matches_url(team_id, "SCHEDULED"), headers, cache=cache
    )
    upcoming_matches = [] if upcoming_error else upcoming_data.get("matches", [])[:5]

    squad_by_position = api.group_squad_by_position(team_data.get("squad", []))
    is_favorite = any(t["id"] == team_id for t in _favorite_teams())

    return render_template(
        "team.html",
        team=team_data,
        squad_by_position=squad_by_position,
        recent_matches=recent_matches,
        upcoming_matches=upcoming_matches,
        matches_unavailable=bool(recent_error and upcoming_error),
        is_favorite=is_favorite,
    )


@app.route("/match/<int:match_id>", methods=["GET"])
def match_detail(match_id):
    headers = _api_headers()

    h2h_data, error = api.fetch_json(api.head2head_url(match_id), headers, cache=cache)
    if error:
        return render_template("error.html", message=f"Error fetching head-to-head: {error}"), 502

    summary = api.summarize_head2head(h2h_data)

    return render_template("match.html", summary=summary)


@app.route("/favorites/team/toggle", methods=["POST"])
def toggle_favorite_team():
    team_id = int(request.form["team_id"])
    favorites = _favorite_teams()
    if any(t["id"] == team_id for t in favorites):
        favorites[:] = [t for t in favorites if t["id"] != team_id]
    else:
        favorites.append({
            "id": team_id,
            "name": request.form.get("team_name", "Unknown team"),
            "crest": request.form.get("team_crest", ""),
        })
    session.modified = True
    return redirect(request.form.get("next") or url_for("team_profile", team_id=team_id))


@app.route("/favorites/league/toggle", methods=["POST"])
def toggle_favorite_league():
    league_id = request.form["league_id"]
    favorites = _favorite_leagues()
    if league_id in favorites:
        favorites.remove(league_id)
    else:
        if league_id in api.LEAGUES:
            favorites.append(league_id)
    session.modified = True
    return redirect(request.form.get("next") or url_for("home", league=league_id))


if __name__ == "__main__":
    app.run(debug=False)
