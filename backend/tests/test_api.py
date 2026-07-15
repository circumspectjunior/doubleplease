import pytest
from fastapi.testclient import TestClient

from src import api, config
from src.db import init_db
from src.value_calculator import run_value_calculator


@pytest.fixture
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setattr(config, "DB_PATH", db_path)

    conn = init_db(db_path)
    conn.execute("INSERT INTO teams (id, name, league) VALUES (1, 'Home', 'Premier League')")
    conn.execute("INSERT INTO teams (id, name, league) VALUES (2, 'Away', 'Premier League')")
    conn.execute("INSERT INTO teams (id, name, league) VALUES (3, 'NewClub', 'Premier League')")
    for _ in range(10):
        conn.execute(
            "INSERT INTO matches (league, season, home_team_id, away_team_id, "
            "home_goals, away_goals, status) VALUES ('Premier League', '2024', 1, 2, 1, 1, 'finished')"
        )
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
    run_value_calculator(conn)
    conn.close()

    return TestClient(api.app)


def test_list_leagues_returns_all_five(client):
    response = client.get("/api/leagues")
    assert response.status_code == 200
    names = {league["name"] for league in response.json()}
    assert names == {"Premier League", "La Liga", "Serie A", "Bundesliga", "Ligue 1"}


def test_shortlist_splits_trusted_and_excluded(client):
    response = client.get("/api/shortlist")
    assert response.status_code == 200
    body = response.json()

    assert len(body["trusted"]) == 1
    assert body["trusted"][0]["home_team"] == "Home"
    assert len(body["excluded"]) == 1
    assert body["excluded"][0]["home_team"] == "NewClub"


def test_shortlist_filters_by_league(client):
    response = client.get("/api/shortlist", params={"league": "La Liga"})
    body = response.json()
    assert body["trusted"] == []
    assert body["excluded"] == []


def test_shortlist_respects_top_param(client):
    response = client.get("/api/shortlist", params={"top": 1})
    assert response.status_code == 200


def test_calibration_returns_one_result_per_league(client):
    response = client.get("/api/calibration", params={"test_season": 2024})
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 5
    leagues = {r["league"] for r in body}
    assert leagues == {"Premier League", "La Liga", "Serie A", "Bundesliga", "Ligue 1"}


def test_status_reports_counts(client):
    response = client.get("/api/status")
    assert response.status_code == 200
    body = response.json()
    assert body["teams"] == 3
    assert body["matches"] == 12
    assert body["scheduled_matches"] == 2
    assert body["odds_rows"] == 2
    assert body["predictions"] == 2
