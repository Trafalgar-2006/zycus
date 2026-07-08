"""
config.py — Central configuration for the Project Health Reporting Agent.
All thresholds, weights, and paths are tunable here.
"""
import os
try:
    from dotenv import load_dotenv
    load_dotenv()   # loads .env from repo root if present
except ImportError:
    pass  # dotenv optional — env var can still be set manually

# ── Gemini API ──────────────────────────────────────────────────────────────
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")   # loaded from .env or env var
GEMINI_MODEL   = "gemini-2.0-flash-lite"
USE_LLM        = bool(GEMINI_API_KEY)               # auto-disabled if no key

# ── Project files ───────────────────────────────────────────────────────────
PROJECT_FILES = {
    "Outokumpu S2P": "S2P Project.xlsx",
    "UniSan S2P":    "Project Plan B.xlsx",
}

# ── Output paths ────────────────────────────────────────────────────────────
WEEKLY_OUTPUT_DIR  = "outputs/weekly"
MONTHLY_OUTPUT_DIR = "outputs/monthly"
DB_PATH            = "outputs/project_health.db"

# ── RAG Aggregation ─────────────────────────────────────────────────────────
# Weights for combining forward risk and historical slip
FORWARD_RISK_WEIGHT   = 0.60
HISTORICAL_SLIP_WEIGHT = 0.40

# Minimum critical tasks before falling back to all active tasks
MIN_CRITICAL_N = 5

# Slip ceiling in calendar days (tasks slipping > this are capped at 1.0)
SLIP_CEILING_DAYS = 30

# Project-level RAG thresholds on [0, 1] combined score
GREEN_THRESHOLD = 0.25
AMBER_THRESHOLD = 0.55

# ── Monte Carlo ─────────────────────────────────────────────────────────────
MONTE_CARLO_SIMULATIONS = 10_000
DAG_MIN_COVERAGE        = 0.50    # minimum predecessor coverage to run simulate_v2
                                   # Outokumpu=28% → v1 only; UniSan=74% → v2 flagship

# ── Clustering ──────────────────────────────────────────────────────────────
N_CLUSTERS = 3   # for at-risk task clustering

# ── Scheduling ──────────────────────────────────────────────────────────────
WEEKLY_RUN_DAY  = "monday"   # schedule.every().monday
WEEKLY_RUN_TIME = "08:00"

# ── Known data anomalies (documented, not silently dropped) ─────────────────
SIGN_INVERTED_TASKS = [
    "Onsite- Design Session-Design Session Completion and Sign off",
    "User Setup",
]
