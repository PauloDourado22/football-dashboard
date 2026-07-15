"""Integration tests for the Flask route, using the test client.

These patch football_api.requests.get (not app.requests.get) because app.py
delegates all HTTP calls to football_api.fetch_json.
"""

from unittest.mock import Mock, patch

import requests
from bs4 import BeautifulSoup


def make_team(pos, tid, name):
    return {
        "position": pos,
        "team": {"id": tid, "name": name, "crest": ""},
        "playedGames": 10,
        "won": 5,
        "draw": 2,
        "lost": 3,
        "points": 17,
    }


def make_match(date, home_id, home_name, away_id, away_name, hg=None, ag=None, match_id=1):
    return {
        "id": match_id,
        "utcDate": date,
        "homeTeam": {"id": home_id, "name": home_name, "crest": ""},
        "awayTeam": {"id": away_id, "name": away_name, "crest": ""},
        "score": {"fullTime": {"home": hg, "away": ag}},
    }


def make_scorer(player_id, name, team_id, team_name, goals, assists=0):
    return {
        "player": {"id": player_id, "name": name},
        "team": {"id": team_id, "name": team_name, "crest": ""},
        "goals": goals,
        "assists": assists,
    }


def fake_get_factory(finished=None, scheduled=None, table_size=20, scorers=None):
    finished = finished if finished is not None else []
    scheduled = (
        scheduled
        if scheduled is not None
        else [make_match("2026-07-20T15:00:00Z", 5, "Team 5", 6, "Team 6")]
    )
    scorers = scorers if scorers is not None else []

    def fake_get(url, headers=None, timeout=None):
        response = Mock(status_code=200)
        if "standings" in url:
            table = [make_team(i, i, f"Team {i}") for i in range(1, table_size + 1)]
            response.json.return_value = {
                "standings": [{"table": table}],
                "competition": {"currentSeason": {"currentMatchday": 10}},
            }
        elif "scorers" in url:
            response.json.return_value = {"scorers": scorers}
        elif "FINISHED" in url:
            response.json.return_value = {"matches": finished}
        else:
            response.json.return_value = {"matches": scheduled}
        return response

    return fake_get


def test_happy_path_renders_standings(client):
    with patch("football_api.requests.get", side_effect=fake_get_factory()):
        response = client.get("/?league=PL")
    assert response.status_code == 200
    assert b"Team 1" in response.data


def test_get_query_string_selects_league(client):
    with patch("football_api.requests.get", side_effect=fake_get_factory()):
        response = client.get("/?league=PD")
    assert response.status_code == 200
    assert b'value="PD" selected' in response.data


def test_invalid_league_falls_back_to_pl(client):
    with patch("football_api.requests.get", side_effect=fake_get_factory()):
        response = client.get("/?league=NOT_REAL")
    assert response.status_code == 200
    assert b'value="PL" selected' in response.data


def test_timeout_returns_502_with_error_banner(client):
    def timeout_get(*args, **kwargs):
        raise requests.exceptions.Timeout()

    with patch("football_api.requests.get", side_effect=timeout_get):
        response = client.get("/")
    assert response.status_code == 502
    assert b"took too long to respond" in response.data


def test_empty_standings_list_handled(client):
    def empty_get(url, headers=None, timeout=None):
        response = Mock(status_code=200)
        if "standings" in url:
            response.json.return_value = {"standings": [], "competition": {}}
        else:
            response.json.return_value = {"matches": []}
        return response

    with patch("football_api.requests.get", side_effect=empty_get):
        response = client.get("/")
    assert response.status_code == 502
    assert b"No standings are available" in response.data


def test_zone_highlighting_applied_for_domestic_league(client):
    with patch("football_api.requests.get", side_effect=fake_get_factory(table_size=20)):
        response = client.get("/?league=PD")
    html = response.data.decode()
    assert "zone-continental" in html
    assert "zone-relegation" in html


def test_champions_league_has_no_zone_highlighting(client):
    with patch("football_api.requests.get", side_effect=fake_get_factory(table_size=20)):
        response = client.get("/?league=CL")
    html = response.data.decode()
    assert "zone-legend" not in html


def test_stat_cards_render_leader_and_next_kickoff(client):
    with patch("football_api.requests.get", side_effect=fake_get_factory()):
        response = client.get("/")
    html = response.data.decode()
    assert "League leader" in html
    assert "Next kickoff" in html


def test_form_dots_render(client):
    finished = [
        make_match("2026-06-01T15:00:00Z", 1, "Team 1", 2, "Team 2", 3, 1),
        make_match("2026-06-08T15:00:00Z", 3, "Team 3", 1, "Team 1", 2, 2),
    ]
    with patch("football_api.requests.get", side_effect=fake_get_factory(finished=finished)):
        response = client.get("/")
    html = response.data.decode()
    assert 'class="form-dot w">W' in html
    assert 'class="form-dot d">D' in html


def test_caching_avoids_duplicate_live_calls_for_same_league(client):
    calls = {"n": 0}
    base_fake = fake_get_factory()

    def counting_get(*args, **kwargs):
        calls["n"] += 1
        return base_fake(*args, **kwargs)

    with patch("football_api.requests.get", side_effect=counting_get):
        client.get("/?league=PL")
        client.get("/?league=PL")

    assert calls["n"] == 4  # standings + scheduled + finished + scorers, fetched once


def test_markup_parses_and_has_expected_row_count(client):
    with patch("football_api.requests.get", side_effect=fake_get_factory(table_size=20)):
        response = client.get("/")
    soup = BeautifulSoup(response.data, "html.parser")
    rows = soup.select("table.standings tbody tr")
    assert len(rows) == 20


def test_scorers_table_renders_when_available(client):
    scorers = [make_scorer(1, "Top Scorer", 1, "Team 1", 20, 5)]
    with patch("football_api.requests.get", side_effect=fake_get_factory(scorers=scorers)):
        response = client.get("/")
    html = response.data.decode()
    assert "Top Scorer" in html
    assert "Top Scorers" in html


def test_scorers_section_omitted_when_unavailable(client):
    with patch("football_api.requests.get", side_effect=fake_get_factory(scorers=[])):
        response = client.get("/")
    html = response.data.decode()
    # Check for the actual heading/table, not the HTML comment above the
    # section — the comment text itself contains "Top Scorers" regardless
    # of whether the {% if scorers %} block rendered.
    assert "<h2>Top Scorers</h2>" not in html
    assert 'table class="scorers"' not in html


def test_standings_team_names_link_to_team_profile(client):
    with patch("football_api.requests.get", side_effect=fake_get_factory(table_size=5)):
        response = client.get("/")
    html = response.data.decode()
    assert '/team/1"' in html


# --- Team profile page ---

def make_team_detail(team_id, name, crest="", squad=None):
    return {
        "id": team_id,
        "name": name,
        "crest": crest,
        "venue": "Test Stadium",
        "founded": 1900,
        "squad": squad if squad is not None else [],
    }


def test_team_profile_renders_squad_grouped_by_position(client):
    team_data = make_team_detail(66, "Test United", squad=[
        {"name": "Keeper Kim", "position": "Goalkeeper", "shirtNumber": 1, "nationality": "England"},
        {"name": "Striker Sam", "position": "Offence", "shirtNumber": 9, "nationality": "Brazil"},
    ])

    def fake_get(url, headers=None, timeout=None):
        response = Mock(status_code=200)
        if url.endswith("/teams/66"):
            response.json.return_value = team_data
        else:
            response.json.return_value = {"matches": []}
        return response

    with patch("football_api.requests.get", side_effect=fake_get):
        response = client.get("/team/66")

    assert response.status_code == 200
    html = response.data.decode()
    assert "Test United" in html
    assert "Keeper Kim" in html
    assert "Goalkeeper" in html


def test_team_profile_degrades_gracefully_when_matches_unavailable(client):
    team_data = make_team_detail(66, "Test United")

    def fake_get(url, headers=None, timeout=None):
        if url.endswith("/teams/66"):
            response = Mock(status_code=200)
            response.json.return_value = team_data
            return response
        return Mock(status_code=403)  # simulate a tier-restricted subresource

    with patch("football_api.requests.get", side_effect=fake_get):
        response = client.get("/team/66")

    assert response.status_code == 200
    html = response.data.decode()
    assert "isn't available" in html


def test_team_profile_returns_502_when_team_fetch_fails(client):
    def timeout_get(*args, **kwargs):
        raise requests.exceptions.Timeout()

    with patch("football_api.requests.get", side_effect=timeout_get):
        response = client.get("/team/66")
    assert response.status_code == 502


# --- Match head-to-head page ---

def test_match_detail_renders_head_to_head_summary(client):
    h2h_data = {
        "aggregates": {
            "numberOfMatches": 3,
            "totalGoals": 7,
            "homeTeam": {"name": "Team 1", "wins": 2, "draws": 0, "losses": 1},
            "awayTeam": {"name": "Team 2", "wins": 1, "draws": 0, "losses": 2},
        },
        "matches": [make_match("2025-01-01T15:00:00Z", 1, "Team 1", 2, "Team 2", 2, 1)],
    }

    def fake_get(url, headers=None, timeout=None):
        response = Mock(status_code=200)
        response.json.return_value = h2h_data
        return response

    with patch("football_api.requests.get", side_effect=fake_get):
        response = client.get("/match/999")

    assert response.status_code == 200
    html = response.data.decode()
    assert "Team 1" in html
    assert "Team 2" in html


def test_match_detail_returns_502_on_error(client):
    def timeout_get(*args, **kwargs):
        raise requests.exceptions.Timeout()

    with patch("football_api.requests.get", side_effect=timeout_get):
        response = client.get("/match/999")
    assert response.status_code == 502


# --- Favorites ---

def test_toggle_favorite_team_adds_and_removes(client):
    with patch("football_api.requests.get", side_effect=fake_get_factory()):
        # Add
        response = client.post(
            "/favorites/team/toggle",
            data={"team_id": "66", "team_name": "Test United", "team_crest": "", "next": "/"},
        )
        assert response.status_code == 302
        home_response = client.get("/")
        assert "Test United" in home_response.data.decode()

        # Remove (toggling again)
        client.post(
            "/favorites/team/toggle",
            data={"team_id": "66", "team_name": "Test United", "team_crest": "", "next": "/"},
        )
        home_response = client.get("/")
        assert "Test United" not in home_response.data.decode()


def test_toggle_favorite_league_adds_and_removes(client):
    with patch("football_api.requests.get", side_effect=fake_get_factory()):
        response = client.post(
            "/favorites/league/toggle", data={"league_id": "PD", "next": "/"}
        )
        assert response.status_code == 302
        home_response = client.get("/")
        assert "favorite-chip" in home_response.data.decode()

        client.post("/favorites/league/toggle", data={"league_id": "PD", "next": "/"})
        home_response = client.get("/")
        assert "favorite-chip" not in home_response.data.decode()


def test_toggle_favorite_league_ignores_unknown_league_id(client):
    with patch("football_api.requests.get", side_effect=fake_get_factory()):
        client.post("/favorites/league/toggle", data={"league_id": "NOT_REAL", "next": "/"})
        home_response = client.get("/")
    assert "favorite-chip" not in home_response.data.decode()
