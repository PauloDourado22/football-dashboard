"""Unit tests for football_api.py — no Flask app, no real network calls."""

import requests
from unittest.mock import Mock, patch

import football_api as api


def make_match(date, home_id, away_id, home_goals, away_goals):
    return {
        "utcDate": date,
        "homeTeam": {"id": home_id, "name": f"Team {home_id}"},
        "awayTeam": {"id": away_id, "name": f"Team {away_id}"},
        "score": {"fullTime": {"home": home_goals, "away": away_goals}},
    }


class FakeCache:
    """Minimal stand-in for a Flask-Caching Cache instance."""

    def __init__(self):
        self.store = {}

    def get(self, key):
        return self.store.get(key)

    def set(self, key, value):
        self.store[key] = value


def test_compute_form_orders_most_recent_first():
    finished = [
        make_match("2026-06-01T15:00:00Z", 1, 2, 3, 1),  # team 1 win
        make_match("2026-06-08T15:00:00Z", 3, 1, 2, 2),  # team 1 draw
        make_match("2026-06-15T15:00:00Z", 1, 4, 0, 1),  # team 1 loss
    ]
    assert api.compute_form(1, finished) == ["L", "D", "W"]


def test_compute_form_ignores_matches_for_other_teams():
    finished = [make_match("2026-06-01T15:00:00Z", 5, 6, 1, 0)]
    assert api.compute_form(1, finished) == []


def test_compute_form_skips_matches_with_missing_scores():
    finished = [make_match("2026-06-01T15:00:00Z", 1, 2, None, None)]
    assert api.compute_form(1, finished) == []


def test_compute_form_respects_limit():
    finished = [
        make_match(f"2026-06-{d:02d}T15:00:00Z", 1, 2, 1, 0) for d in range(1, 10)
    ]
    assert len(api.compute_form(1, finished, limit=3)) == 3


def test_standings_url_and_matches_url():
    assert api.standings_url("PL") == "https://api.football-data.org/v4/competitions/PL/standings"
    assert api.matches_url("PL", "FINISHED") == (
        "https://api.football-data.org/v4/competitions/PL/matches?status=FINISHED"
    )


def test_fetch_json_success_without_cache():
    fake_response = Mock(status_code=200)
    fake_response.json.return_value = {"ok": True}
    with patch("football_api.requests.get", return_value=fake_response):
        data, error = api.fetch_json("http://example.test", {}, cache=None)
    assert error is None
    assert data == {"ok": True}


def test_fetch_json_timeout_returns_error_not_exception():
    with patch("football_api.requests.get", side_effect=requests.exceptions.Timeout):
        data, error = api.fetch_json("http://example.test", {}, cache=None)
    assert data is None
    assert "too long" in error


def test_fetch_json_connection_error_returns_error_not_exception():
    with patch("football_api.requests.get", side_effect=requests.exceptions.ConnectionError):
        data, error = api.fetch_json("http://example.test", {}, cache=None)
    assert data is None
    assert "Could not reach" in error


def test_fetch_json_non_200_returns_error():
    fake_response = Mock(status_code=404)
    with patch("football_api.requests.get", return_value=fake_response):
        data, error = api.fetch_json("http://example.test", {}, cache=None)
    assert data is None
    assert "404" in error


def test_fetch_json_caches_successful_response():
    calls = {"n": 0}

    def fake_get(*args, **kwargs):
        calls["n"] += 1
        response = Mock(status_code=200)
        response.json.return_value = {"n": calls["n"]}
        return response

    cache = FakeCache()
    with patch("football_api.requests.get", side_effect=fake_get):
        data1, _ = api.fetch_json("http://example.test", {}, cache=cache)
        data2, _ = api.fetch_json("http://example.test", {}, cache=cache)

    assert calls["n"] == 1  # second call served from cache
    assert data1 == data2 == {"n": 1}


def test_fetch_json_does_not_cache_errors():
    calls = {"n": 0}

    def flaky_get(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise requests.exceptions.Timeout()
        response = Mock(status_code=200)
        response.json.return_value = {"ok": True}
        return response

    cache = FakeCache()
    with patch("football_api.requests.get", side_effect=flaky_get):
        data1, error1 = api.fetch_json("http://example.test", {}, cache=cache)
        data2, error2 = api.fetch_json("http://example.test", {}, cache=cache)

    assert error1 is not None and data1 is None
    assert error2 is None and data2 == {"ok": True}
    assert calls["n"] == 2  # error was not cached, so it retried live
