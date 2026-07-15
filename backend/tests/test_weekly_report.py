from datetime import date

from src.db import init_db
from src.value_calculator import run_value_calculator
from src.weekly_report import (
    build_reliable_team_ids,
    generate_report,
    is_reliable,
    render_report,
    split_shortlist,
)


def seed_league_with_one_reliable_and_one_new_team(conn):
    """Team 1 & 2 have plenty of history; Team 3 ('NewClub') has zero games, mirroring
    the real Hull City case where the model falls back to a naive league-average
    strength and produces a spurious edge against a market that knows better."""
    conn.execute("INSERT INTO teams (id, name, league) VALUES (1, 'Home', 'Premier League')")
    conn.execute("INSERT INTO teams (id, name, league) VALUES (2, 'Away', 'Premier League')")
    conn.execute("INSERT INTO teams (id, name, league) VALUES (3, 'NewClub', 'Premier League')")

    for i in range(10):
        conn.execute(
            "INSERT INTO matches (league, season, home_team_id, away_team_id, "
            "home_goals, away_goals, status) VALUES ('Premier League', '2024', 1, 2, 1, 1, 'finished')"
        )

    # a trustworthy fixture: both teams have history
    conn.execute(
        "INSERT INTO matches (id, league, season, match_date, home_team_id, away_team_id, status) "
        "VALUES (101, 'Premier League', '2026', '2026-08-15', 1, 2, 'scheduled')"
    )
    conn.execute(
        "INSERT INTO odds (match_id, bookmaker, odds_home, odds_draw, odds_away, odds_1x, odds_x2, odds_12) "
        "VALUES (101, 'book', 2.0, 4.0, 4.0, 1.3, 1.8, 1.3)"
    )
    conn.execute(
        "INSERT INTO predictions (match_id, p_home, p_draw, p_away, p_1x, p_x2, p_12) "
        "VALUES (101, 0.5, 0.25, 0.25, 0.75, 0.55, 0.70)"
    )

    # an unreliable fixture: NewClub has zero training games
    conn.execute(
        "INSERT INTO matches (id, league, season, match_date, home_team_id, away_team_id, status) "
        "VALUES (102, 'Premier League', '2026', '2026-08-16', 3, 2, 'scheduled')"
    )
    conn.execute(
        "INSERT INTO odds (match_id, bookmaker, odds_home, odds_draw, odds_away, odds_1x, odds_x2, odds_12) "
        "VALUES (102, 'book', 1.5, 4.0, 6.0, 1.2, 2.0, 1.1)"
    )
    conn.execute(
        "INSERT INTO predictions (match_id, p_home, p_draw, p_away, p_1x, p_x2, p_12) "
        "VALUES (102, 0.5, 0.25, 0.25, 0.75, 0.50, 0.75)"
    )
    conn.commit()


def test_build_reliable_team_ids_excludes_zero_game_team(tmp_path):
    conn = init_db(tmp_path / "test.db")
    seed_league_with_one_reliable_and_one_new_team(conn)

    reliable = build_reliable_team_ids(conn, [2024])

    assert 1 in reliable["Premier League"]
    assert 2 in reliable["Premier League"]
    assert 3 not in reliable["Premier League"]
    conn.close()


def test_split_shortlist_separates_trusted_from_excluded(tmp_path):
    conn = init_db(tmp_path / "test.db")
    seed_league_with_one_reliable_and_one_new_team(conn)
    run_value_calculator(conn)
    reliable_team_ids = build_reliable_team_ids(conn, [2024])

    from src.value_calculator import get_shortlist

    shortlist = get_shortlist(conn, top_n=10)
    trusted, excluded = split_shortlist(shortlist, reliable_team_ids, top_n=10)

    assert len(trusted) == 1
    assert trusted[0]["home_team_id"] == 1
    assert len(excluded) == 1
    assert excluded[0]["home_team_id"] == 3
    conn.close()


def test_is_reliable_true_only_when_both_teams_have_enough_games():
    reliable_team_ids = {"Premier League": {1, 2}}
    assert is_reliable({"league": "Premier League", "home_team_id": 1, "away_team_id": 2}, reliable_team_ids)
    assert not is_reliable({"league": "Premier League", "home_team_id": 1, "away_team_id": 3}, reliable_team_ids)


def test_render_report_includes_trusted_table_and_excluded_section():
    trusted = [
        {
            "match_date": "2026-08-15",
            "league": "Premier League",
            "home_team": "Home",
            "away_team": "Away",
            "best_double_chance": "X2",
            "best_dc_odds": 1.8,
            "best_dc_probability": 0.55,
            "edge": 0.05,
        }
    ]
    excluded = [
        {
            "match_date": "2026-08-16",
            "league": "Premier League",
            "home_team": "NewClub",
            "away_team": "Away",
            "best_double_chance": "1X",
            "edge": 0.30,
        }
    ]

    report = render_report(trusted, excluded, date(2026, 7, 15))

    assert "Weekly Double-Chance Shortlist" in report
    assert "Home vs Away" in report
    assert "X2" in report
    assert "Excluded (1)" in report
    assert "NewClub vs Away" in report


def test_render_report_handles_empty_trusted_list():
    report = render_report([], [], date(2026, 7, 15))
    assert "No fixtures currently clear" in report


def test_generate_report_end_to_end(tmp_path):
    conn = init_db(tmp_path / "test.db")
    seed_league_with_one_reliable_and_one_new_team(conn)
    run_value_calculator(conn)

    report = generate_report(conn, [2024], top_n=10)

    assert "Home vs Away" in report
    assert "NewClub vs Away" in report
    assert "Excluded (1)" in report
    conn.close()
