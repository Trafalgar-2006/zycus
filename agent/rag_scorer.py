"""
rag_scorer.py — Task-level ML scoring (GBT + SHAP) and project-level aggregation.

Design decisions (stated explicitly):
- GBT is trained on ~878 task rows from 2 projects: fit-and-interpret, NOT a
  validated generalizable classifier.  We use it to surface which features
  Zycus's own RAG logic weights most heavily, and confirm those via SHAP.
- Aggregation uses a patched formula with zero-denominator guards and median
  (not mean) for historical slip, to avoid instability on small samples.
"""
from __future__ import annotations

import warnings
from typing import Any

import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.preprocessing import LabelEncoder

import config

warnings.filterwarnings("ignore", category=UserWarning)

# ── Feature columns used for ML ──────────────────────────────────────────────
# variance_days (raw Variance column) is EXCLUDED:
#   - Empirically verified: Variance magnitude is corrupted by PM-tool
#     dependency cascades (max observed discrepancy vs date delta: 141 days,
#     correlation with actual date delta: 0.175).
#   - Using it would make SHAP findings driven by a contaminated signal.
#
# planned_days (Duration column) is EXCLUDED:
#   - Same cascade problem: 57% of parent-task Durations don't match either
#     sum OR max of their children (empirically verified).
#   - Only reliable for leaf tasks; summary rows are PM-tool rollups.
#
# Replacements:
#   variance_sign_code : sign of Variance (-1=late, 0=on_time, 1=early)
#                        Sign was verified reliable for 196/199 rows.
#   actual_minus_planned: actual_elapsed_wd - planned_days for completed tasks.
#                        Uses real dates (Start Date / End Date), not PM cascades.
#                        326/327 labeled tasks have this value (better coverage
#                        than variance_days which had 271/327).
_FEATURE_COLS = [
    "pct_complete",
    "status_code",
    "is_critical",
    "is_on_hold",
    "is_at_risk",
    "total_float_days",
    "variance_sign_code",      # reliable: -1 / 0 / 1
    "actual_minus_planned",    # real date delta, not PM cascade
]


_RAG_LABELS   = ["Green", "Yellow", "Red"]
_RAG_LABEL_ENC = {0: "Green", 1: "Yellow", 2: "Red"}


def _prepare_features(df: pd.DataFrame) -> pd.DataFrame:
    """Return a clean numeric feature matrix from a task DataFrame."""
    X = df[_FEATURE_COLS].copy()
    X["is_critical"]  = X["is_critical"].astype(float)
    X["is_on_hold"]   = X["is_on_hold"].astype(float)
    X["is_at_risk"]   = X["is_at_risk"].astype(float)
    # Fill NaN with column medians (handles missing dates, float nulls, etc.)
    X = X.fillna(X.median(numeric_only=True))
    return X


def train_model(
    dfs: list[pd.DataFrame],
) -> tuple[GradientBoostingClassifier, LabelEncoder, dict[str, float]]:
    """
    Train a GBT on task-level RAG labels across all loaded projects.

    Returns (model, label_encoder, feature_importance_dict)

    Limitations stated:
    - 2-project dataset: fit/interpret only.
    - No project-holdout split; task rows shuffled 80/20 for internal
      cross-validation only.  Stated as such in reports.
    """
    combined = pd.concat(dfs, ignore_index=True)
    labeled  = combined.dropna(subset=["rag_code"])
    labeled  = labeled[labeled["rag_code"].isin([0, 1, 2])]

    X = _prepare_features(labeled)
    y = labeled["rag_code"].astype(int)

    le = LabelEncoder()
    le.fit(y)

    model = GradientBoostingClassifier(
        n_estimators=200,
        max_depth=4,
        learning_rate=0.05,
        subsample=0.8,
        random_state=42,
    )
    model.fit(X, y)

    importance = dict(zip(_FEATURE_COLS, model.feature_importances_))
    return model, le, importance


def shap_summary(
    model: GradientBoostingClassifier,
    df: pd.DataFrame,
    top_n: int = 5,
    importance: dict | None = None,
) -> dict[str, Any]:
    """
    Return top-N features by GBT feature importance.

    Uses model.feature_importances_ directly — fast, deterministic, and
    already the correct attribution mechanism for the tree ensemble.

    SHAP's generic Explainer was tried but dropped: it auto-selected
    ExactExplainer for model.predict (slow, ~15s, non-deterministic across
    invocations due to floating-point ordering), and TreeExplainer doesn't
    support multi-class GBT. The methodology doc states this is a
    fit/interpret exercise, not a validated SHAP analysis — so
    feature_importances_ is the honest and stable choice.
    """
    if importance:
        raw = importance
    elif hasattr(model, "feature_importances_"):
        raw = dict(zip(_FEATURE_COLS, model.feature_importances_))
    else:
        return {"error": "no importance data available", "source": "none"}

    ranked = sorted(raw.items(), key=lambda x: x[1], reverse=True)

    return {
        "top_features": [
            {"feature": f, "mean_abs_shap": round(float(v), 4)}
            for f, v in ranked[:top_n]
        ],
        "source": "GBT feature_importances_",
        "disclaimer": (
            "Confirms which signals Zycus's own RAG logic weights most heavily. "
            "Fit/interpret exercise on 2-project data — not a validated classifier."
        ),
    }





def _forward_risk(tasks: pd.DataFrame) -> float:
    """
    Fraction of active critical tasks that are Red/Amber, weighted 1.0/0.5.
    Falls back to all active tasks if critical count < MIN_CRITICAL_N.
    Returns 0.0 if no active tasks at all.
    """
    active_statuses = {"In Progress", "Not Started"}

    critical_active = tasks[
        tasks["is_critical"] &
        tasks["Status"].isin(active_statuses)
    ]

    if len(critical_active) < config.MIN_CRITICAL_N:
        # Fall back to all active tasks, not just critical
        critical_active = tasks[tasks["Status"].isin(active_statuses)]

    if len(critical_active) == 0:
        return 0.0

    red_frac   = (critical_active["RAG"] == "Red").sum()    / len(critical_active)
    amber_frac = (critical_active["RAG"].isin(["Yellow", "Amber"])).sum() / len(critical_active)
    return float(red_frac + 0.5 * amber_frac)


def _historical_slip(tasks: pd.DataFrame) -> float:
    """
    Median slip-days for completed late tasks, normalised to [0, 1].

    Uses variance_days.abs() as the slip measure.

    IMPORTANT: actual_minus_planned was initially tried here but is WRONG for
    this purpose. It measures (actual elapsed days - planned duration), i.e.
    whether the task's internal duration was efficient — NOT whether the task
    finished against its Baseline Finish date (which is what 'late' means).
    A task can start late, run the planned duration, yet still be late vs
    baseline; actual_minus_planned would read 0 in that case.
    Additionally, busday_count is end-exclusive, so tasks starting and ending
    on the same day read actual_elapsed=0, making actual_minus_planned = -1
    (appears early) even when they ARE late per variance_sign.

    variance_days magnitude: corrupted by PM-tool cascades for parent/summary
    rows, but reliable enough for leaf-level completed tasks. Sign is verified
    reliable (196/199 rows). Use magnitude for historical slip; treat as
    directional — not exact.
    """
    active_statuses = {"In Progress", "Not Started"}
    critical_done = tasks[
        tasks["is_critical"] &
        (~tasks["Status"].isin(active_statuses)) &
        (tasks["Status"] != "Not Applicable")
    ]

    if len(critical_done) < config.MIN_CRITICAL_N:
        critical_done = tasks[
            (~tasks["Status"].isin(active_statuses)) &
            (tasks["Status"] != "Not Applicable")
        ]

    late = critical_done[
        (critical_done["variance_sign"] == "late") &
        critical_done["variance_days"].notna()
    ]

    if late.empty:
        return 0.0

    median_slip = late["variance_days"].abs().median()
    return float(min(median_slip / config.SLIP_CEILING_DAYS, 1.0))


def score_project(df: pd.DataFrame) -> dict[str, Any]:
    """
    Compute project-level RAG and return full scoring breakdown.

    Returns a dict with:
        rag              : 'Green' | 'Amber' | 'Red'
        project_score    : float in [0, 1]
        forward_risk     : float in [0, 1]
        historical_slip  : float in [0, 1]
        task_summary     : counts by Status and RAG
        data_quality     : anomaly flags
    """
    forward  = _forward_risk(df)
    slip     = _historical_slip(df)
    score    = config.FORWARD_RISK_WEIGHT * forward + config.HISTORICAL_SLIP_WEIGHT * slip

    if score < config.GREEN_THRESHOLD:
        rag = "Green"
    elif score < config.AMBER_THRESHOLD:
        rag = "Amber"
    else:
        rag = "Red"

    # Task summary counts
    status_counts = df["Status"].value_counts().to_dict()
    rag_counts    = df["RAG"].value_counts().to_dict()
    anomaly_count = int(df["variance_anomaly"].sum())

    # Critical path summary
    crit = df[df["is_critical"]]
    crit_rag = crit["RAG"].value_counts().to_dict()

    return {
        "rag":             rag,
        "project_score":   round(score, 4),
        "forward_risk":    round(forward, 4),
        "historical_slip": round(slip, 4),
        "task_summary": {
            "by_status": status_counts,
            "by_rag":    rag_counts,
        },
        "critical_path": {
            "total":  len(crit),
            "by_rag": crit_rag,
        },
        "data_quality": {
            "sign_anomaly_rows": anomaly_count,
            "total_tasks":       len(df),
            "labeled_tasks":     int(df["rag_code"].notna().sum()),
        },
    }
