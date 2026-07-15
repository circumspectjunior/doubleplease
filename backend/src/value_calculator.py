from __future__ import annotations

import argparse
import sqlite3

from src import config
from src.db import init_db

# Section 6's caution: an edge this large against a liquid soccer market is more
# likely a data/model bug than genuine value - flagged, not discarded, so the
# report can show it with a caveat rather than hide it.
MAX_TRUSTED_EDGE = 0.20

_OUTCOME_TO_ODDS_COLUMN = {"1X": "odds_1x", "X2": "odds_x2", "12": "odds_12"}


def normalize_1x2(odds_home: float, odds_draw: float, odds_away: float) -> dict:
    """Removes the bookmaker's overround from the 1X2 market to get fair probabilities.
    This is the one native double-chance-adjacent market that's a true partition
    (mutually exclusive + exhaustive), so it's the theoretically sound basis for
    normalization - the double-chance market's 3 quoted prices overlap in outcome
    space (1X and 12 both include a home win), so overround-normalizing them
    directly the way Section 6 describes generically isn't well-founded."""
    raw_home = 1 / odds_home
    raw_draw = 1 / odds_draw
    raw_away = 1 / odds_away
    overround = raw_home + raw_draw + raw_away
    return {
        "home": raw_home / overround,
        "draw": raw_draw / overround,
        "away": raw_away / overround,
        "overround": overround,
    }


def implied_double_chance_fair(fair_1x2: dict) -> dict:
    return {
        "1X": fair_1x2["home"] + fair_1x2["draw"],
        "X2": fair_1x2["draw"] + fair_1x2["away"],
        "12": fair_1x2["home"] + fair_1x2["away"],
    }


def compute_edges(model_probs: dict, implied_fair: dict) -> dict:
    return {
        "1X": model_probs["p_1x"] - implied_fair["1X"],
        "X2": model_probs["p_x2"] - implied_fair["X2"],
        "12": model_probs["p_12"] - implied_fair["12"],
    }


def evaluate_bookmaker_odds(model_probs: dict, odds_row) -> dict:
    fair_1x2 = normalize_1x2(odds_row["odds_home"], odds_row["odds_draw"], odds_row["odds_away"])
    implied_fair = implied_double_chance_fair(fair_1x2)
    edges = compute_edges(model_probs, implied_fair)
    return {"fair_1x2": fair_1x2, "implied_fair_dc": implied_fair, "edges": edges}


def get_latest_odds_per_bookmaker(conn: sqlite3.Connection, match_id: int) -> list:
    """Odds are stored as time-stamped snapshots (fetched_at) so movement can be
    tracked, but a "current best price" query must only compare each bookmaker's
    most recent snapshot - otherwise a stale price from an earlier ingestion run
    could still win the "best edge" comparison against today's real price."""
    return conn.execute(
        """
        SELECT o.* FROM odds o
        INNER JOIN (
            SELECT bookmaker, MAX(id) AS max_id FROM odds WHERE match_id = ? GROUP BY bookmaker
        ) latest ON o.id = latest.max_id
        """,
        (match_id,),
    ).fetchall()


def best_pick_for_match(conn: sqlite3.Connection, match_id: int, prediction_row) -> dict | None:
    """Across each bookmaker's latest odds for this match, finds the (bookmaker,
    outcome) pair with the highest edge - i.e. the best price actually shoppable
    for the outcome the model thinks the market is most wrong about."""
    odds_rows = get_latest_odds_per_bookmaker(conn, match_id)

    model_probs = {
        "p_1x": prediction_row["p_1x"],
        "p_x2": prediction_row["p_x2"],
        "p_12": prediction_row["p_12"],
    }
    model_prob_by_outcome = {"1X": model_probs["p_1x"], "X2": model_probs["p_x2"], "12": model_probs["p_12"]}

    best = None
    for row in odds_rows:
        if row["odds_home"] is None or row["odds_draw"] is None or row["odds_away"] is None:
            continue  # need the full 1X2 triple for a sound overround calc
        evaluation = evaluate_bookmaker_odds(model_probs, row)

        for outcome, edge in evaluation["edges"].items():
            outcome_odds = row[_OUTCOME_TO_ODDS_COLUMN[outcome]]
            if outcome_odds is None:
                continue
            if best is None or edge > best["edge"]:
                best = {
                    "match_id": match_id,
                    "bookmaker": row["bookmaker"],
                    "outcome": outcome,
                    "edge": edge,
                    "model_probability": model_prob_by_outcome[outcome],
                    "odds": outcome_odds,
                    "suspect": abs(edge) > MAX_TRUSTED_EDGE,
                }
    return best


def get_latest_predictions(conn: sqlite3.Connection) -> list:
    return conn.execute(
        """
        SELECT p.* FROM predictions p
        INNER JOIN (SELECT match_id, MAX(id) AS max_id FROM predictions GROUP BY match_id) latest
        ON p.id = latest.max_id
        """
    ).fetchall()


def update_predictions_with_value(conn: sqlite3.Connection, prediction_id: int, best: dict) -> None:
    conn.execute(
        """
        UPDATE predictions
        SET best_double_chance = ?, best_dc_probability = ?, best_dc_odds = ?, edge = ?
        WHERE id = ?
        """,
        (best["outcome"], best["model_probability"], best["odds"], best["edge"], prediction_id),
    )


def run_value_calculator(conn: sqlite3.Connection) -> int:
    count = 0
    for prediction in get_latest_predictions(conn):
        best = best_pick_for_match(conn, prediction["match_id"], prediction)
        if best is None:
            continue
        update_predictions_with_value(conn, prediction["id"], best)
        count += 1
    conn.commit()
    return count


def get_shortlist(conn: sqlite3.Connection, top_n: int = 20) -> list:
    rows = conn.execute(
        """
        SELECT p.*, m.match_date, m.league, m.home_team_id, m.away_team_id,
               h.name AS home_team, a.name AS away_team
        FROM predictions p
        INNER JOIN (SELECT match_id, MAX(id) AS max_id FROM predictions GROUP BY match_id) latest
            ON p.id = latest.max_id
        JOIN matches m ON p.match_id = m.id
        JOIN teams h ON m.home_team_id = h.id
        JOIN teams a ON m.away_team_id = a.id
        WHERE p.edge IS NOT NULL
        ORDER BY p.edge DESC
        LIMIT ?
        """,
        (top_n,),
    ).fetchall()
    return [dict(row) for row in rows]


def main() -> None:
    parser = argparse.ArgumentParser(description="Compute edge vs market for stored predictions")
    parser.add_argument("--top", type=int, default=20)
    args = parser.parse_args()

    conn = init_db(config.DB_PATH)
    count = run_value_calculator(conn)
    print(f"Computed edge for {count} matches")

    for row in get_shortlist(conn, args.top):
        flag = " (SUSPECT)" if abs(row["edge"]) > MAX_TRUSTED_EDGE else ""
        print(
            f"{row['match_date']} {row['home_team']} vs {row['away_team']} "
            f"[{row['league']}]: {row['best_double_chance']} @ {row['best_dc_odds']} "
            f"edge={row['edge']:+.3f}{flag}"
        )
    conn.close()


if __name__ == "__main__":
    main()
