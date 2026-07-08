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

# 3. Run the agent (all projects — generates MD reports + exec summaries + PPTX)
python main.py

# 4. Single project
python main.py --project "UniSan S2P"

# 5. Regenerate monthly PPTX from existing MD files (standalone)
python main.py --monthly

# 6. Run on weekly schedule (every Monday 08:00)
python main.py --schedule
```

**No API key?** The agent runs fully without one — rule-based narrative fallback.
All scoring, ML, Monte Carlo (v1 + v2 DAG), clustering, and delta tracking work
regardless. LLM adds richer prose, not different numbers.

---

## Output Files

```
outputs/
├── weekly/
│   ├── YYYY-MM-DD_Outokumpu_S2P.md   ← weekly Markdown health report
│   └── YYYY-MM-DD_UniSan_S2P.md      ← includes confidence tag + naive baseline
├── exec/
│   ├── YYYY-MM-DD_Outokumpu_S2P_exec.md  ← one-page executive summary
│   └── YYYY-MM-DD_UniSan_S2P_exec.md     ← RAG + reason + P(on-time) + action
├── monthly/
│   └── Executive_Report_YYYY-MM.pptx ← 6-slide executive deck (live data)
└── project_health.db                 ← SQLite delta store (week-on-week)
```

---

## Project Structure

```
├── agent/
│   ├── data_loader.py       # Excel parsing, normalisation, column aliases
│   ├── rag_scorer.py        # GBT + feature_importances_ + aggregation formula
│   ├── monte_carlo.py       # MC v1 (throughput) + v2 (DAG-aware) simulation
│   ├── dag_builder.py       # MS Project predecessor parser → nx.DiGraph + CP
│   ├── cluster_analyzer.py  # At-risk task clustering (TF-IDF + KMeans)
│   ├── delta_store.py       # SQLite week-on-week tracking
│   ├── reasoner.py          # LLM narrative (Gemini 2.0 / rule-based fallback)
│   ├── verifier.py          # LLM self-verification loop
│   └── report_writer.py     # Markdown report + exec summary composer
├── diagnostics/             # One-off audit/debug scripts (not production)
├── main.py                  # CLI entry point — orchestrates full pipeline
├── scheduler.py             # Weekly cron runner
├── pptx_generator.py        # Executive PPTX builder (consumes live pipeline data)
├── config.py                # All thresholds (tunable)
├── RAG_Methodology.md       # Full methodology, audit trail, v1→v2 build reasoning
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

### 2. Two-Model Monte Carlo: Throughput (v1) → Dependency-Aware DAG (v2)
The agent outputs probability distributions: *"78% chance of meeting the
Dec 2026 deadline."* Two complementary models:

**v1 — Throughput baseline:**
1. Measures historical task completion rate (tasks/week) from actual End Dates
2. Fits a log-normal to duration ratios (actual elapsed / planned) for variance
3. 10,000 simulations → P(on-time) + median finish date

**v2 — Dependency-aware DAG (UniSan only):**
1. Parses MS Project `Predecessors` column → directed acyclic graph (nx.DiGraph)
2. Propagates sampled durations topologically (task starts only after all predecessors finish + lag)
3. Runs only when predecessor coverage ≥ 50% — below that threshold, the sparse graph would understate risk

**Why two models?** v1 assumes serial execution which over-estimates risk for parallel workstreams.
v2 respects the actual dependency structure: UniSan goes from 5% → 15% P(on-time)
because many tasks that v1 counts as serial backlog actually run concurrently.
Both results are shown side-by-side with a pp interpretation note.
The 50-task graph-computed CP matches the PM-flagged 50 CP tasks exactly — cross-validation.

**Why throughput (not serial sum) for v1?** Serial sum of remaining tasks × duration
produced 3–7 year estimates because it ignores team parallelism (22–42 tasks
run concurrently). Throughput captures real team concurrency naturally.

### 3. Naïve Baseline Comparison in Every Report
Each weekly report contains a "Naïve vs Model Baseline" table showing:
- What a simple %-complete view would say ("X% done, Y% of time elapsed")
- What the RAG+ML model says (score, Red CP tasks)
- What the Monte Carlo says (P(on-time) with v1→v2 correction if available)

This answers the "why does this tool add value beyond a spreadsheet?" question
explicitly in the report rather than leaving it implicit.

### 4. Data Confidence Tier per Report
Each report carries a one-line **Data Confidence** tag (🟢 High / 🟡 Medium / 🔴 Low)
computed from actual field null-rates:
- `predecessor coverage` (weighted 0.40) — controls whether DAG-MC is trustworthy
- `planned_days` missing rate (weighted 0.30)
- `pct_complete` missing rate (weighted 0.30)

Outokumpu: **Medium** (28% predecessor coverage drags weighted score to 0.31).
UniSan: **High** (74% predecessor coverage, low null rates; weighted score 0.15).

### 5. Delta Reporting via SQLite
Every run persists scores to a local SQLite database. Subsequent runs
automatically compute and report week-on-week changes: *"Moved Amber → Red;
score grew 0.42 → 0.61."*

### 6. LLM Self-Verification Loop
After Gemini writes a narrative, the same model is given the raw numbers and
asked to fact-check its own claims. Catches hallucinated statistics. This is
a lightweight agentic pattern — no LangChain/CrewAI overhead.

### 7. Honest Limitations Stated Explicitly
- **Variance sign**: 2 known anomalous rows documented, not silently dropped
- **Variance magnitude**: excluded from ML (PM-tool cascade contamination verified)
- **Duration magnitude**: 57% of parent-task Durations don't match child sums — excluded for parent rows
- **ML model**: fit/interpret only on 2 projects, no holdout validation possible
- **RAG is PM-set**: model predicts PM judgment, not a formula
- **MC v2**: no resource leveling; non-FS relationships simplified to FS+lag (18 edges, 6%); 40 duration fallbacks logged
- **DAG coverage gate**: v2 skipped for Outokumpu (28% < 50% threshold) to avoid understating risk on sparse graph

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
| `DAG_MIN_COVERAGE` | 0.50 | Min predecessor coverage to enable MC v2 |
| `N_CLUSTERS` | 3 | K for at-risk task clustering |
| `GEMINI_MODEL` | gemini-2.0-flash-lite | LLM model (requires billing-enabled key) |
| `WEEKLY_RUN_DAY` | monday | Scheduler trigger day |
| `WEEKLY_RUN_TIME` | 08:00 | Scheduler trigger time |

---

## Methodology

See [`RAG_Methodology.md`](RAG_Methodology.md) for the full audit trail
covering sign convention verification, variance cascade analysis, Duration
cascade findings, feature importance ranking, Monte Carlo model assumptions,
and the full v1 → v2 build reasoning (why throughput felt too pessimistic,
what the dependency graph revealed, and what changed).
