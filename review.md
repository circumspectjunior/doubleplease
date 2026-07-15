# Review

Tracks what has actually been implemented against [build-plan.md](build-plan.md), phase by phase.

## Repo structure

Split into `backend/` (Python ingestion + future prediction engine) and `frontend/`
(placeholder for the Phase 6 dashboard, not yet implemented). `.env` lives in
`backend/` and is gitignored; `backend/.env.example` documents the required keys.

## Phase 1 — Fixtures ingestion (`backend/src/ingest_fixtures.py`)

- `fetch_fixtures(league_id, season)` calls API-Football v3 `/fixtures` with the
  `x-apisports-key` header.
- `normalize_fixture()` flattens the API response into the `matches`/`teams` schema
  from build-plan Section 4.
- `upsert_team()` / `upsert_match()` write to SQLite. Matches are keyed on the
  API-Football fixture id (used directly as `matches.id`), so re-running ingestion
  updates existing rows (e.g. once a match finishes and gets a score) instead of
  duplicating them.
- Tests (`backend/tests/test_ingest_fixtures.py`, 5 tests): normalization for
  scheduled/finished fixtures, team+match storage, idempotent re-ingestion, and an
  HTTP-mocked check that the API key header and query params are sent correctly.

## Phase 2 — Odds ingestion (`backend/src/ingest_odds.py`)

- `fetch_odds_for_date(date)` calls OddsPapi's odds endpoint for a given date.
- **Assumption flagged in code:** OddsPapi's exact request/response shape wasn't
  verified against live docs (no network access in this environment) — the request
  format (`Authorization: Bearer` header, `date`/`sport` params) and response shape
  (`data: [...]` with nested `1x2`/`double_chance` markets) are best-effort and
  should be confirmed against OddsPapi's current API reference before running this
  against the real service.
- Since OddsPapi and API-Football don't share fixture IDs, odds are matched to
  stored matches by home team + away team + match date (`find_match_id()`). Odds
  for fixtures not already in the `matches` table are skipped rather than guessed.
- Each ingestion run inserts a new `odds` row per bookmaker (rather than
  overwriting), since the schema's `fetched_at` column is there to support tracking
  odds movement over time for later backtesting (Section 7).
- Tests (`backend/tests/test_ingest_odds.py`, 6 tests): market flattening, fixture
  matching (found/not found), storing odds for known fixtures, skipping unmatched
  fixtures, and an HTTP-mocked check of the auth header/query params.

## Test status

13/13 tests passing (`cd backend && pytest`). All external HTTP calls are mocked
with `responses`; no live requests were made to API-Football or OddsPapi, so API
quotas were not consumed.

## Not yet built

Phases 3-6 (Poisson prediction model, value calculator, backtesting, weekly report
+ automation) and the frontend dashboard — out of scope for this PR.
