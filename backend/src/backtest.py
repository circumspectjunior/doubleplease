from __future__ import annotations

import argparse
import sqlite3

from src import config
from src.db import init_db
from src.model_poisson import DEFAULT_STRENGTH, compute_team_strengths, predict_fixture

CALIBRATION_BUCKET_WIDTH = 0.1
DOUBLE_CHANCE_OUTCOMES = (("1X", "p_1x"), ("X2", "p_x2"), ("12", "p_12"))


def get_finished_matches(conn: sqlite3.Connection, league: str, season: int) -> list:
    return conn.execute(
        "SELECT id, home_team_id, away_team_id, home_goals, away_goals FROM matches "
        "WHERE league = ? AND season = ? AND status = 'finished'",
        (league, str(season)),
    ).fetchall()


def actual_double_chance_outcomes(home_goals: int, away_goals: int) -> dict:
    if home_goals > away_goals:
        result = "home"
    elif home_goals == away_goals:
        result = "draw"
    else:
        result = "away"
    return {
        "1X": result in ("home", "draw"),
        "X2": result in ("draw", "away"),
        "12": result in ("home", "away"),
    }


def collect_calibration_points(
    conn: sqlite3.Connection, league: str, train_seasons: list, test_season: int
) -> list:
    """Predicts every finished match in test_season using only train_seasons data
    (so the held-out season never leaks into its own training), and pairs each
    double-chance market's predicted probability with what actually happened."""
    strengths, league_rates = compute_team_strengths(conn, league, train_seasons)

    points = []
    for match in get_finished_matches(conn, league, test_season):
        home_strength = strengths.get(match["home_team_id"], DEFAULT_STRENGTH)
        away_strength = strengths.get(match["away_team_id"], DEFAULT_STRENGTH)
        prediction = predict_fixture(home_strength, away_strength, league_rates)
        actual = actual_double_chance_outcomes(match["home_goals"], match["away_goals"])
        for outcome_key, prob_key in DOUBLE_CHANCE_OUTCOMES:
            points.append((prediction[prob_key], actual[outcome_key]))
    return points


def bucket_calibration(points: list, bucket_width: float = CALIBRATION_BUCKET_WIDTH) -> list:
    """Groups (predicted_probability, actual_outcome) pairs into probability bins
    and computes each bin's actual hit rate, for comparison against its mean
    prediction - the core check from Section 7 ('of matches predicted ~70%, did
    roughly 70% actually hit?')."""
    n_buckets = int(round(1 / bucket_width))
    buckets: dict = {}
    for prob, outcome in points:
        index = min(int(prob / bucket_width), n_buckets - 1)
        low = round(index * bucket_width, 2)
        b = buckets.setdefault(low, {"count": 0, "sum_predicted": 0.0, "hits": 0})
        b["count"] += 1
        b["sum_predicted"] += prob
        b["hits"] += int(outcome)

    return [
        {
            "bucket_low": low,
            "bucket_high": round(low + bucket_width, 2),
            "count": b["count"],
            "mean_predicted": b["sum_predicted"] / b["count"],
            "actual_hit_rate": b["hits"] / b["count"],
        }
        for low, b in sorted(buckets.items())
    ]


def expected_calibration_error(buckets: list) -> float:
    """Weighted-average gap between predicted probability and actual hit rate
    across buckets - 0 is perfect calibration, larger is worse."""
    total = sum(b["count"] for b in buckets)
    if total == 0:
        return 0.0
    return sum(b["count"] * abs(b["mean_predicted"] - b["actual_hit_rate"]) for b in buckets) / total


def run_calibration_backtest(
    conn: sqlite3.Connection, league: str, train_seasons: list, test_season: int
) -> dict:
    points = collect_calibration_points(conn, league, train_seasons, test_season)
    buckets = bucket_calibration(points)
    return {
        "league": league,
        "train_seasons": train_seasons,
        "test_season": test_season,
        "n_points": len(points),
        "buckets": buckets,
        "expected_calibration_error": expected_calibration_error(buckets),
    }


def simulate_roi(bets: list) -> dict:
    """Pure ROI simulation over a list of {"odds", "won"} flat-stake bets - kept
    separate from data sourcing so it's testable regardless of odds availability.
    profit uses decimal odds: won -> +(odds-1) stake, lost -> -1 stake."""
    if not bets:
        return {"n_bets": 0, "total_staked": 0, "total_profit": 0.0, "roi": None}

    total_profit = sum((bet["odds"] - 1) if bet["won"] else -1 for bet in bets)
    return {
        "n_bets": len(bets),
        "total_staked": len(bets),
        "total_profit": total_profit,
        "roi": total_profit / len(bets),
    }


def run_roi_backtest(conn: sqlite3.Connection, league: str, test_season: int) -> dict:
    """Would simulate hypothetical weekly-shortlist ROI against real historical odds
    for the held-out season. As of this build, neither API-Football nor OddsPapi's
    free tiers expose historical odds (verified live - both returned empty/"not
    found" for real fixture ids), so this reports unavailability rather than
    fabricating a number that could mislead a real betting decision."""
    has_historical_odds = conn.execute(
        """
        SELECT COUNT(*) AS c FROM odds o
        JOIN matches m ON o.match_id = m.id
        WHERE m.league = ? AND m.season = ? AND m.status = 'finished'
        """,
        (league, str(test_season)),
    ).fetchone()["c"]

    if not has_historical_odds:
        return {
            "available": False,
            "reason": (
                "No historical odds stored for this season. Neither API-Football nor "
                "OddsPapi's free tiers expose historical odds data (verified live) - "
                "ROI backtesting needs a paid odds-history source to run for real."
            ),
        }
    return {"available": True}  # real simulation would run simulate_roi() here


def main() -> None:
    parser = argparse.ArgumentParser(description="Backtest the Poisson model against a held-out season")
    parser.add_argument("--test-season", type=int, default=max(config.HISTORICAL_SEASONS))
    args = parser.parse_args()

    train_seasons = [s for s in config.HISTORICAL_SEASONS if s != args.test_season]
    conn = init_db(config.DB_PATH)

    for league in config.LEAGUES:
        result = run_calibration_backtest(conn, league["name"], train_seasons, args.test_season)
        print(
            f"\n{league['name']} (train={train_seasons}, test={args.test_season}): "
            f"{result['n_points']} data points, ECE={result['expected_calibration_error']:.3f}"
        )
        for b in result["buckets"]:
            print(
                f"  [{b['bucket_low']:.1f}-{b['bucket_high']:.1f}) n={b['count']:>4} "
                f"predicted={b['mean_predicted']:.2f} actual={b['actual_hit_rate']:.2f}"
            )

        roi = run_roi_backtest(conn, league["name"], args.test_season)
        if not roi["available"]:
            print(f"  ROI backtest: unavailable - {roi['reason']}")

    conn.close()


if __name__ == "__main__":
    main()
