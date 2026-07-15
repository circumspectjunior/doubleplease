import responses

from src.db import init_db
from src.ingest_odds import (
    extract_prices,
    fetch_fixture_metadata,
    fetch_odds_for_tournaments,
    infer_season,
    ingest_odds_for_league,
)


def make_fixture_meta(
    fixture_id="id1", home="Arsenal FC", away="Fulham FC", start="2026-08-15T14:00:00.000Z"
):
    return {
        "fixtureId": fixture_id,
        "participant1Name": home,
        "participant2Name": away,
        "startTime": start,
        "tournamentId": 17,
    }


def make_odds_entry(fixture_id="id1", bookmaker="unibet", has_dc=True, has_odds=True):
    markets = {
        "101": {
            "outcomes": {
                "101": {"players": {"0": {"price": 1.8}}},
                "102": {"players": {"0": {"price": 3.5}}},
                "103": {"players": {"0": {"price": 4.2}}},
            }
        }
    }
    if has_dc:
        markets["101902"] = {
            "outcomes": {
                "101902": {"players": {"0": {"price": 1.2}}},
                "101903": {"players": {"0": {"price": 1.15}}},
                "101904": {"players": {"0": {"price": 1.9}}},
            }
        }
    return {
        "fixtureId": fixture_id,
        "hasOdds": has_odds,
        "bookmakerOdds": {bookmaker: {"markets": markets}},
    }


def test_infer_season_maps_month_to_season_start_year():
    assert infer_season("2026-08-15") == 2026
    assert infer_season("2027-03-01") == 2026


def test_extract_prices_maps_1x2_and_double_chance():
    markets = make_odds_entry()["bookmakerOdds"]["unibet"]["markets"]
    prices = extract_prices(markets)

    assert prices == {
        "odds_home": 1.8,
        "odds_draw": 3.5,
        "odds_away": 4.2,
        "odds_1x": 1.2,
        "odds_12": 1.15,
        "odds_x2": 1.9,
    }


def test_extract_prices_handles_missing_double_chance_market():
    markets = make_odds_entry(has_dc=False)["bookmakerOdds"]["unibet"]["markets"]
    prices = extract_prices(markets)

    assert prices["odds_home"] == 1.8
    assert prices["odds_1x"] is None


def test_ingest_odds_for_league_creates_match_and_stores_odds(tmp_path):
    conn = init_db(tmp_path / "test.db")

    count = ingest_odds_for_league(
        conn,
        league_name="Premier League",
        tournament_id=17,
        bookmaker="unibet",
        fixture_metadata=[make_fixture_meta()],
        odds_entries=[make_odds_entry()],
    )

    assert count == 1
    match = conn.execute("SELECT * FROM matches").fetchone()
    assert match["status"] == "scheduled"
    assert match["match_date"] == "2026-08-15"
    odds = conn.execute("SELECT * FROM odds").fetchone()
    assert odds["odds_1x"] == 1.2
    assert odds["bookmaker"] == "unibet"
    conn.close()


def test_ingest_odds_for_league_reuses_existing_match_via_fuzzy_name(tmp_path):
    conn = init_db(tmp_path / "test.db")
    conn.execute("INSERT INTO teams (id, name, league) VALUES (1, 'Arsenal', 'Premier League')")
    conn.execute("INSERT INTO teams (id, name, league) VALUES (2, 'Fulham', 'Premier League')")
    conn.execute(
        "INSERT INTO matches (id, league, match_date, home_team_id, away_team_id, status) "
        "VALUES (99, 'Premier League', '2026-08-15', 1, 2, 'scheduled')"
    )
    conn.commit()

    count = ingest_odds_for_league(
        conn,
        league_name="Premier League",
        tournament_id=17,
        bookmaker="unibet",
        fixture_metadata=[make_fixture_meta()],
        odds_entries=[make_odds_entry()],
    )

    assert count == 1
    assert conn.execute("SELECT COUNT(*) AS c FROM matches").fetchone()["c"] == 1
    odds = conn.execute("SELECT * FROM odds WHERE match_id = 99").fetchone()
    assert odds is not None
    conn.close()


def test_ingest_odds_for_league_skips_fixtures_without_odds(tmp_path):
    conn = init_db(tmp_path / "test.db")

    count = ingest_odds_for_league(
        conn,
        league_name="Premier League",
        tournament_id=17,
        bookmaker="unibet",
        fixture_metadata=[make_fixture_meta()],
        odds_entries=[make_odds_entry(has_odds=False)],
    )

    assert count == 0
    assert conn.execute("SELECT COUNT(*) AS c FROM matches").fetchone()["c"] == 0
    conn.close()


def test_ingest_odds_for_league_skips_entries_missing_metadata(tmp_path):
    conn = init_db(tmp_path / "test.db")

    count = ingest_odds_for_league(
        conn,
        league_name="Premier League",
        tournament_id=17,
        bookmaker="unibet",
        fixture_metadata=[],
        odds_entries=[make_odds_entry()],
    )

    assert count == 0
    conn.close()


@responses.activate
def test_fetch_fixture_metadata_calls_real_endpoint_shape():
    responses.add(
        responses.GET,
        "https://api.oddspapi.io/v4/fixtures",
        json=[make_fixture_meta()],
        status=200,
    )

    result = fetch_fixture_metadata(17, api_key="test-key")

    assert len(result) == 1
    sent = responses.calls[0].request
    assert "tournamentId=17" in sent.url
    assert "apiKey=test-key" in sent.url


@responses.activate
def test_fetch_odds_for_tournaments_joins_multiple_ids():
    responses.add(
        responses.GET,
        "https://api.oddspapi.io/v4/odds-by-tournaments",
        json=[make_odds_entry()],
        status=200,
    )

    result = fetch_odds_for_tournaments([17, 8, 23], "unibet", api_key="test-key")

    assert len(result) == 1
    sent = responses.calls[0].request
    assert "tournamentIds=17%2C8%2C23" in sent.url
    assert "bookmaker=unibet" in sent.url
