# RAG Methodology — Project Health Reporting Agent

**Prepared for:** Zycus Professional Services Leadership
**Author:** AI Engineer Intern Assignment
**Version:** 1.1 | July 2026 *(updated after Duration cascade check and ML feature audit)*

---

## Purpose

This document defines how the agent determines a **Red / Amber / Green (RAG)**
status for each project. Every number and threshold is stated explicitly so
any reviewer can challenge or recalibrate it.

---

## Composite Score Formula

```
Project Score = 0.60 × Forward Risk  +  0.40 × Historical Slip
```

Both components are normalised to **[0.0, 1.0]**.

| Score Range | RAG Status |
|-------------|-----------|
| 0.00 – 0.24 | 🟢 Green   |
| 0.25 – 0.54 | 🟡 Amber   |
| 0.55 – 1.00 | 🔴 Red     |

---

## Component 1 — Forward Risk (Weight: 60%)

Measures **what is actively at risk right now** on the critical path.

```
Forward Risk = (Red_fraction) + 0.5 × (Amber_fraction)
```

Computed over **critical-path tasks** that are `In Progress` or `Not Started`.

**Fallback guard:** If fewer than 5 critical tasks are active (e.g., late-stage
project or no critical flag set), the calculation falls back to **all active
tasks** to avoid a tiny denominator swinging the score by ±33% per task.

If zero active tasks exist (fully complete project), `Forward Risk = 0`.

---

## Component 2 — Historical Slip (Weight: 40%)

Measures **how badly completed tasks have drifted** from baseline.

```
Historical Slip = min( median(slip_days) / 30 ,  1.0 )
```

Where `slip_days = actual_elapsed_working_days − planned_duration` for each
**late** completed critical task (`variance_sign == "late"`).

**Design decisions:**
- **Median, not mean** — a single 90-day outlier task should not dominate the score.
- **30-day ceiling** — slips beyond 30 days all score 1.0; the ceiling is tunable in `config.py`.
- **`variance_days.abs()` as the slip magnitude, not `actual_minus_planned`:**
  `actual_minus_planned = actual_elapsed_wd − planned_duration` was initially
  considered as a "cleaner" measure, but is wrong for this purpose.
  It measures whether the task's *internal duration* was efficient — not whether
  the task finished against its *Baseline Finish* date. A task that starts late
  but runs for the planned number of days reads `actual_minus_planned ≈ 0` yet
  is genuinely late vs baseline. Additionally, `busday_count` is end-exclusive,
  so same-day tasks read `actual_elapsed=0`, causing `actual_minus_planned = -1`
  (appears early) regardless of their lateness. `variance_days` measures the
  right thing: how far the Actual Finish Date is from the Baseline Finish Date.
  Its magnitude has known cascade contamination for parent/summary rows (see
  Assumption 3), but is directionally reliable for leaf-level completed tasks.
- **Same fallback guard** as Forward Risk: if fewer than 5 critical completed
  tasks exist, uses all completed tasks.

**Known limitation — Duration cascade (verified 2026-07-08):**
The Duration column is also affected by the PM tool's dependency-cascade
machinery for parent/summary rows. Empirically checked by comparing each
parent task's stated Duration to the sum and max of its immediate children
across 98 parent-child groups in S2P data:

| Pattern | Count | % |
|---------|-------|---|
| parent_dur ≈ sum(children) — additive | 32 | 32% |
| parent_dur ≈ max(children) — critical path | 10 | 10% |
| **Neither — PM-tool adjusted/cascaded** | **56** | **57%** |

Example: *Phase 1-S2C* has `Duration = 158d`, but its 3 direct children sum to
only 90 days (ratio 1.76×). This is the same rollup inflation seen in Variance.

Consequence for Historical Slip: `actual_elapsed − planned_duration` is
**reliable only for leaf tasks** (tasks with no sub-tasks). For parent/summary
rows, `planned_duration` inherits the cascade and the difference is not
interpretable as "task-level overrun". The agent does not currently filter to
leaf tasks only — this is an open refinement for when hierarchy data is available.
The output should be read as directional, not precise.

---

## Variance Sign Convention

**Verified empirically:** Negative Variance = **late** (behind schedule).
Positive Variance = **early** (ahead of schedule).

Cross-checked by computing `Baseline Finish − End Date` in working days for
196 tasks — signs agreed in 196/199 rows. The 3 discrepant rows were inspected
individually:
- 2 rows are data-entry anomalies (sign inverted by PM). Documented in `config.SIGN_INVERTED_TASKS`. Not silently dropped.
- 1 row had a missing Baseline Finish (NaT) — not a valid comparison.

The **magnitude** of Variance is unreliable (PM-tool cascaded). Only the sign
is used as a reliable signal. See Assumption 3.

---

## ML Feature Importance (Supplementary)

A `GradientBoostingClassifier` is trained on ~878 task rows across both
projects to predict the existing RAG/Schedule Health label.

**Verified importance ranking (current feature set, 2026-07-08):**

| Feature | Importance | Interpretation |
|---------|-----------|----------------|
| `total_float_days` | **0.544** | Slack available before a task becomes critical — dominant signal |
| `variance_sign_code` | **0.272** | Sign of lateness (-1/0/+1) — second-strongest signal |
| `pct_complete` | 0.105 | Task progress |
| `status_code` | 0.053 | In Progress / Not Started / On Hold encoding |
| `actual_minus_planned` | 0.018 | Duration efficiency (near-zero — included but negligible) |
| `is_on_hold`, `is_at_risk`, `is_critical` | < 0.005 each | Weak signals in this dataset |

**Critical disclosure — RAG is manually set by PMs, not computed from Variance:**

Spot-checking UniSan's Schedule Health column (Check 4, verified 2026-07-08)
revealed three Training Phase tasks (`Training Phase I`, `Train The Trainer`,
`Admin Training`) with `variance_sign = early` (+17 days ahead of schedule)
but labeled **Red** in Schedule Health. A formulaic rule would mark these
Green or Yellow. The PM marked them Red for reasons not captured in the
schedule data (likely resource readiness, training material quality, or
stakeholder availability).

Consequence: **the GBT is learning to predict PM judgment, not a deterministic
formula.** The SHAP/importance findings ("total_float_days and
variance_sign_code drive RAG") are learning the dominant *pattern* in the PM's
decisions, not the PM's actual decision rule. This is still informative — it
tells us what the PM weighs most heavily on average — but should not be
presented as a mechanistic model.

**Explicit limitation:** Fit/interpret exercise on 2 projects. No
project-holdout split possible. The value is transparency: understanding what
signals correlate with the PM's health judgments in this dataset.

---

## Monte Carlo Deadline Forecast

- **Input:** Distribution of `duration_ratio = actual_elapsed / planned_days`
  across all **completed** tasks with parseable dates.
- **Model:** Log-normal (keeps ratios positive; heavier right tail appropriate
  for task overruns).
- **Simulations:** 10,000 per project.
- **Output:** P(finish by deadline), P(slip 1 week), P(slip 2+ weeks).
- **Remaining work estimate:** Active tasks with `planned_days ≤ 45` only.
  This leaf-task heuristic excludes parent/summary rollup rows whose Duration
  is a PM-tool cascade — the same contamination identified in Assumption 4.
  Without it, parent and child tasks are both counted as active work, inflating
  the estimate by 2–3× and producing nonsensical completion dates (e.g., 2031
  for a 2026 project). Threshold of 45 working days ≈ 9 calendar weeks is a
  generous upper bound for a single delivery task; tunable in `config.py`.
- **Caveat:** Single-snapshot data; no weekly history. Treat as directional.
  Duration cascade contamination affects both the ratio denominator (for
  completed parent-row tasks) and the remaining work estimate (mitigated by the
  leaf-task filter but not eliminated for borderline rows).

---

## Signals Not Included & Why

| Signal | Why Excluded |
|--------|-------------|
| Budget burn | Not present in the provided Excel files |
| Stakeholder sentiment | Comment sheet has ~10 rows (S2P) and 0 rows (UniSan) — too sparse for reliable sentiment |
| Predecessor chain analysis | ~~Would require graph traversal~~ **Now implemented** — see DAG section below |

---

## Assumptions

1. Working days are Monday–Friday. No public holiday calendar applied.
2. The Variance column sign convention is negative = late (verified empirically, 196/199 rows).
3. Variance column **magnitude** is treated as unreliable due to PM-tool dependency cascade effects (max observed discrepancy: 141 days vs computed delta; correlation with real date delta: 0.175). Only the sign is used.
4. Duration column **magnitude** is also treated as unreliable for parent/summary rows — same PM-tool cascade mechanism. Empirically verified: 57% of parent-task Durations don't match sum or max of their children. Duration values are used for leaf-level tasks only, and all results depending on `planned_days` should be read as directional.
5. Tasks with `Status = Not Applicable` are excluded from all scoring.
6. The 30-day slip ceiling and 0.25/0.55 RAG thresholds are **tunable** in `config.py` and should be recalibrated as more project data becomes available.

---

## Dependency Graph & Monte Carlo v2 — Build Reasoning

### Why we built a second model

The throughput-based simulation (v1) produced a **5% P(on-time)** for UniSan and **78%** for Outokumpu *(as of 2026-07-08; numbers update each run as the project progresses)*. The UniSan number felt structurally pessimistic: the throughput model extrapolates a single team-wide completion rate forward, as if every remaining task must be done serially. Real projects don't work that way — workstreams run in parallel, and predecessor constraints tell you *which* tasks are actually blocking others.

To test whether the model was being too conservative, we built the task dependency graph from the MS Project `Predecessors` column and implemented a discrete-event simulation that propagates finish times through the DAG topologically: a task can only start once all its predecessors have finished (plus any lag). This is qualitatively different from a throughput extrapolation — it respects the actual scheduling structure instead of assuming serial execution.

### What changed and why

For **UniSan** (74% predecessor coverage — 283 of 383 tasks have documented predecessors):
- **v1: 5%** | **v2: 15%** — a 10 pp improvement *(as of 2026-07-08)*
- The difference reflects real parallel structure in the schedule. When predecessor constraints are enforced, many tasks that the throughput model counts as a serial backlog turn out to run concurrently with each other. The project is still highly likely to slip (85% probability), but the *mechanism* is now grounded in the actual task graph rather than a flat completion-rate extrapolation.
- The 50-task graph-computed critical path agrees exactly with the PM-flagged 50 critical-path tasks — which is a useful cross-validation: it means the PM was tracking the longest-duration chain, not just applying the flag arbitrarily.

For **Outokumpu** (28% predecessor coverage — 139 of 493 tasks have documented predecessors):
- **v2 not run.** With 72% of tasks having no predecessor data, a graph simulation would treat those tasks as unconstrained roots (starting immediately), almost certainly *understating* risk for the disconnected majority. Presenting a DAG result on a graph this sparse would look rigorous but would be misleading. The threshold of 50% was chosen as the minimum coverage required to trust the graph structure as representative; Outokumpu is well below it.
- The PM-flagged critical path (15 tasks) is the authoritative signal here. The partial graph does identify a 1-task longest chain, but this is disclosed as a sparse-graph artifact, not a project-level finding.

### Honest limitations

- **No resource leveling:** The simulation assumes tasks can start as soon as their predecessors finish, regardless of whether the same person is assigned to multiple concurrent tasks. Real schedules are resource-constrained; this model is not.
- **Non-FS relationships simplified:** 18 FF/SS edges (6% of UniSan's edges) were approximated as FS + lag. This is logged in the report caveat per task pair for full auditability.
- **Duration fallbacks:** 40 UniSan tasks had no parseable `planned_days` and used the dataset mean (≈8 days) as a proxy. This is a known source of noise, not a silent assumption.
- **Single snapshot:** Both v1 and v2 are trained on a single project export. With weekly runs, the duration ratio distribution would update incrementally and the results would become more reliable over time.
