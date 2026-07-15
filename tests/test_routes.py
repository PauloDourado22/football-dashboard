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


def make_match(date, home_id, home_name, away_id, away_name, hg=None, ag=None):
    return {
        "utcDate": date,
        "homeTeam": {"id": home_id, "name": home_name, "crest": ""},
        "awayTeam": {"id": away_id, "name": away_name, "crest": ""},
        "score": {"fullTime": {"home": hg, "away": ag}},
    }


def fake_get_factory(finished=None, scheduled=None, table_size=20):
    finished = finished if finished is not None else []
    scheduled = (
        scheduled
        if scheduled is not None
        else [make_match("2026-07-20T15:00:00Z", 5, "Team 5", 6, "Team 6")]
    )

    def fake_get(url, headers=None, timeout=None):
        response = Mock(status_code=200)
        if "standings" in url:
            table = [make_team(i, i, f"Team {i}") for i in range(1, table_size + 1)]
            response.json.return_value = {
                "standings": [{"table": table}],
                "competition": {"currentSeason": {"currentMatchday": 10}},
            }
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

    assert calls["n"] == 3  # standings + scheduled + finished, fetched once


def test_markup_parses_and_has_expected_row_count(client):
    with patch("football_api.requests.get", side_effect=fake_get_factory(table_size=20)):
        response = client.get("/")
    soup = BeautifulSoup(response.data, "html.parser")
    rows = soup.select("table.standings tbody tr")
    assert len(rows) == 20
