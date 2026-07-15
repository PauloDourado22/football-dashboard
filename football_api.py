"""Pure, Flask-independent helpers for talking to football-data.org and
shaping its responses.

Kept separate from app.py so this logic can be unit tested without spinning
up a Flask app, a cache, or a real network call.
"""

import requests

REQUEST_TIMEOUT = 5  # seconds. Prevents a slow/dead upstream from hanging
                      # the whole app (the Flask dev server is single-threaded
                      # by default).

# Supported leagues: key = API league ID, value = readable name
LEAGUES = {
    "PL": "Premier League",
    "PD": "La Liga",
    "BL1": "Bundesliga",
    "SA": "Serie A",
    "FL1": "Ligue 1",
    "PPL": "Primeira Liga",
    "CL": "Champions League",
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


def standings_url(league_id):
    return f"https://api.football-data.org/v4/competitions/{league_id}/standings"


def matches_url(league_id, status):
    return f"https://api.football-data.org/v4/competitions/{league_id}/matches?status={status}"


def scorers_url(league_id):
    return f"https://api.football-data.org/v4/competitions/{league_id}/scorers?limit=10"


def team_url(team_id):
    return f"https://api.football-data.org/v4/teams/{team_id}"


def team_matches_url(team_id, status):
    return f"https://api.football-data.org/v4/teams/{team_id}/matches?status={status}&limit=5"


def head2head_url(match_id):
    return f"https://api.football-data.org/v4/matches/{match_id}/head2head?limit=10"


def fetch_json(url, headers, cache=None):
    """GET a URL (using `cache` when available) and return (data, error_message).

    Never raises. Only successful responses are cached — an error should
    never get "stuck" for the full TTL, it should retry live next request.

    `cache` is any object exposing .get(key) / .set(key, value), such as a
    Flask-Caching Cache instance. Pass None to always fetch live, which is
    what keeps this function testable without a Flask app context.
    """
    if cache is not None:
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
    if cache is not None:
        cache.set(url, data)
    return data, None


# Squad entries use these position labels (distinct from the scorer/person
# position vocabulary, e.g. "Attacker" — the API isn't consistent about this
# between resources). Anything not in this list is grouped under "Other"
# rather than dropped, since free-tier data occasionally omits/renames a
# position label.
SQUAD_POSITION_ORDER = ["Goalkeeper", "Defence", "Midfield", "Offence"]


def group_squad_by_position(squad):
    """Group a team's squad list into (position, [players]) tuples, ordered
    goalkeepers-first the way a matchday program would list them. Any
    position not in SQUAD_POSITION_ORDER is bucketed under "Other" at the end
    rather than silently dropped.
    """
    groups = {position: [] for position in SQUAD_POSITION_ORDER}
    other = []
    for player in squad:
        position = player.get("position")
        if position in groups:
            groups[position].append(player)
        else:
            other.append(player)

    ordered = [(position, players) for position, players in groups.items() if players]
    if other:
        ordered.append(("Other", other))
    return ordered


def summarize_head2head(h2h_data):
    """Pull out the bits of a /matches/{id}/head2head response the template
    needs, with safe defaults everywhere.

    Kept as its own function (rather than reading nested dicts in the
    template) because this endpoint's shape isn't as thoroughly documented
    as standings/scorers — better to have one place that tolerates a missing
    or renamed field than scattered `.get()` chains across the template.
    """
    aggregates = h2h_data.get("aggregates", {})
    return {
        "number_of_matches": aggregates.get("numberOfMatches", 0),
        "total_goals": aggregates.get("totalGoals", 0),
        "home_team": aggregates.get("homeTeam", {}),
        "away_team": aggregates.get("awayTeam", {}),
        "matches": h2h_data.get("matches", []),
    }


def compute_form(team_id, finished_matches, limit=5):
    """Return the last `limit` results for a team, most recent first, as a
    list of "W"/"D"/"L". Derived from a finished-matches list the caller
    already has — no extra API call needed.
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
