# Football Dashboard

A Flask web dashboard that displays football league standings, recent form, top scorers, team
profiles, and head-to-head history, using the [football-data.org](https://www.football-data.org/) API.

## Features

- Standings for popular European leagues and the Champions League, with continental
  qualification / relegation zone highlighting (approximate — see the note in `football_api.py`)
- Last-5 match form (W/D/L) per team, derived from already-fetched results (no extra API calls)
- Recent results and upcoming fixtures
- Top scorers leaderboard per league
- Team profile pages (squad, recent results, upcoming fixtures) — click any team name
- Head-to-head history between two teams — click a fixture's score/"View" link
- Favorite leagues and teams (stored in a signed session cookie, no login required)
- League selection via a shareable, bookmarkable URL (`?league=PL`)
- In-memory response caching to stay within the API's free-tier rate limit

## Project structure

- `app.py` — Flask app and route handling
- `football_api.py` — Flask-independent API client, caching helper, and form/zone/squad/head2head logic (unit tested separately from the routes)
- `templates/` — `index.html` (dashboard), `team.html` (team profile), `match.html` (head-to-head), `error.html` (shared error page)
- `static/style.css` — styling
- `tests/` — pytest suite (`test_football_api.py` unit tests, `test_routes.py` integration tests via the Flask test client)
- `conftest.py` — shared test fixtures

## Requirements

- Python 3.8+

## Installation

1. Clone the repository.
2. Create a virtual environment (recommended):

```bash
python3 -m venv venv
source venv/bin/activate
```

3. Install dependencies:

```bash
pip install -r requirements.txt
```

For running tests, install the dev requirements instead (it includes everything in `requirements.txt` plus `pytest` and `beautifulsoup4`):

```bash
pip install -r requirements-dev.txt
```

## Configuration

Copy the example file and fill in both values:

```bash
cp .env.example .env
```

```
API_KEY=your_football_data_api_key_here
SECRET_KEY=a_long_random_string
```

- `API_KEY` — your football-data.org API key. The app refuses to start without it.
- `SECRET_KEY` — signs the session cookie used to store favorites. Generate one with:
  `python -c "import secrets; print(secrets.token_hex(32))"`. The app also refuses to start
  without this, deliberately — a randomly-generated fallback would invalidate everyone's
  favorites on every restart, which is a confusing way to find out you forgot to set it.

`.env` is gitignored, so neither value goes into version control.

## Running the app

```bash
python app.py
```

Then open `http://127.0.0.1:5000/` in your browser.

## Running tests

```bash
pytest
```

## Notes

- Standings, results, fixtures, scorers, team profiles, and head-to-head data are cached in-process
  for 5 minutes (`CACHE_TTL` in `app.py`) to avoid hitting the free tier's 10 requests/minute limit.
  The cache resets on restart and isn't shared across multiple worker processes — swap to
  `RedisCache` in `app.py` if you ever deploy with `gunicorn -w >1`.
- Continental/relegation zone spot counts in `football_api.py` are reasonable approximations, not
  authoritative — playoff rules shift season to season.
- Recent/upcoming matches on a team's profile page are treated as optional: some free-tier plans
  restrict the team/matches subresource, so a failure there only hides that section instead of
  breaking the whole page.
- Favorites are stored per-browser in a signed cookie, not a database — there's no login system,
  so favorites won't follow you to a different browser or device. Worth upgrading to real accounts
  + a database later if that matters to you.
- If any API call fails (timeout, network error, non-200 response), the app shows an error banner
  instead of crashing.
