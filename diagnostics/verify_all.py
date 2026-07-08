"""
Comprehensive verification — 5 checks:
  1. Feature importance (current model, new feature set)
  2. Monte Carlo throughput stability (completed task count + rate stability)
  3. P(on-time) gut-check (vs % complete + RAG mix)
  4. UniSan Schedule Health spot-check (4 Red, 4 Green rows by eye)
  5. Output .md report key-line scan (stale numbers / hardcoded strings)
"""
import sys, warnings, json
warnings.filterwarnings('ignore')
sys.path.insert(0, '.')

import numpy as np
import pandas as pd
from agent.data_loader import load_all_projects
from agent.rag_scorer  import train_model, score_project
from agent.monte_carlo import simulate
import config
from datetime import datetime

SEP = "=" * 60

dfs  = load_all_projects(config.PROJECT_FILES)
all_dfs = list(dfs.values())

print(SEP)
print("  CHECK 1 — Feature importance (new feature set)")
print(SEP)

model, _enc, importance = train_model(all_dfs)
ranked = sorted(importance.items(), key=lambda x: x[1], reverse=True)
print("Feature                  Importance")
for f, v in ranked:
    bar = "#" * int(v * 40)
    print(f"  {f:<24} {v:.4f}  {bar}")

print()
print("Interpretation:")
print("  variance_sign_code in top 3 => sign of lateness is a real RAG driver (good)")
print("  actual_minus_planned in top 3 => duration efficiency also predictive")
print("  total_float_days high => slack is dominant (expected for scheduling)")

# ── CHECK 2: Monte Carlo throughput stability ────────────────────────────────
print()
print(SEP)
print("  CHECK 2 — Monte Carlo throughput stability")
print(SEP)

today = datetime.now()
for name, df in dfs.items():
    print(f"\n  {name}")
    completed = df[df["Status"] == "Completed"].copy()
    completed["end_date"] = pd.to_datetime(completed["End Date"], errors="coerce")
    completed = completed.dropna(subset=["end_date"])

    n = len(completed)
    print(f"  Completed tasks with end dates: {n}")

    if n >= 5:
        earliest = completed["end_date"].min()
        latest   = completed["end_date"].max()
        span_weeks = max((latest - earliest).days / 7, 1.0)
        rate = n / span_weeks
        print(f"  Project span (earliest→latest completed): {earliest.date()} → {latest.date()}")
        print(f"  Span: {span_weeks:.1f} weeks | Rate: {rate:.1f} tasks/week")

        # Stability check: compute rate in first half vs second half of span
        mid = earliest + (latest - earliest) / 2
        first_half  = completed[completed["end_date"] <= mid]
        second_half = completed[completed["end_date"] >  mid]
        half_weeks  = span_weeks / 2
        r1 = len(first_half)  / half_weeks if half_weeks > 0 else 0
        r2 = len(second_half) / half_weeks if half_weeks > 0 else 0
        ratio = r2 / r1 if r1 > 0 else float('inf')
        stability = "STABLE" if 0.5 <= ratio <= 2.0 else "UNSTABLE (accelerating/decelerating)"
        print(f"  First-half rate: {r1:.1f}/wk | Second-half rate: {r2:.1f}/wk | Ratio: {ratio:.2f} => {stability}")
    else:
        print(f"  WARNING: only {n} completed tasks — rate will be noisy")

# ── CHECK 3: P(on-time) gut-check ────────────────────────────────────────────
print()
print(SEP)
print("  CHECK 3 — P(on-time) gut-check")
print(SEP)

for name, df in dfs.items():
    scores = score_project(df)
    mc     = simulate(df)

    n_total     = len(df)
    n_completed = int((df["Status"] == "Completed").sum())
    n_active    = int(df["Status"].isin({"In Progress","Not Started"}).sum())
    pct_done    = n_completed / n_total * 100
    rag         = scores["rag"]
    p_on_time   = mc.get("p_on_time")
    deadline    = mc.get("deadline","?")
    tpw         = mc.get("tasks_per_week", "?")
    n_rem       = mc.get("tasks_remaining", "?")
    med_finish  = mc.get("median_finish_date","?")

    print(f"\n  {name}:")
    print(f"    RAG={rag} | score={scores['project_score']:.3f}")
    print(f"    Completed: {n_completed}/{n_total} ({pct_done:.0f}%)")
    print(f"    Remaining active tasks: {n_active}")
    print(f"    Throughput: {tpw} tasks/week")
    print(f"    Deadline: {deadline} | P(on-time): {p_on_time} | Median finish: {med_finish}")

    # Naive gut-check: weeks left = n_remaining / tpw
    if isinstance(tpw, (int,float)) and isinstance(n_rem, int) and tpw > 0:
        naive_weeks = n_rem / tpw
        naive_date  = today + pd.Timedelta(weeks=naive_weeks)
        print(f"    Naive (ratio=1.0) finish: {naive_date.date()} in {naive_weeks:.0f}wk")
        if deadline and deadline != "?":
            ddl = datetime.strptime(deadline, "%Y-%m-%d")
            weeks_to_ddl = (ddl - today).days / 7
            print(f"    Weeks to deadline: {weeks_to_ddl:.0f}wk")
            if naive_weeks <= weeks_to_ddl:
                print(f"    Gut-check: ON TRACK (naive finish before deadline) => P high is EXPECTED")
            else:
                print(f"    Gut-check: BEHIND (naive finish after deadline by {naive_weeks-weeks_to_ddl:.0f}wk) => P low is EXPECTED")

# ── CHECK 4: UniSan Schedule Health spot-check ───────────────────────────────
print()
print(SEP)
print("  CHECK 4 — UniSan Schedule Health -> RAG spot-check")
print(SEP)

unisan_df = dfs.get("UniSan S2P")
if unisan_df is not None:
    print("  4 Red rows (should look behind schedule):")
    red_rows = unisan_df[unisan_df["RAG"] == "Red"][
        ["Task Name","Status","pct_complete","variance_sign","variance_days","RAG"]
    ].head(4)
    print(red_rows.to_string())

    print("\n  4 Green rows (should look on track or completed):")
    green_rows = unisan_df[unisan_df["RAG"] == "Green"][
        ["Task Name","Status","pct_complete","variance_sign","variance_days","RAG"]
    ].head(4)
    print(green_rows.to_string())

    print("\n  RAG vs Status cross-tab:")
    ct = pd.crosstab(unisan_df["Status"], unisan_df["RAG"])
    print(ct)

    print("\n  RAG vs variance_sign cross-tab (completed tasks only):")
    done = unisan_df[unisan_df["Status"] == "Completed"]
    if len(done):
        ct2 = pd.crosstab(done["variance_sign"].fillna("unknown"), done["RAG"].fillna("unlabeled"))
        print(ct2)
else:
    print("  UniSan not found in loaded projects!")

# ── CHECK 5: Output .md file scan ────────────────────────────────────────────
print()
print(SEP)
print("  CHECK 5 — Output .md report scan for stale/wrong text")
print(SEP)

import glob, re, os

stale_patterns = [
    (r"variance_days",           "stale feature name in report"),
    (r"planned_days",            "stale feature name"),
    (r"on the critical path",    "possible mis-attributed CP claim"),
    (r"0%.*2026-12",             "P(on-time)=0% for Dec deadline — was the artifact"),
    (r"median.*203[0-9]",        "future date from serial-sum bug"),
    (r"2031",                    "stale 2031 finish date from serial-sum bug"),
]

md_files = glob.glob("outputs/weekly/*.md")
for fpath in sorted(md_files):
    fname = os.path.basename(fpath)
    issues = []
    with open(fpath, encoding="utf-8", errors="replace") as f:
        content = f.read()
    for pattern, label in stale_patterns:
        if re.search(pattern, content, re.IGNORECASE):
            issues.append(f"  [{label}]: pattern '{pattern}' found")
    if issues:
        print(f"\n  {fname} — ISSUES:")
        for i in issues: print(i)
    else:
        print(f"\n  {fname} — CLEAN")

    # Print key lines
    key_lines = [l.strip() for l in content.splitlines()
                 if any(k in l for k in ["Status:", "Score","P(on","Recommendation","Top drivers","Monte Carlo"])]
    for l in key_lines[:8]:
        print(f"    {l}")
