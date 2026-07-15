# Frontend

React + Vite dashboard for the weekly double-chance shortlist. Reads from the
FastAPI backend (`backend/src/api.py`) - see the root [README.md](../README.md)
for how to run both together.

## Setup

```bash
cd frontend
npm install
npm run dev
```

Expects the backend API running at `http://localhost:8000` (see
`backend/src/api.py` - `uvicorn src.api:app --port 8000`).
