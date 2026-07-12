# Football Dashboard

A simple Flask web dashboard that displays football league standings and upcoming matches using the Football-Data.org API.

## Features

- View standings for popular European leagues and the Champions League
- Select a league from the dropdown menu
- See the next scheduled matches for the selected competition
- Clean responsive layout using HTML and CSS

## Supported Leagues

- Premier League (`PL`)
- La Liga (`PD`)
- Bundesliga (`BL1`)
- Serie A (`SA`)
- Ligue 1 (`FL1`)
- Primeira Liga (`PPL`)
- Champions League (`CL`)

## Requirements

- Python 3.8+
- Flask
- requests

## Installation

1. Clone or download the repository.
2. Create a virtual environment (recommended):

```bash
python3 -m venv venv
source venv/bin/activate
```

3. Install dependencies:

```bash
pip install flask requests
```

## Configuration

The app uses an API key defined in `app.py`:

```python
API_KEY = "YOUR_API_KEY_HERE"
```

For production use, replace this placeholder with your own Football-Data.org API key.

## Running the App

Start the Flask server:

```bash
python app.py
```

Then open `http://127.0.0.1:5000/` in your browser.

## Project Structure

- `app.py` — Flask application and API integration logic
- `templates/index.html` — Dashboard HTML template
- `static/style.css` — Dashboard styling

## Notes

- The app fetches standings and scheduled matches for the selected competition.
- The next matchday is shown using the API's current season data.
- If the API returns an error, the app displays a simple error message.
