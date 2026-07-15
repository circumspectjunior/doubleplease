import os
from pathlib import Path

from dotenv import load_dotenv

BACKEND_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(BACKEND_ROOT / ".env")

API_FOOTBALL_KEY = os.environ.get("API_FOOTBALL_KEY", "")
API_FOOTBALL_BASE_URL = "https://v3.football.api-sports.io"

ODDSPAPI_KEY = os.environ.get("ODDSPAPI_KEY", "")
ODDSPAPI_BASE_URL = "https://api.oddspapi.io/v4"
# Bookmakers confirmed (via live lookup) to publish the "Double Chance Full Time" market.
ODDSPAPI_BOOKMAKERS = ["unibet", "888sport", "1xbet"]

DB_PATH = BACKEND_ROOT / "data" / "predictions.db"

# Tracked leagues: API-Football is the historical results source (full past-season
# access on the free tier); OddsPapi is the upcoming-fixture + odds source (its free
# tier exposes fixtures scheduled months out, unlike API-Football's free tier which
# only allows fixture/date queries within ~1 day of today).
LEAGUES = [
    {"name": "Premier League", "api_football_id": 39, "oddspapi_tournament_id": 17},
    {"name": "La Liga", "api_football_id": 140, "oddspapi_tournament_id": 8},
    {"name": "Serie A", "api_football_id": 135, "oddspapi_tournament_id": 23},
    {"name": "Bundesliga", "api_football_id": 78, "oddspapi_tournament_id": 35},
    {"name": "Ligue 1", "api_football_id": 61, "oddspapi_tournament_id": 34},
]

# API-Football free tier only permits these historical seasons (verified live).
HISTORICAL_SEASONS = [2022, 2023, 2024]
