#!/usr/bin/env bash
set -euo pipefail

# Runs the metricwriter using uv, and relies on python-dotenv
# inside the script to load .env automatically for local runs.
# .env must exist (created from .env.example) in this directory.

if [[ ! -f .env ]]; then
  echo "Missing .env file. Create it from .env.example first." >&2
  exit 1
fi

# Ensure we run inside the uv project folder
cd "$(dirname "$0")"

# Uses the uv project defined in metricwriter/pyproject.toml
# (so this directory should be metricwriter/)
uv run python push_metrics_gauge.py

