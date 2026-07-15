from __future__ import annotations

import argparse
import sqlite3

import numpy as np
from scipy.stats import poisson

from src import config
from src.db import init_db

# Below this many games in the training window, a team's attack/defense estimate
# is too noisy to trust (build-plan Section 5's "newly promoted team" caveat) -
# fall back to a league-average team (1.0/1.0) rather than an unstable estimate.
MIN_GAMES_FOR_RELIABLE_STRENGTH = 5
MAX_GOALS = 10
DEFAULT_STRENGTH = {"attack": 1.0, "defense": 1.0, "games": 0, "low_sample": True}


def compute_league_rates(conn: sqlite3.Connection, league: str, seasons: list) -> dict:
    placeholders = ",".join("?" * len(seasons))
    row = conn.execute(
        f"""
        SELECT AVG(home_goals) AS avg_home, AVG(away_goals) AS avg_away
        FROM matches
        WHERE league = ? AND season IN ({placeholders}) AND status = 'finished'
        """,
        (league, *[str(s) for s in seasons]),
    ).fetchone()
    avg_home = row["avg_home"] or 0.0
    avg_away = row["avg_away"] or 0.0
    return {
        "avg_home_goals": avg_home,
        "avg_away_goals": avg_away,
        "avg_goals_per_game": (avg_home + avg_away) / 2,
    }


def compute_team_stats(conn: sqlite3.Connection, league: str, seasons: list) -> dict:
    """Aggregates goals scored/conceded across home+away appearances per team."""
    placeholders = ",".join("?" * len(seasons))
    rows = conn.execute(
        f"""
        SELECT home_team_id, away_team_id, home_goals, away_goals
        FROM matches
        WHERE league = ? AND season IN ({placeholders}) AND status = 'finished'
        """,
        (league, *[str(s) for s in seasons]),
    ).fetchall()

    stats: dict = {}
    for row in rows:
        home_id, away_id = row["home_team_id"], row["away_team_id"]
        stats.setdefault(home_id, {"scored": 0, "conceded": 0, "games": 0})
        stats.setdefault(away_id, {"scored": 0, "conceded": 0, "games": 0})
        stats[home_id]["scored"] += row["home_goals"]
        stats[home_id]["conceded"] += row["away_goals"]
        stats[home_id]["games"] += 1
        stats[away_id]["scored"] += row["away_goals"]
        stats[away_id]["conceded"] += row["home_goals"]
        stats[away_id]["games"] += 1
    return stats


def compute_team_strengths(conn: sqlite3.Connection, league: str, seasons: list) -> tuple:
    league_rates = compute_league_rates(conn, league, seasons)
    league_avg = league_rates["avg_goals_per_game"]
    team_stats = compute_team_stats(conn, league, seasons)

    strengths = {}
    for team_id, s in team_stats.items():
        games = s["games"]
        if games == 0 or league_avg == 0:
            strengths[team_id] = dict(DEFAULT_STRENGTH, games=games)
            continue
        strengths[team_id] = {
            "attack": (s["scored"] / games) / league_avg,
            "defense": (s["conceded"] / games) / league_avg,
            "games": games,
            "low_sample": games < MIN_GAMES_FOR_RELIABLE_STRENGTH,
        }
    return strengths, league_rates


def match_outcome_probabilities(home_mu: float, away_mu: float, max_goals: int = MAX_GOALS) -> dict:
    goals = np.arange(max_goals + 1)
    home_probs = poisson.pmf(goals, home_mu)
    away_probs = poisson.pmf(goals, away_mu)
    matrix = np.outer(home_probs, away_probs)  # matrix[h, a] = P(home=h, away=a)

    p_home = np.tril(matrix, k=-1).sum()  # home goals > away goals
    p_draw = np.trace(matrix)
    p_away = np.triu(matrix, k=1).sum()

    total = p_home + p_draw + p_away  # < 1 by a negligible amount (truncated tail past max_goals)
    return {
        "p_home": float(p_home / total),
        "p_draw": float(p_draw / total),
        "p_away": float(p_away / total),
    }


def predict_fixture(home_strength: dict, away_strength: dict, league_rates: dict) -> dict:
    home_mu = league_rates["avg_home_goals"] * home_strength["attack"] * away_strength["defense"]
    away_mu = league_rates["avg_away_goals"] * away_strength["attack"] * home_strength["defense"]

    probs = match_outcome_probabilities(home_mu, away_mu)
    p_home, p_draw, p_away = probs["p_home"], probs["p_draw"], probs["p_away"]

    return {
        "expected_home_goals": home_mu,
        "expected_away_goals": away_mu,
        "p_home": p_home,
        "p_draw": p_draw,
        "p_away": p_away,
        "p_1x": p_home + p_draw,
        "p_x2": p_draw + p_away,
        "p_12": p_home + p_away,
    }


def store_prediction(conn: sqlite3.Connection, match_id: int, prediction: dict) -> None:
    conn.execute(
        """
        INSERT INTO predictions (
            match_id, generated_at, p_home, p_draw, p_away, p_1x, p_x2, p_12
        ) VALUES (?, datetime('now'), ?, ?, ?, ?, ?, ?)
        """,
        (
            match_id,
            prediction["p_home"],
            prediction["p_draw"],
            prediction["p_away"],
            prediction["p_1x"],
            prediction["p_x2"],
            prediction["p_12"],
        ),
    )


def generate_predictions_for_league(
    conn: sqlite3.Connection, league_name: str, train_seasons: list
) -> int:
    """Trains attack/defense strengths on train_seasons and predicts every
    'scheduled' fixture stored for this league. best_double_chance/odds/edge are
    left for value_calculator.py to fill in once market odds are available."""
    strengths, league_rates = compute_team_strengths(conn, league_name, train_seasons)
    fixtures = conn.execute(
        "SELECT id, home_team_id, away_team_id FROM matches WHERE league = ? AND status = 'scheduled'",
        (league_name,),
    ).fetchall()

    count = 0
    for fixture in fixtures:
        home_strength = strengths.get(fixture["home_team_id"], DEFAULT_STRENGTH)
        away_strength = strengths.get(fixture["away_team_id"], DEFAULT_STRENGTH)
        prediction = predict_fixture(home_strength, away_strength, league_rates)
        store_prediction(conn, fixture["id"], prediction)
        count += 1

    conn.commit()
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate Poisson predictions for scheduled fixtures")
    parser.add_argument(
        "--seasons", nargs="+", type=int, default=config.HISTORICAL_SEASONS, help="Training seasons"
    )
    args = parser.parse_args()

    conn = init_db(config.DB_PATH)
    total = 0
    for league in config.LEAGUES:
        count = generate_predictions_for_league(conn, league["name"], args.seasons)
        total += count
        print(f"{league['name']}: generated {count} predictions")
    print(f"Total predictions generated: {total}")
    conn.close()


if __name__ == "__main__":
    main()
