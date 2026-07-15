import pytest

from src.db import init_db
from src.model_poisson import (
    DEFAULT_STRENGTH,
    compute_league_rates,
    compute_team_strengths,
    generate_predictions_for_league,
    match_outcome_probabilities,
    predict_fixture,
)


def seed_two_team_league(conn):
    """Team A (id 1) scores heavily, Team B (id 2) is weak, over 6 finished matches
    (3 as home, 3 as away each), so hand-computed expectations are easy to verify."""
    conn.execute("INSERT INTO teams (id, name, league) VALUES (1, 'Strong', 'Test League')")
    conn.execute("INSERT INTO teams (id, name, league) VALUES (2, 'Weak', 'Test League')")
    matches = [
        # home_id, away_id, home_goals, away_goals
        (1, 2, 3, 0),
        (1, 2, 2, 1),
        (1, 2, 3, 1),
        (2, 1, 0, 2),
        (2, 1, 1, 3),
        (2, 1, 0, 4),
    ]
    for i, (h, a, hg, ag) in enumerate(matches):
        conn.execute(
            "INSERT INTO matches (id, league, season, home_team_id, away_team_id, "
            "home_goals, away_goals, status) VALUES (?, 'Test League', '2024', ?, ?, ?, ?, 'finished')",
            (i + 1, h, a, hg, ag),
        )
    conn.commit()


def test_compute_league_rates(tmp_path):
    conn = init_db(tmp_path / "test.db")
    seed_two_team_league(conn)

    rates = compute_league_rates(conn, "Test League", [2024])

    # home goals: 3,2,3,0,1,0 -> avg 1.5 ; away goals: 0,1,1,2,3,4 -> avg 1.8333
    assert rates["avg_home_goals"] == pytest.approx(1.5)
    assert rates["avg_away_goals"] == pytest.approx(11 / 6)
    conn.close()


def test_compute_team_strengths_strong_team_has_high_attack_low_defense(tmp_path):
    conn = init_db(tmp_path / "test.db")
    seed_two_team_league(conn)

    strengths, league_rates = compute_team_strengths(conn, "Test League", [2024])

    strong = strengths[1]
    weak = strengths[2]
    assert strong["attack"] > 1.0
    assert strong["defense"] < 1.0
    assert weak["attack"] < 1.0
    assert weak["defense"] > 1.0
    assert strong["games"] == 6
    conn.close()


def test_compute_team_strengths_flags_low_sample(tmp_path):
    conn = init_db(tmp_path / "test.db")
    conn.execute("INSERT INTO teams (id, name, league) VALUES (1, 'A', 'L')")
    conn.execute("INSERT INTO teams (id, name, league) VALUES (2, 'B', 'L')")
    conn.execute(
        "INSERT INTO matches (id, league, season, home_team_id, away_team_id, "
        "home_goals, away_goals, status) VALUES (1, 'L', '2024', 1, 2, 1, 1, 'finished')"
    )
    conn.commit()

    strengths, _ = compute_team_strengths(conn, "L", [2024])

    assert strengths[1]["low_sample"] is True
    assert strengths[1]["games"] == 1
    conn.close()


def test_match_outcome_probabilities_symmetric_when_mus_equal():
    probs = match_outcome_probabilities(1.5, 1.5)

    assert probs["p_home"] == pytest.approx(probs["p_away"], rel=1e-6)
    assert probs["p_home"] + probs["p_draw"] + probs["p_away"] == pytest.approx(1.0, rel=1e-6)


def test_match_outcome_probabilities_favors_higher_mu():
    probs = match_outcome_probabilities(2.5, 0.8)

    assert probs["p_home"] > probs["p_away"]


def test_predict_fixture_double_chance_probabilities_are_consistent():
    home_strength = {"attack": 1.3, "defense": 0.8, "games": 20, "low_sample": False}
    away_strength = {"attack": 0.9, "defense": 1.1, "games": 20, "low_sample": False}
    league_rates = {"avg_home_goals": 1.5, "avg_away_goals": 1.2, "avg_goals_per_game": 1.35}

    prediction = predict_fixture(home_strength, away_strength, league_rates)

    assert prediction["p_1x"] == pytest.approx(prediction["p_home"] + prediction["p_draw"])
    assert prediction["p_x2"] == pytest.approx(prediction["p_draw"] + prediction["p_away"])
    assert prediction["p_12"] == pytest.approx(prediction["p_home"] + prediction["p_away"])
    total = prediction["p_home"] + prediction["p_draw"] + prediction["p_away"]
    assert total == pytest.approx(1.0, rel=1e-6)


def test_generate_predictions_for_league_stores_one_row_per_scheduled_fixture(tmp_path):
    conn = init_db(tmp_path / "test.db")
    seed_two_team_league(conn)
    conn.execute(
        "INSERT INTO matches (id, league, season, home_team_id, away_team_id, status) "
        "VALUES (7, 'Test League', '2025', 1, 2, 'scheduled')"
    )
    conn.commit()

    count = generate_predictions_for_league(conn, "Test League", [2024])

    assert count == 1
    pred = conn.execute("SELECT * FROM predictions WHERE match_id = 7").fetchone()
    assert pred is not None
    assert pred["p_home"] > pred["p_away"]  # strong team at home vs weak team
    conn.close()


def test_generate_predictions_uses_default_strength_for_unseen_team(tmp_path):
    conn = init_db(tmp_path / "test.db")
    seed_two_team_league(conn)
    conn.execute("INSERT INTO teams (id, name, league) VALUES (3, 'NewlyPromoted', 'Test League')")
    conn.execute(
        "INSERT INTO matches (id, league, season, home_team_id, away_team_id, status) "
        "VALUES (7, 'Test League', '2025', 3, 1, 'scheduled')"
    )
    conn.commit()

    count = generate_predictions_for_league(conn, "Test League", [2024])

    assert count == 1
    pred = conn.execute("SELECT * FROM predictions WHERE match_id = 7").fetchone()
    assert pred["p_home"] + pred["p_draw"] + pred["p_away"] == pytest.approx(1.0, rel=1e-6)
    conn.close()
