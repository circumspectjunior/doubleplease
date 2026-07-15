import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS teams (
  id INTEGER PRIMARY KEY,
  name TEXT UNIQUE NOT NULL,
  league TEXT
);

CREATE TABLE IF NOT EXISTS matches (
  id INTEGER PRIMARY KEY,
  league TEXT,
  season TEXT,
  match_date DATE,
  home_team_id INTEGER REFERENCES teams(id),
  away_team_id INTEGER REFERENCES teams(id),
  home_goals INTEGER,
  away_goals INTEGER,
  status TEXT
);

CREATE TABLE IF NOT EXISTS odds (
  id INTEGER PRIMARY KEY,
  match_id INTEGER REFERENCES matches(id),
  bookmaker TEXT,
  fetched_at TIMESTAMP,
  odds_home REAL,
  odds_draw REAL,
  odds_away REAL,
  odds_1x REAL,
  odds_x2 REAL,
  odds_12 REAL
);

CREATE TABLE IF NOT EXISTS predictions (
  id INTEGER PRIMARY KEY,
  match_id INTEGER REFERENCES matches(id),
  generated_at TIMESTAMP,
  p_home REAL,
  p_draw REAL,
  p_away REAL,
  p_1x REAL,
  p_x2 REAL,
  p_12 REAL,
  best_double_chance TEXT,
  best_dc_probability REAL,
  best_dc_odds REAL,
  edge REAL
);
"""


def get_connection(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: Path) -> sqlite3.Connection:
    conn = get_connection(db_path)
    conn.executescript(SCHEMA)
    conn.commit()
    return conn
