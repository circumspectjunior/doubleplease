import pytest

from src.db import init_db
from src.value_calculator import (
    MAX_TRUSTED_EDGE,
    best_pick_for_match,
    compute_edges,
    get_shortlist,
    implied_double_chance_fair,
    normalize_1x2,
    run_value_calculator,
)


def test_normalize_1x2_removes_overround():
    # implied: 0.5 + 0.25 + 0.25 = 1.0 exactly -> no margin, fair == raw
    fair = normalize_1x2(2.0, 4.0, 4.0)

    assert fair["home"] == pytest.approx(0.5)
    assert fair["draw"] == pytest.approx(0.25)
    assert fair["away"] == pytest.approx(0.25)
    assert fair["overround"] == pytest.approx(1.0)


def test_normalize_1x2_handles_real_bookmaker_margin():
    # raw implied sums to > 1 (typical margin); fair probs must still sum to 1
    fair = normalize_1x2(1.9, 3.6, 4.2)

    assert fair["overround"] > 1.0
    assert fair["home"] + fair["draw"] + fair["away"] == pytest.approx(1.0)


def test_implied_double_chance_fair_derives_from_1x2():
    fair_1x2 = {"home": 0.5, "draw": 0.25, "away": 0.25}
    implied = implied_double_chance_fair(fair_1x2)

    assert implied == {"1X": 0.75, "X2": 0.5, "12": 0.75}


def test_compute_edges_matches_hand_calculation():
    model_probs = {"p_1x": 0.75, "p_x2": 0.55, "p_12": 0.70}
    implied_fair = {"1X": 0.75, "X2": 0.5, "12": 0.75}

    edges = compute_edges(model_probs, implied_fair)

    assert edges["1X"] == pytest.approx(0.0)
    assert edges["X2"] == pytest.approx(0.05)
    assert edges["12"] == pytest.approx(-0.05)


def test_best_pick_for_match_picks_highest_edge_outcome(tmp_path):
    conn = init_db(tmp_path / "test.db")
    conn.execute("INSERT INTO teams (id, name, league) VALUES (1, 'A', 'L')")
    conn.execute("INSERT INTO teams (id, name, league) VALUES (2, 'B', 'L')")
    conn.execute(
        "INSERT INTO matches (id, league, match_date, home_team_id, away_team_id, status) "
        "VALUES (1, 'L', '2026-08-15', 1, 2, 'scheduled')"
    )
    # no-margin odds so fair == raw: home=0.5, draw=0.25, away=0.25 -> 1X=.75 X2=.5 12=.75
    conn.execute(
        "INSERT INTO odds (match_id, bookmaker, odds_home, odds_draw, odds_away, odds_1x, odds_x2, odds_12) "
        "VALUES (1, 'test_book', 2.0, 4.0, 4.0, 1.3, 1.8, 1.3)"
    )
    conn.commit()

    prediction_row = {"p_1x": 0.75, "p_x2": 0.55, "p_12": 0.70}
    best = best_pick_for_match(conn, 1, prediction_row)

    assert best["outcome"] == "X2"
    assert best["edge"] == pytest.approx(0.05)
    assert best["bookmaker"] == "test_book"
    assert best["odds"] == 1.8
    assert best["suspect"] is False
    conn.close()


def test_best_pick_for_match_flags_suspiciously_large_edge(tmp_path):
    conn = init_db(tmp_path / "test.db")
    conn.execute("INSERT INTO teams (id, name, league) VALUES (1, 'A', 'L')")
    conn.execute("INSERT INTO teams (id, name, league) VALUES (2, 'B', 'L')")
    conn.execute(
        "INSERT INTO matches (id, league, match_date, home_team_id, away_team_id, status) "
        "VALUES (1, 'L', '2026-08-15', 1, 2, 'scheduled')"
    )
    conn.execute(
        "INSERT INTO odds (match_id, bookmaker, odds_home, odds_draw, odds_away, odds_1x, odds_x2, odds_12) "
        "VALUES (1, 'test_book', 2.0, 4.0, 4.0, 1.3, 1.8, 1.3)"
    )
    conn.commit()

    # model wildly disagrees with market (implausible outside a bug) -> should be flagged
    prediction_row = {"p_1x": 0.99, "p_x2": 0.55, "p_12": 0.70}
    best = best_pick_for_match(conn, 1, prediction_row)

    assert best["outcome"] == "1X"
    assert best["edge"] > MAX_TRUSTED_EDGE
    assert best["suspect"] is True
    conn.close()


def test_best_pick_for_match_returns_none_without_full_1x2(tmp_path):
    conn = init_db(tmp_path / "test.db")
    conn.execute("INSERT INTO teams (id, name, league) VALUES (1, 'A', 'L')")
    conn.execute("INSERT INTO teams (id, name, league) VALUES (2, 'B', 'L')")
    conn.execute(
        "INSERT INTO matches (id, league, match_date, home_team_id, away_team_id, status) "
        "VALUES (1, 'L', '2026-08-15', 1, 2, 'scheduled')"
    )
    conn.execute(
        "INSERT INTO odds (match_id, bookmaker, odds_1x, odds_x2, odds_12) "
        "VALUES (1, 'test_book', 1.3, 1.8, 1.3)"
    )
    conn.commit()

    best = best_pick_for_match(conn, 1, {"p_1x": 0.75, "p_x2": 0.55, "p_12": 0.70})

    assert best is None
    conn.close()


def test_best_pick_for_match_ignores_stale_odds_snapshot(tmp_path):
    conn = init_db(tmp_path / "test.db")
    conn.execute("INSERT INTO teams (id, name, league) VALUES (1, 'A', 'L')")
    conn.execute("INSERT INTO teams (id, name, league) VALUES (2, 'B', 'L')")
    conn.execute(
        "INSERT INTO matches (id, league, match_date, home_team_id, away_team_id, status) "
        "VALUES (1, 'L', '2026-08-15', 1, 2, 'scheduled')"
    )
    # stale snapshot from an earlier pipeline run (lower id = older)
    conn.execute(
        "INSERT INTO odds (match_id, bookmaker, odds_home, odds_draw, odds_away, odds_1x, odds_x2, odds_12) "
        "VALUES (1, 'test_book', 2.0, 4.0, 4.0, 1.3, 5.0, 1.3)"
    )
    # fresh snapshot from the current run, same bookmaker - should win
    conn.execute(
        "INSERT INTO odds (match_id, bookmaker, odds_home, odds_draw, odds_away, odds_1x, odds_x2, odds_12) "
        "VALUES (1, 'test_book', 2.0, 4.0, 4.0, 1.3, 1.8, 1.3)"
    )
    conn.commit()

    best = best_pick_for_match(conn, 1, {"p_1x": 0.75, "p_x2": 0.55, "p_12": 0.70})

    assert best["outcome"] == "X2"
    assert best["odds"] == 1.8  # the fresh snapshot's price, not the stale 5.0
    conn.close()


def test_get_shortlist_does_not_duplicate_rows_across_repeated_runs(tmp_path):
    conn = init_db(tmp_path / "test.db")
    conn.execute("INSERT INTO teams (id, name, league) VALUES (1, 'A', 'L')")
    conn.execute("INSERT INTO teams (id, name, league) VALUES (2, 'B', 'L')")
    conn.execute(
        "INSERT INTO matches (id, league, match_date, home_team_id, away_team_id, status) "
        "VALUES (1, 'L', '2026-08-15', 1, 2, 'scheduled')"
    )
    conn.execute(
        "INSERT INTO odds (match_id, bookmaker, odds_home, odds_draw, odds_away, odds_1x, odds_x2, odds_12) "
        "VALUES (1, 'test_book', 2.0, 4.0, 4.0, 1.3, 1.8, 1.3)"
    )
    conn.commit()

    # simulate two pipeline runs: predict + compute value, twice
    for _ in range(2):
        conn.execute(
            "INSERT INTO predictions (match_id, p_home, p_draw, p_away, p_1x, p_x2, p_12) "
            "VALUES (1, 0.5, 0.25, 0.25, 0.75, 0.55, 0.70)"
        )
        conn.commit()
        run_value_calculator(conn)

    shortlist = get_shortlist(conn, top_n=10)

    assert len(shortlist) == 1
    conn.close()


def test_run_value_calculator_updates_latest_prediction_only(tmp_path):
    conn = init_db(tmp_path / "test.db")
    conn.execute("INSERT INTO teams (id, name, league) VALUES (1, 'A', 'L')")
    conn.execute("INSERT INTO teams (id, name, league) VALUES (2, 'B', 'L')")
    conn.execute(
        "INSERT INTO matches (id, league, match_date, home_team_id, away_team_id, status) "
        "VALUES (1, 'L', '2026-08-15', 1, 2, 'scheduled')"
    )
    conn.execute(
        "INSERT INTO odds (match_id, bookmaker, odds_home, odds_draw, odds_away, odds_1x, odds_x2, odds_12) "
        "VALUES (1, 'test_book', 2.0, 4.0, 4.0, 1.3, 1.8, 1.3)"
    )
    # stale older prediction, then the current one (higher id = latest)
    conn.execute(
        "INSERT INTO predictions (match_id, p_home, p_draw, p_away, p_1x, p_x2, p_12) "
        "VALUES (1, 0.4, 0.3, 0.3, 0.7, 0.6, 0.7)"
    )
    conn.execute(
        "INSERT INTO predictions (match_id, p_home, p_draw, p_away, p_1x, p_x2, p_12) "
        "VALUES (1, 0.5, 0.25, 0.25, 0.75, 0.55, 0.70)"
    )
    conn.commit()

    count = run_value_calculator(conn)

    assert count == 1
    rows = conn.execute("SELECT * FROM predictions ORDER BY id").fetchall()
    assert rows[0]["edge"] is None  # stale row untouched
    assert rows[1]["best_double_chance"] == "X2"
    assert rows[1]["edge"] == pytest.approx(0.05)
    conn.close()
