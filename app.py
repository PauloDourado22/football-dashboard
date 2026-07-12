import os

from dotenv import load_dotenv
from flask import Flask, render_template, request
import requests

load_dotenv()

app = Flask(__name__)

API_KEY = os.environ.get("API_KEY")

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

@app.route("/", methods=["GET", "POST"])
def home():
    league_id = request.form.get("league") or "PL"  # default Premier League
    headers = {"X-Auth-Token": API_KEY}

    # Fetch standings
    standings_url = f"https://api.football-data.org/v4/competitions/{league_id}/standings"
    standings_response = requests.get(standings_url, headers=headers)
    if standings_response.status_code != 200:
        return f"Error fetching standings: {standings_response.status_code}"

    standings_data = standings_response.json()
    table = standings_data.get("standings", [])[0].get("table", [])

    # Get current matchday from competition data
    competition_info = standings_data.get("competition", {})
    current_matchday = competition_info.get("currentSeason", {}).get("currentMatchday", 1)

    # Fetch all scheduled matches
    matches_url = f"https://api.football-data.org/v4/competitions/{league_id}/matches?status=SCHEDULED"
    matches_response = requests.get(matches_url, headers=headers)
    if matches_response.status_code != 200:
        return f"Error fetching matches: {matches_response.status_code}"

    matches_data = matches_response.json()
    matches = matches_data.get("matches", [])[:5]

    return render_template(
        "index.html",
        table=table,
        matches=matches,
        leagues=LEAGUES,
        selected_league=league_id,
        matchday=current_matchday
    )


if __name__ == "__main__":
    app.run(debug=False)

