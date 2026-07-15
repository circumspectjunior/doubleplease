# DoublePlease

Weekly soccer double-chance prediction app. See [build-plan.md](build-plan.md) for the
full design; [review.md](review.md) tracks what has actually been implemented.

## Structure

```
doubleplease/
├── backend/     # Python ingestion, prediction engine, value calculator, API
└── frontend/    # React + Vite dashboard
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

Run the pipeline (or let `run_weekly_pipeline.sh` do it on the Monday cron job):

```bash
python -m src.ingest_fixtures --league 39 --season 2026
python -m src.ingest_odds
python -m src.model_poisson
python -m src.value_calculator
python -m src.weekly_report
```

Run the API (used by the frontend dashboard):

```bash
uvicorn src.api:app --port 8000
```

## Frontend setup

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173` - expects the backend API running at `http://localhost:8000`.
