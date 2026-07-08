"""
cluster_analyzer.py — At-risk task clustering by Area / Phase / Owner.

Clusters ACTIVE at-risk tasks (not sparse comments) using TF-IDF on combined
Area + Phase + Owner text, then identifies dominant risk concentrations.

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


def _build_text_field(df: pd.DataFrame) -> pd.Series:
    """Combine Area + Phase/Milestone + Assigned To into a single text column."""
    return (
        df["Area"].fillna("unknown_area") + " " +
        df["Phase/Milestone"].fillna("unknown_phase") + " " +
        df["Assigned To"].fillna("unknown_owner")
    ).str.lower().str.strip()


def analyze(df: pd.DataFrame) -> dict[str, Any]:
    """
    Cluster active at-risk / In-Progress tasks.

    Returns
    -------
    dict with:
        n_at_risk_active  : count of active at-risk tasks
        clusters          : list of cluster summaries
        headline          : one-liner insight for the report
        caveat            : data limitation note
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

    text   = _build_text_field(active_risky)
    n_clus = min(config.N_CLUSTERS, n_risky)

    # TF-IDF on combined metadata text
    vec    = TfidfVectorizer(max_features=50, ngram_range=(1, 2))
    X      = vec.fit_transform(text)
    X_norm = normalize(X)

    km = KMeans(n_clusters=n_clus, random_state=42, n_init=10)
    active_risky = active_risky.copy()
    active_risky["cluster"] = km.fit_predict(X_norm)

    clusters = []
    for cid in range(n_clus):
        members = active_risky[active_risky["cluster"] == cid]
        pct     = round(100 * len(members) / n_risky)

        # Dominant Area and Assigned To within this cluster
        top_area  = members["Area"].value_counts().index[0] if members["Area"].notna().any() else "N/A"
        top_phase = members["Phase/Milestone"].value_counts().index[0] if members["Phase/Milestone"].notna().any() else "N/A"
        top_owner = members["Assigned To"].value_counts().index[0] if members["Assigned To"].notna().any() else "N/A"
        red_count = (members["RAG"] == "Red").sum()

        clusters.append({
            "cluster_id":   cid,
            "task_count":   len(members),
            "pct_of_risk":  pct,
            "top_area":     top_area,
            "top_phase":    top_phase,
            "top_owner":    top_owner,
            "red_tasks":    int(red_count),
            "task_names":   members["Task Name"].dropna().tolist()[:5],
        })

    # Sort by size descending
    clusters.sort(key=lambda c: c["task_count"], reverse=True)

    # Headline insight
    biggest = clusters[0]
    headline = (
        f"{biggest['pct_of_risk']}% of active risk tasks cluster around "
        f"'{biggest['top_area']}' / '{biggest['top_phase']}', "
        f"primarily owned by '{biggest['top_owner']}'."
    )

    return {
        "n_at_risk_active": n_risky,
        "clusters":         clusters,
        "headline":         headline,
        "caveat": (
            "Clustered on task Area + Phase + Owner metadata. "
            "Comment-based clustering skipped (sparse data: ~10 comments in S2P, 0 in Project B)."
        ),
    }
