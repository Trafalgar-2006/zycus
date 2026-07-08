"""
monte_carlo.py — Deadline probability simulation.

Uses the distribution of (actual elapsed / planned) ratios from completed
tasks to simulate remaining task durations — NOT the Variance column, whose
magnitude is unreliable (PM-tool cascaded, empirically verified).

Caveat stated in output: single-snapshot data, no weekly history.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import networkx as nx
import numpy as np
import pandas as pd

import config


def _duration_ratios(df: pd.DataFrame) -> np.ndarray:
    """
    Compute (actual_elapsed / planned) for completed tasks where both are known.
    Returns array of ratios (spans both sides of 1.0 — renamed from 'overrun').
    """
    done = df[
        (df["Status"] == "Completed") &
        df["planned_days"].notna() &
        df["actual_elapsed_wd"].notna() &
        (df["planned_days"] > 0)
    ].copy()

    ratios = done["actual_elapsed_wd"] / done["planned_days"]
    # Drop extreme outliers (>5x planned) — likely data entry errors
    ratios = ratios[(ratios > 0) & (ratios < 5)]
    return ratios.values


# Maximum planned_days to accept for a single task when summing remaining work.
# Tasks above this threshold are almost certainly parent/summary rollup rows
# whose Duration is a PM-tool cascade (empirically: 57% of parent Durations
# don't match sum or max of children). 45 working days ≈ 9 calendar weeks —
# a generous upper bound for a single delivery task in this project type.
_MAX_LEAF_TASK_DAYS = 45


def _remaining_work_days(df: pd.DataFrame, today: datetime) -> float:
    """
    Estimate remaining planned working days for non-completed tasks.

    Filters to tasks with planned_days <= _MAX_LEAF_TASK_DAYS to exclude
    parent/summary rows whose Duration is a PM-tool cascade rollup and
    would otherwise be double-counted alongside their children.
    """
    active = df[
        ~df["Status"].isin(["Completed", "Not Applicable"]) &
        df["planned_days"].notna() &
        (df["planned_days"] <= _MAX_LEAF_TASK_DAYS)   # leaf-task heuristic
    ].copy()

    remaining = active["planned_days"] * (1 - active["pct_complete"].fillna(0))
    return float(remaining.sum())


def simulate(
    df: pd.DataFrame,
    n_simulations: int = config.MONTE_CARLO_SIMULATIONS,
    today: datetime | None = None,
) -> dict[str, Any]:
    """
    Run Monte Carlo simulation for project deadline probability.

    Returns
    -------
    dict with:
        deadline                  : project end date from Summary
        p_on_time                 : P(finish by deadline)
        p_slip_1w                 : P(slip 1–7 days)
        p_slip_2w_plus            : P(slip > 14 days)
        median_finish_days_from_now
        duration_ratio_mean       : mean of historical duration ratios
        duration_ratio_std        : std of historical duration ratios
        n_ratio_samples           : how many completed tasks informed the distribution
        caveat                    : honest limitation statement
    """
    if today is None:
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

    # ── Pull project deadline from Summary metadata ──────────────────────────
    summary  = df.attrs.get("summary", {})
    deadline = summary.get("Project End Date")
    if not isinstance(deadline, datetime):
        deadline = None

    # ── Build duration ratio distribution ────────────────────────────────────
    ratios = _duration_ratios(df)
    n_samples = len(ratios)

    if n_samples < 5:
        # Not enough data for a meaningful distribution
        return {
            "deadline":        str(deadline.date()) if deadline else "Unknown",
            "p_on_time":       None,
            "caveat": (
                f"Insufficient completed tasks with date data ({n_samples} found). "
                "Monte Carlo skipped."
            ),
        }

    ratio_mean = float(np.mean(ratios))
    ratio_std  = float(np.std(ratios))

    # ── Throughput-based remaining time estimate ─────────────────────────────
    # Serial sum of remaining task durations vastly overstates calendar time
    # because it ignores team parallelism (22–42 tasks run concurrently).
    # Instead: measure the historical task completion rate (tasks/week) from
    # actual End Dates of completed tasks, then project remaining tasks.
    #
    # This is more honest than dividing by an assumed concurrency factor, and
    # it naturally captures the real pace of the team over the project history.

    completed = df[df["Status"] == "Completed"].copy()
    completed["end_date"] = pd.to_datetime(completed["End Date"], errors="coerce")
    completed = completed.dropna(subset=["end_date"])

    # Compute project start (earliest end date) and span in weeks
    if len(completed) >= 5:
        earliest         = completed["end_date"].min()
        latest_completed = completed["end_date"].max()
        span_weeks       = max((latest_completed - earliest).days / 7, 1.0)
        tasks_per_week   = len(completed) / span_weeks

        # Stability check: first-half vs second-half completion rate
        mid         = earliest + (latest_completed - earliest) / 2
        half_weeks  = span_weeks / 2
        r1 = len(completed[completed["end_date"] <= mid]) / max(half_weeks, 1.0)
        r2 = len(completed[completed["end_date"] >  mid]) / max(half_weeks, 1.0)
        _rate_ratio = r2 / r1 if r1 > 0 else 1.0
    else:
        tasks_per_week = 1.0   # conservative fallback
        _rate_ratio    = 1.0

    active_statuses = {"In Progress", "Not Started"}
    n_remaining = int(df["Status"].isin(active_statuses).sum())

    if n_remaining <= 0:
        return {
            "deadline":    str(deadline.date()) if deadline else "Unknown",
            "p_on_time":   1.0,
            "caveat":      "No remaining tasks detected — project may be complete.",
        }

    # Base estimate: weeks remaining = remaining tasks / completion rate
    weeks_remaining_base     = n_remaining / tasks_per_week
    remaining_calendar_days  = weeks_remaining_base * 7

    # ── Simulate ─────────────────────────────────────────────────────────────
    # Apply log-normal ratio to the throughput-implied remaining duration.
    # ratio < 1 → project running ahead of historical pace; > 1 → behind.
    log_mean = np.log(ratio_mean ** 2 / np.sqrt(ratio_std ** 2 + ratio_mean ** 2))
    log_std  = np.sqrt(np.log(1 + (ratio_std / ratio_mean) ** 2))

    rng            = np.random.default_rng(seed=42)
    sampled_ratios = rng.lognormal(log_mean, log_std, size=n_simulations)
    simulated_calendar = remaining_calendar_days * sampled_ratios
    finish_dates       = [today + timedelta(days=float(d)) for d in simulated_calendar]

    if deadline is None:
        return {
            "deadline":            "Unknown — no end date in Summary",
            "p_on_time":           None,
            "median_finish":       str((today + timedelta(days=float(np.median(simulated_calendar)))).date()),
            "tasks_remaining":     n_remaining,
            "tasks_per_week":      round(tasks_per_week, 1),
            "duration_ratio_mean": round(ratio_mean, 3),
            "duration_ratio_std":  round(ratio_std, 3),
            "n_ratio_samples":     n_samples,
            "caveat":              "No project deadline found; cannot compute on-time probability.",
        }

    n_on_time   = sum(d <= deadline for d in finish_dates)
    n_slip_1w   = sum(deadline < d <= deadline + timedelta(days=7)  for d in finish_dates)
    n_slip_2w   = sum(d > deadline + timedelta(days=14) for d in finish_dates)
    median_days = float(np.median(simulated_calendar))

    _stability_note = ""
    if _rate_ratio > 2.0:
        _stability_note = (
            f" NOTE: completion rate nearly tripled in second half of project "
            f"(x{_rate_ratio:.1f} acceleration) — mean rate may overstate future pace "
            f"if this was a catch-up sprint. P(on-time) may be optimistic."
        )
    elif _rate_ratio < 0.5:
        _stability_note = (
            f" NOTE: completion rate halved in second half (x{_rate_ratio:.1f} deceleration) "
            f"— mean rate may understate risk. P(on-time) may be optimistic relative to current pace."
        )

    return {
        "deadline":                    str(deadline.date()),
        "p_on_time":                   round(n_on_time / n_simulations, 3),
        "p_slip_1w":                   round(n_slip_1w / n_simulations, 3),
        "p_slip_2w_plus":              round(n_slip_2w / n_simulations, 3),
        "median_finish_days_from_now": round(median_days),
        "median_finish_date":          str((today + timedelta(days=median_days)).date()),
        "tasks_remaining":             n_remaining,
        "tasks_per_week":              round(tasks_per_week, 1),
        "throughput_stability_ratio":  round(_rate_ratio, 2),
        "duration_ratio_mean":         round(ratio_mean, 3),
        "duration_ratio_std":          round(ratio_std, 3),
        "n_ratio_samples":             n_samples,
        "caveat": (
            "Based on single-snapshot data. "
            f"Completion rate: {tasks_per_week:.1f} tasks/week from {len(completed)} completed tasks. "
            f"Remaining: {n_remaining} active tasks. "
            f"Duration ratio (log-normal) fitted from {n_samples} tasks with parseable dates. "
            "No weekly history or dependency graph available — treat as directional."
            + _stability_note
        ),
    }


def simulate_v2(
    df: pd.DataFrame,
    dag_info: dict,
    n_simulations: int = config.MONTE_CARLO_SIMULATIONS,
    today: datetime | None = None,
) -> dict[str, Any]:
    """
    Dependency-aware Monte Carlo: propagate sampled task durations through the DAG.

    Algorithm
    ---------
    For each simulation:
      1. Sample each task's duration: planned_days × lognormal(ratio_mean, ratio_std)
      2. Topological traversal: task_start = max(pred_finish + lag) for all predecessors
      3. project_finish = max(task_finish) across all leaf nodes

    Completed tasks get duration = 0 (already done).
    Tasks missing planned_days fall back to dataset mean (logged in n_fallback).
    """
    if today is None:
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

    G       = dag_info.get("graph")
    cov     = dag_info.get("coverage", {})
    simplified_edges = dag_info.get("simplified_edges", [])

    if G is None or G.number_of_nodes() == 0:
        return {"p_on_time": None, "caveat": "DAG unavailable.", "model": "dependency_aware"}

    # ── Duration distribution (same log-normal as v1) ──────────────────────
    ratios = _duration_ratios(df)
    if len(ratios) < 5:
        return {
            "p_on_time": None,
            "caveat":    "Insufficient completed tasks for duration distribution.",
            "model":     "dependency_aware",
        }

    ratio_mean = float(np.mean(ratios))
    ratio_std  = float(np.std(ratios))
    log_mean   = np.log(ratio_mean ** 2 / np.sqrt(ratio_std ** 2 + ratio_mean ** 2))
    log_std    = np.sqrt(np.log(1 + (ratio_std / ratio_mean) ** 2))

    # ── Base durations per node (remaining work) ───────────────────────────
    df_r           = df.reset_index(drop=True)
    mean_dur       = float(df_r["planned_days"].dropna().mean())
    done_statuses  = {"Completed", "Not Applicable"}
    task_base: dict[int, float] = {}
    n_fallback = 0

    for node in G.nodes():
        idx = node - 1
        if not (0 <= idx < len(df_r)):
            task_base[node] = mean_dur
            n_fallback += 1
            continue
        row = df_r.iloc[idx]
        if row["Status"] in done_statuses:
            task_base[node] = 0.0
        else:
            pdays = row.get("planned_days", None)
            if pd.notna(pdays) and float(pdays) > 0:
                pct = row.get("pct_complete", 0.0)
                pct = float(pct) if pd.notna(pct) else 0.0
                task_base[node] = float(pdays) * max(0.0, 1.0 - pct)
            else:
                task_base[node] = mean_dur
                n_fallback += 1

    # ── Topological order ──────────────────────────────────────────────────
    try:
        topo_order = list(nx.topological_sort(G))
    except Exception:
        return {"p_on_time": None, "caveat": "DAG has cycles.", "model": "dependency_aware"}

    # ── Pre-sample ratios: (n_sims, n_nodes) ──────────────────────────────
    rng          = np.random.default_rng(seed=42)
    node_col     = {n: i for i, n in enumerate(topo_order)}
    sampled_r    = rng.lognormal(log_mean, log_std, size=(n_simulations, len(topo_order)))

    # Completed tasks: force ratio = 0 (zero remaining duration)
    for node in topo_order:
        if task_base.get(node, 1.0) == 0.0:
            sampled_r[:, node_col[node]] = 0.0

    # Build predecessor lookup once
    pred_lookup: dict[int, list[tuple[int, float]]] = {
        node: [(p, G.edges[p, node].get("lag", 0.0))
               for p in G.predecessors(node)]
        for node in topo_order
    }

    # ── Simulate ──────────────────────────────────────────────────────────
    proj_finish = np.zeros(n_simulations)

    for sim_i in range(n_simulations):
        finish: dict[int, float] = {}
        for node in topo_order:
            dur   = task_base.get(node, mean_dur) * sampled_r[sim_i, node_col[node]]
            preds = pred_lookup[node]
            start = max((finish.get(p, 0.0) + lag for p, lag in preds), default=0.0)
            finish[node] = start + dur
        proj_finish[sim_i] = max(finish.values(), default=0.0)

    # ── Summarise ─────────────────────────────────────────────────────────
    summary  = df.attrs.get("summary", {})
    deadline = summary.get("Project End Date")
    if not isinstance(deadline, datetime):
        deadline = None

    median_finish = today + timedelta(days=float(np.median(proj_finish)))
    n_edges       = G.number_of_edges()
    n_simp        = len(simplified_edges)
    simp_pct      = 100 * n_simp / max(n_edges, 1)

    caveat = (
        f"Graph covers {cov.get('n_with_preds', 0)}/{cov.get('n_tasks', 0)} tasks "
        f"({cov.get('pct_coverage', 0):.0%} have predecessor data). "
        f"Tasks without predecessors start immediately (treated as roots). "
        + (f"{n_simp} non-FS edge(s) ({simp_pct:.0f}% of edges) simplified to FS+lag "
           f"[types: {', '.join(set(e[2] for e in simplified_edges))}]. "
           if n_simp > 0 else "")
        + (f"{n_fallback} task(s) used dataset-mean duration (planned_days missing). "
           if n_fallback > 0 else "")
        + "No resource leveling applied."
    )

    if deadline is None:
        return {
            "deadline":             "Unknown",
            "p_on_time":            None,
            "median_finish_date":   str(median_finish.date()),
            "model":                "dependency_aware",
            "n_fallback_durations": n_fallback,
            "caveat":               caveat,
        }

    days_to_dl = (deadline - today).days
    p_on_time  = float((proj_finish <= days_to_dl).mean())
    p_slip_1w  = float(((proj_finish > days_to_dl) & (proj_finish <= days_to_dl + 7)).mean())
    p_slip_2w  = float((proj_finish > days_to_dl + 14).mean())

    return {
        "deadline":             str(deadline.date()),
        "p_on_time":            p_on_time,
        "p_slip_1w":            p_slip_1w,
        "p_slip_2w_plus":       p_slip_2w,
        "median_finish_date":   str(median_finish.date()),
        "model":                "dependency_aware",
        "n_fallback_durations": n_fallback,
        "dag_n_edges":          n_edges,
        "caveat":               caveat,
    }
