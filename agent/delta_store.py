"""
delta_store.py — SQLite-backed state persistence for delta reporting.

Saves each run's computed scores.  On the next run, the agent compares
current scores to the previous week's and surfaces trends like:
  "Moved Amber → Red because schedule variance grew from 12 to 19 days."

This is the cheapest mechanism with the highest perceived intelligence gain.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import config


def _get_conn() -> sqlite3.Connection:
    Path(config.DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS weekly_scores (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            run_date      TEXT NOT NULL,
            project_name  TEXT NOT NULL,
            rag           TEXT,
            project_score REAL,
            forward_risk  REAL,
            historical_slip REAL,
            mc_p_on_time  REAL,
            n_red_tasks   INTEGER,
            n_active_risk INTEGER,
            extras        TEXT
        )
    """)
    conn.commit()
    return conn


def save_run(
    project_name: str,
    scores: dict[str, Any],
    mc_result: dict[str, Any],
    cluster_result: dict[str, Any],
    run_date: Optional[datetime] = None,
) -> None:
    """Persist this week's scores to the database."""
    if run_date is None:
        run_date = datetime.now()

    conn = _get_conn()
    conn.execute(
        """
        INSERT INTO weekly_scores
            (run_date, project_name, rag, project_score, forward_risk,
             historical_slip, mc_p_on_time, n_red_tasks, n_active_risk, extras)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_date.isoformat(),
            project_name,
            scores.get("rag"),
            scores.get("project_score"),
            scores.get("forward_risk"),
            scores.get("historical_slip"),
            mc_result.get("p_on_time"),
            scores.get("task_summary", {}).get("by_rag", {}).get("Red", 0),
            cluster_result.get("n_at_risk_active", 0),
            json.dumps({
                "critical_path": scores.get("critical_path"),
                "data_quality":  scores.get("data_quality"),
                "mc_caveat":     mc_result.get("caveat"),
            }),
        ),
    )
    conn.commit()
    conn.close()


def load_previous(project_name: str, n: int = 1) -> list[dict[str, Any]]:
    """Return the last n run records for a project (most recent first)."""
    conn = _get_conn()
    rows = conn.execute(
        """
        SELECT run_date, rag, project_score, forward_risk, historical_slip,
               mc_p_on_time, n_red_tasks, n_active_risk
        FROM   weekly_scores
        WHERE  project_name = ?
        ORDER  BY run_date DESC
        LIMIT  ?
        """,
        (project_name, n),
    ).fetchall()
    conn.close()

    keys = ["run_date", "rag", "project_score", "forward_risk",
            "historical_slip", "mc_p_on_time", "n_red_tasks", "n_active_risk"]
    return [dict(zip(keys, row)) for row in rows]


def build_delta(
    project_name: str,
    current: dict[str, Any],
) -> dict[str, Any]:
    """
    Compare current scores to the previous run.
    Returns a delta dict that the report writer can render as change indicators.
    """
    previous_runs = load_previous(project_name, n=2)
    # Skip the very latest (which IS the current run just saved)
    prev = previous_runs[1] if len(previous_runs) >= 2 else None

    if prev is None:
        return {"has_previous": False, "note": "First run — no previous data."}

    curr_score = current.get("project_score", 0)
    prev_score = prev.get("project_score", 0)
    curr_rag   = current.get("rag", "Unknown")
    prev_rag   = prev.get("rag", "Unknown")

    rag_changed = curr_rag != prev_rag
    score_delta = round(curr_score - prev_score, 4)
    direction   = "↑ worse" if score_delta > 0.02 else ("↓ better" if score_delta < -0.02 else "→ stable")

    # Build a human-readable change sentence
    if rag_changed:
        change_sentence = (
            f"Status moved **{prev_rag} → {curr_rag}** since last run "
            f"(score: {prev_score:.2f} → {curr_score:.2f}, {direction})."
        )
    else:
        change_sentence = (
            f"Status held at **{curr_rag}** "
            f"(score: {prev_score:.2f} → {curr_score:.2f}, {direction})."
        )

    return {
        "has_previous":     True,
        "prev_run_date":    prev.get("run_date", "Unknown"),
        "prev_rag":         prev_rag,
        "curr_rag":         curr_rag,
        "rag_changed":      rag_changed,
        "score_delta":      score_delta,
        "direction":        direction,
        "red_tasks_delta":  current.get("task_summary", {}).get("by_rag", {}).get("Red", 0) - (prev.get("n_red_tasks") or 0),
        "change_sentence":  change_sentence,
    }
