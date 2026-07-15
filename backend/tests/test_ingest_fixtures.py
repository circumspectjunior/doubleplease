import responses

from src.db import init_db
from src.ingest_fixtures import (
    fetch_fixtures,
    ingest_fixtures,
    normalize_fixture,
)


def make_raw_fixture(
    fixture_id=1001,
    status_short="NS",
    home="Arsenal",
    away="Chelsea",
    home_goals=None,
    away_goals=None,
):
    return {
        "fixture": {
            "id": fixture_id,
            "date": "2026-08-15T14:00:00+00:00",
            "status": {"short": status_short},
        },
        "league": {"id": 39, "name": "Premier League", "season": 2026},
        "teams": {"home": {"name": home}, "away": {"name": away}},
        "goals": {"home": home_goals, "away": away_goals},
    }


def test_normalize_fixture_scheduled():
    raw = make_raw_fixture()
    result = normalize_fixture(raw)

    assert result == {
        "fixture_id": 1001,
        "league": "Premier League",
        "season": "2026",
        "match_date": "2026-08-15",
        "home_team": "Arsenal",
        "away_team": "Chelsea",
        "home_goals": None,
        "away_goals": None,
        "status": "scheduled",
    }


def test_normalize_fixture_finished():
    raw = make_raw_fixture(status_short="FT", home_goals=2, away_goals=1)
    result = normalize_fixture(raw)

    assert result["status"] == "finished"
    assert result["home_goals"] == 2
    assert result["away_goals"] == 1


def test_ingest_fixtures_stores_teams_and_matches(tmp_path):
    conn = init_db(tmp_path / "test.db")
    raw_fixtures = [make_raw_fixture(fixture_id=1, home="Arsenal", away="Chelsea")]

    count = ingest_fixtures(conn, league_id=39, season=2026, fixtures=raw_fixtures)

    assert count == 1
    teams = {row["name"] for row in conn.execute("SELECT name FROM teams").fetchall()}
    assert teams == {"Arsenal", "Chelsea"}

    match = conn.execute("SELECT * FROM matches WHERE id = 1").fetchone()
    assert match["league"] == "Premier League"
    assert match["status"] == "scheduled"
    conn.close()


def test_ingest_fixtures_is_idempotent_on_rerun(tmp_path):
    conn = init_db(tmp_path / "test.db")
    raw_fixtures = [make_raw_fixture(fixture_id=1, status_short="NS")]

    ingest_fixtures(conn, league_id=39, season=2026, fixtures=raw_fixtures)

    updated_fixtures = [
        make_raw_fixture(fixture_id=1, status_short="FT", home_goals=3, away_goals=0)
    ]
    ingest_fixtures(conn, league_id=39, season=2026, fixtures=updated_fixtures)

    rows = conn.execute("SELECT * FROM matches").fetchall()
    assert len(rows) == 1
    assert rows[0]["status"] == "finished"
    assert rows[0]["home_goals"] == 3
    conn.close()


@responses.activate
def test_fetch_fixtures_calls_api_football_with_auth_header():
    responses.add(
        responses.GET,
        "https://v3.football.api-sports.io/fixtures",
        json={"response": [make_raw_fixture()]},
        status=200,
    )

    result = fetch_fixtures(league_id=39, season=2026, api_key="test-key")

    assert len(result) == 1
    sent_request = responses.calls[0].request
    assert sent_request.headers["x-apisports-key"] == "test-key"
    assert "league=39" in sent_request.url
    assert "season=2026" in sent_request.url
