"""
cluster_analyzer.py — At-risk task clustering.

Clusters ACTIVE at-risk tasks using TF-IDF on available metadata.
Field sparsity is checked upfront: Area and Phase/Milestone are >98% empty
in both source files, so clustering falls back to Owner + task-name similarity.
This is explicitly flagged in the caveat returned with every cluster result.

Caveat: Comments sheet is sparse (10 rows in S2P, empty in Project B),
so clustering is done on task metadata — not comment sentiment.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.preprocessing import normalize

import config

# Threshold below which a column is considered "too sparse to use"
_SPARSITY_THRESHOLD = 0.10   # column must be non-null in >10% of rows to contribute


def _build_text_field(df: pd.DataFrame) -> tuple[pd.Series, list[str]]:
    """
    Combine available non-sparse metadata columns into a single text column.
    Returns (text_series, list_of_columns_actually_used).
    Columns that are >90% null are excluded and documented in the caveat.
    """
    parts: list[pd.Series] = []
    used:  list[str]       = []

    col_map = {
        "Area":             "Area",
        "Phase/Milestone":  "Phase/Milestone",
        "Assigned To":      "Owner",
        "Task Name":        "Task Name",
    }
    for col, label in col_map.items():
        if col in df.columns:
            fill_rate = df[col].notna().mean()
            if fill_rate > _SPARSITY_THRESHOLD:
                parts.append(df[col].fillna(""))
                used.append(label)

    if not parts:
        # Ultimate fallback: index as string
        return pd.Series(df.index.astype(str)), ["row index"]

    text = parts[0].copy()
    for p in parts[1:]:
        text = text + " " + p
    return text.str.lower().str.strip(), used


def analyze(df: pd.DataFrame) -> dict[str, Any]:
    """
    Cluster active at-risk / In-Progress tasks.

    Returns
    -------
    dict with:
        n_at_risk_active  : count of active at-risk tasks
        clusters          : list of cluster summaries
        headline          : one-liner insight for the report
        caveat            : data limitation note (honest about sparse fields)
    """
    # Active tasks that are Red or explicitly At Risk
    active_risky = df[
        df["Status"].isin(["In Progress", "Not Started"]) &
        (
            (df["RAG"].isin(["Red", "Yellow"])) |
            df["is_at_risk"] |
            df["is_on_hold"]
        )
    ].copy()

    n_risky = len(active_risky)

    if n_risky < 3:
        return {
            "n_at_risk_active": n_risky,
            "clusters":         [],
            "headline":         f"Only {n_risky} active at-risk tasks — too few to cluster.",
            "caveat":           "Clustering skipped due to small sample.",
        }

    text, used_cols = _build_text_field(active_risky)
    n_clus = min(config.N_CLUSTERS, n_risky)

    # Check which columns are sparse (to report honestly)
    sparse_cols = []
    for col in ["Area", "Phase/Milestone"]:
        if col in active_risky.columns:
            fill_rate = active_risky[col].notna().mean()
            if fill_rate <= _SPARSITY_THRESHOLD:
                sparse_cols.append(f"{col} ({fill_rate*100:.0f}% populated)")

    # TF-IDF on combined metadata text
    vec    = TfidfVectorizer(max_features=50, ngram_range=(1, 2))
    X      = vec.fit_transform(text)
    X_norm = normalize(X)

    km = KMeans(n_clusters=n_clus, random_state=42, n_init=10)
    active_risky = active_risky.copy()
    active_risky["cluster"] = km.fit_predict(X_norm)

    clusters = []
    for cid in range(n_clus):
        members  = active_risky[active_risky["cluster"] == cid]
        pct      = round(100 * len(members) / n_risky)
        red_count = (members["RAG"] == "Red").sum()

        # Only surface a field's top value if the field is actually populated
        def top_val(col: str) -> str:
            non_null = members[col].dropna() if col in members.columns else pd.Series(dtype=str)
            non_null = non_null[non_null.str.strip() != ""]
            return non_null.value_counts().index[0] if len(non_null) > 0 else "—"

        top_area  = top_val("Area")
        top_phase = top_val("Phase/Milestone")
        top_owner = top_val("Assigned To")

        clusters.append({
            "cluster_id":  cid,
            "task_count":  len(members),
            "pct_of_risk": pct,
            "top_area":    top_area,
            "top_phase":   top_phase,
            "top_owner":   top_owner,
            "red_tasks":   int(red_count),
            "task_names":  members["Task Name"].dropna().tolist()[:5],
        })

    # Sort by size descending
    clusters.sort(key=lambda c: c["task_count"], reverse=True)

    # Build honest headline — don't surface "N/A" as a finding
    biggest   = clusters[0]
    owner_str = f"primarily owned by '{biggest['top_owner']}'" if biggest["top_owner"] != "—" else "owner unassigned"

    if biggest["top_area"] != "—":
        area_str = f"'{biggest['top_area']}' / '{biggest['top_phase']}'"
        headline = (
            f"{biggest['pct_of_risk']}% of active risk tasks cluster around "
            f"{area_str}, {owner_str}."
        )
    else:
        # Area/Phase empty — surface Owner as the primary signal
        headline = (
            f"{biggest['pct_of_risk']}% of active risk tasks are {owner_str} "
            f"(Area/Phase not populated in source data — clustered on {', '.join(used_cols)})."
        )

    # Build caveat — explicitly state what was and wasn't used
    if sparse_cols:
        sparse_note = (
            f"Note: {'; '.join(sparse_cols)} — these fields were excluded from "
            f"clustering. Clustering based on: {', '.join(used_cols)} only."
        )
    else:
        sparse_note = f"Clustering based on: {', '.join(used_cols)}."

    caveat = (
        f"{sparse_note} "
        "Comment-based clustering skipped (sparse data: ~10 comments in S2P, 0 in UniSan)."
    )

    return {
        "n_at_risk_active": n_risky,
        "clusters":         clusters,
        "headline":         headline,
        "caveat":           caveat,
    }
