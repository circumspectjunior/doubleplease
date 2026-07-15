from __future__ import annotations

import argparse
import sqlite3
import time
from datetime import datetime, timezone

from src import config
from src.db import init_db
from src.http_utils import get_json
from src.team_matching import find_match_id, find_or_create_team

# Verified live against the real OddsPapi v4 API (see review.md):
# market 101 = Full Time Result (1X2), market 101902 = Double Chance Full Time.
MARKET_1X2 = "101"
MARKET_DOUBLE_CHANCE = "101902"
OUTCOME_HOME, OUTCOME_DRAW, OUTCOME_AWAY = "101", "102", "103"
OUTCOME_1X, OUTCOME_12, OUTCOME_2X = "101902", "101903", "101904"


def fetch_fixture_metadata(tournament_id: int, api_key: str | None = None) -> list[dict]:
    """GET /v4/fixtures - fixture list with participant names + start times for a tournament.
    Unlike API-Football's free tier, this isn't restricted to a narrow date window, so it's
    our source for discovering fixtures scheduled weeks/months out."""
    key = api_key or config.ODDSPAPI_KEY
    data = get_json(
        f"{config.ODDSPAPI_BASE_URL}/fixtures",
        params={"tournamentId": tournament_id, "apiKey": key},
    )
    return data if isinstance(data, list) else data.get("data", [])


def fetch_odds_for_tournaments(
    tournament_ids: list[int], bookmaker: str, api_key: str | None = None
) -> list[dict]:
    """GET /v4/odds-by-tournaments for one bookmaker, across one or more tournaments at once."""
    key = api_key or config.ODDSPAPI_KEY
    data = get_json(
        f"{config.ODDSPAPI_BASE_URL}/odds-by-tournaments",
        params={
            "tournamentIds": ",".join(str(t) for t in tournament_ids),
            "bookmaker": bookmaker,
            "apiKey": key,
        },
    )
    return data if isinstance(data, list) else data.get("data", [])


def _price(outcomes: dict, outcome_id: str) -> float | None:
    outcome = outcomes.get(outcome_id)
    if not outcome:
        return None
    player = outcome.get("players", {}).get("0")
    return player["price"] if player else None


def extract_prices(markets: dict) -> dict:
    """Pulls 1X2 + Double Chance prices out of one bookmaker's markets dict for a fixture."""
    market_1x2 = markets.get(MARKET_1X2, {}).get("outcomes", {})
    market_dc = markets.get(MARKET_DOUBLE_CHANCE, {}).get("outcomes", {})
    return {
        "odds_home": _price(market_1x2, OUTCOME_HOME),
        "odds_draw": _price(market_1x2, OUTCOME_DRAW),
        "odds_away": _price(market_1x2, OUTCOME_AWAY),
        "odds_1x": _price(market_dc, OUTCOME_1X),
        "odds_12": _price(market_dc, OUTCOME_12),
        "odds_x2": _price(market_dc, OUTCOME_2X),
    }


def infer_season(match_date: str) -> int:
    """European club seasons run Aug-May; label a date by the year its season started."""
    year, month = int(match_date[:4]), int(match_date[5:7])
    return year if month >= 7 else year - 1


def ensure_match(
    conn: sqlite3.Connection, league_name: str, home_name: str, away_name: str, match_date: str
) -> int:
    """Finds the stored match for this fixture, creating it (status='scheduled') if
    API-Football hasn't surfaced it yet - OddsPapi's fixture list is our only source
    for fixtures further out than API-Football's free-tier date window allows."""
    existing = find_match_id(conn, home_name, away_name, match_date)
    if existing is not None:
        return existing

    home_id = find_or_create_team(conn, home_name, league_name)
    away_id = find_or_create_team(conn, away_name, league_name)
    cursor = conn.execute(
        """
        INSERT INTO matches (league, season, match_date, home_team_id, away_team_id, status)
        VALUES (?, ?, ?, ?, ?, 'scheduled')
        """,
        (league_name, str(infer_season(match_date)), match_date, home_id, away_id),
    )
    return cursor.lastrowid


def insert_odds(conn: sqlite3.Connection, match_id: int, bookmaker: str, prices: dict) -> None:
    conn.execute(
        """
        INSERT INTO odds (
            match_id, bookmaker, fetched_at,
            odds_home, odds_draw, odds_away,
            odds_1x, odds_x2, odds_12
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            match_id,
            bookmaker,
            datetime.now(timezone.utc).isoformat(),
            prices["odds_home"],
            prices["odds_draw"],
            prices["odds_away"],
            prices["odds_1x"],
            prices["odds_x2"],
            prices["odds_12"],
        ),
    )


def ingest_odds_for_league(
    conn: sqlite3.Connection,
    league_name: str,
    tournament_id: int,
    bookmaker: str,
    fixture_metadata: list[dict] | None = None,
    odds_entries: list[dict] | None = None,
) -> int:
    """Matches one bookmaker's odds for one league's tournament to stored (or newly
    created) matches, and stores odds rows. Returns count of odds rows stored."""
    metadata = (
        fixture_metadata
        if fixture_metadata is not None
        else fetch_fixture_metadata(tournament_id)
    )
    fixtures_by_id = {f["fixtureId"]: f for f in metadata}

    entries = (
        odds_entries
        if odds_entries is not None
        else fetch_odds_for_tournaments([tournament_id], bookmaker)
    )

    count = 0
    for entry in entries:
        if not entry.get("hasOdds"):
            continue
        meta = fixtures_by_id.get(entry["fixtureId"])
        if meta is None:
            continue

        markets = entry.get("bookmakerOdds", {}).get(bookmaker, {}).get("markets", {})
        prices = extract_prices(markets)
        if prices["odds_home"] is None and prices["odds_1x"] is None:
            continue  # neither market this bookmaker publishes for this fixture

        match_date = meta["startTime"][:10]
        match_id = ensure_match(
            conn, league_name, meta["participant1Name"], meta["participant2Name"], match_date
        )
        insert_odds(conn, match_id, bookmaker, prices)
        count += 1

    conn.commit()
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest odds from OddsPapi")
    parser.add_argument(
        "--bookmakers",
        nargs="+",
        default=config.ODDSPAPI_BOOKMAKERS,
        help="Bookmaker slugs to pull, e.g. unibet 888sport",
    )
    args = parser.parse_args()

    conn = init_db(config.DB_PATH)

    # /v4/fixtures needs one call per tournament, but /v4/odds-by-tournaments accepts
    # comma-joined tournament ids, so odds are fetched once per bookmaker across all
    # leagues at once rather than once per (league, bookmaker) pair.
    metadata_by_league = {}
    for league in config.LEAGUES:
        metadata_by_league[league["name"]] = fetch_fixture_metadata(
            league["oddspapi_tournament_id"]
        )
        time.sleep(0.4)

    tournament_ids = [league["oddspapi_tournament_id"] for league in config.LEAGUES]

    total = 0
    for bookmaker in args.bookmakers:
        all_entries = fetch_odds_for_tournaments(tournament_ids, bookmaker)
        time.sleep(0.4)
        for league in config.LEAGUES:
            entries_for_league = [
                e
                for e in all_entries
                if e.get("tournamentId") == league["oddspapi_tournament_id"]
            ]
            stored = ingest_odds_for_league(
                conn,
                league["name"],
                league["oddspapi_tournament_id"],
                bookmaker,
                fixture_metadata=metadata_by_league[league["name"]],
                odds_entries=entries_for_league,
            )
            total += stored
            print(f"{league['name']} / {bookmaker}: stored {stored} odds rows")
    print(f"Total odds rows stored: {total}")
    conn.close()


if __name__ == "__main__":
    main()
