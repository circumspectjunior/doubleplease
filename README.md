# DoublePlease

Weekly soccer double-chance prediction app. See [build-plan.md](build-plan.md) for the
full design; [review.md](review.md) tracks what has actually been implemented.

## Structure

```
doubleplease/
├── backend/     # Python data ingestion, prediction engine, value calculator
└── frontend/    # web dashboard (not yet implemented)
```

## Backend setup

```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in API_FOOTBALL_KEY and ODDSPAPI_KEY
```

Run tests:

```bash
pytest
```

Run ingestion scripts:

```bash
python -m src.ingest_fixtures --league 39 --season 2026
python -m src.ingest_odds
```
