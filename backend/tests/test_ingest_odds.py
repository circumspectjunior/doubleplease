import responses

from src.db import init_db
from src.ingest_fixtures import ingest_fixtures
from src.ingest_odds import (
    fetch_odds_for_date,
    find_match_id,
    ingest_odds,
    normalize_odds,
)


def make_raw_fixture(fixture_id, home, away, match_date="2026-08-15"):
    return {
        "fixture": {"id": fixture_id, "date": f"{match_date}T14:00:00+00:00", "status": {"short": "NS"}},
        "league": {"id": 39, "name": "Premier League", "season": 2026},
        "teams": {"home": {"name": home}, "away": {"name": away}},
        "goals": {"home": None, "away": None},
    }


def make_raw_odds(home="Arsenal", away="Chelsea", match_date="2026-08-15", bookmaker="bet365"):
    return {
        "home_team": home,
        "away_team": away,
        "match_date": match_date,
        "bookmaker": bookmaker,
        "markets": {
            "1x2": {"home": 1.8, "draw": 3.5, "away": 4.2},
            "double_chance": {"1x": 1.2, "x2": 1.9, "12": 1.15},
        },
    }


def seeded_conn(tmp_path):
    conn = init_db(tmp_path / "test.db")
    ingest_fixtures(
        conn,
        league_id=39,
        season=2026,
        fixtures=[make_raw_fixture(1, "Arsenal", "Chelsea")],
    )
    return conn


def test_normalize_odds_flattens_markets():
    result = normalize_odds(make_raw_odds())

    assert result == {
        "home_team": "Arsenal",
        "away_team": "Chelsea",
        "match_date": "2026-08-15",
        "bookmaker": "bet365",
        "odds_home": 1.8,
        "odds_draw": 3.5,
        "odds_away": 4.2,
        "odds_1x": 1.2,
        "odds_x2": 1.9,
        "odds_12": 1.15,
    }


def test_find_match_id_matches_by_teams_and_date(tmp_path):
    conn = seeded_conn(tmp_path)

    match_id = find_match_id(conn, "Arsenal", "Chelsea", "2026-08-15")

    assert match_id == 1
    conn.close()


def test_find_match_id_returns_none_when_no_fixture(tmp_path):
    conn = seeded_conn(tmp_path)

    match_id = find_match_id(conn, "Nowhere FC", "Ghost Town", "2026-08-15")

    assert match_id is None
    conn.close()


def test_ingest_odds_stores_row_for_known_fixture(tmp_path):
    conn = seeded_conn(tmp_path)

    count = ingest_odds(conn, "2026-08-15", raw_odds=[make_raw_odds()])

    assert count == 1
    row = conn.execute("SELECT * FROM odds WHERE match_id = 1").fetchone()
    assert row["odds_1x"] == 1.2
    assert row["bookmaker"] == "bet365"
    conn.close()


def test_ingest_odds_skips_unmatched_fixture(tmp_path):
    conn = seeded_conn(tmp_path)

    count = ingest_odds(
        conn, "2026-08-15", raw_odds=[make_raw_odds(home="Unknown", away="Team")]
    )

    assert count == 0
    assert conn.execute("SELECT COUNT(*) AS c FROM odds").fetchone()["c"] == 0
    conn.close()


@responses.activate
def test_fetch_odds_for_date_calls_oddspapi_with_auth_header():
    responses.add(
        responses.GET,
        "https://api.oddspapi.io/odds",
        json={"data": [make_raw_odds()]},
        status=200,
    )

    result = fetch_odds_for_date("2026-08-15", api_key="test-key")

    assert len(result) == 1
    sent_request = responses.calls[0].request
    assert sent_request.headers["Authorization"] == "Bearer test-key"
    assert "date=2026-08-15" in sent_request.url
