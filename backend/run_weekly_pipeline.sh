#!/bin/bash
# Weekly pipeline: refresh odds, regenerate predictions + edge, write the report.
# Historical fixture ingestion isn't re-run here since a season's fixture list
# rarely changes week to week - re-run src.ingest_fixtures manually if needed
# (e.g. once a year when a new season's fixtures are published).
set -euo pipefail

cd "$(dirname "$0")"
source venv/bin/activate

LOG_DIR="data/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/weekly_$(date +%Y-%m-%d_%H%M%S).log"

{
  echo "=== Weekly pipeline run: $(date) ==="
  python -m src.ingest_odds
  python -m src.model_poisson
  python -m src.value_calculator
  python -m src.weekly_report
  echo "=== Done: $(date) ==="
} >> "$LOG_FILE" 2>&1

echo "Pipeline finished. Log: $LOG_FILE"
