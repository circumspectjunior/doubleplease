import pytest

from src.backtest import (
    actual_double_chance_outcomes,
    bucket_calibration,
    collect_calibration_points,
    expected_calibration_error,
    run_roi_backtest,
    simulate_roi,
)
from src.db import init_db


def test_actual_double_chance_outcomes_home_win():
    outcomes = actual_double_chance_outcomes(2, 0)
    assert outcomes == {"1X": True, "X2": False, "12": True}


def test_actual_double_chance_outcomes_draw():
    outcomes = actual_double_chance_outcomes(1, 1)
    assert outcomes == {"1X": True, "X2": True, "12": False}


def test_actual_double_chance_outcomes_away_win():
    outcomes = actual_double_chance_outcomes(0, 2)
    assert outcomes == {"1X": False, "X2": True, "12": True}


def test_bucket_calibration_groups_and_averages_correctly():
    points = [(0.72, True), (0.74, False), (0.71, True), (0.55, True)]

    buckets = bucket_calibration(points, bucket_width=0.1)

    bucket_70 = next(b for b in buckets if b["bucket_low"] == 0.7)
    assert bucket_70["count"] == 3
    assert bucket_70["actual_hit_rate"] == pytest.approx(2 / 3)
    bucket_50 = next(b for b in buckets if b["bucket_low"] == 0.5)
    assert bucket_50["count"] == 1
    assert bucket_50["actual_hit_rate"] == pytest.approx(1.0)


def test_expected_calibration_error_zero_when_perfectly_calibrated():
    buckets = [
        {"count": 10, "mean_predicted": 0.7, "actual_hit_rate": 0.7},
        {"count": 10, "mean_predicted": 0.5, "actual_hit_rate": 0.5},
    ]
    assert expected_calibration_error(buckets) == pytest.approx(0.0)


def test_expected_calibration_error_positive_when_miscalibrated():
    buckets = [{"count": 10, "mean_predicted": 0.9, "actual_hit_rate": 0.5}]
    assert expected_calibration_error(buckets) == pytest.approx(0.4)


def test_collect_calibration_points_uses_only_train_seasons(tmp_path):
    conn = init_db(tmp_path / "test.db")
    conn.execute("INSERT INTO teams (id, name, league) VALUES (1, 'Strong', 'L')")
    conn.execute("INSERT INTO teams (id, name, league) VALUES (2, 'Weak', 'L')")
    # training season 2022: Strong dominates
    conn.execute(
        "INSERT INTO matches (id, league, season, home_team_id, away_team_id, "
        "home_goals, away_goals, status) VALUES (1, 'L', '2022', 1, 2, 3, 0, 'finished')"
    )
    # held-out season 2023: the actual result to check calibration against
    conn.execute(
        "INSERT INTO matches (id, league, season, home_team_id, away_team_id, "
        "home_goals, away_goals, status) VALUES (2, 'L', '2023', 1, 2, 2, 1, 'finished')"
    )
    conn.commit()

    points = collect_calibration_points(conn, "L", [2022], 2023)

    assert len(points) == 3  # one point per double-chance market for the one test match
    conn.close()


def test_simulate_roi_computes_profit_and_roi():
    bets = [
        {"odds": 1.5, "won": True},
        {"odds": 2.0, "won": False},
        {"odds": 1.8, "won": True},
    ]

    result = simulate_roi(bets)

    assert result["n_bets"] == 3
    expected_profit = 0.5 - 1 + 0.8
    assert result["total_profit"] == pytest.approx(expected_profit)
    assert result["roi"] == pytest.approx(expected_profit / 3)


def test_simulate_roi_handles_no_bets():
    result = simulate_roi([])
    assert result["n_bets"] == 0
    assert result["roi"] is None


def test_run_roi_backtest_reports_unavailable_without_historical_odds(tmp_path):
    conn = init_db(tmp_path / "test.db")
    conn.execute("INSERT INTO teams (id, name, league) VALUES (1, 'A', 'L')")
    conn.execute("INSERT INTO teams (id, name, league) VALUES (2, 'B', 'L')")
    conn.execute(
        "INSERT INTO matches (id, league, season, home_team_id, away_team_id, "
        "home_goals, away_goals, status) VALUES (1, 'L', '2024', 1, 2, 1, 0, 'finished')"
    )
    conn.commit()

    result = run_roi_backtest(conn, "L", 2024)

    assert result["available"] is False
    assert "historical odds" in result["reason"].lower()
    conn.close()
