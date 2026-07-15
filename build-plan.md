# DoublePlease — Weekly Soccer Double-Chance Prediction App — Build Plan

**Purpose of this document:** hand this directly to Claude Code (`claude` in your terminal, or paste sections as prompts) to scaffold and build the app in phases. Each phase ends with a suggested prompt you can give Claude Code verbatim.

**Reality check up front:** this app can systematize a statistically grounded methodology and flag where your model disagrees with the bookmaker's market — that's a genuinely useful signal. It cannot guarantee 10–20 correct high-confidence picks every week. No model, including ones built by professional syndicates with far more data, does that reliably. Treat every output as a decision aid, not a certainty, and budget accordingly if real money is involved.

---

## 1. Architecture

```
Fixtures API ─┐
              ├─→ Prediction Engine ─→ Value Calculator ─→ Weekly Shortlist
Odds API ─────┘         │                    │                   │
                    (Poisson/Elo)      (edge vs market)    (top 10-20, ranked)
```

Four components, each independently testable:

1. **Data layer** — pulls this week's fixtures and current odds, stores them.
2. **Prediction engine** — estimates P(home win), P(draw), P(away win) for each match from historical data.
3. **Value calculator** — converts those into double-chance probabilities (1X, X2, 12), compares against the bookmaker's implied probability, and computes an edge.
4. **Ranking/output** — sorts by edge and/or confidence, outputs the top 10–20.

---

## 2. Tech stack recommendation

- **Language:** Python (best library support for stats/data work: `pandas`, `scipy`, `numpy`)
- **Storage:** SQLite to start (zero setup, fine for this scale); Postgres later if you want a hosted dashboard
- **Scheduling:** Claude Code Routines (runs on Anthropic-managed infra on a cron schedule, works even if your machine is off) — or a plain `cron` job if you're running it yourself
- **Output:** start with a CSV/Markdown report emailed or saved locally; a simple web dashboard (Flask + a static HTML table) is a natural v2

---

## 3. Data sources

Verify current pricing/limits yourself before committing — these change and some of what's below comes from third-party comparison sites, not just the vendors themselves.

### Fixtures + historical results — API-Football (api-football.com / api-sports.io)
This is the chosen provider for `ingest_fixtures.py`.
- Free tier: $0/month, 100 requests/day, 10 requests/minute, **all** 1,200+ competitions and endpoints unlocked (fixtures, standings, statistics, odds, predictions) — nothing gated behind paid add-ons.
- Historical seasons are available on the free tier, but depth varies by competition — check your dashboard after signup to confirm how many seasons back you can pull for the leagues you care about. If it's thinner than the 2–3 seasons the Poisson model wants, backfill the gap with football-data.co.uk's free historical CSVs (no API key needed, one-time download).
- Auth: send your key in the `x-apisports-key` header. Base URL: `https://v3.football.api-sports.io`.
- Env var: `API_FOOTBALL_KEY`

### Odds — OddsPapi (oddspapi.io)
This is the chosen provider for `ingest_odds.py`.
- Double chance (1X/X2/12) is a native market — no need to derive it yourself from 1X2 odds.
- Free tier includes broad bookmaker coverage and free historical odds, which is useful later for Section 7's backtesting.
- Env var: `ODDSPAPI_KEY`

**Stick to a licensed odds API rather than scraping bookmaker sites directly** — scraping typically violates bookmaker terms of service.

---

## 4. Data model (SQLite schema sketch)

```sql
CREATE TABLE teams (
  id INTEGER PRIMARY KEY,
  name TEXT UNIQUE,
  league TEXT
);

CREATE TABLE matches (
  id INTEGER PRIMARY KEY,
  league TEXT,
  season TEXT,
  match_date DATE,
  home_team_id INTEGER REFERENCES teams(id),
  away_team_id INTEGER REFERENCES teams(id),
  home_goals INTEGER,      -- null until played
  away_goals INTEGER,      -- null until played
  status TEXT              -- 'scheduled' | 'finished'
);

CREATE TABLE odds (
  id INTEGER PRIMARY KEY,
  match_id INTEGER REFERENCES matches(id),
  bookmaker TEXT,
  fetched_at TIMESTAMP,
  odds_home REAL,
  odds_draw REAL,
  odds_away REAL,
  odds_1x REAL,             -- double chance home-or-draw, if native
  odds_x2 REAL,             -- double chance draw-or-away, if native
  odds_12 REAL              -- double chance home-or-away, if native
);

CREATE TABLE predictions (
  id INTEGER PRIMARY KEY,
  match_id INTEGER REFERENCES matches(id),
  generated_at TIMESTAMP,
  p_home REAL,
  p_draw REAL,
  p_away REAL,
  p_1x REAL,
  p_x2 REAL,
  p_12 REAL,
  best_double_chance TEXT,  -- '1X' | 'X2' | '12'
  best_dc_probability REAL,
  best_dc_odds REAL,
  edge REAL                 -- model probability minus implied market probability
);
```

---

## 5. Prediction methodology

### Poisson goal model (recommended starting point — simple, well-documented, good enough to be useful)

For each team, compute from the last 1–3 seasons:
- **Attack strength** = team's average goals scored per game ÷ league average goals scored per game
- **Defense strength** = team's average goals conceded per game ÷ league average goals conceded per game

For a given fixture (Team A home vs Team B away):
```
expected_goals_A = league_avg_home_goals × A_attack_strength × B_defense_strength
expected_goals_B = league_avg_away_goals × B_attack_strength × A_defense_strength
```

Then model each team's goals as independent Poisson distributions with those means, and compute the full scoreline probability matrix (e.g. 0–0 through 6–6). Summing the relevant cells gives you:
- P(home win) = sum of cells where home goals > away goals
- P(draw) = sum of cells where home goals = away goals
- P(away win) = sum of cells where away goals > home goals

`scipy.stats.poisson.pmf` handles the distribution math directly — this is maybe 40 lines of Python.

**Known weaknesses to be aware of:** treats home/away goals as independent (real matches have some correlation), doesn't account for injuries, red cards, or motivation (e.g. a team with nothing left to play for), and needs a reasonable sample size per team (a newly promoted team with few matches will have unstable estimates). An Elo-rating system is a reasonable alternative or complement if you want something that adapts faster to recent form.

### Double chance probabilities
```
P(1X) = P(home win) + P(draw)
P(X2) = P(draw) + P(away win)
P(12) = P(home win) + P(away win)
```

---

## 6. Value calculator

Bookmaker odds embed a margin ("overround"), so raw implied probability from odds isn't directly comparable to your model. Normalize first:

```
implied_prob_raw = 1 / decimal_odds
overround = sum(implied_prob_raw for all outcomes in the market)
implied_prob_fair = implied_prob_raw / overround
```

Then:
```
edge = model_probability - implied_prob_fair
```

A positive edge means your model thinks the outcome is more likely than the market is pricing it — that's your "value" signal. Rank matches by edge (or by a blend of edge and model confidence) and take the top 10–20 for the week.

Be skeptical of large edges (>15–20 percentage points) on your own model — that's more often a sign of a data or model bug than a genuine market inefficiency, given how liquid soccer moneyline markets are.

---

## 7. Backtesting (do this before trusting any output)

Before running this live, validate the model against past seasons:
1. Hold out the most recent completed season.
2. Generate predictions as if it were upcoming, using only data available before each round.
3. Compare predicted double-chance probabilities against actual outcomes — check calibration (of matches where you predicted ~70% probability, did roughly 70% actually hit?).
4. Track hypothetical ROI if you'd "bet" the shortlist every week, accounting for the bookmaker's margin.

This is the single most important phase for setting realistic expectations before Section 1's caveat becomes a real financial one.

---

## 8. Weekly automation

Claude Code Routines can run this on a schedule (e.g. every Monday at 9am) on Anthropic-managed infrastructure, so it runs even if your laptop is off. Set up with `/schedule` in the CLI once the pipeline script works standalone. The routine would:
1. Pull this week's fixtures for your tracked leagues
2. Pull current odds
3. Run the prediction engine + value calculator
4. Write the top 10–20 to your chosen output (file, email, dashboard)

---

## 9. Suggested repo structure

```
doubleplease/
├── data/
│   └── predictions.db
├── src/
│   ├── ingest_fixtures.py     # API-Football
│   ├── ingest_odds.py         # OddsPapi
│   ├── model_poisson.py
│   ├── value_calculator.py
│   ├── backtest.py
│   └── weekly_report.py
├── tests/
├── .env                  # API_FOOTBALL_KEY, ODDSPAPI_KEY — never committed
├── .gitignore            # must include .env
└── README.md
```

---

## 10. Phased build — prompts for Claude Code

Run these roughly in order, in a fresh project directory with `claude` running.

**Phase 1 — scaffolding and data ingestion**
> "Set up a Python project called doubleplease with the folder structure in [paste Section 9]. Implement `ingest_fixtures.py` to pull upcoming fixtures and historical results from the API-Football v3 API (https://v3.football.api-sports.io) for [list your leagues] and store them in a SQLite database matching [paste Section 4's schema]. Read the API key from an API_FOOTBALL_KEY environment variable via a .env file — never hardcode it."

**Phase 2 — odds ingestion**
> "Implement `ingest_odds.py` to pull current odds for the fixtures already in the database from OddsPapi, storing home/draw/away odds and double chance odds (they offer this as a native market). Read the API key from an ODDSPAPI_KEY environment variable via a .env file."

**Phase 3 — prediction engine**
> "Implement `model_poisson.py`: a Poisson goal-scoring model that computes attack/defense strength per team from historical results in the database, and outputs win/draw/loss and double-chance probabilities for each upcoming fixture. Follow the approach in [paste Section 5]."

**Phase 4 — value calculator**
> "Implement `value_calculator.py` to normalize bookmaker odds for overround, compute edge (model probability minus fair implied probability) for each double chance market, and rank fixtures by edge. Follow [paste Section 6]."

**Phase 5 — backtesting**
> "Implement `backtest.py` to validate the model against a held-out past season: check calibration (predicted probability vs actual outcome frequency) and hypothetical ROI of following the weekly shortlist. Follow [paste Section 7]."

**Phase 6 — report + automation**
> "Implement `weekly_report.py` to output the top 10-20 double chance picks ranked by edge as a Markdown table, and help me set up a Claude Code Routine to run the full pipeline every Monday morning."

---

## 11. Notes on responsible use

- Treat this as a decision-support tool, not a source of guaranteed wins — soccer outcomes have real variance that no model eliminates.
- If you act on these predictions with real money, keep to amounts you're fully comfortable losing, and be aware that consistently beating the market's own pricing over time is difficult even for well-resourced professionals.
- Respect the terms of service of whichever data/odds providers you choose, particularly around scraping and redistribution.
