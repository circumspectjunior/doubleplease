from __future__ import annotations

import argparse
import sqlite3
from datetime import date

from src import config
from src.db import init_db
from src.model_poisson import MIN_GAMES_FOR_RELIABLE_STRENGTH, compute_team_strengths
from src.value_calculator import MAX_TRUSTED_EDGE, get_shortlist

DISCLAIMER = (
    "Decision-support only, not a guarantee - see build-plan.md (Sections 1 & 11) and "
    "review.md's backtest results before acting on any of this. Rows marked ⚠️ have "
    "an edge over 20 percentage points, which Section 6 flags as more likely a data/model "
    "issue than genuine market inefficiency."
)


def build_reliable_team_ids(conn: sqlite3.Connection, seasons: list) -> dict:
    """league name -> set of team_ids with enough historical games in `seasons` to
    trust their attack/defense estimate (see model_poisson.MIN_GAMES_FOR_RELIABLE_STRENGTH).
    A team absent from a league's strengths entirely (zero games) is never reliable."""
    reliable = {}
    for league in config.LEAGUES:
        strengths, _ = compute_team_strengths(conn, league["name"], seasons)
        reliable[league["name"]] = {
            team_id
            for team_id, s in strengths.items()
            if s["games"] >= MIN_GAMES_FOR_RELIABLE_STRENGTH
        }
    return reliable


def is_reliable(row: dict, reliable_team_ids: dict) -> bool:
    reliable_ids = reliable_team_ids.get(row["league"], set())
    return row["home_team_id"] in reliable_ids and row["away_team_id"] in reliable_ids


def split_shortlist(shortlist: list, reliable_team_ids: dict, top_n: int) -> tuple:
    trusted, excluded = [], []
    for row in shortlist:
        if is_reliable(row, reliable_team_ids):
            if len(trusted) < top_n:
                trusted.append(row)
        else:
            excluded.append(row)
    return trusted, excluded


def _pick_row(row: dict) -> str:
    flag = " ⚠️" if abs(row["edge"]) > MAX_TRUSTED_EDGE else ""
    return (
        f"| {row['match_date']} | {row['league']} | {row['home_team']} vs {row['away_team']} "
        f"| {row['best_double_chance']} | {row['best_dc_odds']:.2f} | "
        f"{row['best_dc_probability']:.0%} | {row['edge']:+.1%}{flag} |"
    )


def render_report(trusted: list, excluded: list, report_date: date) -> str:
    lines = [f"# Weekly Double-Chance Shortlist — {report_date.isoformat()}", "", DISCLAIMER, ""]

    if trusted:
        lines += [
            "| Date | League | Match | Pick | Odds | Model Prob | Edge |",
            "|------|--------|-------|------|------|-----------|------|",
        ]
        lines += [_pick_row(row) for row in trusted]
    else:
        lines.append("No fixtures currently clear both the edge and data-reliability bar.")

    if excluded:
        lines += [
            "",
            f"## Excluded ({len(excluded)}) — insufficient historical data for at least one team",
            "",
            "These showed an apparent edge, but one team has too few (or zero) games in the "
            "training data to trust the model's estimate for it - see review.md's Hull City example.",
            "",
            "| Date | League | Match | Would-be pick | Edge |",
            "|------|--------|-------|----------------|------|",
        ]
        lines += [
            f"| {row['match_date']} | {row['league']} | {row['home_team']} vs {row['away_team']} "
            f"| {row['best_double_chance']} | {row['edge']:+.1%} |"
            for row in excluded
        ]

    return "\n".join(lines) + "\n"


def generate_report(conn: sqlite3.Connection, seasons: list, top_n: int = 20) -> str:
    reliable_team_ids = build_reliable_team_ids(conn, seasons)
    shortlist = get_shortlist(conn, top_n=top_n * 3)  # over-fetch; some will be filtered out
    trusted, excluded = split_shortlist(shortlist, reliable_team_ids, top_n)
    return render_report(trusted, excluded, date.today())


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate the weekly double-chance shortlist report")
    parser.add_argument("--top", type=int, default=20)
    parser.add_argument("--seasons", nargs="+", type=int, default=config.HISTORICAL_SEASONS)
    args = parser.parse_args()

    conn = init_db(config.DB_PATH)
    report = generate_report(conn, args.seasons, args.top)

    reports_dir = config.BACKEND_ROOT / "data" / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    out_path = reports_dir / f"weekly_{date.today().isoformat()}.md"
    out_path.write_text(report)

    print(f"Report written to {out_path}\n")
    print(report)
    conn.close()


if __name__ == "__main__":
    main()
