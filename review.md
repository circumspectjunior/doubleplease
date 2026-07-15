# Review

Tracks what has actually been implemented against [build-plan.md](build-plan.md), phase by phase.

## Repo structure

Split into `backend/` (Python ingestion, prediction engine, value calculator, backtesting,
reporting, and a FastAPI layer) and `frontend/` (a React + Vite dashboard - see the
"API + dashboard" section below). `.env` lives in `backend/` and is gitignored;
`backend/.env.example` documents the required keys.

## Phase 1 — Fixtures ingestion (`backend/src/ingest_fixtures.py`)

- `fetch_fixtures(league_id, season)` calls API-Football v3 `/fixtures` with the
  `x-apisports-key` header.
- `normalize_fixture()` flattens the API response into the `matches`/`teams` schema
  from build-plan Section 4.
- `upsert_team()` resolves team names via fuzzy matching (`team_matching.py`, see
  below) rather than exact string match - necessary because API-Football itself
  spells some clubs inconsistently across seasons (e.g. "VfL Bochum" vs "Vfl Bochum",
  "Bayern Munich" vs "Bayern München"), which was silently fragmenting one club's
  historical record across two team rows before this was caught and fixed.
- `upsert_match()` keys matches on the API-Football fixture id (used directly as
  `matches.id`), so re-running ingestion updates existing rows instead of duplicating.
- **Verified live** against real seasons: the free tier only permits **seasons
  2022-2024** (confirmed by testing - 2025 returns "Free plans do not have access to
  this season"), and date-based queries are restricted to roughly a 1-day window
  around today. This is more restrictive than build-plan Section 3 assumed, and
  matters a lot in practice: it means API-Football's free tier alone cannot supply
  "this week's fixtures" once the current season is more than a day away.

## Phase 2 — Odds ingestion (`backend/src/ingest_odds.py`)

Originally built from build-plan Section 3's description before any live verification
was possible; that version has since been **replaced** with one verified against the
real OddsPapi v4 API (base URL `https://api.oddspapi.io/v4`, `apiKey` as a query
param, not the `Authorization: Bearer` header originally assumed):

- `fetch_fixture_metadata()` calls `/v4/fixtures?tournamentId=` - OddsPapi's free tier
  is **not** restricted to a narrow date window the way API-Football's is, so it
  became the source for discovering fixtures scheduled weeks/months out (API-Football
  supplies historical results; OddsPapi supplies near-term fixtures + odds).
- `fetch_odds_for_tournaments()` calls `/v4/odds-by-tournaments`, combining all 5
  leagues into one request per bookmaker (confirmed live) instead of one request per
  league, to conserve API calls.
- Verified live: market `101` = Full Time Result (1X2), market `101902` = Double
  Chance Full Time (outcomes `1X`/`12`/`2X`, mapped to our `odds_x2` column).
- Since OddsPapi doesn't embed team names in its odds response (only opaque
  participant IDs) and doesn't share fixture IDs with API-Football, fixtures are
  matched/created via fuzzy team-name + date matching (`ensure_match()`), creating a
  new `matches` row (status='scheduled') when API-Football hasn't surfaced that
  fixture yet.
- `run_weekly_pipeline.sh`'s odds step deliberately re-inserts a fresh `odds` row per
  bookmaker on every run (time-series design, per `fetched_at`) rather than
  overwriting - `value_calculator.py`'s `get_latest_odds_per_bookmaker()` is what
  keeps repeated runs from serving stale prices (see the "Bugs found" section below).

## Team-name matching (`backend/src/team_matching.py`)

Added because API-Football and OddsPapi routinely spell the same club differently,
and because API-Football spells the same club differently across its own seasons.
Verified live to find and fix real cases, not just the theoretical ones -
`normalize_team_name()` lowercases, strips diacritics (NFKD), and strips a curated
set of generic club-organization tokens ("FC", "SC", "Calcio", "VfL", "TSG", bare
founding-year digits, etc.) from either end of the name before comparing tokens.
Deliberately **not** included in that generic set: words like "United"/"City"/"Real"
that look generic but are actually load-bearing for identity (Manchester United vs
Manchester City; Real Madrid vs Real Sociedad vs Real Betis) - a first version that
allowed whole-string character-level similarity as a fallback scored "Manchester
United" vs "Manchester City" at **0.81**, well above the merge threshold, and was
removed once a test caught it.

A small, explicitly non-exhaustive alias list covers cases neither tokens nor
diacritic-stripping can bridge: `Athletic Bilbao`/`Athletic Club`, `Stade Rennais`/
`Rennes`, `Stade Brest`/`Stade Brestois` (demonyms vs city names), and `Bayern
Munich`/`Bayern München`, `Cologne`/`Köln` (EN/DE city-name translations).

## Bugs found and fixed while verifying against real data

Running the pipeline against real data (rather than only mocked tests) surfaced
issues no amount of mocked-API testing would have caught:

1. **Team identity fragmentation.** Before the fix, 38 of 164 teams in the live
   database were spurious duplicates - some genuinely new clubs (pre-season friendly
   opponents like Hull City, Coventry City), but many were real mismatches: Tottenham,
   Newcastle, Inter, Juventus, Lazio, Marseille, Lyon, PSG, and others were all being
   treated as brand-new "average" teams because OddsPapi's fuller names ("Tottenham
   Hotspur", "Inter Milano", "Paris Saint-Germain") didn't match API-Football's
   shorter ones ("Tottenham", "Inter", "Paris Saint Germain"). This directly corrupted
   the model's predictions for those matches. Fixed by the improved
   `team_matching.py`; verified by re-deriving team counts per league (down from as
   many as 32 to a realistic 23-26 per league across 3 seasons of promotion/relegation)
   and spot-checking that marquee fixtures (Barcelona vs Athletic Club, 1. FC Köln vs
   1899 Hoffenheim) now correctly link to their real historical stats.
2. **Duplicate report rows on repeated runs.** `value_calculator.get_shortlist()`
   originally selected any prediction row with `edge IS NOT NULL`, but predictions
   (and odds) are intentionally stored as time-stamped snapshots across pipeline
   runs - so a second run of the pipeline made every row in the weekly report appear
   twice. Fixed by joining against the latest prediction per match (mirroring
   `get_latest_predictions()`), and by adding `get_latest_odds_per_bookmaker()` so
   `best_pick_for_match()` compares each bookmaker's *current* price rather than
   possibly picking a stale snapshot from an earlier run. Caught by manually running
   `run_weekly_pipeline.sh` twice and noticing every row duplicated - regression tests
   added (`test_get_shortlist_does_not_duplicate_rows_across_repeated_runs`,
   `test_best_pick_for_match_ignores_stale_odds_snapshot`).
3. **Secrets exposed in local tool output/logs.** Unrelated to app code: a command
   printed the real OddsPapi API key in plaintext (via its `/account` response and
   later an HTTP error's URL) into this session's local logs. Not pushed anywhere;
   flagged to the user, and `ingest_odds.py`/`ingest_fixtures.py` were routed through
   `http_utils.get_json()`, which redacts `apiKey` from any error message it raises so
   this can't recur through that path.

## Phase 3 — Poisson prediction engine (`backend/src/model_poisson.py`)

Implements build-plan Section 5 exactly: attack/defense strength per team (goals
scored/conceded per game, normalized against the league average), expected goals per
fixture (`league_avg_home_goals × attack × opponent_defense`), and a full Poisson
scoreline matrix (vectorized with numpy/scipy) summed into home/draw/away and derived
double-chance probabilities. Teams with fewer than 5 games in the training window
(`MIN_GAMES_FOR_RELIABLE_STRENGTH`) fall back to a league-average (1.0/1.0) strength
rather than an unstable estimate, per Section 5's "newly promoted team" caveat - and
are flagged `low_sample` so downstream steps know not to trust them (see Phase 6).

Trained on real historical data: 5,341 finished matches across the top 5 European
leagues, seasons 2022-2024 (API-Football's free-tier limit). Generates 48 real
predictions for real scheduled fixtures (mostly the 2026-27 season openers in late
August, discovered via OddsPapi - see Phase 1/2 notes on why API-Football alone
couldn't supply these).

## Phase 4 — Value calculator (`backend/src/value_calculator.py`)

Implements build-plan Section 6 with one deliberate refinement: overround
normalization is computed from the **1X2 market** (a true mutually-exclusive,
exhaustive partition), and the double-chance implied probabilities are *derived*
from those fair 1X2 probabilities (`p_1x_fair = p_home_fair + p_draw_fair`, etc.)
rather than overround-normalizing the double-chance market's 3 quoted prices
directly - those three outcomes overlap in outcome space (1X and 12 both include a
home win), so treating them as a single normalizable market the way Section 6
describes generically isn't theoretically sound.

For each match, shops across every bookmaker's *latest* odds for the single best
(bookmaker, outcome) combination by edge. Edges over 20 percentage points are flagged
`suspect` (not discarded) per Section 6's explicit caution that such edges are more
often a data/model bug than genuine market inefficiency - and in practice, every
suspect-flagged match in the real output traced back to exactly that: a team with
insufficient historical data (see Phase 6).

## Phase 5 — Backtesting (`backend/src/backtest.py`)

**Calibration** (Section 7's core check - "of matches predicted ~70%, did roughly 70%
actually hit?") is real and running against real data: trained on 2022-2023, tested
against the held-out 2024 season, pooling all three double-chance markets into
probability buckets. Results, honestly reported:

| League | Data points | Expected Calibration Error |
|---|---|---|
| Serie A | 1140 | 0.019 |
| La Liga | 1140 | 0.028 |
| Premier League | 1140 | 0.043 |
| Ligue 1 | 924 | 0.060 |
| Bundesliga | 924 | 0.061 |

(0 = perfect calibration; these are genuinely encouraging numbers, not cherry-picked -
Serie A/La Liga/Premier League track predicted-vs-actual closely across most
probability buckets. Bundesliga/Ligue 1 are weaker, plausibly because 18-team leagues
give less data per team than the 20-team leagues, and some of their probability
buckets have too few matches to be statistically meaningful.)

**ROI backtesting** (Section 7's second check) is implemented and unit-tested
(`simulate_roi()`), but **does not run against real data**: verified live that
neither API-Football's `/odds` endpoint nor OddsPapi's `/historical-odds` endpoint
return historical odds on the free tier (both return empty/"not found" for real
finished-match fixture ids). Rather than fabricate a synthetic ROI number - which
could seriously mislead a real betting decision - `run_roi_backtest()` reports this
unavailability explicitly. A real ROI backtest needs a paid historical-odds source.

## Phase 6 — Weekly report + automation (`backend/src/weekly_report.py`)

Outputs the top-N shortlist ranked by edge as a Markdown table (written to
`backend/data/reports/weekly_<date>.md`), with an explicit disclaimer linking back to
build-plan Sections 1 & 11. Critically, it **excludes** matches where either team
falls below the reliable-sample threshold from the trusted table, moving them to a
separate "Excluded" section instead - directly motivated by the real Hull City vs
Manchester United case (a 37% "edge" driven entirely by the model defaulting an
unknown team to "league average," not genuine value).

**Automation:** a cloud-scheduled routine was considered but rejected - it would run
on a fresh git checkout with no access to `backend/.env`, and the only way to
authenticate it would be embedding the real API keys directly into the routine's
cloud-stored prompt. Given this session already had two accidental local key
exposures, that tradeoff was surfaced to the user explicitly rather than done
silently; a **local cron job** was set up instead (`backend/run_weekly_pipeline.sh`,
every Monday 9am local time via `crontab`), which uses the existing local `.env` and
never sends keys anywhere. It only runs while the machine is on.

## API + dashboard (`backend/src/api.py`, `frontend/`)

A FastAPI layer (`/api/leagues`, `/api/shortlist`, `/api/calibration`, `/api/status`)
sits in front of the same modules the CLI pipeline uses - no duplicated logic, the
API just calls `value_calculator.get_shortlist()`, `weekly_report.split_shortlist()`,
and `backtest.run_calibration_backtest()` directly. It's read-only by design: no
endpoint triggers a live pipeline run, since that would mean exposing paid API calls
(and API keys) to a web request - see the automation note in Phase 6.

The frontend is a React + Vite dashboard (not the plain-HTML v2 the build plan
originally sketched - the user asked for filtering/sorting/charts, which needs
real interactivity). Structurally: a ranked shortlist (matching `weekly_report.py`'s
trusted/excluded split exactly, including the same reliable-sample filtering), a
league filter, an edge/date sort toggle, and a calibration section with one
small-multiple chart per league (predicted-vs-actual against build-plan Section 7's
diagonal, plus a table-view toggle for accessibility) - loaded via the `dataviz`
skill's procedure (form → color → validate → marks → interaction → accessibility),
using the app's own gold/pitch-green identity as the single-series hue since each
chart facet has only one series and needs no categorical palette.

**A real bug caught in verification, not just written by inspection:** the
calibration chart's hover tooltip was originally wired to an invisible larger hit-
circle drawn *underneath* the visible smaller dot. In a real browser the topmost
element (the visible dot) intercepts pointer events, so the hover handler would
silently never fire - Playwright's own hover-timeout diagnostic caught this
(`element ... intercepts pointer events`), not manual inspection. Fixed by moving
the hover/focus handlers to the `<g>` wrapping both circles, which is the correct
pattern regardless of paint order.

Verified with a headless-Chromium (Playwright) script rather than just `npm run
build`: real data renders (30 ranked picks, 5 calibration charts matching the ECE
numbers above), league filtering and sort-by-date both update the list correctly,
the calibration hover tooltip and table-view toggle both work, and there are no
console errors. Screenshots checked at 1200px and a 390px mobile width.

## Test status

89/89 tests passing (`cd backend && pytest`, includes `test_api.py`). All external
HTTP calls in the test suite are mocked with `responses`/FastAPI's `TestClient`; the
real API calls described above were run manually, once, during development to
populate real data and verify the code against reality - not on every test run.

## Known limitations / what to check before trusting the weekly shortlist

- **No real ROI backtest yet** - calibration looks good, but "well-calibrated
  probabilities" and "profitable against real bookmaker margins" are different
  claims. Get a real historical-odds source before increasing confidence here.
- **The team-name alias list is not exhaustive.** It was built by inspecting real
  mismatches this session, not derived from a canonical team database. New
  mismatches will surface as new clubs get promoted/relegated or as more leagues are
  added - check each week's "Excluded" section for a well-known club appearing with
  a suspiciously large edge, the same way Hull City and Real Sociedad were caught.
- **Fixtures beyond the 2026-27 season openers aren't visible yet** - API-Football's
  free tier won't surface the current season's later fixtures until they're within
  about a day, so the weekly report may show fewer matches than expected for
  a given week until then, or until the API plan is upgraded.
- Per build-plan Section 11: treat every output as a decision aid. Backtested
  calibration on 3 seasons of 5 leagues is real signal, not proof of long-run
  profitability against efficient markets.
