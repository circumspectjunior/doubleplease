import sqlite3
from contextlib import contextmanager
from typing import Optional

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware

from src import config
from src.backtest import run_calibration_backtest
from src.db import init_db
from src.model_poisson import MIN_GAMES_FOR_RELIABLE_STRENGTH
from src.value_calculator import MAX_TRUSTED_EDGE, get_shortlist
from src.weekly_report import build_reliable_team_ids, split_shortlist

app = FastAPI(title="DoublePlease API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


@contextmanager
def get_connection():
    conn = init_db(config.DB_PATH)
    try:
        yield conn
    finally:
        conn.close()


@app.get("/api/leagues")
def list_leagues() -> list:
    return [{"name": league["name"]} for league in config.LEAGUES]


@app.get("/api/shortlist")
def shortlist(league: Optional[str] = Query(default=None), top: int = Query(default=20, le=100)) -> dict:
    with get_connection() as conn:
        reliable_team_ids = build_reliable_team_ids(conn, config.HISTORICAL_SEASONS)
        raw = get_shortlist(conn, top_n=top * 3)
        if league:
            raw = [row for row in raw if row["league"] == league]
        trusted, excluded = split_shortlist(raw, reliable_team_ids, top)

    return {
        "trusted": [_serialize_pick(row) for row in trusted],
        "excluded": [_serialize_pick(row) for row in excluded],
        "max_trusted_edge": MAX_TRUSTED_EDGE,
    }


def _serialize_pick(row: dict) -> dict:
    return {
        "match_date": row["match_date"],
        "league": row["league"],
        "home_team": row["home_team"],
        "away_team": row["away_team"],
        "pick": row["best_double_chance"],
        "odds": row["best_dc_odds"],
        "model_probability": row["best_dc_probability"],
        "edge": row["edge"],
        "suspect": abs(row["edge"]) > MAX_TRUSTED_EDGE if row["edge"] is not None else False,
    }


@app.get("/api/calibration")
def calibration(
    test_season: int = Query(default=max(config.HISTORICAL_SEASONS)),
) -> list:
    train_seasons = [s for s in config.HISTORICAL_SEASONS if s != test_season]
    with get_connection() as conn:
        results = [
            run_calibration_backtest(conn, league["name"], train_seasons, test_season)
            for league in config.LEAGUES
        ]
    return results


@app.get("/api/status")
def status() -> dict:
    with get_connection() as conn:
        return {
            "teams": _count(conn, "teams"),
            "matches": _count(conn, "matches"),
            "scheduled_matches": _count(conn, "matches", "status = 'scheduled'"),
            "odds_rows": _count(conn, "odds"),
            "predictions": _count(conn, "predictions"),
            "min_games_for_reliable_strength": MIN_GAMES_FOR_RELIABLE_STRENGTH,
            "last_odds_fetched_at": _max(conn, "odds", "fetched_at"),
            "last_prediction_generated_at": _max(conn, "predictions", "generated_at"),
        }


def _count(conn: sqlite3.Connection, table: str, where: Optional[str] = None) -> int:
    sql = f"SELECT COUNT(*) AS c FROM {table}"
    if where:
        sql += f" WHERE {where}"
    return conn.execute(sql).fetchone()["c"]


def _max(conn: sqlite3.Connection, table: str, column: str):
    row = conn.execute(f"SELECT MAX({column}) AS m FROM {table}").fetchone()
    return row["m"]
