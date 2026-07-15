from __future__ import annotations

import argparse
import sqlite3

from src import config
from src.db import init_db
from src.http_utils import get_json
from src.team_matching import find_or_create_team

FINISHED_STATUSES = {"FT", "AET", "PEN"}


def fetch_fixtures(league_id: int, season: int, api_key: str | None = None) -> list[dict]:
    """Calls API-Football v3 /fixtures for a league/season and returns the raw response list."""
    key = api_key or config.API_FOOTBALL_KEY
    data = get_json(
        f"{config.API_FOOTBALL_BASE_URL}/fixtures",
        params={"league": league_id, "season": season},
        headers={"x-apisports-key": key},
    )
    return data.get("response", [])


def normalize_fixture(raw: dict) -> dict:
    """Flattens one API-Football fixture object into the fields our schema needs."""
    status_short = raw["fixture"]["status"]["short"]
    return {
        "fixture_id": raw["fixture"]["id"],
        "league": raw["league"]["name"],
        "season": str(raw["league"]["season"]),
        "match_date": raw["fixture"]["date"][:10],
        "home_team": raw["teams"]["home"]["name"],
        "away_team": raw["teams"]["away"]["name"],
        "home_goals": raw["goals"]["home"],
        "away_goals": raw["goals"]["away"],
        "status": "finished" if status_short in FINISHED_STATUSES else "scheduled",
    }


def upsert_team(conn: sqlite3.Connection, name: str, league: str) -> int:
    """Fuzzy-matched rather than exact-match: API-Football itself spells some clubs
    inconsistently across seasons (e.g. "VfL Bochum" vs "Vfl Bochum", "Bayern Munich"
    vs "Bayern München"), which would otherwise fragment one club's historical
    record across two team rows and corrupt its attack/defense sample size."""
    return find_or_create_team(conn, name, league)


def upsert_match(conn: sqlite3.Connection, fixture: dict) -> int:
    home_id = upsert_team(conn, fixture["home_team"], fixture["league"])
    away_id = upsert_team(conn, fixture["away_team"], fixture["league"])

    conn.execute(
        """
        INSERT INTO matches (
            id, league, season, match_date, home_team_id, away_team_id,
            home_goals, away_goals, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            league=excluded.league,
            season=excluded.season,
            match_date=excluded.match_date,
            home_team_id=excluded.home_team_id,
            away_team_id=excluded.away_team_id,
            home_goals=excluded.home_goals,
            away_goals=excluded.away_goals,
            status=excluded.status
        """,
        (
            fixture["fixture_id"],
            fixture["league"],
            fixture["season"],
            fixture["match_date"],
            home_id,
            away_id,
            fixture["home_goals"],
            fixture["away_goals"],
            fixture["status"],
        ),
    )
    return fixture["fixture_id"]


def ingest_fixtures(
    conn: sqlite3.Connection,
    league_id: int,
    season: int,
    fixtures: list[dict] | None = None,
) -> int:
    """Fetches (or accepts pre-fetched) fixtures, normalizes and stores them. Returns count stored."""
    raw_fixtures = fixtures if fixtures is not None else fetch_fixtures(league_id, season)
    count = 0
    for raw in raw_fixtures:
        upsert_match(conn, normalize_fixture(raw))
        count += 1
    conn.commit()
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest fixtures from API-Football")
    parser.add_argument("--league", type=int, required=True, help="API-Football league id")
    parser.add_argument("--season", type=int, required=True, help="Season year, e.g. 2025")
    args = parser.parse_args()

    conn = init_db(config.DB_PATH)
    count = ingest_fixtures(conn, args.league, args.season)
    print(f"Stored {count} fixtures for league {args.league}, season {args.season}")
    conn.close()


if __name__ == "__main__":
    main()
