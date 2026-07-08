"""
dag_builder.py — Parse MS Project Predecessors, build a task DAG, compute critical path.

Predecessor IDs are 1-indexed MS Project row numbers (pandas_index + 1).
Non-FS relationships (FF, SS, SF) are approximated as FS + lag and logged
in simplified_edges for full auditability.
"""
from __future__ import annotations

import re
from typing import Any

import networkx as nx
import pandas as pd

# Regex: (ID)(optional rel-type)(optional lag like +2d or -1d)
# The lag group (?:...) is non-capturing+optional so bare IDs like "226" still match
_PRED_RE = re.compile(
    r"(\d+)"                          # predecessor row ID
    r"\s*(FS|FF|SS|SF)?"              # optional relationship type
    r"(?:\s*([+-]\s*\d+)\s*d?)?",    # optional lag/lead in days
    re.IGNORECASE,
)

_NON_FS = {"FF", "SS", "SF"}       # these will be simplified to FS + lag


def parse_predecessors(pred_str: str) -> list[dict]:
    """
    Parse an MS Project predecessor string like '292, 293FS +2d'.

    Returns list of dicts: {id, rel_type, lag_days, simplified}
    """
    results = []
    for token in str(pred_str).split(","):
        m = _PRED_RE.search(token.strip())
        if not m:
            continue
        rel_type = (m.group(2) or "FS").upper()
        lag_str  = m.group(3)
        results.append({
            "id":         int(m.group(1)),
            "rel_type":   rel_type,
            "lag_days":   int(lag_str.replace(" ", "")) if lag_str else 0,
            "simplified": rel_type in _NON_FS,
        })
    return results


def build_dag(df: pd.DataFrame) -> dict[str, Any]:
    """
    Build a NetworkX DiGraph from the Predecessors column.

    Node IDs = 1-indexed (MS Project row number = pandas_index + 1).

    Returns
    -------
    dict with:
        graph                        : nx.DiGraph (nodes have 'duration' weight)
        critical_path                : list[int]  — node IDs on the longest path
        critical_path_duration_days  : float
        critical_path_task_names     : list[str]
        coverage                     : dict with counts and percentages
        simplified_edges             : list[(from_id, to_id, orig_rel)] — auditable
        roots                        : set[int]   — nodes with no incoming edges
    """
    n_tasks  = len(df)
    valid_ids = set(range(1, n_tasks + 1))

    # ── Build node set ─────────────────────────────────────────────────────
    G = nx.DiGraph()
    df_reset = df.reset_index(drop=True)   # ensure positional indexing is clean

    for i, row in df_reset.iterrows():
        task_id = i + 1
        dur = row.get("planned_days", None)
        dur = float(dur) if pd.notna(dur) and float(dur) > 0 else 1.0
        G.add_node(task_id,
                   duration=dur,
                   task_name=str(row.get("Task Name", ""))[:60])

    # ── Find Predecessors column ───────────────────────────────────────────
    pred_col = next(
        (c for c in df_reset.columns if "pred" in str(c).lower()), None
    )

    n_with_preds    = 0
    n_bad_edges     = 0
    simplified_edges: list[tuple[int, int, str]] = []

    if pred_col:
        for i, row in df_reset.iterrows():
            task_id  = i + 1
            raw_pred = row.get(pred_col)
            if pd.isna(raw_pred) or str(raw_pred).strip() == "":
                continue

            parsed = parse_predecessors(str(raw_pred))
            if not parsed:
                continue

            n_with_preds += 1
            for p in parsed:
                pred_id = p["id"]

                if pred_id == task_id:          # self-loop
                    n_bad_edges += 1
                    continue
                if pred_id not in valid_ids:    # out-of-range reference
                    n_bad_edges += 1
                    continue

                if p["simplified"]:
                    simplified_edges.append((pred_id, task_id, p["rel_type"]))

                G.add_edge(pred_id, task_id, lag=p["lag_days"])

                # Reject cycle-inducing edges
                if not nx.is_directed_acyclic_graph(G):
                    G.remove_edge(pred_id, task_id)
                    n_bad_edges += 1

    pct_coverage = n_with_preds / n_tasks if n_tasks > 0 else 0.0
    roots = {n for n in G.nodes() if G.in_degree(n) == 0}

    # ── Critical path: longest path by planned_days ────────────────────────
    critical_path:     list[int] = []
    cp_duration:       float     = 0.0
    cp_task_names:     list[str] = []

    if G.number_of_edges() > 0:
        try:
            topo = list(nx.topological_sort(G))
            dist = {n: G.nodes[n]["duration"] for n in topo}
            prev: dict[int, int | None] = {n: None for n in topo}

            for node in topo:
                for succ in G.successors(node):
                    lag       = G.edges[node, succ].get("lag", 0)
                    candidate = dist[node] + lag + G.nodes[succ]["duration"]
                    if candidate > dist[succ]:
                        dist[succ] = candidate
                        prev[succ] = node

            end_node    = max(dist, key=dist.get)
            cp_duration = dist[end_node]

            # Backtrack
            path: list[int] = []
            cur: int | None = end_node
            while cur is not None:
                path.append(cur)
                cur = prev[cur]
            critical_path = list(reversed(path))
            cp_task_names = [
                G.nodes[n].get("task_name", str(n)) for n in critical_path
            ]
        except Exception:
            pass

    return {
        "graph":                       G,
        "critical_path":               critical_path,
        "critical_path_duration_days": round(cp_duration, 1),
        "critical_path_task_names":    cp_task_names,
        "coverage": {
            "n_tasks":      n_tasks,
            "n_with_preds": n_with_preds,
            "pct_coverage": round(pct_coverage, 3),
            "n_bad_edges":  n_bad_edges,
            "n_simplified": len(simplified_edges),
            "n_roots":      len(roots),
        },
        "simplified_edges": simplified_edges,
        "roots":            roots,
    }
