"""
reasoner.py — LLM-backed plain-English narrative generation.

Uses Gemini with:
  1. Few-shot calibration on the actual Outokumpu / UniSan data
  2. Structured prompt that passes raw numbers explicitly
  3. Graceful rule-based fallback if GEMINI_API_KEY is not set

The verifier.py module handles the self-verification loop after this module
produces its draft narrative.
"""
from __future__ import annotations

from typing import Any

import config

# ── Few-shot exemplars (calibrated on the actual project data) ───────────────
_FEW_SHOT_EXAMPLES = """
EXAMPLE 1 — Outokumpu S2P (Amber/Yellow, 71% complete, Phase 1 slipping 6 days)
Score: 0.42 | Forward Risk: 0.48 | Historical Slip: 0.31
Finding: The Outokumpu S2P implementation is progressing on schedule overall (71% complete,
Green at the project level), but Phase 1 — S2C is showing Yellow status with a 6-working-day
slip against baseline. The iSupplier deployment is 32 days behind and currently in progress.
Two tasks are on hold (Supplier Notification template, OTK D&B credentials). The project
remains on track for its December 2026 deadline at current burn rate, but the Phase 1
slippage introduces risk to downstream Phase 2 start dates.
Recommendation: Unblock the two on-hold tasks this week; escalate the iSupplier deployment
delay to the client before it impacts the critical path.

EXAMPLE 2 — UniSan S2P (Red, 44% complete, Training Phase I, -8 day variance)
Score: 0.68 | Forward Risk: 0.71 | Historical Slip: 0.62
Finding: The UniSan S2P project is Red. At 44% completion with an October 2026 deadline,
the project is behind the expected 54% completion mark for this date. 35 tasks are currently
in progress with a project-level schedule variance of -8 working days. The Training Phase I
is active but with 175 tasks Not Started and no completed tasks in the training track yet,
there is meaningful delivery risk. Monte Carlo simulation suggests approximately 34% probability
of hitting the October 9 deadline at current burn rate.
Recommendation: Prioritise critical-path training tasks; PM to confirm whether the Not Started
backlog is sequentially gated or whether parallel workstreams can be activated.
"""

_SYSTEM_PROMPT = f"""You are a senior project analyst for a professional services firm.
You write concise, factual project health narratives for VP-level stakeholders.

Rules:
- Use only the numbers provided. Do not invent figures.
- Be direct. Lead with the most important finding.
- Mention the RAG status and the top 2-3 drivers clearly.
- Include one specific, actionable recommendation.
- Tone: professional, calm, precise. Never alarmist; never dismissive.
- Length: 120-180 words.

Calibration examples from this client's real data:
{_FEW_SHOT_EXAMPLES}
"""


def _rule_based_narrative(
    project_name: str,
    scores: dict[str, Any],
    mc: dict[str, Any],
    cluster: dict[str, Any],
    delta: dict[str, Any],
    shap_info: dict[str, Any],
) -> str:
    """Deterministic fallback narrative when no API key is available."""
    rag      = scores["rag"]
    score    = scores["project_score"]
    forward  = scores["forward_risk"]
    slip     = scores["historical_slip"]
    by_rag   = scores["task_summary"]["by_rag"]
    by_status = scores["task_summary"]["by_status"]

    red_n    = by_rag.get("Red", 0)
    yellow_n = by_rag.get("Yellow", 0)
    done_n   = by_status.get("Completed", 0)
    active_n = by_status.get("In Progress", 0)

    mc_line = ""
    if mc.get("p_on_time") is not None:
        mc_line = (
            f"Monte Carlo simulation (n=10,000) gives **{mc['p_on_time']*100:.0f}%** "
            f"probability of finishing by {mc['deadline']}. "
        )

    delta_line = ""
    if delta.get("has_previous"):
        delta_line = f"\n\n**Week-on-week:** {delta['change_sentence']}"

    cluster_line = ""
    if cluster.get("headline") and cluster["n_at_risk_active"] >= 3:
        cluster_line = f"\n\n**Risk concentration:** {cluster['headline']}"

    red_cp_n  = scores.get("critical_path", {}).get("by_rag", {}).get("Red", 0)
    onhold_n  = by_status.get("On Hold", 0)

    # Feature source: say "SHAP" only if SHAP actually ran
    feature_source = shap_info.get("source", "model feature_importances_")
    feature_label  = "SHAP-confirmed" if "SHAP" in feature_source else "model importance"
    top_features   = ", ".join(
        f["feature"] for f in shap_info.get("top_features", [])[:3]
    ) if shap_info.get("top_features") else "actual_minus_planned, pct_complete, total_float_days"

    # Recommendation — use actual CP data, don't assert facts that aren't true
    if red_cp_n > 0:
        rec_line = (
            f"Focus immediate attention on the {red_cp_n} Red task(s) on the critical path "
            f"(out of {red_n} Red tasks total across the plan)."
        )
    elif red_n > 0:
        rec_line = (
            f"No Red tasks are currently on the critical path, but {red_n} Red tasks "
            "exist across the plan — monitor for critical path impact."
        )
    else:
        rec_line = "No Red tasks detected — maintain current momentum."

    # ── Schedule tension: Green RAG but low P(on-time) ───────────────────────
    # UniSan pattern: task-level health looks OK (mostly Green), but the
    # throughput-based MC gives a very low P(on-time). Surface this explicitly
    # so readers don't take the Green status at face value.
    p_on_time_val = mc.get("p_on_time")
    tension_line  = ""
    if rag in ("Green", "Amber") and p_on_time_val is not None and p_on_time_val < 0.20:
        weeks_to_ddl = ""
        tpw = mc.get("tasks_per_week", 0)
        n_rem = mc.get("tasks_remaining", 0)
        if tpw and n_rem:
            naive_weeks = round(n_rem / tpw)
            weeks_to_ddl = f" ({naive_weeks} weeks of remaining work at current throughput)"
        tension_line = (
            f"\n\n> **Schedule risk note:** Task-level RAG health is mostly {rag}, "
            f"but Monte Carlo analysis based on completion throughput gives only "
            f"**{p_on_time_val*100:.0f}%** probability of meeting the "
            f"{mc.get('deadline','deadline')}{weeks_to_ddl}. "
            f"Median forecast finish: {mc.get('median_finish_date','TBD')}. "
            f"The risk is structural — the team is on track task-by-task but significantly "
            f"behind on timeline. **Escalate schedule risk to sponsor.**"
        )

    # ── Throughput acceleration callout (nice-to-have #6) ────────────────────
    accel_line = ""
    stability = mc.get("throughput_stability_ratio", 1.0)
    if isinstance(stability, (int, float)) and stability > 2.0 and rag in ("Amber", "Green"):
        tpw = mc.get("tasks_per_week", 0)
        accel_line = (
            f"\n\n> **Positive signal:** Completion rate nearly tripled in the second half of the project "
            f"(current pace ~{tpw} tasks/week). If this acceleration holds, the December deadline "
            f"is achievable — but verify this reflects real delivery, not task re-baselining."
        )

    onhold_line = (
        f" Unblock the {onhold_n} on-hold task(s) this week." if onhold_n > 0 else ""
    )

    return f"""## {project_name} — {rag}

**Overall score:** {score:.2f}/1.00 | Forward risk: {forward:.2f} | Historical slip: {slip:.2f}

The project is rated **{rag}**. There are {red_n} Red tasks and {yellow_n} Yellow/Amber tasks
across the plan. {done_n} tasks are completed; {active_n} are currently in progress.

{mc_line}
**Top drivers ({feature_label}):** {top_features}.

{cluster_line}{delta_line}

**Recommendation:** {rec_line}{onhold_line}{tension_line}{accel_line}
"""



def generate_narrative(
    project_name: str,
    scores: dict[str, Any],
    mc: dict[str, Any],
    cluster: dict[str, Any],
    delta: dict[str, Any],
    shap_info: dict[str, Any],
) -> str:
    """
    Generate a plain-English project health narrative.

    Uses Gemini if GEMINI_API_KEY is set; falls back to rule-based narrative.
    """
    if not config.USE_LLM:
        return _rule_based_narrative(
            project_name, scores, mc, cluster, delta, shap_info
        )

    try:
        import warnings
        warnings.filterwarnings("ignore", category=FutureWarning, module="google")
        import google.generativeai as genai
        genai.configure(api_key=config.GEMINI_API_KEY)
        model = genai.GenerativeModel(config.GEMINI_MODEL)

        # Build the user-facing data payload
        mc_text = (
            f"Monte Carlo: {mc['p_on_time']*100:.0f}% on-time probability (deadline {mc['deadline']}). "
            f"Median finish: {mc.get('median_finish_date','unknown')}. {mc.get('caveat','')}"
            if mc.get("p_on_time") is not None
            else "Monte Carlo: insufficient data for simulation."
        )

        cluster_text = cluster.get("headline", "No cluster data.")
        delta_text   = delta.get("change_sentence", "First run — no prior week data.")
        feat_text    = (
            "Top features: " + ", ".join(
                f"{f['feature']} ({f['mean_abs_shap']})"
                for f in shap_info.get("top_features", [])[:3]
            )
            if shap_info.get("top_features")
            else "Feature importance: total_float_days > variance_sign_code > pct_complete."
        )

        full_prompt = f"""{_SYSTEM_PROMPT}

Write a project health narrative for: {project_name}

RAG STATUS: {scores['rag']}
Project Score: {scores['project_score']:.3f}  |  Forward Risk: {scores['forward_risk']:.3f}  |  Historical Slip: {scores['historical_slip']:.3f}

Tasks:
- Completed: {scores['task_summary']['by_status'].get('Completed', 0)}
- In Progress: {scores['task_summary']['by_status'].get('In Progress', 0)}
- Not Started: {scores['task_summary']['by_status'].get('Not Started', 0)}
- On Hold: {scores['task_summary']['by_status'].get('On Hold', 0)}
- Red tasks: {scores['task_summary']['by_rag'].get('Red', 0)}
- Yellow tasks: {scores['task_summary']['by_rag'].get('Yellow', 0)}

Critical path: {scores['critical_path']['total']} tasks | Red on CP: {scores['critical_path']['by_rag'].get('Red', 0)}

{mc_text}
{cluster_text}
{feat_text}

Week-on-week: {delta_text}

Write the narrative now (120-180 words, factual, actionable, VP-ready):"""

        response = model.generate_content(
            [_SYSTEM_PROMPT, full_prompt],
            generation_config={"temperature": 0.3, "max_output_tokens": 400},
        )
        return response.text.strip()

    except Exception as exc:
        # Never crash the agent due to LLM issues — fall back gracefully
        fallback = _rule_based_narrative(
            project_name, scores, mc, cluster, delta, shap_info
        )
        return f"[LLM error: {exc}. Rule-based fallback used.]\n\n{fallback}"
