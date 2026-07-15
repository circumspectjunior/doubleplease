from __future__ import annotations

import argparse
import sqlite3
from datetime import datetime, timezone

import requests

from src import config
from src.db import init_db


def fetch_odds_for_date(match_date: str, api_key: str | None = None) -> list[dict]:
    """Calls OddsPapi for all fixtures odds on a given date (YYYY-MM-DD).

    NOTE: OddsPapi's exact request/response shape should be confirmed against
    their current docs before relying on this in production - this assumes a
    `date` query param and a response list of per-match odds objects, each
    carrying a native `double_chance` market alongside the 1x2 market.
    """
    key = api_key or config.ODDSPAPI_KEY
    resp = requests.get(
        f"{config.ODDSPAPI_BASE_URL}/odds",
        headers={"Authorization": f"Bearer {key}"},
        params={"date": match_date, "sport": "soccer"},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json().get("data", [])


def normalize_odds(raw: dict) -> dict:
    """Flattens one OddsPapi match-odds object into the fields our schema needs."""
    markets = raw.get("markets", {})
    one_x_two = markets.get("1x2", {})
    double_chance = markets.get("double_chance", {})
    return {
        "home_team": raw["home_team"],
        "away_team": raw["away_team"],
        "match_date": raw["match_date"],
        "bookmaker": raw.get("bookmaker", "unknown"),
        "odds_home": one_x_two.get("home"),
        "odds_draw": one_x_two.get("draw"),
        "odds_away": one_x_two.get("away"),
        "odds_1x": double_chance.get("1x"),
        "odds_x2": double_chance.get("x2"),
        "odds_12": double_chance.get("12"),
    }


def find_match_id(
    conn: sqlite3.Connection, home_team: str, away_team: str, match_date: str
) -> int | None:
    row = conn.execute(
        """
        SELECT m.id FROM matches m
        JOIN teams h ON m.home_team_id = h.id
        JOIN teams a ON m.away_team_id = a.id
        WHERE h.name = ? AND a.name = ? AND m.match_date = ?
        """,
        (home_team, away_team, match_date),
    ).fetchone()
    return row["id"] if row else None


def insert_odds(conn: sqlite3.Connection, match_id: int, odds: dict) -> None:
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
            odds["bookmaker"],
            datetime.now(timezone.utc).isoformat(),
            odds["odds_home"],
            odds["odds_draw"],
            odds["odds_away"],
            odds["odds_1x"],
            odds["odds_x2"],
            odds["odds_12"],
        ),
    )


def get_scheduled_match_dates(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT DISTINCT match_date FROM matches WHERE status = 'scheduled'"
    ).fetchall()
    return [row["match_date"] for row in rows]


def ingest_odds(
    conn: sqlite3.Connection,
    match_date: str,
    raw_odds: list[dict] | None = None,
) -> int:
    """Fetches (or accepts pre-fetched) odds for a date, matches them to stored
    fixtures by team names, and stores them. Returns count of odds rows stored.
    Odds for fixtures not present in the matches table are skipped."""
    entries = raw_odds if raw_odds is not None else fetch_odds_for_date(match_date)
    count = 0
    for raw in entries:
        normalized = normalize_odds(raw)
        match_id = find_match_id(
            conn,
            normalized["home_team"],
            normalized["away_team"],
            normalized["match_date"],
        )
        if match_id is None:
            continue
        insert_odds(conn, match_id, normalized)
        count += 1
    conn.commit()
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest odds from OddsPapi")
    parser.add_argument(
        "--date", type=str, help="YYYY-MM-DD; defaults to all scheduled match dates in the DB"
    )
    args = parser.parse_args()

    conn = init_db(config.DB_PATH)
    dates = [args.date] if args.date else get_scheduled_match_dates(conn)

    total = 0
    for match_date in dates:
        total += ingest_odds(conn, match_date)
    print(f"Stored {total} odds rows across {len(dates)} date(s)")
    conn.close()


if __name__ == "__main__":
    main()
