"""
report_writer.py — Formats the full weekly Markdown report.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import config

_RAG_EMOJI = {"Green": "🟢", "Amber": "🟡", "Red": "🔴"}
_RAG_REASONS = {
    "Red":   "High forward risk and historical slip — critical-path tasks at elevated risk.",
    "Amber": "Moderate forward risk — monitor critical-path tasks and slip trend closely.",
    "Green": "Low forward risk; historical slip within tolerance.",
}


def _rag_badge(rag: str) -> str:
    return f"{_RAG_EMOJI.get(rag, '⚪')} **{rag}**"


def _mc_section(mc: dict) -> str:
    """Single-model MC table (used as v1 / fallback when v2 is unavailable)."""
    if mc.get("p_on_time") is None:
        return f"> ⚠️ {mc.get('caveat', 'Monte Carlo unavailable.')}\n"
    return (
        f"| Metric | Value |\n|--------|-------|\n"
        f"| Deadline | {mc['deadline']} |\n"
        f"| **P(on time)** | **{mc['p_on_time']*100:.0f}%** |\n"
        f"| P(slip 1 week) | {mc.get('p_slip_1w', 0)*100:.0f}% |\n"
        f"| P(slip 2+ weeks) | {mc.get('p_slip_2w_plus', 0)*100:.0f}% |\n"
        f"| Median finish | {mc.get('median_finish_date', 'N/A')} |\n"
        f"| Duration ratio mean | {mc.get('duration_ratio_mean', 'N/A')} "
        f"(std: {mc.get('duration_ratio_std', 'N/A')}) |\n"
        f"| Sample tasks | {mc.get('n_ratio_samples', 0)} completed tasks |\n\n"
        f"> *{mc.get('caveat', '')}*\n"
    )


def _mc_comparison_section(mc_v1: dict, mc_v2: dict | None) -> str:
    """Side-by-side model comparison when v2 is available."""
    if mc_v2 is None or mc_v2.get("model") == "skipped_low_coverage":
        # v2 not available — show v1 with reason
        section = _mc_section(mc_v1)
        if mc_v2:
            section += f"\n> ⚠️ {mc_v2.get('caveat', '')}\n"
        return section

    # Both available — show comparison table
    v1_p = f"{mc_v1['p_on_time']*100:.0f}%" if mc_v1.get('p_on_time') is not None else "N/A"
    v2_p = f"{mc_v2['p_on_time']*100:.0f}%" if mc_v2.get('p_on_time') is not None else "N/A"
    v1_med = mc_v1.get('median_finish_date', 'N/A')
    v2_med = mc_v2.get('median_finish_date', 'N/A')
    deadline = mc_v1.get('deadline', mc_v2.get('deadline', 'N/A'))

    # Interpretation note — compute pp from DISPLAYED rounded values so text matches table
    if mc_v1.get('p_on_time') is not None and mc_v2.get('p_on_time') is not None:
        v1_disp = round(mc_v1['p_on_time'] * 100)
        v2_disp = round(mc_v2['p_on_time'] * 100)
        diff_pp = v2_disp - v1_disp
        if abs(diff_pp) <= 2:
            interp = "Models agree within 2 pp — dependency constraints add little schedule pressure beyond the throughput baseline."
        elif diff_pp < 0:
            interp = (f"Dependency-aware model is {abs(diff_pp)} pp lower than throughput baseline — "
                      "predecessor constraints introduce sequencing delays not visible in raw completion rate.")
        else:
            interp = (f"Dependency-aware model is {diff_pp} pp higher than throughput baseline — "
                      "parallel predecessor paths absorb some schedule risk visible in throughput extrapolation.")
    else:
        interp = ""

    return (
        f"| Model | Basis | P(on-time) | Median Finish |\n"
        f"|-------|-------|-----------|---------------|\n"
        f"| Throughput (v1, baseline) | Completion rate × log-normal variance | **{v1_p}** | {v1_med} |\n"
        f"| Dependency-aware DAG (v2) | Topological propagation through predecessor graph | **{v2_p}** | {v2_med} |\n\n"
        f"**Deadline:** {deadline}\n\n"
        + (f"> *{interp}*\n\n" if interp else "")
        + f"> *v1 caveat: {mc_v1.get('caveat', '')}*\n\n"
        + f"> *v2 caveat: {mc_v2.get('caveat', '')}*\n"
    )


def _cp_comparison_section(scores: dict, dag_info: dict | None) -> str:
    """PM-flagged vs graph-computed critical path comparison.
    
    For projects with <50% predecessor coverage, the graph CP is a partial
    result on a sparse graph and should not be presented as if complete.
    """
    pm_total = scores.get("critical_path", {}).get("total", 0)
    pm_red   = scores.get("critical_path", {}).get("by_rag", {}).get("Red", 0)

    if dag_info is None or not dag_info.get("critical_path"):
        return (
            f"| Critical Path Tasks (PM-flagged) | {pm_total} |\n"
            f"| Red on Critical Path | {pm_red} |\n"
        )

    cov       = dag_info.get("coverage", {})
    pct_cov   = cov.get("pct_coverage", 0)
    graph_cp  = dag_info["critical_path"]
    graph_n   = len(graph_cp)
    cp_dur    = dag_info.get("critical_path_duration_days", 0)

    # If coverage too sparse, show PM count + note but don't imply graph CP is authoritative
    if pct_cov < config.DAG_MIN_COVERAGE:
        return (
            f"| Critical Path (PM-flagged) | {pm_total} tasks | {pm_red} Red |\n"
            f"| Critical Path (graph) | {graph_n} task(s) | "
            f"*(sparse — only {pct_cov:.0%} predecessor coverage; "
            f"graph CP is a partial result on {cov.get('n_with_preds', 0)} connected tasks, "
            f"not a complete project CP)* |\n"
        )

    diff      = graph_n - pm_total
    diff_note = ""
    if diff > 0:
        diff_note = f" ({diff} tasks structurally critical but not PM-flagged)"
    elif diff < 0:
        diff_note = f" ({abs(diff)} tasks PM-flagged but not on longest graph path)"

    return (
        f"| Critical Path (PM-flagged) | {pm_total} tasks | {pm_red} Red |"
        f" *(source: \"Critical ?\" column)*\n"
        f"| Critical Path (graph-computed) | {graph_n} tasks | {cp_dur:.0f} planned days |"
        f" *(longest path by duration through predecessor DAG)*{diff_note}\n"
    )


def _data_confidence_tag(df, dag_info: dict | None) -> str:
    """
    One-line data confidence tier based on key field null rates + predecessor coverage.
    High: weighted badness <20%; Medium: 20–45%; Low: >45%.
    """
    plan_null = float(df["planned_days"].isna().mean()) if "planned_days" in df.columns else 1.0
    pct_null  = float(df["pct_complete"].isna().mean())  if "pct_complete"  in df.columns else 1.0
    pred_gap  = 1.0 - (dag_info or {}).get("coverage", {}).get("pct_coverage", 1.0)
    # pred_gap weighted higher: it controls whether DAG-MC is trustworthy
    bad = 0.4 * pred_gap + 0.3 * plan_null + 0.3 * pct_null

    tier, emoji = ("High", "🟢") if bad < 0.20 else (("Medium", "🟡") if bad < 0.45 else ("Low", "🔴"))
    pred_pct    = (1.0 - pred_gap) * 100
    return (
        f"**Data Confidence: {emoji} {tier}** — "
        f"predecessor coverage: {pred_pct:.0f}%; "
        f"planned\_days missing: {plan_null*100:.0f}%; "
        f"pct\_complete missing: {pct_null*100:.0f}%"
    )


def _naive_baseline_section(df, mc: dict, mc_v2: dict | None, scores: dict) -> str:
    """
    Side-by-side: naive %-complete vs this agent's assessment.
    Answers: 'Why does this tool add value beyond a tracking spreadsheet?'
    """
    active    = df[~df["Status"].isin(["Completed", "Not Applicable"])]
    naive_pct = active["pct_complete"].fillna(0).mean() if len(active) > 0 else 0.0

    summary = df.attrs.get("summary", {})
    start   = summary.get("Project Start Date")
    end     = summary.get("Project End Date")
    today   = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

    time_pct_str  = "N/A"
    naive_verdict = "Cannot assess (missing project dates)"
    if isinstance(start, datetime) and isinstance(end, datetime):
        elapsed    = max((today - start).days, 0)
        total_days = max((end - start).days, 1)
        time_pct   = min(elapsed / total_days * 100, 100)
        time_pct_str = f"{time_pct:.0f}%"
        gap = naive_pct * 100 - time_pct
        naive_verdict = (
            f"On track ({naive_pct*100:.0f}% done; {time_pct:.0f}% of schedule elapsed)"
            if gap >= -5 else
            f"Behind — {naive_pct*100:.0f}% done, {time_pct:.0f}% of time elapsed ({abs(gap):.0f}pp gap)"
        )

    p_on = mc.get("p_on_time")
    p_v2 = (mc_v2 or {}).get("p_on_time")
    p_str = f"{round(p_on*100)}%" if p_on is not None else "N/A"
    v2_note = f" → {round(p_v2*100)}% after dependency-graph correction (DAG v2)" if p_v2 is not None else ""
    red_cp    = scores.get("critical_path", {}).get("by_rag", {}).get("Red", 0)
    cp_total  = scores.get("critical_path", {}).get("total", 0)

    return (
        f"| View | Signal | Verdict |\n"
        f"|------|--------|---------|​\n"
        f"| **Naïve (% complete vs time)** "
        f"| {naive_pct*100:.0f}% tasks done; {time_pct_str} of schedule elapsed "
        f"| {naive_verdict} |\n"
        f"| **This agent — RAG + ML** "
        f"| Score {scores['project_score']:.3f}; {red_cp}/{cp_total} critical-path tasks Red "
        f"| **{scores.get('rag', 'N/A')}** |\n"
        f"| **This agent — Monte Carlo** "
        f"| 10,000 simulations, historical duration ratios from completed tasks "
        f"| P(on-time) = {p_str}{v2_note} |\n\n"
        f"> *The naïve view ignores velocity trends, critical-path composition, and duration variance. "
        f"The agent's MC uses historical slip rates from completed tasks"
        + (" and propagates them through the predecessor DAG" if p_v2 is not None else "")
        + " — producing a calibrated probability rather than a binary on/off.*\n"
    )


def write_exec_summary(
    project_name: str,
    df,
    scores: dict[str, Any],
    mc: dict[str, Any],
    mc_v2: dict[str, Any] | None,
    cluster: dict[str, Any],
    dag_info: dict[str, Any] | None,
    narrative: str,
    run_date: datetime,
    output_dir: str = "outputs/exec",
) -> Path:
    """One-page executive summary: RAG badge, reason, P(on-time), one action item."""
    rag       = scores["rag"]
    emoji     = _RAG_EMOJI.get(rag, "⚪")
    score     = scores["project_score"]
    fwd       = scores.get("forward_risk", 0)
    slip      = scores.get("historical_slip", 0)
    red_cp    = scores.get("critical_path", {}).get("by_rag", {}).get("Red", 0)
    cp_total  = scores.get("critical_path", {}).get("total", 0)

    reason = (
        f"High forward risk ({fwd:.0%}) with {red_cp}/{cp_total} Red tasks on the critical path; "
        f"historical slip {slip:.0%}." if rag == "Red" else
        f"Moderate forward risk ({fwd:.0%}); {red_cp} Red critical-path task(s); slip {slip:.0%}." if rag == "Amber" else
        f"Low forward risk ({fwd:.0%}); historical slip within tolerance ({slip:.0%})."
    )

    p_on_v1 = mc.get("p_on_time")
    p_on_v2 = (mc_v2 or {}).get("p_on_time")
    if p_on_v2 is not None:
        p_str = (
            f"{round(p_on_v2*100)}% (DAG-aware) — vs {round(p_on_v1*100)}% throughput baseline; "
            f"{round(p_on_v2*100) - round(p_on_v1*100):+d} pp from dependency structure"
        )
    elif p_on_v1 is not None:
        p_str = f"{round(p_on_v1*100)}% (throughput model; DAG skipped — low predecessor coverage)"
    else:
        p_str = "N/A"
    deadline = mc.get("deadline", (mc_v2 or {}).get("deadline", "Unknown"))

    n_at_risk   = cluster.get("n_at_risk_active", 0)
    clusters    = cluster.get("clusters", [])
    top_cluster = clusters[0] if clusters else {}
    top_owner   = top_cluster.get("top_owner", "")
    top_n       = top_cluster.get("task_count", 0)
    action = (
        f"Review and triage the {n_at_risk} active at-risk tasks"
        + (f" — {top_n} concentrated under {top_owner}" if top_owner else "")
        + "."
    )

    conf_line = _data_confidence_tag(df, dag_info)

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    safe_name = project_name.replace(" ", "_").replace("/", "-")
    fname = out_dir / f"{run_date.strftime('%Y-%m-%d')}_{safe_name}_exec.md"
    fname.write_text(
        f"# {emoji} {project_name} — Executive Summary\n\n"
        f"**Date:** {run_date.strftime('%d %b %Y')}  |  "
        f"**Status:** {emoji} **{rag}** (score: {score:.3f}/1.00)\n\n"
        f"**Why:** {reason}\n\n"
        f"**P(on-time):** {p_str}\n\n"
        f"**Deadline:** {deadline}\n\n"
        f"**Primary action:** {action}\n\n"
        f"---\n\n"
        f"> {conf_line}\n",
        encoding="utf-8",
    )
    return fname


def _cluster_section(cluster: dict) -> str:
    if not cluster.get("clusters"):
        return f"> {cluster.get('headline', 'No cluster data.')}\n"

    lines = [f"**{cluster['headline']}**\n", f"*{cluster.get('caveat','')}*\n\n"]
    lines.append("| Cluster | Tasks | % of Risk | Top Area | Top Phase | Top Owner | Red Tasks |\n")
    lines.append("|---------|-------|-----------|----------|-----------|-----------|----------|\n")
    for c in cluster["clusters"]:
        lines.append(
            f"| {c['cluster_id']+1} | {c['task_count']} | {c['pct_of_risk']}% | "
            f"{c['top_area']} | {c['top_phase']} | {c['top_owner']} | {c['red_tasks']} |\n"
        )
    return "".join(lines)


def _delta_section(delta: dict) -> str:
    if not delta.get("has_previous"):
        return f"> {delta.get('note', 'First run.')}\n"

    direction = delta.get("direction", "→ stable")
    red_delta = delta.get("red_tasks_delta", 0)
    red_line  = (
        f"Red task count: +{red_delta} (↑ worse)" if red_delta > 0
        else f"Red task count: {red_delta} (↓ better)" if red_delta < 0
        else "Red task count: unchanged"
    )
    return (
        f"{delta['change_sentence']}\n\n"
        f"- Score delta: {delta['score_delta']:+.4f} ({direction})\n"
        f"- {red_line}\n"
        f"- Previous run: {delta['prev_run_date'][:10]}\n"
    )


def _shap_section(shap_info: dict) -> str:
    if shap_info.get("error"):
        return f"> Feature importance: {shap_info['error']}\n"
    lines = [
        "| Feature | Importance |\n|---------|------------|\n"
    ]
    for f in shap_info.get("top_features", []):
        lines.append(f"| {f['feature']} | {f['mean_abs_shap']} |\n")
    lines.append(f"\n> *{shap_info.get('disclaimer', '')}*\n")
    return "".join(lines)


def write_report(
    project_name: str,
    scores: dict[str, Any],
    mc: dict[str, Any],
    mc_v2: dict[str, Any] | None,
    dag_info: dict[str, Any] | None,
    cluster: dict[str, Any],
    delta: dict[str, Any],
    shap_info: dict[str, Any],
    narrative: str,
    verified: bool,
    run_date: datetime | None = None,
    output_dir: str = config.WEEKLY_OUTPUT_DIR,
    df=None,                   # DataFrame for confidence tag + naive baseline
) -> Path:
    """
    Compose and write the full weekly Markdown report.
    Returns the path to the written file.
    """
    if run_date is None:
        run_date = datetime.now()

    date_str = run_date.strftime("%Y-%m-%d")
    safe_name = project_name.replace(" ", "_").replace("/", "-")
    filename = f"{date_str}_{safe_name}.md"

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    filepath = out_dir / filename

    rag = scores["rag"]
    summary = scores.get("task_summary", {})
    by_status = summary.get("by_status", {})
    by_rag    = summary.get("by_rag", {})
    dq        = scores.get("data_quality", {})
    conf_line = _data_confidence_tag(df, dag_info) if df is not None else ""

    # Determine whether LLM actually ran or fell back to rule-based
    _llm_ran = config.USE_LLM and not narrative.startswith("## ")  # rule-based starts with ##
    verify_note = (
        "✅ LLM self-verified (no factual corrections needed)"
        if verified is True and _llm_ran
        else "⚠️ LLM verification flagged corrections (applied)"
        if verified is False and _llm_ran
        else "ℹ️ Rule-based narrative (LLM unavailable or key not set)"
    )

    report = f"""# Weekly Project Health Report
**Project:** {project_name}
**Report Date:** {date_str}
**Generated by:** Zycus Project Health Agent
{("> " + conf_line) if conf_line else ""}

---

## 🏷️ Overall Status: {_rag_badge(rag)}

| Metric | Value |
|--------|-------|
| Project Score | {scores['project_score']:.3f} / 1.00 |
| Forward Risk | {scores['forward_risk']:.3f} |
| Historical Slip | {scores['historical_slip']:.3f} |
| Completed | {by_status.get('Completed', 0)} |
| In Progress | {by_status.get('In Progress', 0)} |
| Not Started | {by_status.get('Not Started', 0)} |
| On Hold | {by_status.get('On Hold', 0)} |
| 🔴 Red Tasks | {by_rag.get('Red', 0)} |
| 🟡 Yellow Tasks | {by_rag.get('Yellow', 0)} |
| 🟢 Green Tasks | {by_rag.get('Green', 0)} |

{_cp_comparison_section(scores, dag_info)}

---

## 📝 Executive Summary

{narrative}

*{verify_note}*

---

## 📊 Week-on-Week Delta

{_delta_section(delta)}

---

## 🎲 Monte Carlo Deadline Forecast

{_mc_comparison_section(mc, mc_v2)}

---

## 📊 Naïve vs Model Baseline

{_naive_baseline_section(df, mc, mc_v2, scores) if df is not None else '> df not passed; baseline unavailable.'}

---

## 🔍 Risk Concentration (Cluster Analysis)

{_cluster_section(cluster)}

---

## 🤖 ML Feature Importance (feature_importances_)

{_shap_section(shap_info)}

---

## ⚙️ Data Quality Notes

| Check | Value |
|-------|-------|
| Total tasks | {dq.get('total_tasks', 0)} |
| Tasks with RAG label | {dq.get('labeled_tasks', 0)} |
| Known sign-anomaly rows | {dq.get('sign_anomaly_rows', 0)} |

> Sign-anomaly rows: tasks where Variance sign appears inverted vs. computed
> date delta. Documented in `config.SIGN_INVERTED_TASKS`. Not silently dropped.

---

*Report generated: {run_date.isoformat()} | Agent version: 1.0*
"""

    filepath.write_text(report, encoding="utf-8")
    return filepath
