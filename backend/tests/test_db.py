from src.db import init_db


def test_init_db_creates_all_tables(tmp_path):
    db_path = tmp_path / "test.db"
    conn = init_db(db_path)

    tables = {
        row["name"]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }

    assert {"teams", "matches", "odds", "predictions"} <= tables
    conn.close()


def test_init_db_is_idempotent(tmp_path):
    db_path = tmp_path / "test.db"
    init_db(db_path).close()
    conn = init_db(db_path)  # should not raise on re-run

    conn.execute(
        "INSERT INTO teams (name, league) VALUES ('Arsenal', 'EPL')"
    )
    conn.commit()

    row = conn.execute("SELECT name FROM teams WHERE name = 'Arsenal'").fetchone()
    assert row["name"] == "Arsenal"
    conn.close()
