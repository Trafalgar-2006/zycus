"""
main.py — CLI entry point for the Project Health Reporting Agent.

Usage:
    python main.py                          # run all projects
    python main.py --project "UniSan S2P"  # single project
    python main.py --schedule              # run weekly on a schedule
    python main.py --monthly               # generate executive PPTX

The agent pipeline per project:
    load → score (GBT+SHAP) → monte_carlo → cluster → delta → reason → verify → report
"""
from __future__ import annotations
import warnings
# Suppress deprecation noise from google-generativeai (still functional; migrate to google-genai when ready)
warnings.filterwarnings("ignore", message="All support for the", category=FutureWarning)
# Suppress pandas downcasting FutureWarning
warnings.filterwarnings("ignore", message="Downcasting behavior", category=FutureWarning)

import argparse
import sys
from datetime import datetime
from pathlib import Path

import config
from agent.data_loader    import load_all_projects, load_project
from agent.rag_scorer     import train_model, score_project, shap_summary
from agent.monte_carlo    import simulate, simulate_v2
from agent.cluster_analyzer import analyze as cluster_analyze
from agent.delta_store    import save_run, build_delta
from agent.dag_builder    import build_dag
from agent.reasoner       import generate_narrative
from agent.verifier       import verify
from agent.report_writer  import write_report


def run_project(
    name: str,
    df,
    model,
    importance: dict,
    all_dfs: list,
    run_date: datetime,
) -> Path:
    """Run the full pipeline for a single project and return report path."""
    print(f"\n{'='*60}")
    print(f"  Processing: {name}")
    print(f"{'='*60}")

    # 1. Score
    print("  [1/7] Scoring RAG...")
    scores   = score_project(df)
    shap_inf = shap_summary(model, df, importance=importance)
    print(f"        -> {scores['rag']} (score={scores['project_score']:.3f})")

    # 2. Monte Carlo v1 (throughput-based)
    print("  [2/8] Running Monte Carlo v1 (throughput)...")
    mc = simulate(df, today=run_date)
    if mc.get("p_on_time") is not None:
        print(f"        -> P(on-time): {mc['p_on_time']*100:.0f}%  |  deadline: {mc['deadline']}")
    else:
        print(f"        -> {mc.get('caveat', 'skipped')}")

    # 2b. Build dependency DAG
    print("  [3/8] Building dependency DAG...")
    dag_info = build_dag(df)
    cov      = dag_info["coverage"]
    cp_graph = dag_info["critical_path"]
    print(f"        -> {cov['n_with_preds']}/{cov['n_tasks']} tasks have predecessors "
          f"({cov['pct_coverage']:.0%} coverage), "
          f"{len(cp_graph)}-task graph-computed critical path")

    # 2c. Monte Carlo v2 (dependency-aware) — only if coverage is sufficient
    mc_v2: dict | None = None
    print("  [4/8] Monte Carlo v2 (dependency-aware)...")
    if cov["pct_coverage"] >= config.DAG_MIN_COVERAGE:
        mc_v2 = simulate_v2(df, dag_info, today=run_date)
        if mc_v2.get("p_on_time") is not None:
            print(f"        -> P(on-time): {mc_v2['p_on_time']*100:.0f}%  "
                  f"(graph: {cov['n_with_preds']} edges, {mc_v2.get('n_fallback_durations', 0)} dur-fallbacks)")
        else:
            print(f"        -> {mc_v2.get('caveat', 'skipped')}")
    else:
        mc_v2 = {
            "p_on_time": None,
            "model":     "skipped_low_coverage",
            "caveat":    (
                f"Dependency-aware simulation skipped: only {cov['pct_coverage']:.0%} of tasks "
                f"have Predecessor data (threshold: {config.DAG_MIN_COVERAGE:.0%}). "
                "Running graph simulation on a 72%-missing edge set would likely understate risk "
                "for unconnected tasks. Throughput model (v1) used as sole forecast."
            ),
        }
        print(f"        -> Skipped (coverage {cov['pct_coverage']:.0%} < "
              f"{config.DAG_MIN_COVERAGE:.0%} threshold) — v1 only")

    # 5. Cluster analysis
    print("  [5/8] Clustering at-risk tasks...")
    cluster = cluster_analyze(df)
    print(f"        -> {cluster['n_at_risk_active']} at-risk active tasks, {len(cluster['clusters'])} clusters")

    # 6. Delta
    print("  [6/8] Computing week-on-week delta...")
    save_run(name, scores, mc, cluster, run_date=run_date)
    delta = build_delta(name, scores)
    if delta.get("has_previous"):
        print(f"        -> {delta['change_sentence']}")
    else:
        print(f"        -> {delta.get('note', 'First run')}")

    # 7. Generate narrative
    print(f"  [7/8] Generating narrative ({'LLM' if config.USE_LLM else 'rule-based'})...")
    narrative = generate_narrative(name, scores, mc, cluster, delta, shap_inf)

    # 8. Self-verify
    print("  [8/8] Self-verifying narrative...")
    narrative, was_modified = verify(narrative, scores, mc)
    if was_modified:
        print("        -> ⚠️  Corrections applied by verifier")
    else:
        print("        -> ✅ Verified clean")

    # Write report
    print("  Writing report...")
    report_path = write_report(
        project_name=name,
        scores=scores,
        mc=mc,
        mc_v2=mc_v2,
        dag_info=dag_info,
        cluster=cluster,
        delta=delta,
        shap_info=shap_inf,
        narrative=narrative,
        verified=not was_modified,
        run_date=run_date,
    )
    print(f"        -> {report_path}")

    return report_path


def run_all(project_filter: str | None = None) -> list[Path]:
    """Load all projects, train shared model, run pipeline."""
    # Snap to midnight so Monte Carlo results are deterministic within a calendar day
    # (both simulate() and simulate_v2() use this as 'today' for date arithmetic)
    run_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

    files = config.PROJECT_FILES
    if project_filter:
        files = {k: v for k, v in files.items() if project_filter.lower() in k.lower()}
        if not files:
            print(f"No project matching '{project_filter}' found.")
            print(f"Available: {list(config.PROJECT_FILES.keys())}")
            sys.exit(1)

    print("\nLoading project files...")
    all_dfs_dict = load_all_projects(files)
    all_dfs = list(all_dfs_dict.values())

    print("Training ML model on task data...")
    model, le, importance = train_model(all_dfs)
    top_feats = sorted(importance.items(), key=lambda x: x[1], reverse=True)[:3]
    print(f"   Top features: {', '.join(f'{k}({v:.3f})' for k,v in top_feats)}")

    reports = []
    for name, df in all_dfs_dict.items():
        path = run_project(name, df, model, importance, all_dfs, run_date)
        reports.append(path)

    print(f"\nDone. {len(reports)} report(s) written.")
    return reports


def main():
    parser = argparse.ArgumentParser(
        description="Project Health Reporting Agent -- Zycus Assignment"
    )
    parser.add_argument(
        "--project", "-p",
        type=str,
        default=None,
        help="Filter to a single project by name substring",
    )
    parser.add_argument(
        "--schedule", "-s",
        action="store_true",
        help="Run on a weekly schedule instead of once",
    )
    parser.add_argument(
        "--monthly", "-m",
        action="store_true",
        help="Generate monthly executive PPTX from weekly outputs",
    )
    args = parser.parse_args()

    if args.monthly:
        from pptx_generator import generate_monthly_pptx
        path = generate_monthly_pptx()
        print(f"\nMonthly PPTX written: {path}")
        return

    if args.schedule:
        import scheduler as sched
        sched.start()
        return

    run_all(project_filter=args.project)


if __name__ == "__main__":
    main()
