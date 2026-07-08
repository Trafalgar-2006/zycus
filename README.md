# Project Health Reporting Agent
**Zycus AI Engineer Intern — Technical Assignment**

---

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. (Optional) Set Gemini API key for LLM narratives
set GEMINI_API_KEY=your_key_here        # Windows
# export GEMINI_API_KEY=your_key_here  # macOS/Linux

# Note: requires a billing-enabled Google AI project.
# Without a key, the agent uses a rule-based narrative fallback.

# 3. Run the agent once (both projects)
python main.py

# 4. Run for a single project
python main.py --project "UniSan S2P"

# 5. Generate monthly executive PPTX
python main.py --monthly

# 6. Run on weekly schedule (every Monday 08:00)
python main.py --schedule
```

**No API key?** The agent runs fully without one — it uses a deterministic
rule-based narrative. All scoring, ML, Monte Carlo, clustering and delta
reporting work regardless. LLM adds richer prose, not different numbers.

---

## Output Files

```
outputs/
├── weekly/
│   ├── YYYY-MM-DD_Outokumpu_S2P.md      ← weekly health report (Markdown)
│   └── YYYY-MM-DD_UniSan_S2P.md
├── monthly/
│   └── Executive_Report_YYYY-MM.pptx    ← 6-slide executive deck
└── project_health.db                    ← SQLite delta store (week-on-week)
```

---

## Project Structure

```
├── agent/
│   ├── data_loader.py       # Excel parsing, normalisation, column aliases
│   ├── rag_scorer.py        # GBT + feature_importances_ + aggregation formula
│   ├── monte_carlo.py       # Throughput-based deadline probability simulation
│   ├── cluster_analyzer.py  # At-risk task clustering (TF-IDF + KMeans)
│   ├── delta_store.py       # SQLite week-on-week tracking
│   ├── reasoner.py          # LLM narrative (Gemini 2.0 / rule-based fallback)
│   ├── verifier.py          # LLM self-verification loop
│   └── report_writer.py     # Markdown report composer
├── diagnostics/             # One-off audit/debug scripts (not production)
├── main.py                  # CLI entry point
├── scheduler.py             # Weekly cron runner
├── pptx_generator.py        # Executive PPTX builder
├── config.py                # All thresholds (tunable)
├── RAG_Methodology.md       # Full methodology + audit trail
└── requirements.txt
```

---

## Design Decisions

### 1. ML-Fitted Weights, Not Guessed Ones
A `GradientBoostingClassifier` is trained on all task rows (both projects)
using the existing RAG/Schedule Health label as ground truth. Feature
importance (`model.feature_importances_`) surfaces which signals drive the
PM's own health labels — verified ranking:

| Feature | Importance | Note |
|---------|-----------|------|
| `total_float_days` | 0.544 | Slack before task hits critical path |
| `variance_sign_code` | 0.272 | Sign of lateness (-1/0/+1) |
| `pct_complete` | 0.105 | Task progress |

**Why not raw `variance_days`?** Variance magnitude is contaminated by
PM-tool dependency cascades (correlation with real date delta: 0.175). Only
the sign is reliable (verified: 196/199 rows). Explicitly framed as a
**fit-and-interpret exercise** — RAG is manually set by PMs, so the model
learns PM judgment patterns, not a formula. Documented in `RAG_Methodology.md`.

### 2. Throughput-Based Monte Carlo Forecasting
The agent outputs probability distributions: *"77% chance of meeting the
Dec 2026 deadline."* Built by:
1. Measuring historical task completion rate (tasks/week) from actual End Dates
2. Fitting a log-normal to duration ratios (actual elapsed / planned) for
   variance around that rate
3. Running 10,000 simulations to produce P(on-time) + median finish date

**Why throughput, not serial-sum?** Serial sum of remaining tasks × duration
produced 3–7 year estimates because it ignores team parallelism (22–42 tasks
run concurrently). Throughput captures real team concurrency naturally.

A stability check flags projects where second-half completion rate is >2×
first-half (acceleration caveat) or <0.5× (deceleration caveat).

### 3. Delta Reporting via SQLite
Every run persists scores to a local SQLite database. Subsequent runs
automatically compute and report week-on-week changes: *"Moved Amber → Red;
score grew 0.42 → 0.61."*

### 4. LLM Self-Verification Loop
After Gemini writes a narrative, the same model is given the raw numbers and
asked to fact-check its own claims. Catches hallucinated statistics. This is
a lightweight agentic pattern — no LangChain/CrewAI overhead.

### 5. Few-Shot Calibration on Real Data
Gemini prompts include actual Outokumpu and UniSan examples so the LLM's
tone and thresholds are calibrated to Zycus's real data, not generic advice.

### 6. Honest Limitations Stated in Every Report
- **Variance sign**: 2 known anomalous rows documented, not silently dropped
- **Variance magnitude**: excluded from ML (PM-tool cascade contamination verified)
- **Duration magnitude**: 57% of parent-task Durations don't match child sums — excluded
- **ML model**: fit/interpret only on 2 projects, no holdout validation possible
- **RAG is PM-set**: model predicts PM judgment, not a formula
- **Monte Carlo**: single snapshot, no dependency graph, tasks treated as independent
- **Throughput stability**: Outokumpu second-half rate 3× first-half — flagged in report caveat

---

## Configuration

All thresholds are in [`config.py`](config.py):

| Setting | Default | Meaning |
|---------|---------|---------| 
| `FORWARD_RISK_WEIGHT` | 0.60 | Weight of active risk in score |
| `HISTORICAL_SLIP_WEIGHT` | 0.40 | Weight of completed-task slippage |
| `MIN_CRITICAL_N` | 5 | Min critical tasks before falling back to all active |
| `SLIP_CEILING_DAYS` | 30 | Days slip that scores 1.0 (max) |
| `GREEN_THRESHOLD` | 0.25 | Score below = Green |
| `AMBER_THRESHOLD` | 0.55 | Score below = Amber, else Red |
| `MONTE_CARLO_SIMULATIONS` | 10,000 | Simulation runs |
| `N_CLUSTERS` | 3 | K for at-risk task clustering |
| `GEMINI_MODEL` | gemini-2.0-flash-lite | LLM model (requires billing-enabled key) |
| `WEEKLY_RUN_DAY` | monday | Scheduler trigger day |
| `WEEKLY_RUN_TIME` | 08:00 | Scheduler trigger time |

---

## Methodology

See [`RAG_Methodology.md`](RAG_Methodology.md) for the full audit trail
covering sign convention verification, variance cascade analysis, Duration
cascade findings, feature importance ranking, and Monte Carlo model assumptions.
