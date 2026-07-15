import pytest

from src.db import init_db
from src.team_matching import find_match_id, find_or_create_team, name_similarity


def test_name_similarity_ignores_club_suffixes():
    assert name_similarity("Fulham FC", "Fulham") > 0.99
    assert name_similarity("Arsenal", "Arsenal FC") > 0.99


def test_name_similarity_low_for_unrelated_names():
    assert name_similarity("Fulham", "Arsenal") < 0.5


@pytest.mark.parametrize(
    "oddspapi_name,api_football_name",
    [
        ("Newcastle United", "Newcastle"),
        ("Tottenham Hotspur", "Tottenham"),
        ("Leeds United", "Leeds"),
        ("Ipswich Town", "Ipswich"),
        ("Brighton & Hove Albion", "Brighton"),
        ("Inter Milano", "Inter"),
        ("Juventus Turin", "Juventus"),
        ("Lazio Rome", "Lazio"),
        ("Genoa CFC", "Genoa"),
        ("Udinese Calcio", "Udinese"),
        ("Como 1907", "Como"),
        ("Olympique Marseille", "Marseille"),
        ("Olympique Lyon", "Lyon"),
        ("Racing Club De Lens", "Lens"),
        ("Lille OSC", "Lille"),
        ("Real Sociedad San Sebastian", "Real Sociedad"),
        ("Athletic Bilbao", "Athletic Club"),
        ("Stade Rennais FC", "Rennes"),
    ],
)
def test_name_similarity_resolves_real_world_provider_mismatches(oddspapi_name, api_football_name):
    assert name_similarity(oddspapi_name, api_football_name) >= 0.75


def test_name_similarity_does_not_confuse_similarly_named_different_clubs():
    # Man United vs Man City share "Manchester" but are different clubs -
    # "United"/"City" is the actually-distinguishing token, so must not be treated
    # as generic filler the way suffix-stripping treats "FC"/"Calcio"/etc.
    assert name_similarity("Manchester United", "Manchester City") < 0.75


@pytest.mark.parametrize(
    "variant_a,variant_b",
    [
        ("VfL Bochum", "Vfl Bochum"),  # case drift within API-Football itself
        ("Borussia Monchengladbach", "Borussia Mönchengladbach"),  # diacritic drift
        ("Bayern Munich", "Bayern München"),  # EN/DE translation, needs the alias
        ("TSG Hoffenheim", "1899 Hoffenheim"),  # generic org prefix vs founding year
        ("SC Paderborn 07", "Paderborn"),  # generic prefix + trailing founding year
        ("FC Schalke 04", "Schalke"),
        ("1. FC Köln", "FC Cologne"),  # EN/DE city name, needs the alias
        ("Hamburger SV", "Hamburger"),  # trailing generic token
    ],
)
def test_name_similarity_resolves_intra_and_cross_provider_drift(variant_a, variant_b):
    assert name_similarity(variant_a, variant_b) >= 0.75


def test_find_or_create_team_reuses_existing_row_via_fuzzy_match(tmp_path):
    conn = init_db(tmp_path / "test.db")
    conn.execute("INSERT INTO teams (name, league) VALUES ('Fulham', 'Premier League')")
    conn.commit()

    team_id = find_or_create_team(conn, "Fulham FC", "Premier League")

    row = conn.execute("SELECT name FROM teams WHERE id = ?", (team_id,)).fetchone()
    assert row["name"] == "Fulham"
    count = conn.execute("SELECT COUNT(*) AS c FROM teams").fetchone()["c"]
    assert count == 1
    conn.close()


def test_find_or_create_team_creates_new_row_when_no_close_match(tmp_path):
    conn = init_db(tmp_path / "test.db")
    conn.execute("INSERT INTO teams (name, league) VALUES ('Arsenal', 'Premier League')")
    conn.commit()

    team_id = find_or_create_team(conn, "Chelsea FC", "Premier League")

    row = conn.execute("SELECT name FROM teams WHERE id = ?", (team_id,)).fetchone()
    assert row["name"] == "Chelsea FC"
    conn.close()


def test_find_match_id_matches_despite_fc_suffix(tmp_path):
    conn = init_db(tmp_path / "test.db")
    conn.execute("INSERT INTO teams (id, name, league) VALUES (1, 'Fulham', 'Premier League')")
    conn.execute("INSERT INTO teams (id, name, league) VALUES (2, 'Arsenal', 'Premier League')")
    conn.execute(
        "INSERT INTO matches (id, league, match_date, home_team_id, away_team_id, status) "
        "VALUES (1, 'Premier League', '2026-08-15', 2, 1, 'scheduled')"
    )
    conn.commit()

    match_id = find_match_id(conn, "Arsenal FC", "Fulham FC", "2026-08-15")

    assert match_id == 1
    conn.close()


def test_find_match_id_returns_none_when_nothing_close(tmp_path):
    conn = init_db(tmp_path / "test.db")
    conn.execute("INSERT INTO teams (id, name, league) VALUES (1, 'Fulham', 'Premier League')")
    conn.execute("INSERT INTO teams (id, name, league) VALUES (2, 'Arsenal', 'Premier League')")
    conn.execute(
        "INSERT INTO matches (id, league, match_date, home_team_id, away_team_id, status) "
        "VALUES (1, 'Premier League', '2026-08-15', 2, 1, 'scheduled')"
    )
    conn.commit()

    match_id = find_match_id(conn, "Coventry City", "Hull City", "2026-08-15")

    assert match_id is None
    conn.close()
