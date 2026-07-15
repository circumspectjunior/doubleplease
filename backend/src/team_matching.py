from __future__ import annotations

import re
import sqlite3
import unicodedata

# Generic club-organization tokens that appear inconsistently across providers/seasons
# for the same real club (e.g. "VfL Bochum" vs "Vfl Bochum", "TSG Hoffenheim" vs
# "1899 Hoffenheim", "SC Paderborn 07" vs "Paderborn") - stripped from either end of
# the name, along with bare founding-year digits, before comparing. Deliberately
# excludes tokens that are actually load-bearing for identity even though they look
# generic, e.g. "United"/"City" (Manchester United vs Manchester City) or "Real"
# (Real Madrid vs Real Sociedad vs Real Betis) - those are NOT in this set.
_GENERIC_ORG_TOKENS = {
    "fc", "afc", "cf", "cfc", "sc", "osc", "sad", "if", "bk", "calcio",
    "sv", "vfb", "vfl", "tsg", "fsv", "rb", "ss", "ssc", "ud", "cd", "rc", "us", "ac",
}

# Genuine same-club name variants that token/diacritic normalization can't bridge:
# EN/DE city-name translations ("Munich"/"München", "Cologne"/"Köln" after diacritic
# stripping still differ letter-for-letter), a demonym vs city name ("Rennais" vs
# "Rennes"), and one club whose official name has no token in common with its common
# name ("Athletic Bilbao" vs "Athletic Club"). Not exhaustive - extend as new
# mismatches surface in a weekly report's "Excluded" section (see review.md).
_ALIASES = {
    "athletic bilbao": "athletic club",
    "stade rennais": "rennes",
    "stade brest": "stade brestois",
    "bayern munich": "bayern munchen",
    "cologne": "koln",
}


def _strip_diacritics(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def normalize_team_name(name: str) -> str:
    normalized = _strip_diacritics(name.lower().strip())
    normalized = re.sub(r"[&'.\-]", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()

    tokens = normalized.split()
    while len(tokens) > 1 and (tokens[0].isdigit() or tokens[0] in _GENERIC_ORG_TOKENS):
        tokens.pop(0)
    while len(tokens) > 1 and (tokens[-1].isdigit() or tokens[-1] in _GENERIC_ORG_TOKENS):
        tokens.pop()

    core = " ".join(tokens)
    return _ALIASES.get(core, core)


def _token_set(name: str) -> set:
    return set(normalize_team_name(name).split())


def name_similarity(a: str, b: str) -> float:
    """1.0 if one name's tokens are fully contained in the other's (handles e.g.
    "Inter Milano" vs "Inter", "Newcastle United" vs "Newcastle"); otherwise plain
    token Jaccard overlap. Deliberately no whole-string character-level fallback:
    that let "Manchester United" and "Manchester City" (different clubs sharing a
    long common prefix) score 0.81 - well above the merge threshold - so anything
    that pure tokens and the alias list can't bridge falls back to creating a new
    team row rather than risking a false merge."""
    tokens_a, tokens_b = _token_set(a), _token_set(b)
    if tokens_a and tokens_b and (tokens_a <= tokens_b or tokens_b <= tokens_a):
        return 1.0
    if not tokens_a and not tokens_b:
        return 0.0
    return len(tokens_a & tokens_b) / len(tokens_a | tokens_b)


def find_or_create_team(
    conn: sqlite3.Connection, name: str, league: str, threshold: float = 0.75
) -> int:
    """Resolves a team name to an existing team row via fuzzy matching (so e.g.
    OddsPapi's "Fulham FC" reuses API-Football's "Fulham" row, and API-Football's
    own "Vfl Bochum"/"VfL Bochum" spelling drift across seasons doesn't fragment
    one club into two rows). Falls back to creating a new row if nothing in the
    league matches closely enough."""
    rows = conn.execute("SELECT id, name FROM teams WHERE league = ?", (league,)).fetchall()
    best_id, best_score = None, 0.0
    for row in rows:
        score = name_similarity(name, row["name"])
        if score > best_score:
            best_id, best_score = row["id"], score

    if best_score >= threshold:
        return best_id

    conn.execute("INSERT OR IGNORE INTO teams (name, league) VALUES (?, ?)", (name, league))
    return conn.execute("SELECT id FROM teams WHERE name = ?", (name,)).fetchone()["id"]


def find_match_id(
    conn: sqlite3.Connection,
    home_name: str,
    away_name: str,
    match_date: str,
    threshold: float = 0.6,
) -> int | None:
    """Finds a stored match on a given date whose team names best fuzzy-match the
    given home/away names. Returns None if nothing clears the threshold."""
    rows = conn.execute(
        """
        SELECT m.id, h.name AS home_name, a.name AS away_name
        FROM matches m
        JOIN teams h ON m.home_team_id = h.id
        JOIN teams a ON m.away_team_id = a.id
        WHERE m.match_date = ?
        """,
        (match_date,),
    ).fetchall()

    best_id, best_score = None, 0.0
    for row in rows:
        score = name_similarity(home_name, row["home_name"]) + name_similarity(
            away_name, row["away_name"]
        )
        if score > best_score:
            best_id, best_score = row["id"], score

    return best_id if best_score >= threshold * 2 else None
